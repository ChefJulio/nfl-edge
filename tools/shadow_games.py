"""(CH) game-level shadow matchups 2025, pre-registered (docs/INSIGHTS.md, 2026-10-21). The list
(data/history/shadow_games_2025.csv) names, per game, a corner who shadowed a named receiver, from after-the-fact
reporting only. Measure: that receiver's miss (actual - projected) in the cached 2025 baseline (relevant rows).
GATE: mean miss < 0 with a 95% week-bootstrap CI excluding 0, <= -1.0 points, negative in weeks 1-9 and 10-18.
Comparison: the same receivers' miss in their other games.

  python tools/shadow_games.py
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
from shadow_eval import TEAM, ci, norm  # noqa: E402


def main():
  g = pd.read_csv(ROOT / "data" / "history" / "shadow_games_2025.csv")
  g["offteam"] = g.offteam.str.strip().replace(TEAM)
  g["key"] = g.receiver.map(norm)
  fs = sorted(glob.glob(str(ROOT / "cache" / "experiments" / "baseline_2025_*.parquet")), key=os.path.getmtime)
  b = relevant(pd.read_parquet(fs[-1]))
  b = b[b.pos.isin(["WR", "TE"])].copy()
  b["team"] = b.team.replace(TEAM)
  b["key"] = b.full_name.map(norm)
  b["miss"] = b.actual - b.proj
  x = g.merge(b[["week", "team", "key", "gsis_id", "proj", "actual", "miss"]],
              left_on=["week", "offteam", "key"], right_on=["week", "team", "key"], how="left")
  gone = x[x.miss.isna()]
  print(f"listed shadow games: {len(g)}; with a projection (played, 2+ prior games): {int(x.miss.notna().sum())}")
  if len(gone):
    print("  not scored (weeks 1-2, did not play, or name / team mismatch):")
    print("   " + "; ".join(f"wk{r.week} {r.receiver} {r.offteam} vs {r.corner}" for r in gone.itertuples()))
  x = x[x.miss.notna()].copy()
  m, lo, hi = ci(x.miss, x.week)
  print(f"\nshadowed receiver miss (actual - projected): {m:+.2f} [{lo:+.2f}, {hi:+.2f}] n {len(x)}; median {x.miss.median():+.2f}")
  sid = set(zip(x.week, x.gsis_id))
  oth = b[b.gsis_id.isin(x.gsis_id) & ~pd.Series(list(zip(b.week, b.gsis_id)), index=b.index).isin(sid)]
  print(f"same receivers, other games: {oth.miss.mean():+.2f} n {len(oth)}")
  e1, e2 = x[x.week <= 9].miss.mean(), x[x.week >= 10].miss.mean()
  print(f"weeks 1-9 {e1:+.2f} (n {int((x.week <= 9).sum())}), 10-18 {e2:+.2f} (n {int((x.week >= 10).sum())})")
  print("\nby corner:")
  print(x.groupby("corner").miss.agg(["size", "mean"]).sort_values("mean").round(2).to_string())
  gate = hi < 0 and m <= -1.0 and e1 < 0 and e2 < 0
  print(f"\nGATE: {'PASS' if gate else 'FAIL'}")


if __name__ == "__main__":
  main()
