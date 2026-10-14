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
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config, load_scoring  # noqa: E402
from nfledge.report import SCORE_KEYS, headshot_url  # noqa: E402

FIRST_SEASON = 1999
POS = ("QB", "RB", "WR", "TE")


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
  st = pd.concat(old + [data.stats], ignore_index=True)
  st = st[st.position.isin(POS)].copy()
  for c in D.STAT_COLS[8:]:
    st[c] = pd.to_numeric(st[c], errors="coerce").fillna(0)
  st["fumble_lost"] = st.sack_fumbles_lost + st.rushing_fumbles_lost + st.receiving_fumbles_lost
  ren = {"passing_yards": "pass_yd", "passing_tds": "pass_td", "passing_interceptions": "interception",
         "rushing_yards": "rush_yd", "rushing_tds": "rush_td", "receptions": "reception", "receiving_yards": "rec_yd",
         "receiving_tds": "rec_td"}
  st = st.rename(columns=ren)
  w = {k: float(v) for k, v in scoring.weights.items()}
  st["fp"] = sum(st[k] * w.get(k, 0.0) for k in SCORE_KEYS) + np.where(st.position == "TE", st.reception * float(scoring.te_reception_bonus), 0)
  st["prk"] = st.groupby(["season", "week", "position"]).fp.rank(ascending=False, method="min").astype(int)
  # Snap share: loaded seasons already carry gsis ids; older ones map pfr -> gsis through nflverse's player table.
  players = cache.get("players", "all", lambda: nfl.load_players(), stale=cache.age_hours("players", "all") > 24 * 7)
  pfr = players.dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates("pfr_id").set_index("pfr_id").gsis_id
  sn_old = [cache.get("snaps", s, lambda: nfl.load_snap_counts([s]), stale=False) for s in range(2012, first_loaded)]
  sn_old = [x[x.game_type == "REG"].assign(gsis_id=lambda x: x.pfr_player_id.map(pfr)) for x in sn_old if x is not None and len(x)]
  sn = pd.concat(sn_old + [data.snaps], ignore_index=True).dropna(subset=["gsis_id"])
  snap = sn.groupby(["season", "week", "gsis_id"]).offense_pct.max()
  ours, opp_rank, everyone = our_weeks(site)
  # Home / away for every past game (the stats feed doesn't say): full schedule history.
  allsched = cache.get("schedules", "since1999", lambda: nfl.load_schedules(list(range(FIRST_SEASON, data.current_season + 1))),
                       stale=cache.age_hours("schedules", "since1999") > 12)
  allsched = allsched[allsched.game_type == "REG"]
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

  contracts = cache.get("contracts", "all", lambda: nfl.load_contracts().select(CONTRACT_COLS),
                        stale=cache.age_hours("contracts", "all") > 24)
  cache.save_meta()  # fetch times for players / contracts, so the next run honors their refresh intervals
  bios = bio_map(data.rosters, data.draft, contracts)
  scr = qb_scrambles(data.pbp)
  out_dir = site / "data" / "players"
  out_dir.mkdir(parents=True, exist_ok=True)
  sts = st[st.player_id.isin(everyone)].sort_values(["season", "week"])
  by_player = {pid: g for pid, g in sts.groupby("player_id")}
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
                "x": [int(r.completions), int(r.attempts), int(r.carries), int(r.targets)], "rk": int(r.prk)}
        if sp is not None and not pd.isna(sp):
          game["sn"] = int(round(100 * float(sp)))
        if mr:
          game["mr"] = int(mr)
        if o.get("pj") is not None:
          game["pj"] = o["pj"]
          game["pjl"] = [round(float(v), 2) for v in o["pjl"]]
        _link(game, gid_of.get((int(r.season), int(r.week), r.team)))
        seasons.setdefault(int(r.season), []).append(game)
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
        if mr:
          e["mr"] = int(mr)
        if o.get("pj") is not None:
          e["pj"] = o["pj"]
          e["pjl"] = [round(float(v), 2) for v in o["pjl"]]
        _link(e, gid_of.get((data.current_season, wk, team)))
        upcoming.append(e)
    name, espn = NAMES.get(pid, (None, None))
    doc = {"pid": pid, "name": name, "espn": espn, "pos": pos, "keys": SCORE_KEYS, "cur": data.current_season, "team": team,
           "seasons": [{"s": s, "g": seasons[s]} for s in sorted(seasons, reverse=True)], "up": upcoming,
           "bio": bios.get(pid, {})}
    if pos == "QB" and pid in scr:
      doc["scr"] = scr[pid]  # {season: [scrambles, dropbacks]}
    (out_dir / f"{pid}.json").write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    n += 1
  size = sum(f.stat().st_size for f in out_dir.glob("*.json"))
  print(f"[logs] wrote {n} player game logs ({size / 1e6:.1f} MB) to {out_dir}", flush=True)
  team_logs(site, cfg, data, cache, nfl, allsched)


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
  year signed. No end year: for an extension OverTheCap's years are the ADDED years (McCaffrey's 2024 2-year
  extension runs through 2027, not 2025), so signed + years would mislead."""
  if contracts is None or not len(contracts):
    return {}
  c = contracts[contracts.is_active.fillna(False).astype(bool)].dropna(subset=["gsis_id", "apy"])
  c = c.sort_values("year_signed").drop_duplicates("gsis_id", keep="last")
  r2 = lambda v: None if pd.isna(v) else round(float(v), 2)
  return {x.gsis_id: {k: v for k, v in {"apy": r2(x.apy), "val": r2(x.value), "gtd": r2(x.guaranteed), "cap": None if pd.isna(x.apy_cap_pct) else round(float(x.apy_cap_pct), 4),
                                        "from": int(x.year_signed), "yrs": None if pd.isna(x.years) else int(x.years)}.items()
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
      frames.append(t[t.season_type == "REG"])
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


def team_logs(site: Path, cfg: dict, data, cache, nfl, allsched: pd.DataFrame):
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
  def stat(gid, team, k):
    try:
      v = ts.at[(gid, team), k]
      return None if pd.isna(v) else float(v)
    except KeyError:
      return None
  for k in ("yd", "py", "ry", "ep", "to", "fd", "sk"):
    T[k] = [stat(a, b, k) for a, b in zip(T.gid, T.team)]
    T["o_" + k] = [stat(a, b, k) for a, b in zip(T.gid, T.opp)]
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
                      "rk": {k: int(a[k + "_rk"]) for k in better_high if pd.notna(a[k + "_rk"])}, "g": games})
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
