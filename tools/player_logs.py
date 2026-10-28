"""Career game logs for the player card: one small JSON per player, <site>/data/players/<gsis_id>.json.

Usage: python tools/player_logs.py --site=site        (CI runs it after the pages are built)

Every regular-season game of the player's career (nflverse weekly stats, 1999 on; snap share from 2012 on), each
with our own pregame matchup rank and projection for that week where we have one: read from the published week
data files (<site>/index.json, <site>/<season>/week-NN.json; 2021 on, plus this season's upcoming weeks), so the
matchup color is what our model said BEFORE that game, not hindsight. Players: everyone on any published week page.
The page re-scores fantasy points with the viewer's scoring; the weekly position rank uses the site's scoring.
"""
import json
import re
from collections import Counter
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.codes import INJURY_LISTS, RESERVE as RESERVE_CODES, reserve as reserve_code  # noqa: E402
from nfledge.config import load_config, load_scoring  # noqa: E402
from nfledge.report import ROSTER_TEAM, SCORE_KEYS, _json_safe, headshot_url  # noqa: E402

FIRST_SEASON = 1999
POS = ("QB", "RB", "WR", "TE")


GSIS_RE = re.compile(r"^\d{2}-\d{7}$")

def week_files(site: Path) -> list[Path]:
  return [p for p in [site / "index.json", *sorted(site.glob("[0-9][0-9][0-9][0-9]/week-[0-9][0-9].json"))] if p.exists()]


OUR_GAMES = {}  # game_id -> our pregame numbers for that game + the week file it lives in (filled by our_weeks)
NAMES = {}  # gsis -> (display name, espn id) from our week files (filled by our_weeks): cards open without a week row


