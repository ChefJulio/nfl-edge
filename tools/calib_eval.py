"""(W) per-position median calibration curve on the final projection (docs/INSIGHTS.md, pre-registered 2026-10-17).

Curve (per position): the fit rows' projections in 20 equal-count bins, each bin's median actual, made non-decreasing
by weighted pool-adjacent-violators (weights = bin counts), applied by linear interpolation between the bins' median
projections (flat beyond the ends). Walk-forward on the cached baseline backtests: season s uses a curve fit on
2021..s-1; decide on 2022-2025, confirm on 2026 (curve from 2021-25).

  python tools/calib_eval.py
"""
from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from experiments import relevant, week_bootstrap  # noqa: E402

POS = ["QB", "RB", "WR", "TE"]
BINS = 20


def load(seasons) -> pd.DataFrame:
  fr = []
  for s in seasons:
    fs = sorted(glob.glob(str(ROOT / "cache" / "experiments" / f"baseline_{s}_*.parquet")), key=os.path.getmtime)
    fr.append(relevant(pd.read_parquet(fs[-1])))
  d = pd.concat(fr, ignore_index=True)
  d["sw"] = d.season.astype(str) + "-" + d.week.astype(str)
  return d


def pava(y: np.ndarray, w: np.ndarray) -> np.ndarray:
  """Weighted pool-adjacent-violators: the closest non-decreasing sequence."""
  blocks = [[float(v), float(c), 1] for v, c in zip(y, w)]  # value, weight, size
  i = 0
  while i < len(blocks) - 1:
    if blocks[i][0] > blocks[i + 1][0]:
      a, b = blocks[i], blocks[i + 1]
      wt = a[1] + b[1]
      blocks[i] = [(a[0] * a[1] + b[0] * b[1]) / wt, wt, a[2] + b[2]]
      del blocks[i + 1]
      i = max(i - 1, 0)
    else:
      i += 1
  return np.concatenate([[v] * n for v, _, n in blocks])


def fit(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
  order = np.argsort(x, kind="stable")
  xs, ys = x[order], y[order]
  parts = np.array_split(np.arange(len(xs)), BINS)
  bx = np.array([np.median(xs[p]) for p in parts])
  by = np.array([np.median(ys[p]) for p in parts])
  return bx, pava(by, np.array([len(p) for p in parts], float))


def apply(curve, x: np.ndarray) -> np.ndarray:
  bx, by = curve
  return np.interp(x, bx, by)  # flat beyond the ends


def calibrate(train: pd.DataFrame, test: pd.DataFrame) -> pd.Series:
  out = pd.Series(np.nan, index=test.index)
  for pos in POS:
    tr, te = train[train.pos == pos], test[test.pos == pos]
    if len(tr) >= BINS * 10 and len(te):
      out[te.index] = apply(fit(tr.proj.to_numpy(float), tr.actual.to_numpy(float)), te.proj.to_numpy(float))
  return out.fillna(test.proj)


def score(d: pd.DataFrame, label: str):
  diff = (d.cal - d.actual).abs() - (d.proj - d.actual).abs()
  lo, hi = week_bootstrap(diff, d.sw)
  print(f"  {label}: rows {len(d)}  MAE {(d.proj - d.actual).abs().mean():.4f} -> {(d.cal - d.actual).abs().mean():.4f}"
        f"  diff {diff.mean():+.4f} [{lo:+.4f}, {hi:+.4f}]")
  return diff.mean(), lo, hi


def tiers(d: pd.DataFrame):
  d = d.copy()
  d["rk"] = d.groupby(["season", "week", "pos"]).proj.rank(ascending=False, method="first")
  for pos, cuts in (("RB", [0, 5, 12, 24, 999]), ("WR", [0, 5, 12, 24, 999]), ("QB", [0, 3, 8, 16, 999]), ("TE", [0, 3, 8, 16, 999])):
    x = d[d.pos == pos]
    parts = []
    for lo, hi in zip(cuts[:-1], cuts[1:]):
      t = x[(x.rk > lo) & (x.rk <= hi)]
      parts.append(f"{lo + 1}-{hi if hi < 999 else '+'} {(t.actual - t.proj).mean():+.2f}->{(t.actual - t.cal).mean():+.2f}")
    print(f"    {pos} bias by tier (actual - proj, raw -> calibrated): " + "  ".join(parts))


def main():
  allr = load(range(2021, 2027))
  dec = []
  for s in range(2022, 2026):
    te = allr[allr.season == s].copy()
    te["cal"] = calibrate(allr[(allr.season >= 2021) & (allr.season < s)], te)
    dec.append(te)
  d = pd.concat(dec)
  print("DECIDE 2022-2025 (walk-forward):")
  m, lo, hi = score(d, "ALL")
  better = 0
  for s, x in d.groupby("season"):
    ms, _, _ = score(x, str(s))
    better += ms < 0
  worse = []
  for pos in POS:
    _, plo, _ = score(d[d.pos == pos], pos)
    if plo > 0:
      worse.append(pos)
  tiers(d)
  ok = hi < 0 and better >= 3 and not worse
  print(f"  better {better}/4 seasons; positions significantly worse: {worse or 'none'}  -> DECIDE {'PASS' if ok else 'FAIL'}")
  te = allr[allr.season == 2026].copy()
  print("CONFIRM 2026 (curve fit on 2021-25):")
  if len(te):
    te["cal"] = calibrate(allr[allr.season.between(2021, 2025)], te)
    c, clo, chi = score(te, "ALL")
    tiers(te)
    conf = c < 0 and clo <= 0
    print(f"  CONFIRM {'PASS' if conf else 'FAIL'}")
  else:
    conf = False
    print("  no 2026 rows")
  print(f"GATE: {'PASS' if ok and conf else 'FAIL'}")


if __name__ == "__main__":
  main()
