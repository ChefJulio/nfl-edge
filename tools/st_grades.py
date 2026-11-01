"""Special-teams and line grades for the player pages (data/grades/<season>.json, the same OVR scale as the others).

Kickers (owner 2026-10-31, INSIGHTS (DY)): accuracy against the league at each distance and in each setting, not
volume. Every field goal and extra point gets an expected make chance from a logistic fit on its season and the
neighboring ones (distance, distance squared, extra-point flag, indoors, outdoor wind, outdoor cold, Denver); a kick's
value is points over expected (3 x (made - chance) for a field goal, 1 x for an extra point). The grade is that value
per attempt over this season and the two before (1 / 0.6 / 0.3), shrunk toward the league by method-of-moments
pseudo-attempts, as a percentile among the season's qualified kickers (0.75 field-goal attempts per team game).
Blocked kicks are left out (mostly the protection's).

Usage: python tools/st_grades.py --eval        the (DY) gate: walk-forward 2005-2025, prints the table
       (the build runs from tools/grade_build.py: build_kickers)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.player_model import mom_prior  # noqa: E402

FIRST = 1999
SEASON_W = (1.0, 0.6, 0.3)
K_QUAL = 0.75  # field-goal attempts per team game
# the special-teams plays every grade here reads (punts kept for the punter grade)
COLS = ["season", "week", "season_type", "game_id", "posteam", "home_team", "play_type", "field_goal_attempt",
        "extra_point_attempt", "field_goal_result", "extra_point_result", "kick_distance", "kicker_player_id",
        "kicker_player_name", "roof", "temp", "wind", "punt_attempt", "punter_player_id", "punter_player_name",
        "yardline_100", "punt_blocked", "touchback", "punt_inside_twenty", "punt_in_endzone", "punt_out_of_bounds",
        "punt_downed", "punt_fair_catch", "return_yards", "return_touchdown", "ep", "epa"]
K_BANDS = [("u40", 0, 39), ("b40", 40, 49), ("b50", 50, 99)]
K_LABELS = ["Field goals over expected / attempt", "Under 40 yards: makes over expected", "40-49 yards: makes over expected",
            "50+ yards: makes over expected", "Extra points over expected"]
BAND_SHRINK = 4.0  # pseudo-attempts at the league rate for a bar's distance band (50+ is a handful of kicks a season)


def st_plays(cache_dir: Path, cur: int, first: int = FIRST) -> pd.DataFrame:
  """Field goals, extra points and punts, regular season, every season since `first`; finished seasons cached in
  cache/pbpst_<season>.parquet, the current one refetched."""
  import nflreadpy as nfl
  out = []
  for s in range(first, cur + 1):
    p = cache_dir / f"pbpst_{s}.parquet"
    if p.exists() and s != cur:
      out.append(pd.read_parquet(p))
      continue
    try:
      df = nfl.load_pbp([s])
      df = df.select([c for c in COLS if c in df.columns]).to_pandas()
      df = df[(df.season_type == "REG") & ((df.field_goal_attempt == 1) | (df.extra_point_attempt == 1) | (df.punt_attempt == 1))]
      df.to_parquet(p, index=False)
      out.append(df)
    except Exception as e:
      print(f"[st] {s}: {type(e).__name__} {str(e)[:80]}", flush=True)
      if p.exists():
        out.append(pd.read_parquet(p))
  return pd.concat(out, ignore_index=True)


def kicks(st: pd.DataFrame) -> pd.DataFrame:
  """Every field goal and extra point (blocked left out) with its expected make chance and points over expected."""
  from sklearn.linear_model import LogisticRegression
  k = st[((st.field_goal_attempt == 1) | (st.extra_point_attempt == 1)) & st.kicker_player_id.notna()].copy()
  k["xp"] = (k.extra_point_attempt == 1).astype(float)
  res = np.where(k.xp == 1, k.extra_point_result, k.field_goal_result)
  k = k[res != "blocked"].copy()
  res = np.where(k.xp == 1, k.extra_point_result, k.field_goal_result)
  k["made"] = np.isin(res, ["made", "good"]).astype(float)
  # an extra point's distance: the snap from the 15 since 2015 (33 yards), the 2 before (20)
  k["d"] = pd.to_numeric(k.kick_distance, errors="coerce")
  k.loc[k.d.isna() & (k.xp == 1), "d"] = np.where(k.season >= 2015, 33.0, 20.0)
  k = k[k.d.notna()].copy()
  indoor = k.roof.isin(["dome", "closed"])
  k["indoor"] = indoor.astype(float)
  k["wind_o"] = np.where(indoor, 0.0, pd.to_numeric(k.wind, errors="coerce").fillna(0.0))
  k["cold_o"] = np.where(indoor, 0.0, (pd.to_numeric(k.temp, errors="coerce") < 40).astype(float))
  k["den"] = (k.home_team == "DEN").astype(float)
  X = lambda f: np.column_stack([f.d / 10, (f.d / 10) ** 2, f.xp, f.indoor, f.wind_o / 10, f.cold_o, f.den])  # noqa: E731
  k["p"] = np.nan
  for s in sorted(k.season.unique()):
    tr = k[k.season.between(s - 1, s + 1)]
    m = LogisticRegression(C=1e4, max_iter=2000).fit(X(tr), tr.made)
    te = k.season == s
    k.loc[te, "p"] = m.predict_proba(X(k[te]))[:, 1]
  k["val"] = np.where(k.xp == 1, 1.0, 3.0) * (k.made - k.p)
  return k


def kicker_seasons(k: pd.DataFrame, sched: pd.DataFrame) -> pd.DataFrame:
  """One row per kicker-season: attempts, value, field-goal value, band and extra-point sums, team, qualified."""
  from grade_build import team_games
  fg, xp = k[k.xp == 0], k[k.xp == 1]
  g = k.groupby(["kicker_player_id", "season"])
  t = pd.DataFrame({"att": g.size(), "val": g.val.sum(), "games": g.game_id.nunique(),
                    "team": g.posteam.agg(lambda x: x.mode().iloc[0])})
  fg_g = fg.groupby(["kicker_player_id", "season"])
  t["fga"], t["fgm"], t["fg_val"] = fg_g.size(), fg_g.made.sum(), fg_g.val.sum()
  for key, lo, hi in K_BANDS:
    b = fg[fg.d.between(lo, hi)].groupby(["kicker_player_id", "season"])
    t[f"{key}_n"], t[f"{key}_x"] = b.size(), b.apply(lambda x: (x.made - x.p).sum())
  x_g = xp[xp.season >= 2015].groupby(["kicker_player_id", "season"])
  t["xp_n"], t["xp_x"] = x_g.size(), x_g.apply(lambda x: (x.made - x.p).sum())
  t = t.fillna({c: 0 for c in t.columns if c.endswith(("_n", "_x")) or c in ("fga", "fgm", "fg_val")}).reset_index()
  t = t.rename(columns={"kicker_player_id": "gsis_id"})
  t["team"] = t.team.map(lambda x: D.RELOCATED.get(x, x))
  tg = team_games(sched)
  t["tgm"] = [tg.get((a, int(b)), np.nan) for a, b in zip(t.team, t.season)]
  t["qual"] = t.fga >= K_QUAL * t.tgm.fillna(17)
  return t


def window(t: pd.DataFrame, s: int, ids, k_prior: float, raw: bool = False):
  """(value per attempt over this season and the two before, shrunk unless raw; weighted attempts)."""
  wv, wa = pd.Series(0.0, index=ids), pd.Series(0.0, index=ids)
  for lag, w in enumerate(SEASON_W):
    prev = t[t.season == s - lag].drop_duplicates("gsis_id").set_index("gsis_id").reindex(ids)
    wv, wa = wv + w * prev.val.fillna(0), wa + w * prev.att.fillna(0)
  return wv / (wa + (0.0 if raw else k_prior)), wa


def prior(k: pd.DataFrame, t: pd.DataFrame) -> float:
  """Method-of-moments pseudo-attempts for value per attempt, on qualified kicker-seasons' games."""
  q = set(zip(t.gsis_id[t.qual], t.season[t.qual]))
  kg = k.groupby(["kicker_player_id", "season", "game_id"]).agg(val=("val", "sum"), att=("val", "size")).reset_index()
  kg = kg.rename(columns={"kicker_player_id": "gsis_id"})
  kg = kg[[(a, b) in q for a, b in zip(kg.gsis_id, kg.season)]]
  r = mom_prior(kg, "val", "att")
  return r[1] if r else 60.0