def our_weeks(site: Path) -> tuple[dict, dict, set]:
  """(season, week, gsis) -> our projection + matchup rank; (season, week, opp, pos) -> matchup rank; all gsis."""
  per_player, per_opp, everyone = {}, {}, set()
  for f in week_files(site):
    d = json.loads(f.read_text(encoding="utf-8"))
    s, w = int(d["season"]), int(d["week"])
    rel = f.relative_to(site).as_posix()
    for g in d.get("games", []):
      if g["id"] not in OUR_GAMES or rel != "index.json":  # archived / lookahead file wins over a stale copy
        OUR_GAMES[g["id"]] = {"fc": g.get("fc") or {}, "pr": g.get("power_rk"), "away": g["away"]["team"],
                              "home": g["home"]["team"], "file": rel, "line": g.get("vegas_line")}
    for pid, p in d["players"].items():
      everyone.add(pid)
      if p.get("name") and (pid not in NAMES or rel == "index.json"):
        NAMES[pid] = (p["name"], p.get("espn") or (NAMES.get(pid) or (None, None))[1])
      m = re.match(r"(\d+)", str(p.get("dvp") or ""))
      rank = int(m.group(1)) if m else None
      per_player[(s, w, pid)] = {"pj": round(float(p["proj"]), 1), "pjl": p["sc"]["pj"], "mr": rank}
      if p.get("mu") is not None:  # week files from 2026-10-14 on: matchup points + emphasis instead of a rank
        per_player[(s, w, pid)].update(mu=round(float(p["mu"]), 1), mh=int(p.get("mu_hi") or 0), mc=p.get("mu_c"))
      if rank and p.get("opp"):
        per_opp[(s, w, p["opp"], p["pos"])] = rank
  return per_player, per_opp, everyone


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = Path(opt.get("site", "site"))
  cfg, scoring = load_config(), load_scoring()
  data = D.load_all(cfg)
  import nflreadpy as nfl
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  first_loaded = min(data.seasons)
  old = [cache.get("stats", s, lambda: nfl.load_player_stats([s]).select(D.STAT_COLS), stale=False)
         for s in range(FIRST_SEASON, first_loaded)]
  old = [o[o.season_type == "REG"].assign(team=lambda x: x.team.replace(D.RELOCATED),
                                          opponent_team=lambda x: x.opponent_team.replace(D.RELOCATED))
         for o in old if o is not None and len(o)]
  ren = {"passing_yards": "pass_yd", "passing_tds": "pass_td", "passing_interceptions": "interception",
         "rushing_yards": "rush_yd", "rushing_tds": "rush_td", "receptions": "reception", "receiving_yards": "rec_yd",
         "receiving_tds": "rec_td"}
  w = {k: float(v) for k, v in scoring.weights.items()}

  def prep(x: pd.DataFrame) -> pd.DataFrame:
    """Fantasy positions, numeric stat line, site-scoring points and the week's position finish."""
    x = x[x.position.isin(POS)].copy()
    for c in D.STAT_COLS[8:]:
      x[c] = pd.to_numeric(x[c], errors="coerce").fillna(0)
    x["fumble_lost"] = x.sack_fumbles_lost + x.rushing_fumbles_lost + x.receiving_fumbles_lost
    x = x.rename(columns=ren)
    x["fp"] = sum(x[k] * w.get(k, 0.0) for k in SCORE_KEYS) + np.where(x.position == "TE", x.reception * float(scoring.te_reception_bonus), 0)
    x["prk"] = x.groupby(["season", "week", "position"]).fp.rank(ascending=False, method="min").astype(int)
    # every stat's finish at his position that week (owner 2026-10-16: color each game-log value by it, Sleeper-style);
    # fewer is better for interceptions and fumbles
    grp = x.groupby(["season", "week", "position"])
    for k in RANKED:
      x[f"{k}_wr"] = grp[k].rank(ascending=k in FEWER_BETTER, method="min").fillna(99).astype(int)
    return x

  st = prep(pd.concat(old + [data.stats], ignore_index=True))
  # Season totals' finish at the position (owner 2026-10-16: the game log's totals row colored like its games): each
  # player's regular-season sums ranked among everyone at his position that season, fantasy points and every stat
  tot = st.groupby(["season", "player_id"]).agg(position=("position", "last"), fp=("fp", "sum"),
                                                **{k: (k, "sum") for k in RANKED}).reset_index()
  tg = tot.groupby(["season", "position"])
  tot["prk"] = tg.fp.rank(ascending=False, method="min")
  for k in RANKED:
    tot[f"{k}_wr"] = tg[k].rank(ascending=k in FEWER_BETTER, method="min")
  season_rank = {(int(r.season), r.player_id): {"trk": int(r.prk), "tr": [int(getattr(r, f"{k}_wr")) for k in RANKED]}
                 for r in tot.itertuples()}
  # Game grade, GRD (owner 2026-10-17: "pure output ... normalize it over an entire season, not just that week"): a
  # game's fantasy points as a percentile (0-99) among every regular-season game that season by QUALIFIED players at
  # his position (the season grade's pool: the NFL's per-team-game minimums, tools/grade_build.py QUALIFY), ties half.
  # Unlike Rk (that week's finish), a 22-point game grades the same in a quiet week as in a shootout week.
  from grade_build import QUALIFY  # noqa: E402 (tools/ is on the path as the script's folder)
  QCOL = {"att": "attempts", "ru_n": "carries", "rec": "reception"}
  tgm = st.groupby(["season", "team"]).week.nunique()
  last_tm = st.sort_values("week").groupby(["season", "player_id"]).team.last()
  grade_pool, qual_of = {}, {}
  need = [c for c in ("attempts", "carries", "reception") if c not in tot]  # the totals may already hold some
  qtot = tot.merge(st.groupby(["season", "player_id"])[need].sum().reset_index(), on=["season", "player_id"]) if need else tot
  for (season, pos), x in qtot.groupby(["season", "position"]):
    if pos not in QUALIFY:
      continue
    n_tg = np.array([tgm.get((season, last_tm.get((season, pid))), np.nan) for pid in x.player_id], float)
    ok = np.zeros(len(x), bool)
    for col, rate in QUALIFY[pos]:
      ok |= (x[QCOL[col]].to_numpy(float) >= rate * n_tg)
    q = set(x.player_id[ok])
    qual_of[(int(season), pos)] = q
    grade_pool[(int(season), pos)] = np.sort(st[(st.season == season) & (st.position == pos) & st.player_id.isin(q)].fp.to_numpy(float))
  # This season isn't over (owner 2026-10-17): its pool is this season's games so far plus LAST season's qualified
  # games from the weeks not played yet, so it has a full season's shape from week 1 and becomes all this season by
  # the end (five weeks alone made early percentiles jumpy).
  cur_s = int(st.season.max())
  done = int(st[st.season == cur_s].week.max())
  for pos in POS:
    prev = qual_of.get((cur_s - 1, pos))
    if prev is None or (cur_s, pos) not in grade_pool:
      continue
    fill = st[(st.season == cur_s - 1) & (st.position == pos) & (st.week > done) & st.player_id.isin(prev)].fp.to_numpy(float)
    grade_pool[(cur_s, pos)] = np.sort(np.concatenate([grade_pool[(cur_s, pos)], fill]))

  # this season's pool as percentiles (site scoring), for client-side game grades (Rankings colors a final score by
  # it; owner 2026-10-17): data/grades/game_pool.json {season, q: {pos: [p0 .. p100]}}
  gp_dir = site / "data" / "grades"
  gp_dir.mkdir(parents=True, exist_ok=True)
  (gp_dir / "game_pool.json").write_text(json.dumps({"season": cur_s, "q": {
    pos: [round(float(x), 2) for x in np.percentile(grade_pool[(cur_s, pos)], range(101))]
    for pos in POS if len(grade_pool.get((cur_s, pos), [])) >= 20}}, separators=(",", ":")), encoding="utf-8")

  def game_grade(season, pos, fp):
    v = grade_pool.get((int(season), pos))
    if v is None or len(v) < 20:
      return None
    below, upto = np.searchsorted(v, fp, "left"), np.searchsorted(v, fp, "right")
    return int(min(99, np.floor(100 * (below + 0.5 * (upto - below)) / len(v))))
  # Playoff games (owner, 2026-10-14: taken seriously, kept apart from the regular season): every season's POST rows
  post = [cache.get("stats", s, lambda: nfl.load_player_stats([s]).select(D.STAT_COLS), stale=False)
          for s in range(FIRST_SEASON, data.current_season + 1)]
  post = pd.concat([x[x.season_type == "POST"] for x in post if x is not None and len(x)], ignore_index=True)
  post = prep(post.assign(team=post.team.replace(D.RELOCATED), opponent_team=post.opponent_team.replace(D.RELOCATED)))
  # A playoff week has 2-12 teams, so ranking among them makes every conference-title QB a top-4 "starter" (owner
  # 2026-10-16). Instead: the rank it would have had in an average regular-season week that season, 1 + (that season's
  # regular-season player-weeks at the position that beat it) / (weeks).
  for (season, pos), g in post.groupby(["season", "position"]):
    ref = st[(st.season == season) & (st.position == pos)]
    if not len(ref):
      continue
    nw = ref.week.nunique()
    for k, col in [("fp", "prk")] + [(k, f"{k}_wr") for k in RANKED]:
      vals, v = np.sort(ref[k].to_numpy(float)), g[k].to_numpy(float)
      better = (np.searchsorted(vals, v, "left") if k in FEWER_BETTER
                else len(vals) - np.searchsorted(vals, v, "right"))
      post.loc[g.index, col] = np.round(1 + better / nw).astype(int)
  # Snap share: loaded seasons already carry gsis ids; older ones map pfr -> gsis through nflverse's player table.
  players = cache.get("players", "all", lambda: nfl.load_players(), stale=cache.age_hours("players", "all") > 24 * 7)
  pfr = players.dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates("pfr_id").set_index("pfr_id").gsis_id
  sn_old = [cache.get("snaps", s, lambda: nfl.load_snap_counts([s]), stale=False) for s in range(2012, first_loaded)]
  sn_old = [x[x.game_type == "REG"].assign(gsis_id=lambda x: x.pfr_player_id.map(pfr)) for x in sn_old if x is not None and len(x)]
  # every season through the player table's pfr -> gsis map (the loaded seasons' roster-based map misses ~30% of
  # rows, mostly linemen and defenders, and ~8% of skill players in 2020-24)
  sn = pd.concat(sn_old + [data.snaps], ignore_index=True)
  sn["gsis_id"] = sn.pfr_player_id.map(pfr).fillna(sn.gsis_id)
  sn = sn.dropna(subset=["gsis_id"])
  snap = sn.groupby(["season", "week", "gsis_id"]).offense_pct.max()
  sn_post = [cache.get("snaps", s, lambda: nfl.load_snap_counts([s]), stale=False) for s in range(2012, data.current_season + 1)]
  sn_post = pd.concat([x[x.game_type != "REG"] for x in sn_post if x is not None and len(x)], ignore_index=True)
  sn_post["gsis_id"] = sn_post.pfr_player_id.map(pfr)
  snap_post = sn_post.dropna(subset=["gsis_id"]).groupby(["season", "week", "gsis_id"]).offense_pct.max()
  ours, opp_rank, everyone = our_weeks(site)
  # Home / away for every past game (the stats feed doesn't say): full schedule history.
  allsched = cache.get("schedules", "since1999", lambda: nfl.load_schedules(list(range(FIRST_SEASON, data.current_season + 1))),
                       stale=cache.age_hours("schedules", "since1999") > 12)
  postsched = allsched[allsched.game_type.isin(["WC", "DIV", "CON", "SB"])]
  allsched = allsched[allsched.game_type == "REG"]
  round_of = {}
  for g in postsched.itertuples():
    h, a = D.RELOCATED.get(g.home_team, g.home_team), D.RELOCATED.get(g.away_team, g.away_team)
    neutral = g.location == "Neutral"  # Super Bowls: neither side is "@"
    for t, hm in ((h, 2 if neutral else 1), (a, 2 if neutral else 0)):
      round_of[(int(g.season), int(g.week), t)] = (g.game_type, hm, g.game_id)
  home_of, gid_of = {}, {}
  for g in allsched.itertuples():
    h, a = D.RELOCATED.get(g.home_team, g.home_team), D.RELOCATED.get(g.away_team, g.away_team)
    home_of[(int(g.season), int(g.week), h)] = 1
    home_of[(int(g.season), int(g.week), a)] = 0
    gid_of[(int(g.season), int(g.week), h)] = gid_of[(int(g.season), int(g.week), a)] = g.game_id

  # Upcoming weeks of this season (and byes) from the schedule.
  sched = data.schedules[(data.schedules.season == data.current_season) & (data.schedules.game_type == "REG")]
  last_week = int(sched.week.max())
  team_games = {}
  for g in sched.itertuples():
    team_games[(g.home_team, g.week)] = (g.away_team, 1, g.home_score)
    team_games[(g.away_team, g.week)] = (g.home_team, 0, g.home_score)
  cur_team = (data.rosters[data.rosters.season == data.current_season].sort_values("week")
              .drop_duplicates("gsis_id", keep="last").set_index("gsis_id").team)

  cpath = cache.path("contracts", "all")
  old = cpath.exists() and "last_year" not in pd.read_parquet(cpath).columns  # cached before last_year existed
  contracts = cache.get("contracts", "all", lambda: load_contracts(nfl), stale=old or cache.age_hours("contracts", "all") > 24)
  cache.save_meta()  # fetch times for players / contracts, so the next run honors their refresh intervals
  # Every roster since 2002 (bios, career teams for every player's page; loaded seasons come with the data)
  ros_cols = ["season", "week", "team", "gsis_id", "full_name", "position", "status", "jersey_number", "birth_date", "height",
              "weight", "college", "headshot_url", "years_exp", "espn_id", "status_description_abbr"]
  all_ros = pd.concat([x[[c for c in ros_cols if c in x]] for x in
                       [cache.get("rosters", s, lambda: nfl.load_rosters_weekly([s]), stale=False) for s in range(2002, first_loaded)]
                       + [data.rosters] if x is not None and len(x)], ignore_index=True)
  bios = bio_map(all_ros, data.draft, contracts)
  # a past player's card leads with NFL.com's photo when it's a real one: his signature team (Tomlinson a Charger, not
  # ESPN's last-team Jet); NFL's gray helmet renders stay behind ESPN's headshot (tools/photo_check.py)
  import photo_check
  past = {g: b["photo"] for g, b in bios.items() if b.get("photo") and b.get("exp_s", data.current_season) < data.current_season}
  for g in photo_check.real_photos(past, cache.dir):
    bios[g]["nfl_pic"] = 1
  # Hall of Fame class (tools/hof_build.py): the card's HOF badge
  hof_csv = ROOT / "data" / "history" / "hof.csv"
  if hof_csv.exists():
    for g, c in pd.read_csv(hof_csv)[["gsis_id", "cls"]].itertuples(index=False):
      bios.setdefault(g, {})["hof"] = int(c)
  # who actually played each game: any snaps (PFR, 2012 on). Weekly rosters only mark game-day inactives from 2019,
  # so before that "ACT" just means on the roster (Allen's 4 missed games in 2018 read as played).
  tot = sn[["offense_snaps", "defense_snaps", "st_snaps"]].fillna(0).sum(axis=1)
  played = set(zip(sn.gsis_id[tot > 0], sn.season[tot > 0].astype(int), sn.week[tot > 0].astype(int)))
  # plus any stat (weekly player stats, from the play-by-play): snap counts come from Pro Football Reference via
  # nflverse a day or more after a game (2026-10-18, Sunday night: snaps for 1 of 12 final games, stats for 9), and
  # until then a listed player who played read as a missed game. Same rule as returns.played_set.
  stat_played = set(zip(data.stats.player_id, data.stats.season.astype(int), data.stats.week.astype(int)))
  played |= stat_played
  prac = practice_timeline(data.practice, allsched, sn, all_ros, data.current_season, gameday_ina(site), stat_played, data.teams)
  # every earlier season with dated practice reports (2018 on; owner 2026-10-21: "shows ALL practices participation for
  # the selected season"): the same team-calendar timeline, gsis -> {season: events}, for the card's full-season sheet
  prac_hist = {}
  for s_ in range(2018, data.current_season):
    fp = cache.path("practice_dated", s_)
    if not fp.exists():
      continue
    tl = practice_timeline(pd.read_parquet(fp), allsched, sn, all_ros, s_, None, stat_played, data.teams)
    for g_, ev in tl.items():
      prac_hist.setdefault(g_, {})[str(s_)] = ev
  print(f"[logs] practice timelines for past seasons: {len(prac_hist)} players", flush=True)
  sn13 = sn[sn.season >= 2013]
  unit_snaps = {"off": sn13.groupby("gsis_id").offense_snaps.sum().to_dict(), "def": sn13.groupby("gsis_id").defense_snaps.sum().to_dict()}
  injuries = injury_history(cache, nfl, data.current_season, all_ros, allsched, played, unit_snaps,
                            ingame_events(cache, nfl, data.current_season, all_ros, site))
  scr = qb_scrambles(data.pbp)
  out_dir = site / "data" / "players"
  out_dir.mkdir(parents=True, exist_ok=True)
  everyone |= set(st.player_id.dropna())  # every QB / RB / WR / TE since 1999, not only those on our week pages
  pinfo = players.dropna(subset=["gsis_id"]).drop_duplicates("gsis_id").set_index("gsis_id")
  sts = st[st.player_id.isin(everyone)].sort_values(["season", "week"])
  by_player = {pid: g for pid, g in sts.groupby("player_id")}
  post_by = {pid: g for pid, g in post[post.player_id.isin(everyone)].sort_values(["season", "week"]).groupby("player_id")}
  sched_w, n_weeks = team_weeks(allsched)
  ros_w = roster_weeks(all_ros[all_ros.gsis_id.isin(everyone)], gameday_ina(site))
  n = 0
  for pid in everyone:
    g = by_player.get(pid)
    pos = g.position.iloc[-1] if g is not None and len(g) else None
    seasons = {}
    if g is not None:
      for r in g.itertuples():
        o = ours.get((int(r.season), int(r.week), pid), {})
        mr = o.get("mr") or opp_rank.get((int(r.season), int(r.week), r.opponent_team, r.position))
        sp = snap.get((int(r.season), int(r.week), pid))
        game = {"w": int(r.week), "o": r.opponent_team, "t": r.team, "h": home_of.get((int(r.season), int(r.week), r.team), 1),
                "c": [round(float(getattr(r, k)), 1) for k in SCORE_KEYS],
                "x": [int(r.completions), int(r.attempts), int(r.carries), int(r.targets)], "rk": int(r.prk),
                "r": [int(getattr(r, f"{k}_wr")) for k in RANKED]}
        gr = game_grade(r.season, r.position, r.fp)
        if gr is not None:
          game["gr"] = gr
        if sp is not None and not pd.isna(sp):
          game["sn"] = int(round(100 * float(sp)))
        if o.get("mu") is not None:
          game["mu"], game["mh"] = o["mu"], o["mh"]
          if o.get("mc"):
            game["mc"] = o["mc"]
        elif mr:
          game["mr"] = int(mr)
        if o.get("pj") is not None:
          game["pj"] = o["pj"]
          game["pjl"] = [round(float(v), 2) for v in o["pjl"]]
        _link(game, gid_of.get((int(r.season), int(r.week), r.team)))
        seasons.setdefault(int(r.season), []).append(game)
    playoffs = {}
    pg = post_by.get(pid)
    if pg is not None:
      for r in pg.itertuples():
        rnd = round_of.get((int(r.season), int(r.week), r.team))
        if rnd is None:
          continue
        game = {"w": int(r.week), "po": rnd[0], "o": r.opponent_team, "t": r.team, "h": rnd[1], "gid": rnd[2],
                "c": [round(float(getattr(r, k)), 1) for k in SCORE_KEYS],
                "x": [int(r.completions), int(r.attempts), int(r.carries), int(r.targets)], "rk": int(r.prk),
                "r": [int(getattr(r, f"{k}_wr")) for k in RANKED]}
        gr = game_grade(r.season, r.position, r.fp)  # against that season's regular-season pool
        if gr is not None:
          game["gr"] = gr
        sp = snap_post.get((int(r.season), int(r.week), pid))
        if sp is not None and not pd.isna(sp):
          game["sn"] = int(round(100 * float(sp)))
        playoffs.setdefault(int(r.season), []).append(game)
    # This season's remaining schedule (with byes), our projection and matchup where a page exists.
    team = cur_team.get(pid)
    upcoming = []
    if team is not None:
      played = {x["w"] for x in seasons.get(data.current_season, [])}
      for wk in range(1, last_week + 1):
        if wk in played:
          continue
        tg = team_games.get((team, wk))
        if tg is None:
          upcoming.append({"w": wk, "bye": 1})
          continue
        if pd.notna(tg[2]):
          continue  # game already final (he didn't play, or stats not in yet)
        o = ours.get((data.current_season, wk, pid), {})
        e = {"w": wk, "o": tg[0], "h": tg[1]}
        mr = o.get("mr") or (opp_rank.get((data.current_season, wk, tg[0], pos)) if pos else None)
        if o.get("mu") is not None:
          e["mu"], e["mh"] = o["mu"], o["mh"]
          if o.get("mc"):
            e["mc"] = o["mc"]
        elif mr:
          e["mr"] = int(mr)
        if o.get("pj") is not None:
          e["pj"] = o["pj"]
          e["pjl"] = [round(float(v), 2) for v in o["pjl"]]
        _link(e, gid_of.get((data.current_season, wk, team)))
        upcoming.append(e)
    name, espn = NAMES.get(pid, (None, None))
    if name is None and pid in pinfo.index:  # not on any week page of ours: nflverse's player table
      name, espn = pinfo.at[pid, "display_name"], espn_str(pinfo.at[pid, "espn_id"])
    doc = {"pid": pid, "name": name, "espn": espn, "pos": pos, "keys": SCORE_KEYS, "cur": data.current_season, "team": team,
           "seasons": [{"s": s, "g": seasons.get(s, []), **({"pg": playoffs[s]} if s in playoffs else {}),
                        **season_rank.get((s, pid), {}),
                        # the weeks he has no game in (this season's byes come with "up")
                        "m": missed_weeks(s, seasons.get(s, []), ros_w.get(pid, {}), sched_w, n_weeks.get(s, 0), gid_of,
                                          byes=s != data.current_season, snap_of=lambda w, s=s: snap.get((s, w, pid)))}
                       for s in sorted(set(seasons) | set(playoffs), reverse=True)], "up": upcoming,
           "bio": bios.get(pid, {})}
    if pid in injuries:
      doc["inj"] = injuries[pid]["eps"]
      doc["dur"] = injuries[pid].get("dur")
    if pid in prac:
      doc["prac"] = prac[pid]
    if pid in prac_hist:
      doc["prac_hist"] = prac_hist[pid]
    if pos == "QB" and pid in scr:
      doc["scr"] = scr[pid]  # {season: [scrambles, dropbacks]}
    (out_dir / f"{pid}.json").write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    n += 1
  size = sum(f.stat().st_size for f in out_dir.glob("*.json"))
  print(f"[logs] wrote {n} player game logs ({size / 1e6:.1f} MB) to {out_dir}", flush=True)
  other_logs(site, cache, nfl, data.current_season, allsched, pinfo, all_ros, sn, bios, written=set(everyone), injuries=injuries,
             post_snaps=sn_post, round_of=round_of, prac=prac, prac_hist=prac_hist)
  team_logs(site, cfg, data, cache, nfl, allsched, postsched)
  qb_throws(site, cache, nfl, data.pbp, data.current_season)
  dst_logs(site, cache, nfl, data, allsched)


