"""(S2) durability judged by snaps survived (pre-registered 2026-10-19, docs/INSIGHTS.md).

For each player-season T (2014-2025, 8+ team games on the roster in T), two scores from his history 2013..T-1 (as in
tools/durability_eval.py): A = share of team games available, shrunk 17 games (the site); B = games missed injured per
1,000 unit snaps, shrunk with (S)'s K. Target: his unit snaps in T before his first game missed injured (event), else
censored at his snaps in T. Metric: Harrell's C-index within position group, weighted by rows. GATE on 2020-25: B - A > 0,
95% player-cluster bootstrap CI excluding 0, B better in >= 4 of 6 seasons.

  python tools/durability_snaps_eval.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from nfledge import data as D  # noqa: E402
from nfledge.config import ROOT, load_config  # noqa: E402
import player_logs as PL  # noqa: E402
from durability_eval import DEFENSE, GRP, OFFENSE  # noqa: E402

K = {"TE": 2000}  # (S)'s choice on 2014-19: 250 everywhere but TE
DECIDE = range(2020, 2026)


def load():
  import nflreadpy as nfl
  cfg = load_config()
  data = D.load_all(cfg)
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  first = min(data.seasons)
  players = cache.get("players", "all", lambda: nfl.load_players(), stale=False)
  pfr = players.dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates("pfr_id").set_index("pfr_id").gsis_id
  old = [cache.get("snaps", s, lambda: nfl.load_snap_counts([s]), stale=False) for s in range(2012, first)]
  old = [x[x.game_type == "REG"] for x in old if x is not None and len(x)]
  sn = pd.concat(old + [data.snaps], ignore_index=True)
  sn["gsis_id"] = sn.pfr_player_id.map(pfr).fillna(sn.gsis_id) if "gsis_id" in sn else sn.pfr_player_id.map(pfr)
  sn = sn.dropna(subset=["gsis_id"])
  allsched = cache.get("schedules", "since1999", lambda: None, stale=False)
  allsched = allsched[allsched.game_type == "REG"]
  ros_cols = ["season", "week", "team", "gsis_id", "position", "status", "status_description_abbr"]
  all_ros = pd.concat([x[[c for c in ros_cols if c in x]] for x in
                       [cache.get("rosters", s, lambda: None, stale=False) for s in range(2002, first)] + [data.rosters]
                       if x is not None and len(x)], ignore_index=True)
  tot = sn[["offense_snaps", "defense_snaps", "st_snaps"]].fillna(0).sum(axis=1)
  played = set(zip(sn.gsis_id[tot > 0], sn.season[tot > 0].astype(int), sn.week[tot > 0].astype(int)))
  inj = PL.injury_history(cache, nfl, data.current_season, all_ros, allsched, played)
  pos = all_ros.dropna(subset=["gsis_id"]).sort_values(["season", "week"]).drop_duplicates("gsis_id", keep="last").set_index("gsis_id").position
  wk_off = sn.groupby(["gsis_id", "season", "week"]).offense_snaps.sum().to_dict()
  wk_def = sn.groupby(["gsis_id", "season", "week"]).defense_snaps.sum().to_dict()
  out = {}
  for g, v in inj.items():
    grp = GRP.get(str(pos.get(g)), str(pos.get(g)))
    if grp not in OFFENSE | DEFENSE:
      continue
    unit = wk_off if grp in OFFENSE else wk_def
    missed = {}
    for e in v["eps"]:
      if e.get("missed") is not None:
        missed[e["s"]] = missed.get(e["s"], 0) + e["missed"]
    weeks = {}
    for s, w, o in v.get("wk", []):
      weeks.setdefault(s, []).append((w, o, float(unit.get((g, s, w), 0.0) or 0.0)))
    snaps = {s: sum(x[2] for x in ws) for s, ws in weeks.items()}
    out[g] = (grp, v["gs"], missed, snaps, weeks)
  return out


def rows(P: dict, T: int) -> pd.DataFrame:
  r = []
  for g, (grp, gs, missed, snaps, weeks) in P.items():
    if gs.get(T, 0) < 8 or T not in weeks:
      continue
    hist = [s for s in gs if 2013 <= s < T]
    if not hist:
      continue
    G = sum(gs[s] for s in hist)
    M = sum(missed.get(s, 0) for s in hist)
    S = sum(snaps.get(s, 0.0) for s in hist)
    ws = sorted(weeks[T])
    if ws[0][1]:
      continue  # out injured in his first week of T: not at risk from a healthy start
    t, ev = 0.0, 0
    for w, o, sn in ws:
      if o:
        ev = 1
        break
      t += sn
    if t <= 0:
      continue
    r.append((g, grp, G, M, S, t, ev))
  return pd.DataFrame(r, columns=["gsis", "grp", "G", "M", "S", "t", "e"])


def scores(d: pd.DataFrame) -> pd.DataFrame:
  d = d.copy()
  d["A"] = np.nan
  d["B"] = np.nan
  for grp, x in d.groupby("grp"):
    pool = x[x.G >= 17]
    a0 = 1 - pool.M.sum() / max(1, pool.G.sum())
    r0 = x.M.sum() / max(1.0, x.S.sum()) * 1000
    d.loc[x.index, "A"] = ((1 - x.M / x.G.where(x.G > 0, 1)) * x.G + a0 * 17) / (x.G + 17)
    k = K.get(grp, 250)
    d.loc[x.index, "B"] = -((x.M + r0 * k / 1000) / ((x.S + k) / 1000))
  return d


def cindex(t, e, s) -> tuple[float, float]:
  """Harrell's C: pairs where i had the event first; concordant if i's durability score is lower (ties half).
  Returns (concordant, comparable)."""
  t, e, s = np.asarray(t, float), np.asarray(e, int), np.asarray(s, float)
  i = np.where(e == 1)[0]
  if not len(i):
    return 0.0, 0.0
  comp = t[i][:, None] < t[None, :]
  conc = (s[i][:, None] < s[None, :]) + 0.5 * (s[i][:, None] == s[None, :])
  return float((conc * comp).sum()), float(comp.sum())


def season_c(d: pd.DataFrame, col: str) -> float:
  tot, n = 0.0, 0
  for _, x in d.groupby("grp"):
    if len(x) < 20 or x.e.sum() < 3:
      continue
    c, m = cindex(x.t, x.e, x[col])
    if m:
      tot += c / m * len(x)
      n += len(x)
  return tot / n if n else np.nan


def main():
  P = load()
  S = {T: scores(rows(P, T)) for T in DECIDE}
  print("rows per season:", {T: len(d) for T, d in S.items()}, "events:", {T: int(d.e.sum()) for T, d in S.items()})
  per = {T: (season_c(d, "A"), season_c(d, "B")) for T, d in S.items()}
  for T, (a, b) in per.items():
    print(f"{T}: C-index A {a:.4f}  B {b:.4f}  B-A {b - a:+.4f}")
  diff = np.mean([b - a for a, b in per.values()])
  better = sum(b > a for a, b in per.values())
  allr = pd.concat([d.assign(T=T) for T, d in S.items()], ignore_index=True)
  ids = allr.gsis.unique()
  by = {g: x for g, x in allr.groupby("gsis")}
  rng = np.random.default_rng(7)
  boots = []
  for _ in range(500):
    smp = pd.concat([by[g] for g in rng.choice(ids, len(ids))], ignore_index=True)
    boots.append(np.mean([season_c(x, "B") - season_c(x, "A") for _, x in smp.groupby("T")]))
  lo, hi = np.percentile(boots, [2.5, 97.5])
  print(f"DECIDE 2020-25: B-A {diff:+.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]  B better {better}/6")
  for grp in sorted(allr.grp.unique()):
    a = np.nanmean([season_c(d[d.grp == grp], "A") for d in S.values()])
    b = np.nanmean([season_c(d[d.grp == grp], "B") for d in S.values()])
    print(f"  {grp}: A {a:.4f}  B {b:.4f}  (rows {int((allr.grp == grp).sum())}, events {int(allr[allr.grp == grp].e.sum())})")
  print("GATE:", "PASS" if lo > 0 and better >= 4 else "FAIL")


if __name__ == "__main__":
  main()
