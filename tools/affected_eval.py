"""Affected-row comparison of two cached experiment variants (tools/experiments.py): rows of POS whose projection
moves more than MIN points between REF and VAR; MAE (fantasy points) and carries MAE difference with a 95% bootstrap
CI over season-weeks; bias before / after.

  python tools/affected_eval.py REF VAR [--pos=RB] [--min=0.05] [--seasons=2021-2025]
"""
import glob
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from experiments import relevant, week_bootstrap  # noqa: E402,F401


def latest(name, s):
  fs = sorted(glob.glob(str(ROOT / "cache" / "experiments" / f"{name}_{s}_*.parquet")), key=os.path.getmtime)
  return pd.read_parquet(fs[-1])


def ci(diff: pd.Series, cl: pd.Series):
  gr = pd.DataFrame({"d": diff.to_numpy(), "c": cl.to_numpy()}).groupby("c").d.agg(["sum", "size"])
  s_, n_ = gr["sum"].to_numpy(), gr["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(gr), (4000, len(gr)))
  bt = s_[idx].sum(1) / n_[idx].sum(1)
  return diff.mean(), np.percentile(bt, 2.5), np.percentile(bt, 97.5)


def main():
  args = [a for a in sys.argv[1:] if not a.startswith("--")]
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  ref, var = args[0], args[1]
  pos, mn = opt.get("pos", "RB"), float(opt.get("min", 0.05))
  a, b = (int(x) for x in opt.get("seasons", "2021-2025").split("-"))
  key = ["season", "week", "gsis_id"]
  fr = []
  for s in range(a, b + 1):
    r = relevant(latest(ref, s))
    v = latest(var, s)[key + ["proj", "carries"]].rename(columns={"proj": "proj_v", "carries": "car_v"})
    fr.append(r.merge(v, on=key))
  d = pd.concat(fr, ignore_index=True)
  d = d[(d.pos == pos) & ((d.proj_v - d.proj).abs() > mn)]
  cl = d.season.astype(str) + "-" + d.week.astype(str)
  m, lo, hi = ci((d.actual - d.proj_v).abs() - (d.actual - d.proj).abs(), cl)
  print(f"{var} vs {ref}, {pos} rows moving > {mn}: n {len(d)}")
  print(f"  MAE {(d.actual - d.proj).abs().mean():.3f} -> {(d.actual - d.proj_v).abs().mean():.3f}  diff {m:+.3f} [{lo:+.3f}, {hi:+.3f}]")
  print(f"  bias (actual - proj) {(d.actual - d.proj).mean():+.2f} -> {(d.actual - d.proj_v).mean():+.2f}")
  c = d.dropna(subset=["a_rush"])
  mc, lc, hc = ci((c.a_rush - c.car_v).abs() - (c.a_rush - c.carries).abs(), c.season.astype(str) + "-" + c.week.astype(str))
  print(f"  carries MAE {(c.a_rush - c.carries).abs().mean():.2f} -> {(c.a_rush - c.car_v).abs().mean():.2f}  diff {mc:+.3f} [{lc:+.3f}, {hc:+.3f}]; carries bias {(c.a_rush - c.carries).mean():+.2f} -> {(c.a_rush - c.car_v).mean():+.2f}")
  for lab, g in (("gained work (proj up)", d[d.proj_v > d.proj]), ("lost work (proj down)", d[d.proj_v < d.proj])):
    print(f"  {lab}: n {len(g)}, MAE {(g.actual - g.proj).abs().mean():.3f} -> {(g.actual - g.proj_v).abs().mean():.3f}, bias {(g.actual - g.proj).mean():+.2f} -> {(g.actual - g.proj_v).mean():+.2f}")


if __name__ == "__main__":
  main()
