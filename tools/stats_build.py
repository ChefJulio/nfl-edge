"""Season stats for Teams > Stats and Players > Stats (data only; rendered by teamstats.js / playerstats.js).

Writes <site>/data/stats/teams_<season>.json, players_<season>.json and index.json (regular season), plus
teams_<season>_post.json / players_<season>_post.json for every season with playoff games (index "post"; the tabs'
Regular season / Playoffs toggle; owner 2026-10-14: playoff stats matter, kept apart).

Usage: python tools/stats_build.py [--site=site] [--seasons=1999-2026]   (CI runs it after run.py)

Team stats are computed from our own play-by-play (nflverse team-level EPA doesn't reconcile with pbp, INSIGHTS
section 7), offense and defense. Player stats are season totals of nflverse's weekly player stats, plus snaps
(2012 on), inside-10 carries and red-zone targets (from the same pbp), and bio / draft / contract (the player-card
helpers in tools/player_logs.py). Finished seasons are aggregated once and cached (cache/seasonstats_*.parquet);
the current season is redone when its count of final games changes.
"""
import json
import re
import shutil
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.report import SCORE_KEYS  # noqa: E402
from nfledge.standings import RELOCATED  # noqa: E402

V = 1
FIRST = 1999
PBP_COLS = ["game_id", "play_id", "season", "week", "season_type", "posteam", "defteam", "play_type", "yards_gained", "pass_attempt",
            "complete_pass", "sack", "passing_yards", "rushing_yards", "rush_attempt", "pass_touchdown", "rush_touchdown",
            "interception", "fumble_lost", "first_down_rush", "first_down_pass", "first_down_penalty", "third_down_converted",
            "third_down_failed", "fourth_down_converted", "fourth_down_failed", "penalty", "penalty_team", "penalty_yards",
            "fixed_drive", "fixed_drive_result", "drive_inside20", "drive_time_of_possession", "epa", "success", "qb_kneel",
            "yardline_100", "rusher_player_id", "receiver_player_id", "td_team"]


def _mmss(s) -> float:
  try:
    m, x = str(s).split(":")
    return int(m) * 60 + int(x)
  except ValueError:
    return np.nan


def is_type(col: pd.Series, st: str) -> pd.Series:
  """season_type / game_type column is regular season ("REG") or playoffs (POST, or WC / DIV / CON / SB)."""
  return col == "REG" if st == "REG" else col != "REG"


