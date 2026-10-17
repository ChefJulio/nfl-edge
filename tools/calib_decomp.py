"""(W) follow-up: how much of the calibration gain is a constant shift toward the median vs the curve shape."""
import sys; sys.path.insert(0, "tools")
import numpy as np, pandas as pd
import calib_eval as C
from experiments import week_bootstrap
allr = C.load(range(2021, 2026))
out = []
for s in range(2022, 2026):
  tr, te = allr[allr.season < s], allr[allr.season == s].copy()
  te["curve"] = C.calibrate(tr, te)
  # constant median shift per position: median(actual - proj) on the fit seasons
  sh = (tr.actual - tr.proj).groupby(tr.pos).median()
  te["shift"] = te.proj + te.pos.map(sh)
  # shape only: the curve re-centered so its mean change per position is zero (keeps averages, bends the tiers)
  dc = (te.curve - te.proj).groupby(te.pos).transform("mean")
  te["shape"] = te.curve - dc
  out.append(te)
d = pd.concat(out)
e = lambda c: (d[c] - d.actual).abs()
for c in ["shift", "shape", "curve"]:
  diff = e(c) - e("proj"); lo, hi = week_bootstrap(diff, d.sw)
  print(f"{c:6}: MAE diff {diff.mean():+.4f} [{lo:+.4f}, {hi:+.4f}]   mean change per pos " +
        " ".join(f"{p} {(d[c] - d.proj)[d.pos == p].mean():+.2f}" for p in C.POS))
print("median shifts used (2021-24 fit):", (allr[allr.season < 2025].actual - allr[allr.season < 2025].proj).groupby(allr.pos).median().round(2).to_dict())