def build_kickers(out: Path, cur: int, sched: pd.DataFrame, cache_dir: Path) -> None:
  """Adds K records (the defenders' layout) to data/grades/<season>.json: [OVR, "K", games, weighted attempts,
  window value / attempt (raw), [bars], season-only OVR, season value / attempt (raw), games, None, {fgm, fga}]."""
  from grade_build import pct
  k = kicks(st_plays(cache_dir, cur))
  t = kicker_seasons(k, sched)
  kp = prior(k, t)
  n_all = 0
  for s in sorted(t.season.unique()):
    f = out / f"{int(s)}.json"
    doc = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"season": int(s), "stats": {}, "qualified": {}, "players": {}}
    one = t[t.season == s].drop_duplicates("gsis_id").set_index("gsis_id")
    ids = list(one.index[one.qual])
    if len(ids) < 5:
      continue
    o = one.loc[ids]
    # the percentiles rank the shrunk rates (a perfect 5 for 5 isn't a 99); the values shown are what he did (raw)
    cur_v, wa = window(t, s, ids, kp)
    sea_v = o.val / (o.att + kp)
    cur_raw, sea_raw = window(t, s, ids, kp, raw=True)[0], o.val / o.att
    bars = [o.fg_val / o.fga.replace(0, np.nan)] + [o[f"{b}_x"] / (o[f"{b}_n"] + BAND_SHRINK) for b, _, _ in K_BANDS]
    labels = list(K_LABELS[:4])
    if s >= 2015:
      bars.append(o.xp_x / (o.xp_n + BAND_SHRINK))
      labels.append(K_LABELS[4])
    bp = [pct(b.fillna(b.median()).fillna(0.0)) for b in bars]
    gp, sg = pct(cur_v), pct(sea_v)
    doc["stats"]["K"], doc["qualified"]["K"] = labels, len(ids)
    for x in ids:
      doc["players"][x] = [int(gp[x]), "K", int(o.games[x]), int(round(wa[x])), round(float(cur_raw[x]), 4), [int(b[x]) for b in bp],
                           int(sg[x]), round(float(sea_raw[x]), 4), int(o.games[x]),
                           None, {"fgm": int(o.fgm[x]), "fga": int(o.fga[x])}]
    n_all += len(ids)
    f.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
  print(f"[grades] kickers: {n_all} graded kicker-seasons, {int(t.season.min())}-{int(t.season.max())} "
        f"(shrinkage {kp:.0f} pseudo-attempts)", flush=True)


# ---- Punters (INSIGHTS (DZ)): net yards against the league from the same spot, the return set to the league's
# average (coverage is the team's, kept apart)
P_QUAL = 1.75  # punts per team game
P_LABELS = ["Net yards over expected / punt", "Distance from his own side (over expected)", "Pinned inside the 20 from midfield in",
            "Touchbacks from midfield in (fewer is better)", "Fair catches, out of bounds and downed (no return)"]