def team_stats(pbp: pd.DataFrame, sched: pd.DataFrame, season: int, st: str = "REG") -> pd.DataFrame:
  """One row per team: offense columns o_* and defense (allowed) columns d_*."""
  p = pbp[is_type(pbp.season_type, st)].copy()
  for c in ("posteam", "defteam", "penalty_team"):
    p[c] = p[c].replace(RELOCATED)
  sc = p[p.play_type.isin(["pass", "run"])]
  def side(g):
    att = g.pass_attempt.sum() - g.sack.sum()
    sacks = g.sack.sum()
    sack_yds = -g.loc[g.sack == 1, "yards_gained"].sum()
    gross = g.passing_yards.sum()
    rush_att = g.rush_attempt.sum()
    third_c, third_f = g.third_down_converted.sum(), g.third_down_failed.sum()
    fourth_c, fourth_f = g.fourth_down_converted.sum(), g.fourth_down_failed.sum()
    return pd.Series({
      "plays": len(g), "yds": g.yards_gained.sum(), "att": att, "cmp": g.complete_pass.sum(), "pass_yds": gross - sack_yds,
      "pass_td": g.pass_touchdown.sum(), "int": g.interception.sum(), "sacks": sacks, "sack_yds": sack_yds,
      "rush_att": rush_att, "rush_yds": g.rushing_yards.sum(), "rush_td": g.rush_touchdown.sum(),
      "fum_lost": g.fumble_lost.sum(), "first_downs": g.first_down_rush.sum() + g.first_down_pass.sum() + g.first_down_penalty.sum(),
      "third_c": third_c, "third_att": third_c + third_f, "fourth_c": fourth_c, "fourth_att": fourth_c + fourth_f,
      "epa": g.epa.sum(), "success": g.success.sum()})
  off = sc.groupby("posteam").apply(side, include_groups=False).add_prefix("o_")
  dfn = sc.groupby("defteam").apply(side, include_groups=False).add_prefix("d_")
  # Drives: red-zone trips and touchdowns, time of possession (one row per drive)
  dr = p.dropna(subset=["fixed_drive"]).drop_duplicates(["game_id", "posteam", "fixed_drive"])
  dr = dr.assign(rz=dr.drive_inside20.fillna(0).astype(int), td=(dr.fixed_drive_result == "Touchdown").astype(int),
                 top=dr.drive_time_of_possession.map(_mmss))
  for who, key in (("o", "posteam"), ("d", "defteam")):
    g = dr.groupby(key)
    rz = g.rz.sum(); rz_td = dr[dr.rz == 1].groupby(key).td.sum()
    off_or_d = off if who == "o" else dfn
    off_or_d[f"{who}_rz"] = rz.reindex(off_or_d.index).fillna(0)
    off_or_d[f"{who}_rz_td"] = rz_td.reindex(off_or_d.index).fillna(0)
  off["o_top"] = dr.groupby("posteam").top.sum().reindex(off.index)
  # one flagged play = one penalty (the old key, drive + team + yards + play type, merged two false starts on a drive)
  pen = p[(p.penalty == 1) & p.penalty_team.notna()].drop_duplicates(["game_id", "play_id"])
  off["pen"] = pen.groupby("penalty_team").size().reindex(off.index).fillna(0)
  off["pen_yds"] = pen.groupby("penalty_team").penalty_yards.sum().reindex(off.index).fillna(0)
  drew = pen.posteam.where(pen.penalty_team != pen.posteam, pen.defteam)  # the team the flag went against's opponent
  off["pen_drawn"] = pen.groupby(drew).size().reindex(off.index).fillna(0)
  t = off.join(dfn, how="outer")
  # Points and record from the schedule (final scores)
  s = sched[(sched.season == season) & is_type(sched.game_type, st) & sched.home_score.notna()]
  h, a = s.home_team.replace(RELOCATED), s.away_team.replace(RELOCATED)
  g = pd.concat([pd.DataFrame({"team": h, "pf": s.home_score, "pa": s.away_score}),
                 pd.DataFrame({"team": a, "pf": s.away_score, "pa": s.home_score})])
  agg = g.groupby("team").agg(g=("pf", "size"), pf=("pf", "sum"), pa=("pa", "sum"),
                              w=("pf", lambda x: 0), )
  res = g.assign(w=(g.pf > g.pa).astype(int), l=(g.pf < g.pa).astype(int), t=(g.pf == g.pa).astype(int)).groupby("team")[["w", "l", "t"]].sum()
  t = t.join(agg[["g", "pf", "pa"]]).join(res)
  t["takeaways"] = t.d_int + t.d_fum_lost
  t["turnovers"] = t.o_int + t.o_fum_lost
  return t.reset_index().rename(columns={"index": "team", "posteam": "team"})


def player_extras(pbp: pd.DataFrame, st: str = "REG") -> pd.DataFrame:
  """Per player-season usage only pbp has: inside-10 carries, red-zone targets."""
  p = pbp[is_type(pbp.season_type, st)]
  i10 = p[(p.rush_attempt == 1) & (p.yardline_100 <= 10) & p.rusher_player_id.notna()].groupby("rusher_player_id").size()
  rz = p[(p.pass_attempt == 1) & (p.sack != 1) & (p.yardline_100 <= 20) & p.receiver_player_id.notna()].groupby("receiver_player_id").size()
  return pd.DataFrame({"car_i10": i10, "tgt_rz": rz}).fillna(0)


