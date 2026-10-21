"""How often the higher-projected player outscores the other, by projection gap (owner 2026-10-21: a 0.9-point gap,
Woody Marks over Kenneth Walker, read as a recommendation). Every pair of players at the same position in the same
week (cached baseline backtests 2021-25, relevant rows, projections 5+), ties dropped. The league page's start / bench
cards use the pooled curve (league.js H2H): the chance shown, and "toss-up" under the TOSSUP gap.

  python tools/h2h_curve.py
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

BINS = [0, 0.5, 1, 1.5, 2, 3, 4, 6, 9, 99]


def main():
  fr = []
  for s in range(2021, 2026):
    fs = sorted(glob.glob(str(ROOT / "cache" / "experiments" / f"baseline_{s}_*.parquet")), key=os.path.getmtime)
    fr.append(relevant(pd.read_parquet(fs[-1])))
  d = pd.concat(fr, ignore_index=True)
  d = d[d.pos.isin(["QB", "RB", "WR", "TE"]) & (d.proj >= 5)]
  parts = []
  for (_, _, pos), g in d.groupby(["season", "week", "pos"]):
    v, a = g.proj.to_numpy(), g.actual.to_numpy()
    i, j = np.triu_indices(len(g), 1)
    keep = (a[i] != a[j]) & (v[i] != v[j])
    parts.append(pd.DataFrame({"pos": pos, "gap": np.abs(v[i] - v[j])[keep],
                               "win": np.where(v[i] > v[j], a[i] > a[j], a[j] > a[i])[keep]}))
  x = pd.concat(parts)
  t = x.groupby(pd.cut(x.gap, BINS), observed=True).agg(gap=("gap", "median"), win=("win", "mean"), n=("win", "size"))
  print(t.round(3).to_string())
  print("\nleague.js H2H points [gap, chance]:", [[round(float(r.gap), 2), round(float(r.win), 3)] for r in t.itertuples()])


if __name__ == "__main__":
  main()