# ---------------------------------------------------------------------------------------------------------------
# Every other player (defense, line, specialists): a page without the fantasy parts. kind = which stat set the page
# shows; the page reads the stat names from the doc ("keys"), so the stat choice lives in one place (here).
KIND_OF = {**{p: "off" for p in "QB RB WR TE FB HB".split()},
           **{p: "def" for p in "DE DT NT DL LB ILB OLB MLB CB S SS FS SAF DB".split()},
           **{p: "ol" for p in "T OT G OG C OL".split()}, "K": "k", "PK": "k", "P": "p", "LS": "ls"}
KIND_STATS = {
  "def": [("tk", "def_tackles_solo"), ("ast", "def_tackle_assists"), ("tfl", "def_tackles_for_loss"), ("sk", "def_sacks"),
          ("qbh", "def_qb_hits"), ("int", "def_interceptions"), ("pd", "def_pass_defended"), ("ff", "def_fumbles_forced"),
          ("fr", "fumble_recovery_opp"), ("td", "def_tds"), ("sf", "def_safeties"), ("blk", "def_blocks")],
  "k": [("fgm", "fg_made"), ("fga", "fg_att"), ("lng", "fg_long"), ("xpm", "pat_made"), ("xpa", "pat_att")],
  "p": [("pu", "pt_att"), ("yd", "pt_yards"), ("net", "pt_net_yards"), ("i20", "pt_inside_20"), ("lng", "pt_long")],
  "ol": [], "ls": [],
  # fullbacks and skill players without fantasy-relevant stats (blocking backs, depth WRs): the offense basics
  "off": [("car", "carries"), ("ryd", "rushing_yards"), ("rec", "receptions"), ("yd", "receiving_yards"), ("td", "receiving_tds")],
}
RET = [("kr", "kickoff_returns"), ("kry", "kickoff_return_yards"), ("pr", "punt_returns"), ("pry", "punt_return_yards")]
SNAP_UNIT = {"def": "defense_pct", "ol": "offense_pct", "off": "offense_pct", "k": "st_pct", "p": "st_pct", "ls": "st_pct"}
RANKED = ["pass_yd", "pass_td", "interception", "rush_yd", "rush_td", "reception", "rec_yd", "rec_td", "fumble_lost",
          "completions", "attempts", "carries", "targets"]  # = SCORE_KEYS + the game row's x stats, in that order
FEWER_BETTER = {"interception", "fumble_lost"}
BLOCKS = ["def_punt_blocks", "def_fg_blocks", "def_pat_blocks"]  # summed into def_blocks (blocked kicks, IDP scoring)
FULL_COLS = ["player_id", "player_display_name", "position", "season", "week", "season_type", "team", "opponent_team"] + \
  sorted(({c for v in KIND_STATS.values() for _, c in v} | {c for _, c in RET} | set(BLOCKS)) - {"def_blocks"})
# PFR's advanced defense per game (2018 on; load_pfr_advstats "def"), the page's "a" array in this order: pressures,
# hurries, blitzes, coverage targets / completions / yards / TDs allowed, missed tackles (owner 2026-10-18: "complete
# stats" for individual defenders). Sacks and QB hits come from the box score ("d").
ADV_DEF = [("prs", "def_pressures"), ("hur", "def_times_hurried"), ("blz", "def_times_blitzed"), ("tgt", "def_targets"),
           ("cmp", "def_completions_allowed"), ("yda", "def_yards_allowed"), ("tda", "def_receiving_td_allowed"),
           ("mt", "def_missed_tackles")]
ADV_FIRST = 2018


# Every regular-season week in a player's game log (owner 2026-10-16: "weeks the player didn't play should still be
# there"): the weeks he has no game get a row saying why, from his weekly roster status that week.
INA_FROM = 2019  # first season the weekly rosters mark game-day inactives (INA)


def practice_timeline(practice, allsched: pd.DataFrame, sn: pd.DataFrame, ros: pd.DataFrame, cur: int,
                      ina: dict | None = None, stat_played: set | None = None, teams: pd.DataFrame | None = None,
                      now: pd.Timestamp | None = None) -> dict:
  """gsis -> this season's practice days and games in date order (owner 2026-10-17: "the date the report was out,
  show the last 6, include games in that timeline, dates near each"). Events: ["p", date, D/L/F, game status on the
  week's last day or "", 1 when inferred], ["g", date, opponent, "vs"/"@", snap share or "out" or "" (upcoming), week].
  His TEAM's calendar, whatever his status (owner 2026-10-21, Jordan Mason on IR showed his week-1 practices as his
  latest): on a reserve list a day is ["p", date, "R", "IR" / "PUP" / "NFI" / "Res"] and a game's result is that tag;
  on the practice squad ["p", date, "S", "PS"] and "PS".
  Every report day of the season (owner 2026-10-18: "rows for every day we know there's practice. full participation
  if they're healthy that day and not listed"): his listing that day if he was on the report, else full participation
  while he's on the 53-man roster (ACT / INA that week; reserve lists, practice squad and free agents get no row).
  Report days: each team's days in the injury chronology (nfledge/chronology.py: the calendar fixed by game day, plus
  any day it filed), and only the ones whose report is in ("filed"). A day not filed yet, late, or never filed is
  unknown, not "full" (owner 2026-10-22, Rashee Rice read "Full, not on the report" on a Thursday KC hadn't filed: the
  timeline had its own notion of "the latest day reached"). Every rostered player this season; the card shows the
  latest few. now: the moment (None: the real time; tools/scenario_audit.py sets it)."""
  if practice is None or "dates" not in practice:
    return {}
  from types import SimpleNamespace
  from nfledge.chronology import Chronology
  pr = practice[(practice.season == cur) & practice.gsis_id.notna()]
  if not len(pr):
    return {}
  sch = allsched[allsched.season == cur]
  games = {}
  for g in sch.itertuples():
    for t, o, h in ((g.home_team, g.away_team, "vs"), (g.away_team, g.home_team, "@")):
      games[(D.RELOCATED.get(t, t), int(g.week))] = (str(g.gameday)[:10], D.RELOCATED.get(o, o), h, bool(pd.notna(g.home_score)), g.game_id)
  rc = ros[(ros.season == cur) & ros.gsis_id.notna()]
  rc = rc[["gsis_id", "week", "team", "status"] + (["status_description_abbr"] if "status_description_abbr" in rc else [])]
  team_wk = {(r.gsis_id, int(r.week)): ROSTER_TEAM.get(r.team, r.team) for r in rc.itertuples()}
  st_wk = {(r.gsis_id, int(r.week)): r.status for r in rc.itertuples()}
  # his reserve list that week (IR / PUP / NFI), for the days and games he spent on it
  res_wk = {(r.gsis_id, int(r.week)): roster_tag("RES", getattr(r, "status_description_abbr", None))
            for r in rc.itertuples() if r.status == "RES"}
  st_exact = st_wk  # that week's own roster row (no carry-forward)
  ina_posted = {(ROSTER_TEAM.get(t, t), int(w)) for t, w in zip(rc[rc.status == "INA"].team, rc[rc.status == "INA"].week)}  # game-day list out
  ros_weeks = sorted({int(w) for w in rc.week})
  snap = {(r.gsis_id, int(r.week)): r.offense_pct for r in sn[sn.season == cur][["gsis_id", "week", "offense_pct"]].itertuples()}
  # a game counts as played-or-missed once it is final AND its snap counts are published (the week clock's "final";
  # owner 2026-10-18: a game played today, or snaps not in yet, read as "did not play"). Per game: nflverse posts a
  # week's snaps game by game (2026-10-18: Josh Allen's late game read "did not play" beside the early games' snaps).
  snap_games = set(sn[sn.season == cur].game_id.dropna()) if "game_id" in sn else set()

  def at(m, gid, w):  # this week's roster row, else his latest earlier one (this week's roster not out yet)
    for k in range(w, 0, -1):
      v = m.get((gid, k))
      if v is not None:
        return v
    return None

  # what each listed player's report said, by date
  listed = {}
  for r in pr.sort_values("week").itertuples():
    ds = [d for d in str(r.dates or "").split(",") if d]
    if len(ds) != len(str(r.days)):
      continue
    gs = "" if r.game_status in (None, "None") else str(r.game_status).capitalize()
    for i, (d, c) in enumerate(zip(ds, str(r.days))):
      listed[(r.gsis_id, d)] = (c, gs if i == len(ds) - 1 else "")
  # each week's report days and their state, from the chronology (the one report calendar)
  src = SimpleNamespace(schedules=allsched, practice=pr, rosters=ros, teams=teams)
  cal = {w: Chronology(src, cur, w, now).day_states() for w in sorted({int(w) for w in pr.week})}
  last_w = max(cal) if cal else 0
  out = {}
  for gid in {g for g, _ in team_wk} | {g for g, _ in listed}:
    ev = []
    for w, tdays in cal.items():
      t, st = at(team_wk, gid, w), at(st_wk, gid, w)
      for d, state in (tdays.get(t) or {}).items() if t else ():
        if state != "filed":  # not in (yet): unknown
          continue
        if (gid, d) in listed:
          c, gs = listed[(gid, d)]
          ev.append(["p", d, c, gs])
        elif st in ("ACT", "INA"):
          ev.append(["p", d, "F", "", 1])  # 1 = inferred: on the roster, not on that day's report
        elif st == "RES":
          ev.append(["p", d, "R", at(res_wk, gid, w) or "Res"])  # on a reserve list that day
        elif st == "DEV":
          ev.append(["p", d, "S", "PS"])  # on the practice squad
    if not ev:
      continue
    for w in range(1, last_w + 2):  # his games through the week after the latest report week (the next one)
      t = at(team_wk, gid, w)
      gm = t and games.get((t, w))
      stw = at(st_wk, gid, w)
      if not gm or (w <= max(ros_weeks, default=0) and stw not in ("ACT", "INA", "RES", "DEV")):
        continue
      if stw in ("RES", "DEV") and (gid, w) not in team_wk and not any((gid, k) in team_wk for k in range(w, 0, -1)):
        continue
      s_ = snap.get((gid, w))
      # a final game: inactive (game-day list, ESPN's ruling, or a reserve list) = "out"; his snap share once
      # posted and over 0; else a stat line = "p" (played, share not out yet); else on the active list = "a" (dressed,
      # no snap or none posted yet: available, not a missed game). Snaps alone never make it "out" (owner 2026-10-18).
      res = ""
      if gm[3] and stw == "RES":
        res = at(res_wk, gid, w) or "Res"  # missed it on a reserve list
      elif gm[3] and stw == "DEV" and not ((gid, cur, w) in (stat_played or set()) or (snap.get((gid, w)) or 0) > 0):
        res = "PS"  # on the practice squad, not elevated
      elif gm[3]:
        rs = st_exact.get((gid, w))
        posted = (t, w) in ina_posted
        if (cur, w) in (ina or {}).get(gid, {}) or (posted and rs in ("INA", "RES")):
          res = "out"
        elif gm[4] in snap_games and s_ is not None and s_ == s_ and float(s_) > 0:
          res = int(round(100 * float(s_)))
        elif (gid, cur, w) in (stat_played or set()):
          res = "p"
        elif posted and rs == "ACT":
          res = "a"
        elif gm[4] in snap_games:
          res = "out"  # snaps posted, none for him, no game-day list to say otherwise
      ev.append(["g", gm[0], gm[1], gm[2], res, w])  # gm[3] (final) stays out of the file  # w: the week (the card dates "hurt in the week N game")
    ev.sort(key=lambda e: (e[1], 0 if e[0] == "p" else 1))
    out[gid] = ev
  return out