PSUM = ["completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions", "sacks_suffered", "sack_yards_lost",
        "passing_air_yards", "passing_first_downs", "passing_epa", "passing_2pt_conversions", "carries", "rushing_yards", "rushing_tds",
        "rushing_first_downs", "rushing_epa", "rushing_2pt_conversions", "receptions", "targets", "receiving_yards", "receiving_tds",
        "receiving_air_yards", "receiving_yards_after_catch", "receiving_first_downs", "receiving_epa", "receiving_2pt_conversions",
        "fumbles_lost_total", "sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost",
        "def_tackles_solo", "def_tackle_assists", "def_tackles_for_loss", "def_sacks", "def_qb_hits", "def_interceptions",
        "def_pass_defended", "def_fumbles_forced", "def_tds", "fg_made", "fg_att", "pat_made", "pat_att", "pt_att", "pt_yards",
        "punt_returns", "punt_return_yards", "kickoff_returns", "kickoff_return_yards", "special_teams_tds"]


def player_stats(ps: pd.DataFrame, snaps: pd.DataFrame | None, pfr2gsis: pd.Series, extras: pd.DataFrame,
                 team_totals: pd.DataFrame, st: str = "REG") -> pd.DataFrame:
  w = ps[is_type(ps.season_type, st)].copy()
  w["team"] = w.team.replace(RELOCATED)
  cols = [c for c in PSUM if c in w.columns]
  for c in cols:
    w[c] = pd.to_numeric(w[c], errors="coerce").fillna(0)
  w = w.sort_values("week")
  agg = w.groupby("player_id").agg(**{c: (c, "sum") for c in cols}, games=("week", "nunique"),
                                   name=("player_display_name", "last"), pos=("position", "last"), team=("team", "last"),
                                   fg_long=("fg_long", "max") if "fg_long" in w else ("week", "size"))
  agg = agg.join(extras, how="left")
  if snaps is not None and len(snaps):
    sn = snaps[is_type(snaps.game_type, st)].assign(gsis=lambda d: d.pfr_player_id.map(pfr2gsis))
    sn["key"] = sn.gsis.fillna("pfr:" + sn.pfr_player_id.astype(str))
    sa = sn.groupby("key").agg(snaps_o=("offense_snaps", "sum"), snap_pct=("offense_pct", "mean"), snaps_d=("defense_snaps", "sum"),
                               snap_pct_d=("defense_pct", "mean"), snap_pct_st=("st_pct", "mean"),
                               snaps_st=("st_snaps", "sum"), snap_games=("week", "nunique"), sn_name=("player", "last"),
                               sn_pos=("position", "last"), sn_team=("team", "last"))
    sa = sa[(sa.snaps_o + sa.snaps_d + sa.snaps_st) > 0]
    agg = agg.join(sa, how="outer")
    agg["name"] = agg.name.fillna(agg.sn_name); agg["pos"] = agg.pos.fillna(agg.sn_pos)
    agg["team"] = agg.team.fillna(agg.sn_team.replace(RELOCATED))
    agg["games"] = agg.games.fillna(0).combine(agg.snap_games.fillna(0), max)
    agg = agg.drop(columns=["sn_name", "sn_pos", "sn_team", "snap_games"])
  agg = agg.fillna({c: 0 for c in cols + ["car_i10", "tgt_rz"]})
  # Shares of the team's season totals (targets of all passes, designed carries of all runs)
  agg["tgt_share"] = agg.targets / agg.team.map(team_totals.tgt).replace(0, np.nan)
  agg["car_share"] = agg.carries / agg.team.map(team_totals.car).replace(0, np.nan)
  agg.index.name = "pid"
  return agg.reset_index()


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = Path(opt.get("site", "site"))
  cfg = load_config()
  import nflreadpy as nfl
  import player_logs as PL
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  current = int(nfl.get_current_season())
  sched = cache.get("schedules", "since1999", lambda: nfl.load_schedules(list(range(FIRST, current + 1))),
                    stale=cache.age_hours("schedules", "since1999") > 6)
  a, _, b = opt.get("seasons", f"{FIRST}-{current}").partition("-")
  seasons = [s for s in range(int(a), int(b or a) + 1) if (sched.season == s).any()]
  players = cache.get("players", "all", lambda: nfl.load_players(), stale=cache.age_hours("players", "all") > 24 * 7)
  espn_of = {g: str(e).replace(".0", "") for g, e in zip(players.gsis_id, players.espn_id) if isinstance(g, str) and pd.notna(e) and str(e)}
  # site-wide headshot map (NFLE.ui.player): players active since 2010 (~11k, ~90 KB gzipped, loaded once)
  recent = set(players[pd.to_numeric(players.last_season, errors="coerce") >= 2010].gsis_id)
  (site / "data").mkdir(parents=True, exist_ok=True)
  (site / "data" / "espn_ids.json").write_text(json.dumps({g: e for g, e in espn_of.items() if g in recent}, separators=(",", ":")), encoding="utf-8")
  pfr2gsis = players.dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates("pfr_id").set_index("pfr_id").gsis_id
  rosters = pd.concat([x for x in (cache.get("rosters", s, lambda: nfl.load_rosters_weekly([s]), stale=False)
                                   for s in range(max(FIRST, current - 9), current + 1)) if x is not None], ignore_index=True)
  teams = cache.get("teams", "all", lambda: nfl.load_teams(), stale=False)
  draft = cache.get("draft", "all", lambda: nfl.load_draft_picks(), stale=cache.age_hours("draft", "all") > 24 * 30)
  contracts = cache.get("contracts", "all", lambda: PL.load_contracts(nfl), stale=cache.age_hours("contracts", "all") > 24)
  bios = PL.bio_map(rosters, draft, contracts)
  out = site / "data" / "stats"
  out.mkdir(parents=True, exist_ok=True)
  meta_key = "seasonstats_final"
  n_final_cur = int(sched[(sched.season == current) & (sched.game_type == "REG")].home_score.notna().sum())
  done, post_seasons = 0, []
  for s in seasons:
    tf, pf_ = cache.path("seasonstats_teams_v2", s), cache.path("seasonstats_players", s)  # v2: penalty count fix
    # this season also redoes while a final game was missing from nflverse at the last build (a late-posted Monday
    # game), retried hourly (2026-10-19: the final-game count alone never changed again, so it waited a week)
    lag = s == current and cache.meta.get(f"{meta_key}_missing", 1) and \
      (time.time() - float(cache.meta.get(f"{meta_key}_at", 0))) / 3600 > D.LAG_RETRY_HOURS
    redo = not tf.exists() or not pf_.exists() or (s == current and cache.meta.get(meta_key) != n_final_cur) or bool(lag)
    po_done = int((is_type(sched[sched.season == s].game_type, "POST") & sched[sched.season == s].home_score.notna()).sum())
    tfp, pfp = cache.path("seasonstats_teams_post_v2", s), cache.path("seasonstats_players_post", s)
    redo_po = po_done > 0 and (not tfp.exists() or not pfp.exists() or cache.meta.get(f"{meta_key}_post_{s}") != po_done)
    pbp = ps = sn = None
    if redo or redo_po:
      pbp = nfl.load_pbp([s]).select([c for c in PBP_COLS]).to_pandas()
      for c in ("pass_attempt", "complete_pass", "sack", "interception", "fumble_lost", "rush_attempt", "pass_touchdown",
                "rush_touchdown", "first_down_rush", "first_down_pass", "first_down_penalty", "third_down_converted",
                "third_down_failed", "fourth_down_converted", "fourth_down_failed", "penalty", "success"):
        pbp[c] = pd.to_numeric(pbp[c], errors="coerce").fillna(0)
      for c in ("yards_gained", "passing_yards", "rushing_yards", "epa", "penalty_yards"):
        pbp[c] = pd.to_numeric(pbp[c], errors="coerce").fillna(0)
      ps = nfl.load_player_stats([s]).to_pandas()
      sn = cache.get("snaps", s, lambda: nfl.load_snap_counts([s]), stale=(s == current)) if s >= 2012 else None

    def build(st):
      ts_ = team_stats(pbp, sched, s, st)
      x = pbp[is_type(pbp.season_type, st)].assign(posteam=lambda d: d.posteam.replace(RELOCATED))
      tt = pd.DataFrame({"tgt": x[(x.pass_attempt == 1) & (x.sack != 1) & x.receiver_player_id.notna()].groupby("posteam").size(),
                         "car": x[(x.rush_attempt == 1) & (x.qb_kneel != 1)].groupby("posteam").size()})
      return ts_, player_stats(ps, sn, pfr2gsis, player_extras(pbp, st), tt, st)

    if redo:
      ts, pl = build("REG")
      ts.to_parquet(tf, index=False); pl.to_parquet(pf_, index=False)
      if s == current:
        cache.meta[meta_key] = n_final_cur
        # final games whose teams have no player-stat rows yet: flag them for the hourly retry
        fin = sched[(sched.season == s) & (sched.game_type == "REG") & sched.home_score.notna()]
        reg = ps[is_type(ps.season_type, "REG")]
        have = set(zip(reg.week.astype(int), reg.team.replace(RELOCATED)))
        miss = [g for g in fin.itertuples() if (int(g.week), RELOCATED.get(g.home_team, g.home_team)) not in have
                or (int(g.week), RELOCATED.get(g.away_team, g.away_team)) not in have]
        cache.meta[f"{meta_key}_missing"] = len(miss)
        cache.meta[f"{meta_key}_at"] = time.time()
        if miss:
          print(f"[stats] {len(miss)} final games not in nflverse's player stats yet: retry next run after an hour", flush=True)
      done += 1
    if redo_po:
      tsp, plp = build("POST")
      tsp.to_parquet(tfp, index=False); plp.to_parquet(pfp, index=False)
      cache.meta[f"{meta_key}_post_{s}"] = po_done
      cache.save_meta()  # a long first run (every season's pbp) can stop midway: keep what's done
    ts, pl = pd.read_parquet(tf), pd.read_parquet(pf_)
    pl = with_def(pl, def_extras(cache, nfl, s, current, pfr2gsis))
    pl.to_parquet(cache.path("seasonstats_players_def", s), index=False)  # with the extras: the careers read these
    write_team(out / f"teams_{s}.json", ts, s, teams)
    write_players(out / f"players_{s}.json", pl, s, current, bios, espn_of)
    if po_done and tfp.exists() and pfp.exists():
      write_team(out / f"teams_{s}_post.json", pd.read_parquet(tfp), s, teams)
      write_players(out / f"players_{s}_post.json", with_def(pd.read_parquet(pfp), def_extras(cache, nfl, s, current, pfr2gsis, "POST")),
                    s, current, bios, espn_of)
      post_seasons.append(s)
  cache.save_meta()
  # All years (owner 2026-10-18: "we need an all positions and all years filter"; a name search finds a player
  # whatever the filters): one row per player, regular-season careers since FIRST, from the per-season caches
  frames = [pd.read_parquet(cache.path("seasonstats_players_def", s)).assign(season=s) for s in range(FIRST, current + 1)
            if cache.path("seasonstats_players_def", s).exists()]
  if frames:
    car = career_rows(frames)
    write_players(out / "players_career.json", car, current, current, bios, espn_of)
    print(f"[stats] careers: {len(car)} players", flush=True)
    write_finder_past(out / "finder_past", car)
  (out / "index.json").write_text(json.dumps({"v": V, "seasons": seasons, "current": current, "keys": SCORE_KEYS,
                                               "post": post_seasons, "career": bool(frames)}), encoding="utf-8")
  print(f"[stats] {len(seasons)} seasons ({done} recomputed) -> {out}", flush=True)


