"""(AL) in-season calibration of the projection level (pre-registered in docs/INSIGHTS.md 2026-10-17).

Usage: python tools/env_eval.py
For week w of season s every projection is multiplied by r = (A + k M) / (P + k M): A, P = actual and projected points
of the season's played rows (projection >= 3) in weeks before w, M = their mean projection, k pseudo player-games.
One league-wide r per week (uniform, so it never reorders players). Walk-forward backtests cache/experiments/adopted_*,
weeks 3-18, rows played with projection >= 3. CHOOSE k in {250, 1000, 4000} by MAE on 2021-23; DECIDE on 2024-25: MAE
lower with a 95% CI over season-weeks excluding 0 and lower in both seasons; guard: no position significantly worse.
"""
import glob
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
GRID, CHOOSE, DECIDE = [250, 1000, 4000], [2021, 2022, 2023], [2024, 2025]

d = pd.concat([pd.read_parquet(f, columns=["season", "week", "pos", "played", "proj", "actual"])
               for f in sorted(glob.glob(str(ROOT / "cache" / "experiments" / "adopted_*.parquet")))])
d = d[d.played & (d.proj >= 3) & d.week.between(3, 18)].reset_index(drop=True)
d["wk"] = d.season.astype(str) + "-" + d.week.astype(str)


def factors(k: float) -> pd.Series:
  """r for every (season, week) from that season's earlier weeks."""
  out = {}
  for s, g in d.groupby("season"):
    for w in sorted(g.week.unique()):
      prev = g[g.week < w]
      if len(prev):
        A, P, M = prev.actual.sum(), prev.proj.sum(), prev.proj.mean()
        out[(s, w)] = (A + k * M) / (P + k * M)
      else:
        out[(s, w)] = 1.0
  return pd.Series(out)


def ci(diff, groups):
  g = pd.DataFrame({"d": diff, "g": groups}).groupby("g").d.agg(["sum", "size"])
  idx = np.random.default_rng(0).integers(0, len(g), size=(2000, len(g)))
  m = g["sum"].to_numpy()[idx].sum(1) / g["size"].to_numpy()[idx].sum(1)
  return np.percentile(m, [2.5, 97.5])


base_err = (d.proj - d.actual).abs()
res = {}
for k in GRID:
  r = factors(k)
  adj = d.proj * pd.Series([r[(s, w)] for s, w in zip(d.season, d.week)], index=d.index)
  res[k] = ((adj - d.actual).abs(), adj, r)
print("CHOOSE 2021-23 (MAE diff vs today):")
m = d.season.isin(CHOOSE)
for k in GRID:
  diff = (res[k][0] - base_err)[m].to_numpy()
  lo, hi = ci(diff, d.wk[m])
  print(f"  k {k}: {diff.mean():+.4f} [{lo:+.4f}, {hi:+.4f}]")
best = min(GRID, key=lambda k: res[k][0][m].mean())
print(f"  chosen: k {best}")
m2 = d.season.isin(DECIDE)
diff = (res[best][0] - base_err)[m2]
lo, hi = ci(diff.to_numpy(), d.wk[m2])
per = diff.groupby(d.season[m2]).mean()
print(f"DECIDE 2024-25: {diff.mean():+.4f} [{lo:+.4f}, {hi:+.4f}]  " + " ".join(f"{s} {v:+.4f}" for s, v in per.items()))
worse = []
for pos, idx in d[m2].groupby("pos").groups.items():
  dd = diff.loc[idx]
  plo, phi = ci(dd.to_numpy(), d.wk.loc[idx])
  print(f"    {pos}: {dd.mean():+.4f} [{plo:+.4f}, {phi:+.4f}]")
  if plo > 0:
    worse.append(pos)
ok = hi < 0 and (per < 0).all() and not worse
print("GATE:", "PASS" if ok else "FAIL")
adj = res[best][1]
print("\nbias (actual - projected, % of projected) by season, today -> calibrated:")
for s, g in d.groupby("season"):
  b0 = 100 * (g.actual.sum() - g.proj.sum()) / g.proj.sum()
  b1 = 100 * (g.actual.sum() - adj[g.index].sum()) / adj[g.index].sum()
  print(f"  {s}: {b0:+.1f}% -> {b1:+.1f}%")
r = res[best][2]
print("\nr by week, 2024 and 2025 (kickoff-rule years):")
for s in (2024, 2025):
  print(f"  {s}: " + " ".join(f"{w}:{r[(s, w)]:.3f}" for w in range(3, 19) if (s, w) in r))

# reported, not gated: squared error (the loss an expected value minimizes) and median vs mean of outcomes
print("\nnot gated: MSE diff (calibrated - today) by season, and how far the median outcome sits below the mean:")
for s, g in d.groupby("season"):
  e0, e1 = ((g.proj - g.actual) ** 2).mean(), ((adj[g.index] - g.actual) ** 2).mean()
  print(f"  {s}: MSE {e0:.2f} -> {e1:.2f} ({e1 - e0:+.3f})   actual median / mean {g.actual.median() / g.actual.mean():.2f}")
