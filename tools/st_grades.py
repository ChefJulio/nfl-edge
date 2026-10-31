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