def roster_tag(status, abbr) -> str:
  if status == "INA":
    return "INA"  # declared inactive on game day (rosters mark it from 2019; before that he reads DNP)
  if status == "RES":
    return reserve_code(abbr)  # nfledge/codes.py: IR / PUP / NFI / SSPD, else "Res"
  return {"DEV": "PS", "CUT": "Cut", "RET": "Ret"}.get(status, "DNP")


def team_weeks(allsched: pd.DataFrame) -> tuple[dict, dict]:
  """(season, week, team) -> (opponent, home 1/0, final) for every regular-season game, relocated team codes; and
  season -> its last week with a finished game (all of a past season; this season so far: later weeks belong to the
  upcoming schedule, and rosters don't exist for them yet)."""
  games, n_weeks = {}, {}
  for g in allsched.itertuples():
    h, a = D.RELOCATED.get(g.home_team, g.home_team), D.RELOCATED.get(g.away_team, g.away_team)
    s, w, fin = int(g.season), int(g.week), pd.notna(g.home_score)
    games[(s, w, h)], games[(s, w, a)] = (a, 1, fin), (h, 0, fin)
    if fin:
      n_weeks[s] = max(n_weeks.get(s, 0), w)
  return games, n_weeks


def gameday_ina(site: Path) -> dict:
  """gsis_id -> {(season, week): team}: the game-day inactives ESPN ruled (run.py archives each week's rulings in
  data/live_inputs/gameday_<season>_<week>.json). nflverse's weekly rosters mark INA a day or two after the games
  (owner 2026-10-18: Tyler Warren's inactive week read as nothing meanwhile); this bridges that gap."""
  out = {}
  for f in (site / "data" / "live_inputs").glob("gameday_*.json"):
    try:
      s_, w = map(int, f.stem.split("_")[1:3])
      log = json.loads(f.read_text(encoding="utf-8"))
    except (ValueError, OSError):
      continue
    for g, v in log.items():
      if v.get("ruling") == "INA" and v.get("team"):
        t = "LA" if v["team"] == "LAR" else v["team"]
        out.setdefault(g, {})[(s_, w)] = D.RELOCATED.get(t, t)
  return out


def roster_weeks(ros: pd.DataFrame, ina: dict | None = None) -> dict:
  """gsis_id -> {(season, week): (team, status, status code)} from the weekly rosters (2002 on). ina (gameday_ina):
  game-day inactives for weeks the rosters don't mark yet (no row, or still ACT); a published INA / reserve stands."""
  r = ros.dropna(subset=["gsis_id"])[["gsis_id", "season", "week", "team", "status", "status_description_abbr"]]
  r = r.assign(team=r.team.replace({"LAR": "LA"}).map(lambda t: D.RELOCATED.get(t, t)))
  out = {}
  for g, s_, w, t, st_, ab in zip(r.gsis_id, r.season.astype(int), r.week.astype(int), r.team, r.status, r.status_description_abbr):
    out.setdefault(g, {})[(s_, w)] = (t, st_, ab)
  for g, wk in (ina or {}).items():
    for k, t in wk.items():
      cur = out.get(g, {}).get(k)
      if cur is None or cur[1] == "ACT":
        out.setdefault(g, {})[k] = (t, "INA", None)
  return out


def missed_weeks(season: int, games: list, ros_wk: dict, sched: dict, n_weeks: int, gid_of: dict,
                 byes: bool = True, snap_of=None) -> list:
  """Rows for the regular-season weeks of `season` he has no game in: {"w", "bye": 1} when his team was off, else
  {"w", "o", "h", "t", "miss": tag} (tag from roster_tag; "FA" = on no roster that week). Weeks whose game isn't
  final yet are left to the upcoming schedule. His team that week: the roster's, else (no roster that season, e.g.
  before 2002) the team of his nearest game."""
  played = {e["w"] for e in games}
  has_ros = any(k[0] == season for k in ros_wk)
  out = []
  for w in range(1, n_weeks + 1):
    if w in played:
      continue
    r = ros_wk.get((season, w))
    if r:
      team = r[0]
    elif has_ros:
      # no roster row: a team's bye week has none, so on the same team the weeks before and after = still his team;
      # otherwise he wasn't signed yet, or had been released
      before = [k for k in ros_wk if k[0] == season and k[1] < w]
      after = [k for k in ros_wk if k[0] == season and k[1] > w]
      t0 = ros_wk[max(before)][0] if before else None
      if t0 is None or not after or ros_wk[min(after)][0] != t0 or ros_wk[max(before)][1] in ("CUT", "RET"):
        out.append({"w": w, "miss": "FA"})
        continue
      team = t0
    elif games:
      team = min(games, key=lambda e: (abs(e["w"] - w), e["w"] > w))["t"]
    else:
      out.append({"w": w, "miss": "FA"})
      continue
    team = D.RELOCATED.get(team, team)
    g = sched.get((season, w, team))
    if g is None:
      if byes:
        out.append({"w": w, "bye": 1})
      continue
    if not g[2]:
      continue  # not played yet
    e = {"w": w, "o": g[0], "h": g[1], "t": team, "miss": roster_tag(r[1], r[2]) if r else "DNP"}
    sp = snap_of(w) if snap_of else None
    if sp is not None and not pd.isna(sp) and sp > 0:  # on the field without a stat (Allen's 1-snap week 18, 2024)
      e["miss"], e["sn"] = "", int(round(100 * float(sp)))
    _link(e, gid_of.get((season, w, team)))
    out.append(e)
  return out


def espn_str(e):
  if e is None or (isinstance(e, float) and pd.isna(e)):
    return None
  e = str(e).replace(".0", "")
  return e if e.isdigit() else None


def rows_by(df: pd.DataFrame | None, key: str) -> dict:
  """{key value: [row, ...]} in frame order, rows as plain namedtuples. One pass over the frame instead of a
  groupby into thousands of small frames read back row by row (that pandas overhead was most of this step's time);
  extension columns (pyarrow strings) go to object first, whose per-item access is far slower to iterate."""
  if df is None or not len(df):
    return {}
  ext = {c: object for c in df.columns if not isinstance(df[c].dtype, np.dtype)}
  out: dict = {}
  for r in (df.astype(ext) if ext else df).itertuples(index=False):
    out.setdefault(getattr(r, key), []).append(r)
  return out