# Defenders (owner 2026-10-18: "individual defense players ... complete stats"): per player-season extras merged into
# each season's rows when written (no play-by-play recompute): safeties, opponent fumble recoveries and blocked kicks
# from the weekly stats; pressures, hurries, blitzes, coverage allowed and missed tackles from PFR (2018 on).
DEF_BOX = {"def_safeties": "def_safeties", "def_fum_rec": "fumble_recovery_opp"}
DEF_PFR = {"prs": "def_pressures", "hur": "def_times_hurried", "blz": "def_times_blitzed", "cov_tgt": "def_targets",
           "cov_cmp": "def_completions_allowed", "cov_yds": "def_yards_allowed", "cov_td": "def_receiving_td_allowed",
           "cov_int": "def_ints", "mt": "def_missed_tackles", "tk_comb": "def_tackles_combined"}


def def_extras(cache, nfl, s: int, current: int, p2g: pd.Series, st: str = "REG") -> pd.DataFrame:
  """pid -> the defense extras for season s (empty frame when nothing is published)."""
  import player_logs as PL
  out = []
  x = cache.get("stats_full", s, lambda: nfl.load_player_stats([s]).select(PL.FULL_COLS).to_pandas(),
                stale=(s == current and cache.age_hours("stats_full", s) > 6) or cache.lacks("stats_full", s, PL.FULL_COLS))
  if x is not None and len(x):
    x = x[is_type(x.season_type, st)]
    for c in list(DEF_BOX.values()) + PL.BLOCKS:
      x[c] = pd.to_numeric(x[c], errors="coerce").fillna(0)
    b = x.groupby("player_id")[list(DEF_BOX.values()) + PL.BLOCKS].sum()
    b = b.rename(columns={v: k for k, v in DEF_BOX.items()}).assign(def_blocks=b[PL.BLOCKS].sum(axis=1)).drop(columns=PL.BLOCKS)
    out.append(b)
  if s >= 2018:
    a = cache.get("pfrdef", s, lambda: nfl.load_pfr_advstats([s], stat_type="def", summary_level="week"),
                  stale=s == current and cache.age_hours("pfrdef", s) > 6)
    if a is not None and len(a):
      a = a[is_type(a.game_type, st)].assign(g=lambda d: d.pfr_player_id.map(p2g)).dropna(subset=["g"])
      for c in DEF_PFR.values():
        a[c] = pd.to_numeric(a[c], errors="coerce").fillna(0)
      out.append(a.groupby("g")[list(DEF_PFR.values())].sum().rename(columns={v: k for k, v in DEF_PFR.items()}))
  return pd.concat(out, axis=1) if out else pd.DataFrame()


