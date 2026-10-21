"""Do we pull rushing efficiency too hard toward average? (owner 2026-10-21: Woody Marks projected 4.4 yards a carry on a
3.6 career; Kenneth Walker 4.2 on 7.) Descriptive, on the cached baseline backtests (tools/experiments.py), before any
change is pre-registered.

RBs with a record (n_rush >= MIN carries before the week) who had 5+ carries in the game: bucketed by the yards per
carry the model saw (rush_yd_per_rush); per bucket, projected yards per carry (rush_yd / carries) vs actual
(a_rush_yd / a_rush), and the same for rushing TDs per carry. If low-efficiency backs run below their projection and
high ones above, the efficiency inputs are under-weighted.

  python tools/eff_resid.py [--min=100]
"""
import glob
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  mn = int(opt.get("min", 100))
  fr = []
  for s in range(2021, 2026):
    fs = sorted(glob.glob(str(ROOT / "cache" / "experiments" / f"baseline_{s}_*.parquet")), key=os.path.getmtime)
    if fs:
      fr.append(pd.read_parquet(fs[-1]))
  d = pd.concat(fr, ignore_index=True)
  d = d[(d.pos == "RB") & (d.played == 1) & (d.n_rush >= mn) & (d.a_rush >= 5) & (d.carries > 0)].copy()
  d["p_ypc"], d["a_ypc"] = d.rush_yd / d.carries, d.a_rush_yd / d.a_rush
  d["p_tdc"], d["a_tdc"] = d.rush_td / d.carries, d.a_rush_td / d.a_rush
  d["h_ypc"] = d.rush_yd_per_rush
  print(f"RB games {len(d)} (2021-25, {mn}+ prior carries, 5+ carries in the game)\n")
  d["bin"] = pd.qcut(d.h_ypc, 6)
  rows = []
  for b, g in d.groupby("bin", observed=True):
    w = g.a_rush  # carry-weighted rates
    rows.append({"hist ypc": f"{g.h_ypc.min():.2f}-{g.h_ypc.max():.2f}", "games": len(g),
                 "proj ypc": np.average(g.p_ypc, weights=w), "actual ypc": g.a_rush_yd.sum() / g.a_rush.sum(),
                 "proj td/c": np.average(g.p_tdc, weights=w), "actual td/c": g.a_rush_td.sum() / g.a_rush.sum(),
                 "pts bias": (g.actual - g.proj).mean()})
  t = pd.DataFrame(rows)
  t["ypc miss"] = t["actual ypc"] - t["proj ypc"]
  print(t.round(3).to_string(index=False))
  # the same by the TD rate the model saw
  d["tbin"] = pd.qcut(d.rush_td_per_rush.rank(method="first"), 5)
  print("\nby historical rush TD per carry:")
  for b, g in d.groupby("tbin", observed=True):
    print(f"  hist {g.rush_td_per_rush.min():.3f}-{g.rush_td_per_rush.max():.3f}  games {len(g):>5}  proj td/c "
          f"{np.average(g.p_tdc, weights=g.a_rush):.4f}  actual {g.a_rush_td.sum() / g.a_rush.sum():.4f}")


if __name__ == "__main__":
  main()