def punts(st: pd.DataFrame) -> pd.DataFrame:
  """Every punt (blocked left out) with the punter's value: net yards with the return replaced by the league's
  average, against the league's average from the same line of scrimmage (5-yard bins, that season +-1); plus the
  coverage part (return yards beyond average) and the inputs of the bars."""
  p = st[(st.punt_attempt == 1) & st.punter_player_id.notna() & (pd.to_numeric(st.punt_blocked, errors="coerce").fillna(0) != 1)].copy()
  p["L"] = pd.to_numeric(p.yardline_100, errors="coerce")
  p["g"] = pd.to_numeric(p.kick_distance, errors="coerce")
  p = p[p.L.notna() & p.g.notna()].copy()
  flag = lambda c: pd.to_numeric(p[c], errors="coerce").fillna(0) == 1  # noqa: E731
  p["tb"] = (flag("touchback") | flag("punt_in_endzone")).astype(float)
  p["nr"] = ((flag("punt_fair_catch") | flag("punt_out_of_bounds") | flag("punt_downed")) & (p.tb == 0)).astype(float)
  p["in20"] = (flag("punt_inside_twenty") & (p.tb == 0)).astype(float)
  p["ret"] = ((p.tb == 0) & (p.nr == 0)).astype(float)
  p["ry"] = pd.to_numeric(p.return_yards, errors="coerce").fillna(0.0)
  p["bin"] = (p.L // 5).clip(upper=19)
  p["pv"] = p["exp"] = p["cov"] = p["g_x"] = p["in20_x"] = p["tb_x"] = p["nr_x"] = np.nan
  for s in sorted(p.season.unique()):
    nb = p[p.season.between(s - 1, s + 1)]
    avg_ret = float(nb.loc[nb.ret == 1, "ry"].mean())
    te = p.season == s
    pv = np.where(p.tb == 1, p.L - 20, np.where(p.nr == 1, p.g, p.g - avg_ret))
    p.loc[te, "pv"] = pv[te.to_numpy()]
    p.loc[te, "cov"] = np.where(p.loc[te, "ret"] == 1, p.loc[te, "ry"] - avg_ret, np.nan)
    nb = nb.assign(pv=np.where(nb.tb == 1, nb.L - 20, np.where(nb.nr == 1, nb.g, nb.g - avg_ret)))
    by = nb.groupby("bin")[["pv", "g", "in20", "tb", "nr"]].mean()
    b = p.loc[te, "bin"]
    p.loc[te, "exp"] = b.map(by.pv).to_numpy()
    for c in ("g", "in20", "tb", "nr"):
      p.loc[te, f"{c}_x"] = (p.loc[te, c] - b.map(by[c])).to_numpy()
  p["val"] = p.pv - p.exp
  return p


def punter_seasons(p: pd.DataFrame, sched: pd.DataFrame) -> pd.DataFrame:
  from grade_build import team_games
  g = p.groupby(["punter_player_id", "season"])
  t = pd.DataFrame({"att": g.size(), "val": g.val.sum(), "games": g.game_id.nunique(), "net": g.pv.mean(),
                    "in20": g.in20.sum(), "team": g.posteam.agg(lambda x: x.mode().iloc[0])})
  deep, plus = p[p.L >= 60], p[p.L <= 50]
  for name, df, c in (("gross", deep, "g_x"), ("pin", plus, "in20_x"), ("tbx", plus, "tb_x"), ("nrx", p, "nr_x")):
    a = df.groupby(["punter_player_id", "season"])[c]
    t[f"{name}_n"], t[f"{name}_x"] = a.size(), a.sum()
  t = t.fillna({c: 0 for c in t.columns if c.endswith(("_n", "_x"))}).reset_index().rename(columns={"punter_player_id": "gsis_id"})
  t["team"] = t.team.map(lambda x: D.RELOCATED.get(x, x))
  tg = team_games(sched)
  t["tgm"] = [tg.get((a, int(b)), np.nan) for a, b in zip(t.team, t.season)]
  t["qual"] = t.att >= P_QUAL * t.tgm.fillna(17)
  return t


def coverage(p: pd.DataFrame) -> pd.DataFrame:
  """Team-season punt coverage: return yards beyond the league's average per returned punt (higher = worse)."""
  r = p[p.ret == 1].assign(team=lambda d: d.posteam.map(lambda x: D.RELOCATED.get(x, x)))
  return r.groupby(["team", "season"]).agg(cov=("cov", "mean"), returned=("cov", "size")).reset_index()


def _prior(rows: pd.DataFrame, id_col: str, t: pd.DataFrame, default: float) -> float:
  q = set(zip(t.gsis_id[t.qual], t.season[t.qual]))
  kg = rows.groupby([id_col, "season", "game_id"]).agg(val=("val", "sum"), att=("val", "size")).reset_index()
  kg = kg.rename(columns={id_col: "gsis_id"})
  kg = kg[[(a, b) in q for a, b in zip(kg.gsis_id, kg.season)]]
  r = mom_prior(kg, "val", "att")
  return r[1] if r else default


def build_punters(out: Path, cur: int, sched: pd.DataFrame, cache_dir: Path) -> None:
  """Adds P records (the kickers' layout) to data/grades/<season>.json: [OVR, "P", games, weighted punts, window
  value / punt (raw), [bars], season-only OVR, season value / punt (raw), games, None, {punts, net, in20}]; and
  data/grades/coverage.json (team punt coverage per season, for a later team stat)."""
  from grade_build import pct
  p = punts(st_plays(cache_dir, cur))
  t = punter_seasons(p, sched)
  kp = _prior(p, "punter_player_id", t, 40.0)
  n_all = 0
  for s in sorted(t.season.unique()):
    f = out / f"{int(s)}.json"
    doc = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"season": int(s), "stats": {}, "qualified": {}, "players": {}}
    one = t[t.season == s].drop_duplicates("gsis_id").set_index("gsis_id")
    ids = list(one.index[one.qual])
    if len(ids) < 5:
      continue
    o = one.loc[ids]
    cur_v, wa = window(t, s, ids, kp)
    sea_v = o.val / (o.att + kp)
    cur_raw, sea_raw = window(t, s, ids, kp, raw=True)[0], o.val / o.att
    bars = [o.val / o.att] + [o[f"{b}_x"] / (o[f"{b}_n"] + BAND_SHRINK) for b in ("gross", "pin")]
    bars += [-(o.tbx_x / (o.tbx_n + BAND_SHRINK)), o.nrx_x / (o.nrx_n + BAND_SHRINK)]
    bp = [pct(b.fillna(b.median()).fillna(0.0)) for b in bars]
    gp, sg = pct(cur_v), pct(sea_v)
    doc["stats"]["P"], doc["qualified"]["P"] = P_LABELS, len(ids)
    for x in ids:
      doc["players"][x] = [int(gp[x]), "P", int(o.games[x]), int(round(wa[x])), round(float(cur_raw[x]), 2), [int(b[x]) for b in bp],
                           int(sg[x]), round(float(sea_raw[x]), 2), int(o.games[x]),
                           None, {"punts": int(o.att[x]), "net": round(float(o.net[x]), 1), "in20": int(o.in20[x])}]
    n_all += len(ids)
    f.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
  cv = coverage(p)
  (out / "coverage.json").write_text(json.dumps({"cols": ["team", "season", "cov", "returned"],
                                                 "rows": [[tm, int(sn), round(float(c), 2), int(n)] for (tm, sn, c, n) in zip(cv.team, cv.season, cv["cov"], cv.returned)]},
                                                separators=(",", ":")), encoding="utf-8")
  print(f"[grades] punters: {n_all} graded punter-seasons, {int(t.season.min())}-{int(t.season.max())} "
        f"(shrinkage {kp:.0f} pseudo-punts)", flush=True)