RATES = ["snap_pct", "snap_pct_d", "snap_pct_st", "tgt_share", "car_share"]  # per-season shares: games-weighted over a career


def finder_norm(t: str) -> str:
  """A name as the finder compares it (shell.js norm, keep the two in step): accents off, lowercase, periods and
  apostrophes dropped ("A.J." -> "aj"), anything else between words a space."""
  t = unicodedata.normalize("NFD", str(t or ""))
  t = "".join(ch for ch in t if not unicodedata.combining(ch)).lower()
  t = re.sub(r"[.'\u2019]", "", t)
  return re.sub(r"[^a-z0-9]+", " ", t).strip()


def write_finder_past(out: Path, car: pd.DataFrame):
  """The player finder's past players (owner 2026-10-21: "no tomlinson? can we add a section for historical
  players"; "lazy load everything but the name/position/years active"; "what if i search linson looking for
  tomlinson"): everyone with a career row since FIRST, filed under every two-letter pair inside his name's words
  (<out>/<pair>.json; "tomlinson" sits under to, om, ml, li, in, ns, so, on), so a search loads one small file, its
  rarest pair's (<out>/index.json: rows per pair), and finds a name by any part of it. A row is one line,
  "id|name|pos|first|last|weight": id without its "00-00" (gsis ids are 00-00 + 5 digits; anything else in full),
  weight 0-9 ranking same-name matches (log of career half-PPR points for offense and kickers, of games x 4 for
  everyone else). His photo, team and the rest come with his card. Current-roster players are dropped in the browser."""
  n = lambda c: pd.to_numeric(car[c], errors="coerce").fillna(0) if c in car else 0  # noqa: E731
  fp = (n("passing_yards") / 25 + 4 * n("passing_tds") - 2 * n("passing_interceptions") + n("rushing_yards") / 10
        + 6 * (n("rushing_tds") + n("receiving_tds")) + 0.5 * n("receptions") + n("receiving_yards") / 10
        - 2 * n("fumbles_lost_total") + 3 * n("fg_made") + n("pat_made"))
  raw = np.where(car.pos.isin(["QB", "RB", "FB", "WR", "TE", "K"]), fp, 4 * n("games")).clip(0)
  weight = np.minimum(9, np.floor(np.log10(1 + raw) * 2.4)).astype(int)  # 10k points ~ 9, 1k ~ 7, 100 ~ 4
  shards: dict[str, list[str]] = {}
  for p, nm, ps, a, b, w in zip(car.pid, car.name, car.pos, car["first"], car.season, weight):
    if not isinstance(nm, str) or not nm or not isinstance(p, str):
      continue
    pid = p[5:] if re.fullmatch(r"00-00\d{5}", p) else p
    line = "|".join([pid, nm.replace("|", " "), ps if isinstance(ps, str) else "", str(int(a)), str(int(b)), str(int(w))])
    for k in {w0[i:i + 2] for w0 in finder_norm(nm).split() for i in range(len(w0) - 1)}:
      shards.setdefault(k, []).append(line)
  if out.exists():
    shutil.rmtree(out)
  out.mkdir(parents=True)
  for k, lines in shards.items():
    (out / f"{k}.json").write_text(json.dumps({"v": 1, "d": "\n".join(lines)}, separators=(",", ":")), encoding="utf-8")
  (out / "index.json").write_text(json.dumps({"v": 1, "n": {k: len(v) for k, v in sorted(shards.items())}}, separators=(",", ":")), encoding="utf-8")
  print(f"[stats] finder past players: {len(car)} in {len(shards)} pair files", flush=True)