def other_logs(site: Path, cache, nfl, cur: int, allsched: pd.DataFrame, pinfo: pd.DataFrame, ros: pd.DataFrame,
               snaps: pd.DataFrame, bios: dict, written: set, injuries: dict | None = None,
               post_snaps: pd.DataFrame | None = None, round_of: dict | None = None, prac: dict | None = None,
               prac_hist: dict | None = None):
  """<site>/data/players/<gsis>.json for everyone the fantasy pass didn't write: every player in nflverse's weekly
  stats (1999 on), on a weekly roster (2002 on) or in the snap counts (2012 on). Per game: his kind's stat line
  ("d", in "keys" order), returns ("r") when he had any, his unit's snap share ("sn"). Plus "ros": per season, his
  team(s) and weeks on the active roster (the career table for players without stats, e.g. linemen before 2012).
  Playoff games ("pg" per season, round in "po"), kept apart from the regular season like the fantasy pass."""
  r1 = lambda v: int(v) if float(v).is_integer() else round(float(v), 1)  # noqa: E731
  frames = []
  for s in range(FIRST_SEASON, cur + 1):
    x = cache.get("stats_full", s, lambda: nfl.load_player_stats([s]).select(FULL_COLS).to_pandas(),
                  stale=(s == cur and cache.age_hours("stats_full", s) > 6) or cache.lacks("stats_full", s, FULL_COLS))
    if x is not None and len(x):
      frames.append(x[x.season_type.isin(["REG", "POST"])])
  cache.save_meta()
  st = pd.concat(frames, ignore_index=True)
  st = st[~st.player_id.isin(written)].copy()
  for c in FULL_COLS[8:]:
    st[c] = pd.to_numeric(st[c], errors="coerce").fillna(0)
  st["def_blocks"] = st[BLOCKS].sum(axis=1)
  # PFR advanced defense, keyed (gsis, season, week); PFR ids map to gsis through nflverse's player table
  p2g = pinfo.reset_index().dropna(subset=["pfr_id"]).drop_duplicates("pfr_id").set_index("pfr_id")["gsis_id"] \
    if "pfr_id" in pinfo.columns else pd.Series(dtype=object)
  adv = {}
  for s in range(ADV_FIRST, cur + 1):
    a = cache.get("pfrdef", s, lambda: nfl.load_pfr_advstats([s], stat_type="def", summary_level="week"),
                  stale=s == cur and cache.age_hours("pfrdef", s) > 6)
    if a is None or not len(a):
      continue
    a = a[a.game_type == "REG"] if "game_type" in a else a
    for r in a.assign(g=a.pfr_player_id.map(p2g)).dropna(subset=["g"]).itertuples():
      adv[(r.g, int(r.season), int(r.week))] = [r1(getattr(r, c)) if pd.notna(getattr(r, c)) else 0 for _, c in ADV_DEF]
  for c in ("team", "opponent_team"):
    st[c] = st[c].replace(D.RELOCATED)
  pst, st = st[st.season_type == "POST"], st[st.season_type == "REG"]
  round_of = round_of or {}
  pst_by = rows_by(pst, "player_id")
  ps = post_snaps[post_snaps.gsis_id.notna()].assign(team=lambda x: x.team.replace(D.RELOCATED)) if post_snaps is not None else None
  psnap_by = rows_by(ps, "gsis_id")
  home_of, gid_of, opp_of = {}, {}, {}
  for g in allsched.itertuples():
    h, a = D.RELOCATED.get(g.home_team, g.home_team), D.RELOCATED.get(g.away_team, g.away_team)
    for t, o, hm in ((h, a, 2 if g.location == "Neutral" else 1), (a, h, 0)):
      home_of[(int(g.season), int(g.week), t)] = hm
      gid_of[(int(g.season), int(g.week), t)] = g.game_id
      opp_of[(int(g.season), int(g.week), t)] = o
  ros = ros.dropna(subset=["gsis_id"]).copy()
  ros["team"] = ros.team.replace(ROSTER_TEAM)
  sn = snaps[snaps.gsis_id.notna()].copy()
  sn["team"] = sn.team.replace(D.RELOCATED)
  # position: latest roster row, else latest stat row, else nflverse's player table
  pos_of = dict(zip(st.sort_values(["season", "week"]).player_id, st.sort_values(["season", "week"]).position))
  rs_sorted = ros.sort_values(["season", "week"])
  pos_of.update(dict(zip(rs_sorted.gsis_id, rs_sorted.position)))
  # real player ids only (00-0012345): one source carries a placeholder "0" that became data/players/0.json
  ids = {g for g in (set(st.player_id) | set(ros.gsis_id) | set(sn.gsis_id)) - written if isinstance(g, str) and GSIS_RE.match(g)}
  stat_by = rows_by(st, "player_id")
  snap_by = rows_by(sn, "gsis_id")
  # active-roster weeks per player and season, weeks in order (a stable sort: two teams in one week keep frame order)
  ros_by = rows_by(ros[ros.status == "ACT"].sort_values(["gsis_id", "season", "week"], kind="stable"), "gsis_id")
  sched_w, n_weeks = team_weeks(allsched)
  ros_w = roster_weeks(ros, gameday_ina(site))
  last_ros = rs_sorted.drop_duplicates("gsis_id", keep="last")
  name_of = dict(zip(st.player_id, st.player_display_name))
  name_of.update(dict(zip(last_ros.gsis_id, last_ros.full_name)))
  last_ros = {k: v[0] for k, v in rows_by(last_ros, "gsis_id").items()}
  # defenders' game grades (owner 2026-10-18: "get the grades working"): a game's IDP points (IDP123, as the season
  # grade) against every game that season by qualified defenders in his group; qualification is grade_build's
  import grade_build as GB
  dg, _, _, dqual = GB.defense_table(cache, cur, allsched)
  dpools = GB.defense_game_pools(dg, dqual)
  dgame = {(a, int(b), int(c)): (p, f) for a, b, c, p, f in zip(dg.gsis_id, dg.season, dg.week, dg.pos, dg.fp)}

  def def_grade(pid, s, w, pos):
    # on the field without a stat line (snaps only): a 0-point game in his group, not an ungraded one
    x = dgame.get((pid, s, w)) or ((GB.DEF_GROUP[pos], 0.0) if pos in GB.DEF_GROUP else None)
    v = dpools.get((s, x[0])) if x else None
    if v is None or len(v) < 20:
      return None
    below, upto = np.searchsorted(v, x[1], "left"), np.searchsorted(v, x[1], "right")
    return int(min(99, np.floor(100 * (below + 0.5 * (upto - below)) / len(v))))
  out_dir = site / "data" / "players"
  n = 0
  for pid in ids:
    pos = pos_of.get(pid)
    if not isinstance(pos, str) and pid in pinfo.index:
      pos = pinfo.at[pid, "position"]
    kind = KIND_OF.get(str(pos), "def" if isinstance(pos, str) else "ol")
    keys = KIND_STATS[kind]
    games = {}
    g = stat_by.get(pid)
    if g is not None:
      for r in g:
        key = (int(r.season), int(r.week))
        e = {"w": key[1], "t": r.team, "o": r.opponent_team, "h": home_of.get((key[0], key[1], r.team), 1)}
        if keys:
          e["d"] = [r1(getattr(r, c)) for _, c in keys]
        ret = [r1(getattr(r, c)) for _, c in RET]
        if any(ret):
          e["r"] = ret
        games[key] = e
    sg = snap_by.get(pid)
    unit = SNAP_UNIT[kind]
    if sg is not None:
      for r in sg:
        key = (int(r.season), int(r.week))
        e = games.get(key)
        if e is None:
          if not ((r.offense_snaps or 0) + (r.defense_snaps or 0) + (r.st_snaps or 0)):
            continue
          e = games[key] = {"w": key[1], "t": r.team, "o": opp_of.get((key[0], key[1], r.team), r.opponent),
                            "h": home_of.get((key[0], key[1], r.team), 1)}
          if keys:
            e["d"] = [0] * len(keys)
        pct = getattr(r, unit)
        if pd.notna(pct):
          e["sn"] = int(round(100 * float(pct)))
    if kind == "def":
      for (s, w), e in games.items():
        a = adv.get((pid, s, w))
        if a is not None:
          e["a"] = a
        gr = def_grade(pid, s, w, pos)
        if gr is not None:
          e["gr"] = gr
    seasons = {}
    for (s, w), e in sorted(games.items()):
      gid = gid_of.get((s, w, e["t"]))
      if gid:
        e["gid"] = gid
      seasons.setdefault(s, []).append(e)
    playoffs = {}  # (season, week) -> game, same shape + the round
    for r in pst_by.get(pid, []):
      rnd = round_of.get((int(r.season), int(r.week), r.team))
      if rnd is None:
        continue
      e = {"w": int(r.week), "po": rnd[0], "t": r.team, "o": r.opponent_team, "h": rnd[1], "gid": rnd[2]}
      if keys:
        e["d"] = [r1(getattr(r, c)) for _, c in keys]
      ret = [r1(getattr(r, c)) for _, c in RET]
      if any(ret):
        e["r"] = ret
      playoffs[(int(r.season), int(r.week))] = e
    for r in psnap_by.get(pid, []):
      key = (int(r.season), int(r.week))
      rnd = round_of.get((key[0], key[1], r.team))
      if rnd is None:
        continue
      e = playoffs.get(key)
      if e is None:
        if not ((r.offense_snaps or 0) + (r.defense_snaps or 0) + (r.st_snaps or 0)):
          continue
        e = playoffs[key] = {"w": key[1], "po": rnd[0], "t": r.team, "o": r.opponent, "h": rnd[1], "gid": rnd[2]}
        if keys:
          e["d"] = [0] * len(keys)
      pct = getattr(r, unit)
      if pd.notna(pct):
        e["sn"] = int(round(100 * float(pct)))
    pg = {}
    for (s, w), e in sorted(playoffs.items()):
      pg.setdefault(s, []).append(e)
    rs = {}
    by_season: dict = {}
    for r in ros_by.get(pid, []):
      by_season.setdefault(int(r.season), []).append(r)
    for s_, x in sorted(by_season.items()):
      rs[str(s_)] = ["/".join(dict.fromkeys(r.team for r in x)), len({r.week for r in x})]
    lr = last_ros.get(pid)
    team = lr.team if lr is not None and int(lr.season) == cur and lr.status not in ("CUT", "RET") else None
    espn = espn_str(getattr(lr, "espn_id", None)) if lr is not None else None
    if espn is None and pid in pinfo.index:
      espn = espn_str(pinfo.at[pid, "espn_id"])
    name = name_of.get(pid) or (pinfo.at[pid, "display_name"] if pid in pinfo.index else pid)
    doc = {"pid": pid, "name": name, "espn": espn, "pos": pos if isinstance(pos, str) else None, "kind": kind,
           "keys": [k for k, _ in keys], "ret_keys": [k for k, _ in RET], "cur": cur, "team": team,
           **({"adv_keys": [k for k, _ in ADV_DEF]} if kind == "def" else {}),
           "seasons": [{"s": s, "g": seasons.get(s, []), **({"pg": pg[s]} if s in pg else {}),
                        "m": missed_weeks(s, seasons.get(s, []), ros_w.get(pid, {}), sched_w, n_weeks.get(s, 0), gid_of)}
                       for s in sorted(set(seasons) | set(pg), reverse=True)], "ros": rs, "bio": bios.get(pid, {})}
    if injuries and pid in injuries:
      doc["inj"] = injuries[pid]["eps"]
      doc["dur"] = injuries[pid].get("dur")
    if prac and pid in prac:
      doc["prac"] = prac[pid]
    if prac_hist and pid in prac_hist:
      doc["prac_hist"] = prac_hist[pid]
    (out_dir / f"{pid}.json").write_text(json.dumps(_json_safe(doc), separators=(",", ":"), allow_nan=False), encoding="utf-8")
    n += 1
  print(f"[logs] wrote {n} other player pages (defense, line, specialists, players without fantasy stats)", flush=True)


# ---------------------------------------------------------------------------------------------------------------
# Injury history for the player page's Injuries tab: episodes built from every official injury report (2009 on:
# body part, game status) and the weekly rosters (2002 on: active / inactive / reserve lists), team game weeks only.
RESERVE = {k: v for k, v in RESERVE_CODES.items() if v in INJURY_LISTS}  # nfledge/codes.py: the injury lists
NOT_INJURY = re.compile(r"not injury|rest|personal|resting|coach", re.I)
SEVERITY = {"Questionable": 1, "Doubtful": 2, "Out": 3}


SNAPS_FROM = 2013  # games missed / played are counted from snap counts (nflverse has none for 2012)


def ingame_events(cache, nfl, cur: int, ros: pd.DataFrame, site: Path) -> dict:
  """(gsis, season) -> [(week, quarter or None, source)]: in-game injuries from the play-by-play notes ("was injured
  during the play", 2009 on; nfledge/ingame.py) and, this season, ESPN news blurbs ("left Sunday's game", "did not
  return"; tools/espn_news.py). Notes miss injuries without a stoppage; blurbs only exist for this season."""
  from nfledge import ingame
  out = {}
  for s in range(2009, cur + 1):
    rs = cache.get("rosters", s, lambda: nfl.load_rosters_weekly([s]), stale=False)  # full columns (jersey, names)
    if rs is None or not len(rs):
      continue
    n = ingame.load(cache, nfl, s, rs, stale=s == cur and cache.age_hours("ingame", s) > 6)
    if n is None or not len(n):
      continue
    n = ingame.hurt_rows(n)  # injuries, not returns
    n = n[(n.season_type == "REG") & n.gsis_id.notna()]
    for g, w, q in zip(n.gsis_id, n.week, n.qtr):
      out.setdefault((g, int(s)), []).append((int(w), int(q) if pd.notna(q) and q <= 4 else None, "pbp"))
  news = site / "data" / "espn_news" / "ingame.json"
  if news.exists():
    try:
      doc = json.loads(news.read_text(encoding="utf-8"))
      pl = cache.get("players", "all", lambda: nfl.load_players(), stale=False)
      gs = {str(e).replace(".0", ""): g for g, e in zip(pl.gsis_id, pl.espn_id) if isinstance(g, str) and pd.notna(e)}
      for e in doc.get("events", []):
        g = gs.get(str(e.get("espn")))
        if g and e.get("week"):
          out.setdefault((g, int(doc["season"])), []).append((int(e["week"]), e.get("q"), "news"))
    except Exception:
      pass
  return out