# ---- Offensive line (INSIGHTS (EA)): the line graded as a unit each game, every lineman credited by his snaps
OL_FIRST = 2012  # snap counts
OL_POS = {"T", "G", "C", "OT", "OG", "OL"}
OL_QUAL = 0.40  # share of the team's offensive snaps over its games
RUN_CLIP = 1.5
OL_LABELS = ["Pass protection (the line)", "Run blocking (the line)"]
OLCOLS = ["game_id", "play_id", "season", "week", "season_type", "posteam", "defteam", "play_type", "qb_dropback", "qb_kneel",
          "qb_spike", "qb_scramble", "rush", "sack", "qb_hit", "epa", "penalty", "penalty_player_id", "penalty_team",
          "run_location", "run_gap"]
SLOTS = ["LT", "LG", "C", "RG", "RT"]
# a designed run's credit by where it went (owner 2026-10-31, (EB)): the slots whose blocks open that gap
GAP_CREDIT = {("left", "end"): {"LT": 1.0}, ("left", "tackle"): {"LT": 0.5, "LG": 0.5}, ("left", "guard"): {"LG": 0.5, "C": 0.5},
              ("middle", None): {"C": 0.5, "LG": 0.25, "RG": 0.25},
              ("right", "guard"): {"RG": 0.5, "C": 0.5}, ("right", "tackle"): {"RT": 0.5, "RG": 0.5}, ("right", "end"): {"RT": 1.0}}
PRS_FIRST, FTN_FIRST = 2018, 2022


def ol_plays(cache_dir: Path, cur: int) -> pd.DataFrame:
  """Regular-season scrimmage plays for the line grade (cache/pbpol2_<season>.parquet, the current season refetched)."""
  import nflreadpy as nfl
  out = []
  for s in range(OL_FIRST, cur + 1):
    p = cache_dir / f"pbpol2_{s}.parquet"
    if p.exists() and s != cur:
      out.append(pd.read_parquet(p))
      continue
    try:
      df = nfl.load_pbp([s]).select(OLCOLS).to_pandas()
      df = df[df.season_type == "REG"]
      df.to_parquet(p, index=False)
      out.append(df)
    except Exception as e:
      print(f"[ol] {s}: {type(e).__name__} {str(e)[:80]}", flush=True)
      if p.exists():
        out.append(pd.read_parquet(p))
  return pd.concat(out, ignore_index=True)


def _season_cache(cache_dir: Path, name: str, s: int, cur: int, load):
  """A per-season frame from nflverse, cached as cache/<name>_<season>.parquet (the current season refetched)."""
  p = cache_dir / f"{name}_{s}.parquet"
  if p.exists() and s != cur:
    return pd.read_parquet(p)
  try:
    df = load()
    df.to_parquet(p, index=False)
    return df
  except Exception as e:
    print(f"[ol] {name} {s}: {type(e).__name__} {str(e)[:80]}", flush=True)
    return pd.read_parquet(p) if p.exists() else None


def pass_inputs(cache_dir: Path, cur: int, pl: pd.DataFrame) -> pd.DataFrame:
  """Per (season, week, team), 2018 on: the line's pressures (PFR, the QB's view), sacks FTN charts as the QB's fault
  and FTN's average pass rushers (2022 on), the QBs' time to throw (Next Gen Stats, attempts-weighted)."""
  import nflreadpy as nfl
  rows = []
  for s in range(PRS_FIRST, cur + 1):
    a = _season_cache(cache_dir, "pfrpass", s, cur, lambda: nfl.load_pfr_advstats([s], stat_type="pass", summary_level="week").to_pandas()[
      ["season", "week", "game_type", "team", "times_pressured"]])
    if a is None:
      continue
    a = a[a.game_type == "REG"].assign(team=lambda d: d.team.map(lambda t: D.RELOCATED.get(t, t)))
    x = a.groupby(["season", "week", "team"]).times_pressured.sum().rename("prs").to_frame()
    n = _season_cache(cache_dir, "ngspass", s, cur, lambda: nfl.load_nextgen_stats([s], stat_type="passing").to_pandas()[
      ["season", "season_type", "week", "team_abbr", "attempts", "avg_time_to_throw"]])
    if n is not None and len(n):
      n = n[(n.season_type == "REG") & (n.week > 0)].assign(team=lambda d: d.team_abbr.map(lambda t: D.RELOCATED.get(t, t)))
      n = n.assign(w=n.attempts * n.avg_time_to_throw).groupby(["season", "week", "team"])[["w", "attempts"]].sum()
      x = x.join((n.w / n.attempts.replace(0, np.nan)).rename("ttt"), how="left")
    if s >= FTN_FIRST:
      f = _season_cache(cache_dir, "ftn", s, cur, lambda: nfl.load_ftn_charting([s]).to_pandas()[
        ["nflverse_game_id", "nflverse_play_id", "is_qb_fault_sack", "n_pass_rushers"]])
      if f is not None and len(f):
        k = pl[pl.season == s][["game_id", "play_id", "week", "posteam", "qb_dropback"]].copy()
        f = f.assign(game_id=f.nflverse_game_id, play_id=pd.to_numeric(f.nflverse_play_id, errors="coerce"))
        k["play_id"] = pd.to_numeric(k.play_id, errors="coerce")
        m = k.merge(f[["game_id", "play_id", "is_qb_fault_sack", "n_pass_rushers"]], on=["game_id", "play_id"], how="inner")
        m = m[pd.to_numeric(m.qb_dropback, errors="coerce").fillna(0) == 1].assign(
          team=lambda d: d.posteam.map(lambda t: D.RELOCATED.get(t, t)), season=s,
          qbf=lambda d: d.is_qb_fault_sack.astype(float), rush_n=lambda d: pd.to_numeric(d.n_pass_rushers, errors="coerce"))
        g = m.groupby(["season", "week", "team"]).agg(qbf=("qbf", "sum"), rushers=("rush_n", "mean"))
        x = x.join(g, how="left")
    rows.append(x.reset_index())
  out = pd.concat(rows, ignore_index=True)
  for c in ("ttt", "qbf", "rushers"):
    if c not in out:
      out[c] = np.nan
  return out