def career_rows(frames: list) -> pd.DataFrame:
  """Season rows (players_<season>, a "season" column) -> one row per player: counting stats summed, the longest
  field goal, shares weighted by games (seasons that have them), name / position from his latest season, team =
  the one he played the most games for,
  plus "first" (first season), "season" (latest) and "nsea" (seasons played)."""
  c = pd.concat(frames, ignore_index=True).sort_values("season")
  c = c[c.pid.astype(str) != "0"]  # one source's placeholder id (see player_logs GSIS_RE)
  num = [x for x in c.select_dtypes("number").columns if x not in ("season", "fg_long", *RATES)]
  g = c.groupby("pid")
  out = g[num].sum(min_count=1)
  out["fg_long"] = g.fg_long.max()
  for r in RATES:
    if r in c:
      w = c.games.fillna(0).where(c[r].notna(), 0)
      out[r] = (c[r].fillna(0) * w).groupby(c.pid).sum() / w.groupby(c.pid).sum().replace(0, np.nan)
  out = out.join(g[["name", "pos"]].last()).join(g.season.agg(first="min", season="max", nsea="nunique"))
  # his team: where he played the most games (owner 2026-10-18: LaDainian Tomlinson read NYJ, Adrian Peterson SEA,
  # their last stops); ties go to the earlier team
  tg = c.dropna(subset=["team"]).groupby(["pid", "team"]).agg(n=("games", "sum"), s0=("season", "min")).reset_index()
  out["team"] = tg.sort_values(["pid", "n", "s0"], ascending=[True, False, True]).drop_duplicates("pid").set_index("pid").team
  return out.reset_index()