def injury_history(cache, nfl, cur: int, ros: pd.DataFrame, allsched: pd.DataFrame, played: set,
                   unit_snaps: dict | None = None,
                   ig: dict | None = None) -> dict:
  """gsis -> [episode], newest first. An episode = consecutive team games where he was on the injury report or a
  reserve list for an injury (a bye doesn't break it; a game played with no listing ends it). Per episode: season,
  first / last week, body part (the one listed most), games missed (not active), games played while listed, the
  reserve list if any, the worst game status."""
  inj = []
  for s in range(2009, cur + 1):
    x = D.season_injuries(cache, nfl, s)  # current season: NFL.com's report (one source)
    if x is not None and len(x):
      inj.append(x[x.game_type == "REG"][["season", "week", "gsis_id", "report_primary_injury", "practice_primary_injury", "report_status"]])
  inj = pd.concat(inj, ignore_index=True).dropna(subset=["gsis_id"])
  inj["part"] = inj.report_primary_injury.fillna(inj.practice_primary_injury).astype("string").str.strip().str.capitalize()  # "right Finger" -> "Right finger"
  inj = inj[inj.part.notna() & ~inj.part.astype(str).str.contains(NOT_INJURY)]
  listed = {(g, int(s), int(w)): (str(p), str(st) if isinstance(st, str) else "") for g, s, w, p, st in
            zip(inj.gsis_id, inj.season, inj.week, inj.part, inj.report_status)}
  games = set()
  for x in allsched.itertuples():
    if pd.isna(x.home_score):  # played games only (2026-10-22 audit: this week's roster row counted his game as played
      continue                 # or missed before kickoff, in the episode, the games total and durability)
    for t in (x.home_team, x.away_team):
      games.add((int(x.season), int(x.week), ROSTER_TEAM.get(t, t)))
  r = ros.dropna(subset=["gsis_id"])[["gsis_id", "season", "week", "team", "status", "status_description_abbr"]].copy()
  r["team"] = r.team.replace(ROSTER_TEAM)
  r = r[[(int(a), int(b), c) in games for a, b, c in zip(r.season, r.week, r.team)]]
  r = r[r.status.isin(["ACT", "INA", "RES"]) & (r.season >= 2009)]  # on the team for that game; 2009 on (official
  # reports; earlier weekly rosters are too sparse to count games: Brady's 2008 has one row)
  pos_of = ros.dropna(subset=["gsis_id"]).sort_values(["season", "week"]).drop_duplicates("gsis_id", keep="last").set_index("gsis_id").position
  r = r.sort_values(["gsis_id", "season", "week"]).drop_duplicates(["gsis_id", "season", "week"], keep="last")
  out = {}
  for gid, g in r.groupby("gsis_id", sort=False):
    eps, cur_ep = [], None

    def close():
      nonlocal cur_ep
      if cur_ep:
        # the part listed most; ties to the alphabetically first, as pandas' mode() sorts them (a Series per
        # episode was ~17 s of this step)
        cnt = Counter(cur_ep.pop("parts"))
        top = max(cnt.values(), default=0)
        cur_ep["part"] = min(k for k, n in cnt.items() if n == top) if cnt else ("Undisclosed" if cur_ep.get("list") else "")
        if not cur_ep.pop("counted"):
          cur_ep["missed"] = cur_ep["played"] = None  # before 2012: no snap counts to tell
        eps.append(cur_ep)
      cur_ep = None

    last_season = None
    wk_out = []  # (season, week, out injured): (S2) durability by snaps survived, tools/durability_eval.py
    for s, w, st, code in zip(g.season, g.week, g.status, g.status_description_abbr):
      s, w = int(s), int(w)
      if s != last_season:
        close()
        last_season = s
      lst = listed.get((gid, s, w))
      res = RESERVE.get(code) if st == "RES" else None
      counted = s >= SNAPS_FROM  # before snap counts nobody can tell who sat: listed, not counted
      # from 2019 the weekly rosters mark the game-day inactives: dressed (ACT) = available, whether or not he got a
      # snap (owner 2026-10-18: "0 snaps has never meant injured ... lots of players are active and don't play");
      # before that, a snap
      active = st == "ACT" if s >= INA_FROM else (gid, s, w) in played if counted else st == "ACT"
      if counted:
        wk_out.append((s, w, bool((lst or res) and not active)))
      if lst or res:  # a week off the report and off reserve lists ends the episode (backups who rarely play
        # would otherwise "miss" every later game)
        if cur_ep is None:
          cur_ep = {"s": s, "w0": w, "w1": w, "missed": 0, "played": 0, "parts": [], "worst": "", "counted": counted}
        cur_ep["w1"] = w
        if lst:
          cur_ep["parts"].append(lst[0])
          if SEVERITY.get(lst[1], 0) > SEVERITY.get(cur_ep["worst"], 0):
            cur_ep["worst"] = lst[1]
        if res:
          cur_ep["list"] = res
        if active:
          cur_ep["played"] += 1
        else:
          cur_ep["missed"] += 1
      elif cur_ep:
        close()
    close()
    # the game it started in: an in-game injury in the episode's first week or the week before it (hurt Sunday,
    # listed from the next report); the earliest such game, pbp note or news blurb
    for e in eps:
      evs = sorted((x for x in (ig or {}).get((gid, e["s"]), []) if e["w0"] - 1 <= x[0] <= e["w0"]), key=lambda x: x[0])
      if evs:
        wk = evs[0][0]
        qs = [x[1] for x in evs if x[0] == wk and x[1]]
        e["ig"] = [wk, qs[0] if qs else None]
    out[gid] = {"eps": [{k: v for k, v in e.items() if v not in ("", None)} for e in reversed(eps)],
                "games": int((g.season >= SNAPS_FROM).sum()), "missed": sum(e["missed"] or 0 for e in eps),
                # (S3) injuries that cost him a game, from SNAPS_FROM: the durability events (not games missed)
                "inj": sum(1 for e in eps if (e["missed"] or 0) > 0 and e["s"] >= SNAPS_FROM),
                # team games per season on the roster (not written to the pages; tools/durability_eval.py)
                "gs": {int(k): int(v) for k, v in g.season[g.season >= SNAPS_FROM].value_counts().items()},
                "wk": wk_out}
  # Durability: share of his team's games he was available for (games missed inside injury episodes count against
  # him; healthy scratches and suspensions don't), shrunk toward his position's average by one season of games
  # (17), then his percentile among everyone at the position with a season or more of games.
  grp = {**{p: "OL" for p in "T OT G OG C OL".split()}, **{p: "DL" for p in "DE DT NT DL".split()},
         **{p: "LB" for p in "LB ILB OLB MLB".split()}, **{p: "DB" for p in "CB S SS FS SAF DB".split()},
         "FB": "RB", "PK": "K"}
  # (S2, {#durability-snaps}; owner 2026-10-19: "a player who plays 3 snaps a game and never gets injured over 3
  # years" vs a 40-snap player who missed one game in 8 isn't more durable) skill and defensive players: games missed
  # injured per 1,000 snaps of his unit (offense / defense), shrunk toward the group's rate by K snaps (250; TE 2000),
  # percentile among the group's players with 1,000+ snaps. Judged by snaps survived before the next missed game it
  # beat the per-game share every season 2020-25. Kickers, punters, long snappers: the per-game share as before.
  # (S3, {#durability-episodes}; owner 2026-10-28: Josh Allen, one 2018 injury that cost 4 games, ranked below
  # one-season backups with none) the per-snap score counts injuries that cost a game, not games missed (one injury,
  # one event), shrunk 2,000 snaps (chosen 2014-19): better at predicting snaps survived in 5 of 6 seasons 2020-25
  df = pd.DataFrame([(g, v["games"], v["missed"], v.get("inj", 0)) for g, v in out.items()], columns=["gsis_id", "games", "missed", "inj"])
  df["grp"] = [grp.get(str(pos_of.get(g)), str(pos_of.get(g))) for g in df.gsis_id]
  prior = df[df.games >= 17].groupby("grp").apply(lambda x: 1 - x.missed.sum() / x.games.sum()).to_dict()
  df["avail"] = 1 - df.missed / df.games.where(df.games > 0, 1)
  df["shrunk"] = [(a * n + prior.get(gp, 0.95) * 17) / (n + 17) for a, n, gp in zip(df.avail, df.games, df.grp)]
  OFFG, DEFG = {"QB", "RB", "WR", "TE", "OL"}, {"DL", "LB", "DB"}
  us = unit_snaps or {}
  df["snaps"] = [float(us.get(("off" if gp in OFFG else "def"), {}).get(g, 0.0)) if gp in OFFG | DEFG else np.nan
                 for g, gp in zip(df.gsis_id, df.grp)]
  per_snap = df.grp.isin(OFFG | DEFG) & bool(us)
  r0 = {gp: x.inj.sum() / max(1.0, x.snaps.sum()) * 1000 for gp, x in df[per_snap].groupby("grp")}
  kk = {gp: 2000 for gp in OFFG | DEFG}
  df.loc[per_snap, "shrunk"] = [-((m + r0[gp] * kk[gp] / 1000) / ((sn + kk[gp]) / 1000))
                                for m, sn, gp in zip(df[per_snap].inj, df[per_snap].snaps, df[per_snap].grp)]
  qual = np.where(per_snap, df.snaps >= 1000, df.games >= 17)
  qs = pd.Series(qual, index=df.index)
  peers = {gp: np.sort(df.shrunk[(df.grp == gp) & qs].to_numpy(dtype=float)) for gp in df.grp.unique()}
  for x, q in zip(df.itertuples(), qual):
    pr = peers.get(x.grp)
    pct = float(np.searchsorted(pr, x.shrunk, side="right") / len(pr)) if pr is not None and len(pr) else None
    ps = bool(per_snap.loc[x.Index])
    out[x.gsis_id]["dur"] = {"games": int(x.games), "missed": int(x.missed), "avail": round(float(x.avail), 3),
                             # under 1,000 snaps: too little time on the field to rank either way (no percentile)
                             "pct": None if pct is None or (ps and not q) else round(pct, 3), "grp": x.grp, "small": not bool(q),
                             **({"snaps": int(x.snaps), "inj": int(x.inj),
                                 "per1k": round(float(x.inj / max(x.snaps, 1.0) * 1000), 2)} if ps else {})}
  return out


def _link(e: dict, gid) -> None:
  """Game id (every game: the log row opens its gamecast) + the week file holding our numbers for it (2021 on:
  the gamecast's Pregame tab and player cards need it)."""
  if not gid:
    return
  e["gid"] = gid
  ours = OUR_GAMES.get(gid)
  if ours:
    e["f"] = ours["file"]


CONTRACT_COLS = ["gsis_id", "is_active", "year_signed", "years", "value", "apy", "guaranteed", "apy_cap_pct",
                 "draft_year", "draft_overall"]


def load_contracts(nfl) -> pd.DataFrame:
  """OverTheCap contracts (nflverse) plus last_year: the final season he is actually paid, from the per-season
  history. Void years (added to spread bonus money; placeholder salaries like 85 or 99, but no cash) don't count:
  Allen's deal lists seasons to 2033 and pays through 2030; McCaffrey's through 2027 (lists 2030)."""
  c = nfl.load_contracts()
  def last_paid(h):
    yrs = [int(s["year"]) for s in (h or []) if str(s.get("year") or "").isdigit() and (s.get("cash_paid") or 0) > 0]
    return max(yrs) if yrs else None
  out = c.select(CONTRACT_COLS).to_pandas()
  paid = pd.Series([last_paid(h) for h in c["season_history"].to_list()], index=out.index, dtype="float")
  # A deal whose seasons have no cash posted yet (fresh minimum / practice-squad signings): its own length.
  own = out.year_signed + out.years.fillna(1) - 1
  out["last_year"] = paid.where(paid >= out.year_signed, own)
  return out