def pressure_cost(cache_dir: Path, cur: int, pl: pd.DataFrame) -> dict:
  """{season: EPA cost of a pressure} = mean EPA of clean dropbacks - pressured ones (participation, 2017-2025);
  other seasons get the average."""
  import nflreadpy as nfl
  cost = {}
  for s in range(2017, min(cur, 2025) + 1):
    p = _season_cache(cache_dir, "part", s, -1, lambda: nfl.load_participation([s]).to_pandas()[["nflverse_game_id", "play_id", "was_pressure"]])
    if p is None or not len(p):
      continue
    k = pl[(pl.season == s) & (pd.to_numeric(pl.qb_dropback, errors="coerce").fillna(0) == 1)][["game_id", "play_id", "epa"]].copy()
    k["play_id"] = pd.to_numeric(k.play_id, errors="coerce")
    q = p.rename(columns={"nflverse_game_id": "game_id"}).assign(play_id=lambda d: pd.to_numeric(d.play_id, errors="coerce"))
    m = k.merge(q, on=["game_id", "play_id"]).dropna(subset=["was_pressure", "epa"])
    if len(m) > 1000:
      wp = m.was_pressure.astype(bool)
      cost[s] = float(m.epa[~wp].mean() - m.epa[wp].mean())
  avg = float(np.mean(list(cost.values()))) if cost else 0.8
  return {s: cost.get(s, avg) for s in range(OL_FIRST, cur + 1)}


def ol_slots(cache_dir: Path, cur: int) -> dict:
  """(gsis, season) -> his most common starting slot (LT / LG / C / RG / RT) on that season's depth charts."""
  import nflreadpy as nfl
  out = {}
  for s in range(OL_FIRST, cur + 1):
    d = _season_cache(cache_dir, "dcol", s, cur, lambda: nfl.load_depth_charts([s]).to_pandas())
    if d is None or not len(d):
      continue
    if "pos_abb" in d:  # 2025 on: ESPN's charts (pos_rank 1 = the starter)
      x = d[(pd.to_numeric(d.pos_rank, errors="coerce") == 1) & d.pos_abb.isin(SLOTS)][["gsis_id", "pos_abb"]].rename(columns={"pos_abb": "slot"})
    else:
      x = d[(d.depth_team.astype(str) == "1") & d.depth_position.isin(SLOTS) & (d.game_type == "REG")][["gsis_id", "depth_position"]].rename(
        columns={"depth_position": "slot"})
    x = x.dropna(subset=["gsis_id"])
    for g, sl in x.groupby("gsis_id").slot.agg(lambda v: v.mode().iloc[0]).items():
      out[(g, s)] = sl
  return out


def ol_units(pl: pd.DataFrame, inputs: pd.DataFrame | None = None, cost: dict | None = None) -> pd.DataFrame:
  """One row per team-game: the line's value (EPA) against the opponent's norm, pass protection and run blocking, and
  the run part by slot (run_LT ... run_RT; each run credited by its gap). Pass protection from real pressures (2018 on,
  inputs) against an expected rate (QB time to throw, opponent, rushers); before 2018 sacks + half hits."""
  f = lambda c: pd.to_numeric(pl[c], errors="coerce").fillna(0)  # noqa: E731
  db = (f("qb_dropback") == 1) & (f("qb_spike") == 0)
  run = (f("rush") == 1) & (f("qb_scramble") == 0) & (f("qb_kneel") == 0)
  x = pd.DataFrame({"game_id": pl.game_id, "season": pl.season, "week": pl.week, "team": pl.posteam, "opp": pl.defteam,
                    "db": db.astype(float), "prs1": (db & ((f("sack") == 1) | (f("qb_hit") == 1))).astype(float)
                    * np.where(f("sack") == 1, 1.0, 0.5),
                    "sack_epa": np.where(db & (f("sack") == 1), pd.to_numeric(pl.epa, errors="coerce"), np.nan),
                    "run": run.astype(float), "run_epa": np.where(run, pd.to_numeric(pl.epa, errors="coerce").clip(-RUN_CLIP, RUN_CLIP), 0.0),
                    "loc": pl.run_location, "gap": pl.run_gap})
  x = x[x.team.notna() & x.opp.notna()].copy()
  for c in ("team", "opp"):
    x[c] = x[c].map(lambda t: D.RELOCATED.get(t, t))
  g = x.groupby(["season", "week", "game_id", "team", "opp"]).agg(db=("db", "sum"), prs1=("prs1", "sum"), run=("run", "sum"),
                                                                   run_epa=("run_epa", "sum")).reset_index()
  sack_cost = x.groupby("season").sack_epa.mean().abs()

  def other_games(df, num, den):  # each defense's rate over its other games that season
    d = df.groupby(["season", "opp"])[[num, den]].sum()
    k = d.reindex(pd.MultiIndex.from_frame(df[["season", "opp"]])).to_numpy() - df[[num, den]].to_numpy()
    return k[:, 0] / np.maximum(k[:, 1], 1)
  g["exp_run"] = other_games(g, "run_epa", "run")
  g["run_v"] = g.run_epa - g.exp_run * g.run
  # sacks + half hits for every season; real pressures replace it from 2018 where the inputs exist
  g["pass_v"] = (other_games(g, "prs1", "db") - g.prs1 / g.db.clip(lower=1)) * g.db * g.season.map(sack_cost).to_numpy()
  g["pass_basis"] = "sacks"
  if inputs is not None and len(inputs):
    g = g.merge(inputs, on=["season", "week", "team"], how="left")
    have = (g.prs.notna() & (g.season >= PRS_FIRST)).to_numpy()
    g["prs2"] = (g.prs - g.qbf.fillna(0)).clip(lower=0)
    g["rate"] = g.prs2 / g.db.clip(lower=1)
    g["opp_rate"] = np.nan
    gg = g[have]
    g.loc[have, "opp_rate"] = other_games(gg, "prs2", "db")
    for s in sorted(g.loc[have, "season"].unique()):
      tr = g[have & g.season.between(s - 1, s + 1).to_numpy()].copy()
      te = have & (g.season == s).to_numpy()
      fill = {c: (tr[c].mean() if tr[c].notna().any() else 0.0) for c in ("ttt", "rushers")}
      tr = tr.fillna(fill)
      X = lambda d: np.column_stack([np.ones(len(d)), d.ttt, d.opp_rate, d.rushers])  # noqa: E731
      w = np.sqrt(tr.db.to_numpy())
      beta = np.linalg.lstsq(X(tr) * w[:, None], tr.rate.to_numpy() * w, rcond=None)[0]
      t2 = g[te].fillna(fill)
      exp_rate = X(t2) @ beta
      g.loc[te, "pass_v"] = (exp_rate - t2.rate.to_numpy()) * t2.db.to_numpy() * (cost or {}).get(int(s), 0.8)
      g.loc[te, "pass_basis"] = "pressures"
  # the run part by slot: each run's excess over the opponent's norm, credited by its gap
  x = x.merge(g[["game_id", "team", "exp_run"]], on=["game_id", "team"], how="left")
  rx = x[x.run == 1].copy()
  rx["ex"] = rx.run_epa - rx.exp_run
  for sl in SLOTS:
    rx[f"run_{sl}"] = 0.0
  for (loc, gap), cr in GAP_CREDIT.items():
    m = (rx["loc"] == loc) & ((rx.gap == gap) if gap else rx.gap.isna())
    for sl, c in cr.items():
      rx.loc[m, f"run_{sl}"] += c * rx.loc[m, "ex"]
  none = ~rx["loc"].isin(["left", "middle", "right"])  # no location recorded: shared evenly
  for sl in SLOTS:
    rx.loc[none, f"run_{sl}"] += rx.loc[none, "ex"] / 5
  slot = rx.groupby(["game_id", "team"])[[f"run_{sl}" for sl in SLOTS]].sum()
  g = g.join(slot, on=["game_id", "team"])
  for sl in SLOTS:
    g[f"run_{sl}"] = g[f"run_{sl}"].fillna(0.0)
  g["plays"] = g.db + g.run
  g["val"] = g.pass_v + g.run_v
  return g