def with_def(pl: pd.DataFrame, ex: pd.DataFrame) -> pd.DataFrame:
  """The season rows plus the defense extras (0 where a player has none; the PFR columns stay empty before 2018)."""
  if not len(ex):
    return pl
  m = pl.merge(ex, left_on="pid", right_index=True, how="left")
  for c in ex.columns:
    if c in DEF_BOX or c == "def_blocks":
      m[c] = m[c].fillna(0)
  return m


def _clean(v):
  if v is None or (isinstance(v, float) and not np.isfinite(v)):
    return None
  if isinstance(v, (np.integer,)):
    return int(v)
  if isinstance(v, (float, np.floating)):
    return round(float(v), 4) if abs(v - round(v)) > 1e-9 else int(round(v))
  return v


def write_team(path: Path, ts: pd.DataFrame, season: int, teams: pd.DataFrame):
  cols = [c for c in ts.columns if c != "team"]
  t = teams.assign(team_abbr=teams.team_abbr.replace(RELOCATED)).drop_duplicates("team_abbr").set_index("team_abbr")
  info = {a: {"nick": t.at[a, "team_nick"], "name": t.at[a, "team_name"], "logo": t.at[a, "team_logo_espn"], "color": t.at[a, "team_color"]}
          for a in ts.team if a in t.index}
  doc = {"v": V, "season": season, "cols": cols, "info": info,
         "teams": {r.team: [_clean(getattr(r, c)) for c in cols] for r in ts.itertuples()}}
  path.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")