def draft_map(draft: pd.DataFrame | None, contracts: pd.DataFrame | None) -> dict:
  """gsis -> {"y": year, "r": round, "p": pick within the round, "o": overall} or {"u": 1} (undrafted). nflverse's
  draft table first; OverTheCap's draft year + overall pick (contracts) for players it lacks; undrafted = an
  OverTheCap player with no draft year."""
  if draft is None or not len(draft):
    return {}
  d = draft.dropna(subset=["round", "pick"]).copy()
  d["in_rd"] = d.pick - d.groupby(["season", "round"]).pick.transform("min") + 1
  rec = lambda x: {"y": int(x.season), "r": int(x["round"]), "p": int(x.in_rd), "o": int(x.pick)}
  out = {g: rec(x) for g, x in d.dropna(subset=["gsis_id"]).drop_duplicates("gsis_id").set_index("gsis_id").iterrows()}
  if contracts is not None:
    by_slot = {(int(x.season), int(x.pick)): rec(x) for _, x in d.iterrows()}
    for g, x in contracts.dropna(subset=["gsis_id"]).drop_duplicates("gsis_id").set_index("gsis_id").iterrows():
      if g in out:
        continue
      if pd.isna(x.draft_year):
        out[g] = {"u": 1}
      elif pd.notna(x.draft_overall) and (int(x.draft_year), int(x.draft_overall)) in by_slot:
        out[g] = by_slot[(int(x.draft_year), int(x.draft_overall))]
  return out


def contract_map(contracts: pd.DataFrame | None) -> dict:
  """gsis -> current contract (OverTheCap via nflverse): $M per year, total, years, guaranteed, share of the cap,
  year signed, and the season he'd reach free agency if not extended (the season after the last one he is paid;
  not signed + years: for an extension OverTheCap's years are only the ADDED years)."""
  if contracts is None or not len(contracts):
    return {}
  c = contracts[contracts.is_active.fillna(False).astype(bool)].dropna(subset=["gsis_id", "apy"])
  c = c.sort_values("year_signed").drop_duplicates("gsis_id", keep="last")
  r2 = lambda v: None if pd.isna(v) else round(float(v), 2)
  return {x.gsis_id: {k: v for k, v in {"apy": r2(x.apy), "val": r2(x.value), "gtd": r2(x.guaranteed), "cap": None if pd.isna(x.apy_cap_pct) else round(float(x.apy_cap_pct), 4),
                                        "from": int(x.year_signed), "yrs": None if pd.isna(x.years) else int(x.years),
                                        "fa": None if pd.isna(getattr(x, "last_year", np.nan)) else int(x.last_year) + 1}.items()
                      if v is not None}
          for x in c.itertuples()}


def bio_map(rosters: pd.DataFrame, draft: pd.DataFrame | None = None, contracts: pd.DataFrame | None = None) -> dict:
  """gsis -> card bio from each player's latest roster row: jersey number, birth date, height (in), weight (lb),
  accrued seasons as of that roster season, college, official headshot URL; plus draft slot and current contract."""
  r = rosters.dropna(subset=["gsis_id"]).sort_values(["season", "week"]).drop_duplicates("gsis_id", keep="last")
  num = lambda v: None if pd.isna(v) else int(v)
  drafts, deals = draft_map(draft, contracts), contract_map(contracts)
  out = {}
  for x in r.itertuples():
    b = {"num": num(getattr(x, "jersey_number", None)), "ht": num(getattr(x, "height", None)),
         "wt": num(getattr(x, "weight", None)), "exp": num(getattr(x, "years_exp", None)), "exp_s": int(x.season)}
    bd = getattr(x, "birth_date", None)
    if bd is not None and not pd.isna(bd):
      b["born"] = str(bd)[:10]
    for k, col in (("college", "college"), ("photo", "headshot_url")):
      v = getattr(x, col, None)
      if isinstance(v, str) and v:
        b[k] = headshot_url(v) if k == "photo" else v
    if x.gsis_id in drafts:
      b["draft"] = drafts[x.gsis_id]
    if x.gsis_id in deals:
      b["deal"] = deals[x.gsis_id]
    out[x.gsis_id] = {k: v for k, v in b.items() if v is not None}
  return out


# D/ST stat line per game (owner 2026-10-18: D/ST cards). Keys match the browser's D/ST scorer (shell.js NFLE.kdst
# DSTAT) plus points and yards allowed, so a finished game is scored with the league's own D/ST rules.
DST_KEYS = ["sack", "int", "fum_rec", "ff", "def_td", "st_td", "safe", "blk", "pass_def", "tkl_loss", "forced_punts", "def_2pt", "pa", "ya"]


def dst_logs(site: Path, cache, nfl, data, allsched: pd.DataFrame) -> None:
  """data/dst/<TEAM>.json: {team, keys, seasons: [{s, g: [{w, o, h, gid, l: [DST_KEYS values]}]}]} for this season and
  last, regular season. Team stats from nflverse (load_team_stats, weekly); forced punts from play-by-play (the
  opponent's punts); points allowed = the opponent's score; yards allowed = the opponent's net yards."""
  cur = data.current_season
  seasons = [cur - 1, cur]
  frames = []
  for season in seasons:
    t = cache.get("teamstats", season, lambda: nfl.load_team_stats([season], summary_level="week"),
                  stale=(season == cur and cache.age_hours("teamstats", season) > 6))
    if t is not None and len(t):
      frames.append(t[t.season_type == "REG"])
  if not frames:
    return
  t = pd.concat(frames, ignore_index=True)
  for c in ("team", "opponent_team"):
    t[c] = t[c].replace(D.RELOCATED)
  num = lambda c: pd.to_numeric(t[c], errors="coerce").fillna(0) if c in t else pd.Series(0.0, index=t.index)
  t = t.assign(
    sack=num("def_sacks"), int=num("def_interceptions"), fum_rec=num("fumble_recovery_opp"), ff=num("def_fumbles_forced"),
    # def_tds already holds the defense's fumble-return TDs; fumble_recovery_tds would add offenses recovering their own
    # fumble in the end zone (2025: Texans wk 15, Titans wk 5) - not D/ST points
    def_td=num("def_tds"), st_td=num("special_teams_tds"), safe=num("def_safeties"),
    blk=num("def_punt_blocks") + num("def_fg_blocks") + num("def_pat_blocks"), pass_def=num("def_pass_defended"),
    tkl_loss=num("def_tackles_for_loss"), def_2pt=num("def_2pt_made"),
    oyd=num("passing_yards") + num("rushing_yards") - num("sack_yards_lost").abs())
  # the opponent's row: its net yards are this defense's yards allowed
  opp_yd = dict(zip(zip(t.game_id, t.team), t.oyd))
  pb = data.pbp[(data.pbp.season.isin(seasons)) & (data.pbp.play_type == "punt")]
  punts = pb.groupby(["game_id", "posteam"]).size().to_dict()
  sch = allsched[allsched.season.isin(seasons) & (allsched.game_type == "REG")]
  score = {}
  for g in sch.itertuples():
    if pd.notna(g.home_score):
      h, a = D.RELOCATED.get(g.home_team, g.home_team), D.RELOCATED.get(g.away_team, g.away_team)
      score[(g.game_id, h)], score[(g.game_id, a)] = (int(g.away_score), 1), (int(g.home_score), 0)
  out_dir = site / "data" / "dst"
  out_dir.mkdir(parents=True, exist_ok=True)
  n = 0
  for team, g in t.sort_values(["season", "week"]).groupby("team"):
    by = {}
    for r in g.itertuples():
      pa = score.get((r.game_id, team))
      if pa is None:
        continue
      line = [float(getattr(r, k)) for k in DST_KEYS[:10]]
      line += [float(punts.get((r.game_id, r.opponent_team), 0)), float(r.def_2pt), float(pa[0]),
               float(opp_yd.get((r.game_id, r.opponent_team), 0.0))]
      by.setdefault(int(r.season), []).append({"w": int(r.week), "o": r.opponent_team, "h": pa[1], "gid": r.game_id,
                                               "l": [round(v, 1) for v in line]})
    doc = {"team": team, "cur": cur, "keys": DST_KEYS, "seasons": [{"s": s_, "g": by[s_]} for s_ in sorted(by, reverse=True)]}
    (out_dir / f"{team}.json").write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    n += 1
  print(f"[logs] wrote {n} D/ST game logs to {out_dir}", flush=True)


# pass direction, kept out of the model's PBP_COLS (adding one there refetches every cached season of the model's play-by-
# play): its own small cache of [game_id, play_id, pass_location] per season, refetched when the season has new games
LOC_COLS = ["game_id", "play_id", "pass_location"]
RES = {"inc": 0, "comp": 1, "td": 2, "int": 3}


def qb_throws(site: Path, cache, nfl, pbp: pd.DataFrame, cur: int) -> None:
  """Every regular-season pass a QB threw in the loaded seasons, for the player card's Throws chart (owner 2026-10-17:
  the air-yards-by-side graphic): data/throws/<gsis>.json = {pid, keys, s: {season: [[week, quarter, air yards, side
  (0 left / 1 middle / 2 right / -1 unknown), result (0 incomplete / 1 complete / 2 TD / 3 INT), YAC or null,
  receiver, play id], ...]}}. Spikes and throws without air yards (nflverse leaves them blank) are left out."""
  x = pbp[(pbp.season_type == "REG") & pbp.passer_player_id.notna() & pbp.air_yards.notna() & (pbp.qb_spike != 1)
          & (pbp.pass_attempt == 1) & (pbp.sack != 1)]
  locs = []
  for season in sorted(x.season.unique()):
    season = int(season)
    want = set(x[x.season == season].game_id)
    loc = cache.get("pbploc", season, lambda: nfl.load_pbp([season]).select(LOC_COLS), stale=False)
    if loc is None or (season == cur and want - set(loc.game_id)):
      loc = cache.get("pbploc", season, lambda: nfl.load_pbp([season]).select(LOC_COLS), stale=True)
    if loc is not None:
      locs.append(loc)
  if locs:
    x = x.merge(pd.concat(locs, ignore_index=True), on=["game_id", "play_id"], how="left")
  else:
    x = x.assign(pass_location=None)
  side = x.pass_location.map({"left": 0, "middle": 1, "right": 2}).fillna(-1).astype(int)
  res = np.where(x.interception == 1, RES["int"], np.where(x.pass_touchdown == 1, RES["td"],
                 np.where(x.complete_pass == 1, RES["comp"], RES["inc"])))
  x = x.assign(side=side, res=res)
  out_dir = site / "data" / "throws"
  out_dir.mkdir(parents=True, exist_ok=True)
  n = 0
  for pid, g in x.sort_values(["season", "week", "play_id"]).groupby("passer_player_id"):
    if len(g) < 20:  # a trick-play passer, not a QB
      continue
    seasons = {}
    for r in g.itertuples():
      yac = None if pd.isna(r.yards_after_catch) else int(r.yards_after_catch)
      rec = r.receiver_player_name if isinstance(r.receiver_player_name, str) else ""
      seasons.setdefault(str(int(r.season)), []).append([int(r.week), int(r.qtr), int(r.air_yards), int(r.side), int(r.res),
                                                         yac, rec, int(r.play_id)])
    doc = {"pid": pid, "keys": ["w", "q", "air", "side", "res", "yac", "rec", "play"], "s": seasons}
    (out_dir / f"{pid}.json").write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    n += 1
  size = sum(f.stat().st_size for f in out_dir.glob("*.json"))
  print(f"[logs] wrote {n} QB throw charts ({size / 1e6:.1f} MB) to {out_dir}", flush=True)


def qb_scrambles(pbp: pd.DataFrame) -> dict:
  """gsis -> {season: [scrambles, dropbacks]} from play-by-play (loaded seasons)."""
  db = pbp[pbp.is_dropback.astype(bool)] if "is_dropback" in pbp else pbp[pbp.qb_dropback == 1]
  db = db.assign(gsis_id=db.passer_player_id.fillna(db.rusher_player_id)).dropna(subset=["gsis_id"])
  g = db.groupby(["gsis_id", "season"]).agg(scr=("qb_scramble", "sum"), n=("qb_scramble", "size"))
  out = {}
  for (gid, s), x in g.iterrows():
    out.setdefault(gid, {})[str(int(s))] = [int(x.scr), int(x.n)]
  return out