def ol_seasons(units: pd.DataFrame, pl: pd.DataFrame, cache_dir: Path, cur: int, sched: pd.DataFrame, slots: dict | None = None):
  """(lineman-game rows, lineman-seasons). Pass protection is the line's; the run part is his slot's (x 5, so the
  five slots average to the unit), or the line's when he has no slot. Snap counts map PFR ids to gsis."""
  import nflreadpy as nfl
  players = D.Cache(cache_dir).get("players", "all", lambda: nfl.load_players(), stale=False)
  p2g = players.dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates("pfr_id").set_index("pfr_id").gsis_id
  sn = []
  for s in range(OL_FIRST, cur + 1):
    f = cache_dir / f"snaps_{s}.parquet"
    if f.exists():
      x = pd.read_parquet(f)
      sn.append(x[(x.game_type == "REG") & x.position.isin(OL_POS)])
  sn = pd.concat(sn, ignore_index=True)
  sn = sn.assign(gsis_id=sn.pfr_player_id.map(p2g), team=sn.team.map(lambda t: D.RELOCATED.get(t, t))).dropna(subset=["gsis_id"])
  sn["snaps"] = pd.to_numeric(sn.offense_snaps, errors="coerce").fillna(0)
  sn = sn[sn.snaps > 0].copy()
  u = units.set_index(["game_id", "team"])
  key = pd.MultiIndex.from_arrays([sn.game_id, sn.team])
  for c in ["val", "plays", "pass_v", "run_v"] + [f"run_{sl}" for sl in SLOTS]:
    sn[c] = u[c].reindex(key).to_numpy()
  sn = sn.dropna(subset=["val"]).copy()
  slots = slots or {}
  sn["slot"] = [slots.get((g, int(s))) for g, s in zip(sn.gsis_id, sn.season)]
  own = np.full(len(sn), np.nan)
  for sl in SLOTS:
    m = (sn.slot == sl).to_numpy()
    own[m] = 5 * sn[f"run_{sl}"].to_numpy()[m]
  sn["run_own"] = np.where(np.isnan(own), sn.run_v, own)
  sn["val"] = sn.pass_v + sn.run_own
  pen = pl[pd.to_numeric(pl.penalty, errors="coerce").fillna(0) == 1].groupby(["season", "penalty_player_id"]).size()
  team_snaps = sn.groupby(["season", "team", "game_id"]).snaps.max().groupby(["season", "team"]).sum()
  w = sn.snaps / sn.plays.clip(lower=1)  # his share of the unit's plays that game
  sn["wv"], sn["wp"], sn["wr"], sn["wpl"] = sn.val * w, sn.pass_v * w, sn.run_own * w, sn.plays * w
  g = sn.groupby(["gsis_id", "season"])
  t = pd.DataFrame({"val": g.wv.sum(), "att": g.wpl.sum(), "pass_v": g.wp.sum(), "run_v": g.wr.sum(), "snaps": g.snaps.sum(),
                    "games": g.game_id.nunique(), "team": g.team.agg(lambda x: x.mode().iloc[0]),
                    "pos": g.position.agg(lambda x: x.mode().iloc[0]),
                    "slot": g.slot.agg(lambda x: x.dropna().mode().iloc[0] if x.notna().any() else None)}).reset_index()
  t["tsn"] = [team_snaps.get((int(s), tm), np.nan) for s, tm in zip(t.season, t.team)]
  t["share"] = t.snaps / t.tsn
  t["qual"] = t.share >= OL_QUAL
  t["pen"] = [int(pen.get((int(s), p), 0)) for s, p in zip(t.season, t.gsis_id)]
  return sn, t