def write_players(path: Path, pl: pd.DataFrame, season: int, current: int, bios: dict, espn: dict | None = None):
  num = [c for c in pl.columns if c not in ("pid", "name", "pos", "team")]
  rows = []
  per_row = "season" in pl  # careers: each player's latest season dates his age, experience and contract
  for r in pl.itertuples(index=False):
    if per_row:
      season = int(r.season)
    b = bios.get(r.pid, {})
    d, k = b.get("draft") or {}, b.get("deal") or {}
    born = b.get("born")
    age = round((pd.Timestamp(f"{season}-09-07") - pd.Timestamp(born)).days / 365.25, 1) if born else None
    rows.append([r.pid, _clean(r.name), _clean(r.pos), _clean(r.team)] + [_clean(getattr(r, c)) for c in num] + [
      age, b.get("ht"), b.get("wt"), (b.get("college") or "").split(";")[0].strip() or None,
      (b.get("exp") - (b.get("exp_s", season) - season)) if b.get("exp") is not None else None,
      d.get("y"), d.get("r"), d.get("p"), d.get("o"), 1 if d.get("u") else 0,
      k.get("apy") if season == current else None, k.get("val") if season == current else None,
      k.get("gtd") if season == current else None, k.get("fa") if season == current else None,
      (espn or {}).get(r.pid)])  # ESPN id: the headshot on the tile rows (NFLE.ui.player)
  cols = ["pid", "name", "pos", "team"] + num + ["age", "ht", "wt", "college", "exp", "draft_y", "draft_r", "draft_p",
                                                 "draft_o", "udfa", "apy", "deal_val", "deal_gtd", "fa", "espn"]
  doc = {"v": V, "season": season, "cols": cols, "rows": rows, "keys": SCORE_KEYS}
  path.write_text(json.dumps(doc, separators=(",", ":"), default=_clean), encoding="utf-8")


if __name__ == "__main__":
  main()
