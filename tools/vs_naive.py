"""Is the model worth anything? (owner 2026-10-21: "suggesting Marks ... over Ken Walker, the #2 RB on the season".)
On the cached baseline backtests 2021-25 (tools/experiments.py relevant rows: played, 2+ prior games), weeks 4+, our
projection vs two baselines a fantasy player would use: season-to-date points per game (raw_fpg) and the expert
consensus converted to points (ecr_pts). Metrics per position: MAE; start / sit accuracy (every pair of players at the
position in the same week whose predictions differ: share where the higher-predicted one scored more); and the
gap check: rows bucketed by FP/G minus our projection, actual minus projection per bucket (if players far above their
projection keep outscoring it, the model under-weights season form).

  python tools/vs_naive.py
"""
import glob
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from experiments import relevant  # noqa: E402


def pairs_acc(g: pd.DataFrame, col: str, rng) -> tuple[float, int]:
  hit = n = 0
  for _, w in g.groupby(["season", "week"]):
    if len(w) < 2:
      continue
    v, a = w[col].to_numpy(), w.actual.to_numpy()
    i, j = np.triu_indices(len(w), 1)
    keep = (v[i] != v[j]) & (a[i] != a[j])
    hit += int(((v[i] > v[j]) == (a[i] > a[j]))[keep].sum())
    n += int(keep.sum())
  return hit / max(n, 1), n


def main():
  fr = []
  for s in range(2021, 2026):
    fs = sorted(glob.glob(str(ROOT / "cache" / "experiments" / f"baseline_{s}_*.parquet")), key=os.path.getmtime)
    fr.append(relevant(pd.read_parquet(fs[-1])))
  d = pd.concat(fr, ignore_index=True)
  d = d[(d.week >= 4) & d.raw_fpg.notna() & (d.raw_games >= 3)].copy()
  rng = np.random.default_rng(0)
  print(f"rows {len(d)} (2021-25, weeks 4+, 3+ games so far)\n")
  print(f"{'pos':<4}{'n':>7}  {'MAE model':>9} {'FP/G':>6} {'ECR':>6}   {'start/sit model':>15} {'FP/G':>6} {'ECR':>6}")
  for pos in ["QB", "RB", "WR", "TE"]:
    g = d[d.pos == pos]
    e = g.dropna(subset=["ecr_pts"])
    m = [np.abs(g.actual - g.proj).mean(), np.abs(g.actual - g.raw_fpg).mean(), np.abs(e.actual - e.ecr_pts).mean() if len(e) else np.nan]
    a = [pairs_acc(g, "proj", rng)[0], pairs_acc(g, "raw_fpg", rng)[0], pairs_acc(e, "ecr_pts", rng)[0] if len(e) else np.nan]
    a_e = pairs_acc(e, "proj", rng)[0] if len(e) else np.nan
    print(f"{pos:<4}{len(g):>7}  {m[0]:>9.3f} {m[1]:>6.3f} {m[2]:>6.3f}   {a[0]:>15.3f} {a[1]:>6.3f} {a[2]:>6.3f}   (model on ECR rows {a_e:.3f}, n {len(e)})")
  print("\nRB / WR: actual minus projection, by season FP/G minus projection (the Walker / Marks gap):")
  for pos in ["RB", "WR"]:
    g = d[d.pos == pos].copy()
    g["gap"] = g.raw_fpg - g.proj
    bins = [-99, -6, -3, -1, 1, 3, 6, 99]
    g["b"] = pd.cut(g.gap, bins)
    t = g.groupby("b", observed=True).apply(lambda x: pd.Series({"n": len(x), "proj": x.proj.mean(), "fpg": x.raw_fpg.mean(),
                                                                 "actual": x.actual.mean(), "miss": (x.actual - x.proj).mean()}))
    print(f"  {pos}\n" + t.round(2).to_string())


if __name__ == "__main__":
  main()