def line_table(cache_dir: Path, cur: int, sched: pd.DataFrame):
  """(units, lineman-seasons, shrinkage) for the build and the check."""
  pl = ol_plays(cache_dir, cur)
  units = ol_units(pl, pass_inputs(cache_dir, cur, pl), pressure_cost(cache_dir, cur, pl))
  sn, t = ol_seasons(units, pl, cache_dir, cur, sched, ol_slots(cache_dir, cur))
  r = mom_prior(units.assign(gsis_id=units.team), "val", "plays")
  return units, t, (r[1] if r else 300.0)


def build_line(out: Path, cur: int, sched: pd.DataFrame, cache_dir: Path) -> None:
  """OL unit grades, by snaps (owner 2026-10-31: "only pin this grade to the linemen who played, weighted by snap
  share"): each game the line is graded as a unit (pass protection from real pressures 2018 on, run blocking, both
  against the opponent's norm), and a lineman's grade is those game grades weighted by his snaps in each game, so a
  backup carries only the stretches he played. Three-season form (1 / 0.6 / 0.3), shrunk by pseudo-plays (a few
  snaps lean on the league average), a percentile among linemen with 40%+ of their team's offensive snaps; linemen
  under that with 2+ games get an asterisked grade against them ([9] = 1), not counted in the rankings. Records:
  [OVR, "OL", games, weighted plays, window value / play (raw), [pass, run percentiles], season-only OVR, season value
  / play (raw), games, under-qualified flag, {unit, snap, pen, pos}]."""
  from grade_build import pct, pct_vs
  pl = ol_plays(cache_dir, cur)
  units = ol_units(pl, pass_inputs(cache_dir, cur, pl), pressure_cost(cache_dir, cur, pl))
  sn, t = ol_seasons(units, pl, cache_dir, cur, sched, {})  # no slots: the line's run blocking, shared
  r = mom_prior(units.assign(gsis_id=units.team), "val", "plays")
  kp = r[1] if r else 300.0
  n_q = n_u = 0
  for s in sorted(t.season.unique()):
    f = out / f"{int(s)}.json"
    doc = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"season": int(s), "stats": {}, "qualified": {}, "players": {}}
    one = t[t.season == s].drop_duplicates("gsis_id").set_index("gsis_id")
    q = list(one.index[one.qual])
    if len(q) < 10:
      continue
    uq = list(one.index[~one.qual & (one.games >= 2)])
    allp = q + uq
    o = one.loc[allp]
    cur_v, wa = window(t, s, allp, kp)
    sea_v = o.val / (o.att + kp)
    cur_raw, sea_raw = window(t, s, allp, kp, raw=True)[0], o.val / o.att
    pv, rv = o.pass_v / o.att, o.run_v / o.att
    gp, sg = pd.concat([pct(cur_v[q]), pct_vs(cur_v[q], cur_v[uq])]), pd.concat([pct(sea_v[q]), pct_vs(sea_v[q], sea_v[uq])])
    bp = [pd.concat([pct(b[q]), pct_vs(b[q], b[uq])]) for b in (pv.fillna(0.0), rv.fillna(0.0))]
    doc["stats"]["OL"], doc["qualified"]["OL"] = OL_LABELS, len(q)
    for x in allp:
      doc["players"][x] = [int(gp[x]), "OL", int(o.games[x]), int(round(wa[x])), round(float(cur_raw[x]), 4), [int(b[x]) for b in bp],
                           int(sg[x]), round(float(sea_raw[x]), 4), int(o.games[x]), 1 if x in uq else None,
                           {"unit": str(o.team[x]), "snap": int(round(100 * float(o.share[x]))) if pd.notna(o.share[x]) else None,
                            "pen": int(o.pen[x]), "pos": str(o.pos[x])}]
    n_q, n_u = n_q + len(q), n_u + len(uq)
    f.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
  print(f"[grades] offensive line (unit, by snaps): {n_q} qualified + {n_u} part-time lineman-seasons, "
        f"{int(t.season.min())}-{int(t.season.max())} (shrinkage {kp:.0f} pseudo-plays)", flush=True)


def evaluate_line(cache_dir: Path, cur: int, sched: pd.DataFrame) -> None:
  """(EB) description check: AP first-team linemen grade high (and (EA)'s 74.0 beaten)."""
  from grade_build import pct
  import nflreadpy as nfl
  hon = _honors()
  ap1 = {(pid, int(c[1])) for pid, hs in hon.items() for c in hs if c[0] == "AP1"}
  units, t, kp = line_table(cache_dir, cur, sched)
  sp = {}
  for s in sorted(t.season.unique()):
    one = t[(t.season == s) & t.qual].drop_duplicates("gsis_id").set_index("gsis_id")
    if len(one) >= 10:
      for pid, v in pct(one.val / (one.att + kp)).items():
        sp[(pid, int(s))] = int(v)
  hits = {k: sp[k] for k in ap1 if k in sp and 2013 <= k[1] <= 2025}
  v = np.array(list(hits.values()))
  avg, share = float(v.mean()), float(np.mean(v > 50))
  ovr = lambda p: round(50 + 49 * p / 99)  # noqa: E731
  names = nfl.load_players().to_pandas().set_index("gsis_id").display_name
  print(f"(EB) offensive line v2: shrinkage {kp:.0f} pseudo-plays; {int(t.qual.sum())} qualified lineman-seasons; "
        f"slots known for {t[t.qual].slot.notna().mean():.0%}")
  print(f"  pass basis: {units.groupby('pass_basis').size().to_dict()}")
  print(f"  AP first-team linemen 2013-2025: {len(v)} graded seasons, average season grade {avg:.1f} ((EA) 74.0), "
        f"{share:.0%} above the median (need 75%+); at 99 OVR: {int(sum(ovr(x) >= 99 for x in v))}, "
        f"90+: {int(sum(ovr(x) >= 90 for x in v))}, under 75: {int(sum(ovr(x) < 75 for x in v))}")
  print(f"  CHECK: {'PASS' if avg > 74.0 and share >= 0.75 else 'FAIL'}")
  pid = names[names == "Joe Thomas"].index[0]
  print("  Joe Thomas: " + ", ".join(f"{y} {ovr(sp[(pid, y)]) if (pid, y) in sp else '-'}" for y in (2013, 2014, 2015)))
  den = t[(t.season == 2013) & (t.team == "DEN") & t.qual]
  print("  2013 Broncos: " + ", ".join(f"{names.get(g, g)} {ovr(sp.get((g, 2013), 0))}" for g in den.gsis_id))