def _team_stat_rows(cache, nfl, seasons: list, current: int) -> pd.DataFrame:
  frames = []
  for s in seasons:
    t = cache.get("teamstats", s, lambda: nfl.load_team_stats([s], summary_level="week"),
                  stale=(s == current and cache.age_hours("teamstats", s) > 6))
    if t is not None and len(t):
      frames.append(t[t.season_type.isin(["REG", "POST"])])
  t = pd.concat(frames, ignore_index=True)
  for c in ("team", "opponent_team"):
    t[c] = t[c].replace(D.RELOCATED)
  num = lambda c: pd.to_numeric(t[c], errors="coerce").fillna(0) if c in t else 0
  plays = num("attempts") + num("sacks_suffered") + num("carries")
  out = pd.DataFrame({
    "game_id": t.game_id, "team": t.team,
    "py": num("passing_yards") + num("sack_yards_lost").where(num("sack_yards_lost") <= 0, -num("sack_yards_lost")),
    "ry": num("rushing_yards"), "plays": plays,
    "to": num("passing_interceptions") + num("sack_fumbles_lost") + num("rushing_fumbles_lost") + num("receiving_fumbles_lost"),
    "fd": num("passing_first_downs") + num("rushing_first_downs"), "sk": num("sacks_suffered"),
    "pen": num("penalty_yards")})
  out["yd"] = out.py + out.ry
  # Yards per play, not EPA: nflverse's team passing EPA leaves sacks out while the play count includes them,
  # which inflates every team's EPA per play (rankings would survive, the shown number would not).
  out["ep"] = out.yd / out.plays.where(out.plays > 0, np.nan)
  return out.set_index(["game_id", "team"])


def team_logs(site: Path, cfg: dict, data, cache, nfl, allsched: pd.DataFrame, postsched: pd.DataFrame | None = None):
  """<site>/data/teams/<TEAM>.json: every regular-season game since 1999 with score, Vegas line and result
  against it, both teams' Elo going in, per-game stats for and against (yards, yards per play, turnovers...), and
  from 2021 on our pregame win chances and both teams' power ranks that week; season summaries with league ranks;
  and this season's remaining schedule."""
  from nfledge import elo
  wm = cfg["report"]["win_model"]
  cur = data.current_season
  g = elo.finished(allsched.assign(home_team=allsched.home_team.replace(D.RELOCATED),
                                   away_team=allsched.away_team.replace(D.RELOCATED)))
  pre = []
  elo.run(g, wm["elo_k"], wm["elo_hfa"], wm["elo_revert"], wm["elo_margin"], pre=pre)
  g = g.assign(elo_h=[round(x[0]) for x in pre], elo_a=[round(x[1]) for x in pre])
  g = g[g.game_type == "REG"]
  ts = _team_stat_rows(cache, nfl, sorted(g.season.unique()), cur)
  rows = []
  for x in g.itertuples():
    for team, opp, home, ps, pa, el, oel in ((x.home_team, x.away_team, 1, x.home_score, x.away_score, x.elo_h, x.elo_a),
                                             (x.away_team, x.home_team, 0, x.away_score, x.home_score, x.elo_a, x.elo_h)):
      line = (x.spread_line if home else -x.spread_line) if pd.notna(x.spread_line) else None  # + = favored by
      rows.append({"season": int(x.season), "week": int(x.week), "gid": x.game_id, "team": team, "opp": opp,
                   "h": 2 if x.location == "Neutral" else home, "ps": int(ps), "pa": int(pa), "line": line,
                   "tot": float(x.total_line) if pd.notna(x.total_line) else None, "elo": int(el), "oelo": int(oel),
                   "ot": bool(x.overtime == 1)})
  T = pd.DataFrame(rows)
  T["r"] = np.where(T.ps > T.pa, "W", np.where(T.ps < T.pa, "L", "T"))
  for k in ("yd", "py", "ry", "ep", "to", "fd", "sk"):
    # one plain dict per stat, (game id, team) -> value: a pandas cell lookup per game was ~25 s of this step
    lk = ts[k].to_dict() if k in ts.columns else {}
    stat = lambda gid, team: None if pd.isna(v := lk.get((gid, team), np.nan)) else float(v)  # noqa: E731
    T[k] = [stat(a, b) for a, b in zip(T.gid, T.team)]
    T["o_" + k] = [stat(a, b) for a, b in zip(T.gid, T.opp)]
  # season summaries + league ranks (per-game averages; 1 = best)
  agg = T.groupby(["season", "team"]).agg(gp=("ps", "size"), w=("r", lambda s: (s == "W").sum()), l=("r", lambda s: (s == "L").sum()),
                                          t=("r", lambda s: (s == "T").sum()), pf=("ps", "mean"), pa=("pa", "mean"),
                                          yd=("yd", "mean"), oyd=("o_yd", "mean"), ep=("ep", "mean"), oep=("o_ep", "mean"),
                                          to=("to", "mean"), oto=("o_to", "mean"))
  agg["tom"] = agg.oto - agg.to
  better_high = {"pf": True, "pa": False, "yd": True, "oyd": False, "ep": True, "oep": False, "tom": True}
  for k, hi in better_high.items():
    agg[k + "_rk"] = agg.groupby("season")[k].rank(ascending=not hi, method="min")
  # this season's remaining games
  sched = data.schedules[(data.schedules.season == cur) & (data.schedules.game_type == "REG")]
  out_dir = site / "data" / "teams"
  out_dir.mkdir(parents=True, exist_ok=True)
  r1 = lambda v, n=1: None if v is None or pd.isna(v) else round(float(v), n)
  # playoff games per (team, season), kept apart from the regular season (round in "po")
  po = {}
  ts_rows = ts.to_dict("index")  # (game id, team) -> its stats, for the per-game lookups below
  for x in (postsched.itertuples() if postsched is not None else []):
    if pd.isna(x.home_score):
      continue
    h, a = D.RELOCATED.get(x.home_team, x.home_team), D.RELOCATED.get(x.away_team, x.away_team)
    nt = x.location == "Neutral"
    for team, opp, home, ps_, pa_ in ((h, a, 2 if nt else 1, x.home_score, x.away_score), (a, h, 2 if nt else 0, x.away_score, x.home_score)):
      e = {"w": int(x.week), "po": x.game_type, "gid": x.game_id, "o": opp, "h": home, "ps": int(ps_), "pa": int(pa_),
           "r": "W" if ps_ > pa_ else "L" if ps_ < pa_ else "T"}
      if x.overtime == 1:
        e["ot"] = 1
      if pd.notna(x.spread_line):
        line = x.spread_line if team == h else -x.spread_line
        e["ln"] = r1(line)
        m = ps_ - pa_ - line
        e["ats"] = "W" if m > 0 else "L" if m < 0 else "P"
      def stat(t, k):
        v = ts_rows.get((x.game_id, t), {}).get(k, np.nan)
        return None if pd.isna(v) else float(v)
      e["s"] = [r1(stat(team, "yd"), 0), r1(stat(team, "py"), 0), r1(stat(team, "ry"), 0), r1(stat(team, "ep")), r1(stat(team, "to"), 0), r1(stat(team, "fd"), 0)]
      e["os"] = [r1(stat(opp, "yd"), 0), r1(stat(opp, "py"), 0), r1(stat(opp, "ry"), 0), r1(stat(opp, "ep")), r1(stat(opp, "to"), 0)]
      po.setdefault((team, int(x.season)), []).append(e)
  for team in sorted(T.team.unique()):
    if team not in set(sched.home_team) | set(sched.away_team):
      continue  # defunct codes
    me = T[T.team == team].sort_values(["season", "week"])
    seasons = []
    for s, gs in me.groupby("season"):
      a = agg.loc[(s, team)]
      games = []
      for x in gs.itertuples():
        e = {"w": x.week, "gid": x.gid, "o": x.opp, "h": x.h, "ps": x.ps, "pa": x.pa, "r": x.r, "elo": x.elo, "oelo": x.oelo}
        if x.ot:
          e["ot"] = 1
        if x.line is not None and not pd.isna(x.line):
          e["ln"] = r1(x.line)
          m = x.ps - x.pa - x.line
          e["ats"] = "W" if m > 0 else "L" if m < 0 else "P"
        if x.tot is not None and not pd.isna(x.tot):
          e["tot"] = r1(x.tot)
        e["s"] = [r1(x.yd, 0), r1(x.py, 0), r1(x.ry, 0), r1(x.ep), r1(x.to, 0), r1(x.fd, 0)]
        e["os"] = [r1(x.o_yd, 0), r1(x.o_py, 0), r1(x.o_ry, 0), r1(x.o_ep), r1(x.o_to, 0)]
        ours = OUR_GAMES.get(x.gid)
        if ours:
          fc, home = ours["fc"], ours["home"] == team
          if fc.get("src") == "Vegas" and fc.get("p_home") is not None:
            e["vc"] = fc["p_home"] if home else fc["p_away"]
          if fc.get("model_pct") is not None:
            e["mc"] = fc["model_pct"] if fc.get("model_fav") == team else 100 - fc["model_pct"]
          if ours["pr"]:
            mine, theirs = (ours["pr"][1], ours["pr"][0]) if home else (ours["pr"][0], ours["pr"][1])
            if mine:
              e["pr"] = int(mine)
            if theirs:
              e["opr"] = int(theirs)
          e["f"] = ours["file"]
        games.append(e)
      seasons.append({"s": int(s), "rec": f"{int(a.w)}-{int(a.l)}" + (f"-{int(a.t)}" if a.t else ""),
                      "avg": {k: r1(a[k], 1 if k not in ("ep", "oep") else 2) for k in ("pf", "pa", "yd", "oyd", "ep", "oep", "tom")},
                      "rk": {k: int(a[k + "_rk"]) for k in better_high if pd.notna(a[k + "_rk"])}, "g": games,
                      **({"pg": sorted(po[(team, int(s))], key=lambda e: e["w"])} if (team, int(s)) in po else {})})
    played = {e["w"] for x in seasons if x["s"] == cur for e in x["g"]}
    up = []
    for x in sched.itertuples():
      if team not in (x.home_team, x.away_team) or x.week in played or pd.notna(x.home_score):
        continue
      home = x.home_team == team
      e = {"w": int(x.week), "gid": x.game_id, "o": x.away_team if home else x.home_team,
           "h": 2 if x.location == "Neutral" else int(home)}
      if pd.notna(x.spread_line):
        e["ln"] = r1(x.spread_line if home else -x.spread_line)
      ours = OUR_GAMES.get(x.game_id)
      if ours:
        fc = ours["fc"]
        if fc.get("src") == "Vegas" and fc.get("p_home") is not None:
          e["vc"] = fc["p_home"] if home else fc["p_away"]
        if fc.get("model_pct") is not None:
          e["mc"] = fc["model_pct"] if fc.get("model_fav") == team else 100 - fc["model_pct"]
        if ours["pr"]:
          e["opr"] = int(ours["pr"][0] if home else ours["pr"][1])
        e["f"] = ours["file"]
      up.append(e)
    byes = sorted(set(range(1, int(sched.week.max()) + 1))
                  - set(int(w) for w in sched[(sched.home_team == team) | (sched.away_team == team)].week))
    doc = {"team": team, "cur": cur, "byes": byes, "seasons": sorted(seasons, key=lambda x: -x["s"]), "up": up,
           "stat_keys": ["yd", "py", "ry", "ypp", "to", "fd"]}
    (out_dir / f"{team}.json").write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
  size = sum(f.stat().st_size for f in out_dir.glob("*.json"))
  print(f"[logs] wrote {len(list(out_dir.glob('*.json')))} team game logs ({size / 1e6:.1f} MB) to {out_dir}", flush=True)


if __name__ == "__main__":
  main()