def _honors() -> dict:
  f = ROOT / "scratch" / "site" / "data" / "honors.json"
  if f.exists():
    return json.loads(f.read_text(encoding="utf-8"))["p"]
  import urllib.request
  return json.load(urllib.request.urlopen("https://chefjulio.github.io/nfl-edge/data/honors.json"))["p"]


def evaluate_punters(cache_dir: Path, cur: int, sched: pd.DataFrame) -> None:
  """(DZ) description checks: AP first-team punters grade high; the punter's value is apart from his coverage."""
  from grade_build import pct
  hon = _honors()
  ap1 = {(pid, int(c[1])) for pid, hs in hon.items() for c in hs if c[0] == "AP1"}

  def season_pct(t, kp):
    out = {}
    for s in sorted(t.season.unique()):
      one = t[(t.season == s) & t.qual].drop_duplicates("gsis_id").set_index("gsis_id")
      if len(one) >= 5:
        for pid, v in pct(one.val / (one.att + kp)).items():
          out[(pid, int(s))] = int(v)
    return out
  p = punts(st_plays(cache_dir, cur))
  t = punter_seasons(p, sched)
  kp = _prior(p, "punter_player_id", t, 40.0)
  sp = season_pct(t, kp)
  hits = [sp[k] for k in ap1 if k in sp and 2001 <= k[1] <= 2025]
  avg, share = float(np.mean(hits)), float(np.mean(np.array(hits) > 50))
  cv = coverage(p).set_index(["team", "season"])["cov"]
  q = t[t.qual & t.season.between(2001, 2025)]
  rr = pd.DataFrame({"v": q.val / q.att, "c": [cv.get((a, int(b)), np.nan) for a, b in zip(q.team, q.season)]}).dropna()
  r = float(np.corrcoef(rr.v, rr.c)[0, 1])
  print(f"(DZ) punters: shrinkage {kp:.0f} pseudo-punts; {int(t.qual.sum())} qualified punter-seasons")
  print(f"  (1) AP first-team punters 2001-2025: {len(hits)} graded seasons, average season grade {avg:.1f} "
        f"(need 75+), {share:.0%} above the median (need 80%+)")
  print(f"  (2) value per punt vs his team's coverage, {len(rr)} punter-seasons: r = {r:+.3f} (need within +-0.2)")
  ok = avg >= 75 and share >= 0.80 and abs(r) <= 0.2
  print(f"  CHECKS: {'PASS' if ok else 'FAIL'}")
  # reported, not gating: the kicker grade against AP first-team kickers
  k = kicks(st_plays(cache_dir, cur))
  tk = kicker_seasons(k, sched)
  kk = prior(k, tk)
  spk = season_pct(tk, kk)
  kh = [spk[x] for x in ap1 if x in spk and 2001 <= x[1] <= 2025]
  print(f"  (reported) AP first-team kickers: {len(kh)} graded seasons, average {np.mean(kh):.1f}, "
        f"{np.mean(np.array(kh) > 50):.0%} above the median")


def evaluate(cache_dir: Path, cur: int, sched: pd.DataFrame) -> None:
  """(DY) gate: does the grade's rate this season rank next season's field-goal value per attempt better than raw FG%?"""
  from scipy.stats import spearmanr
  k = kicks(st_plays(cache_dir, cur))
  t = kicker_seasons(k, sched)
  kp = prior(k, t)
  rows = []
  for s in range(2005, 2025):
    a = t[(t.season == s) & t.qual].set_index("gsis_id")
    b = t[(t.season == s + 1) & t.qual].set_index("gsis_id")
    ids = a.index.intersection(b.index)
    if len(ids) < 8:
      continue
    gv, _ = window(t, s, list(ids), kp)
    rows.append(pd.DataFrame({"season": s, "grade": gv.to_numpy(), "fgpct": (a.fgm / a.fga).reindex(ids).to_numpy(),
                              "next": (b.fg_val / b.fga).reindex(ids).to_numpy()}))
  r = pd.concat(rows, ignore_index=True)
  rho = lambda d, c: spearmanr(d[c], d["next"]).statistic  # noqa: E731
  g0, f0 = rho(r, "grade"), rho(r, "fgpct")
  rng = np.random.default_rng(0)
  boot = []
  for _ in range(2000):
    d = r.iloc[rng.integers(0, len(r), len(r))]
    boot.append(rho(d, "grade") - rho(d, "fgpct"))
  lo, hi = np.percentile(boot, [2.5, 97.5])
  per = r.groupby("season").apply(lambda d: rho(d, "grade") > rho(d, "fgpct"))
  print(f"(DY) kickers qualified in back-to-back seasons, 2005-2025: {len(r)} pairs; shrinkage {kp:.0f} pseudo-attempts")
  print(f"  rank corr. with next season's FG points over expected / attempt: grade {g0:.3f}, raw FG% {f0:.3f}")
  print(f"  difference {g0 - f0:+.3f} [{lo:+.3f}, {hi:+.3f}]; grade better in {int(per.sum())}/{len(per)} seasons")
  print(f"  GATE: {'PASS' if lo > 0 else 'FAIL'}")


if __name__ == "__main__":
  from nfledge.config import load_config
  cfg = load_config()
  cache_dir = ROOT / cfg["data"]["cache_dir"]
  sched = D.Cache(cache_dir).get("schedules", "since1999", None, stale=False)
  import nflreadpy as nfl
  cur = int(nfl.get_current_season())
  if "--eval" in sys.argv:
    evaluate(cache_dir, cur, sched)
  if "--eval-p" in sys.argv:
    evaluate_punters(cache_dir, cur, sched)
  if "--eval-ol" in sys.argv:
    evaluate_line(cache_dir, cur, sched)
