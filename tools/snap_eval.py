"""(T) snap trend and (U) snap share in absorption: the pre-registered subsets (docs/INSIGHTS.md, 2026-10-17).

Reads the cached walk-forward backtests tools/experiments.py wrote (cache/experiments/<variant>_<season>_*.parquet,
newest per season) and scores them on identical rows:
  (T) RB / WR / TE with |snap_trend| >= 0.15 (from the snap_trend run)
  (U) rows whose projection moved by > 0.05 pts, bias by prior snap share
95% bootstrap over season-weeks, as tools/experiments.py.

  python tools/snap_eval.py
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

SEASONS = range(2021, 2026)


def load(name: str) -> pd.DataFrame:
  fr = []
  for s in SEASONS:
    fs = sorted(glob.glob(str(ROOT / "cache" / "experiments" / f"{name}_{s}_*.parquet")), key=os.path.getmtime)
    if not fs:
      sys.exit(f"no cached {name} {s}: run tools/experiments.py first")
    fr.append(pd.read_parquet(fs[-1]))
  return pd.concat(fr, ignore_index=True)


def paired(base: pd.DataFrame, var: pd.DataFrame, rows: pd.Series | None = None) -> pd.DataFrame:
  k = ["season", "week", "gsis_id"]
  b = relevant(base)[k + ["pos", "proj", "actual", "snap_pct"]]
  v = var[k + ["proj"] + (["snap_trend"] if "snap_trend" in var else [])].rename(columns={"proj": "proj_v"})
  m = b.merge(v, on=k)
  m["e_b"] = (m.proj - m.actual).abs()
  m["e_v"] = (m.proj_v - m.actual).abs()
  m["sw"] = m.season.astype(str) + "-" + m.week.astype(str)
  return m


def report(m: pd.DataFrame, label: str) -> tuple[float, float, float, int]:
  d = m.e_v - m.e_b
  lo, hi = week_bootstrap(d, m.sw)
  better = sum((x.e_v - x.e_b).mean() < 0 for _, x in m.groupby("season"))
  print(f"  {label}: rows {len(m)}  MAE {m.e_b.mean():.3f} -> {m.e_v.mean():.3f}  diff {d.mean():+.4f} "
        f"[{lo:+.4f}, {hi:+.4f}]  better {better}/{m.season.nunique()} seasons  (CI width {hi - lo:.4f})")
  return d.mean(), lo, hi, better


def guards(m: pd.DataFrame):
  report(m, "ALL rows")
  for pos in ["QB", "RB", "WR", "TE"]:
    x = m[m.pos == pos]
    d = x.e_v - x.e_b
    lo, hi = week_bootstrap(d, x.sw)
    print(f"    {pos}: {d.mean():+.4f} [{lo:+.4f}, {hi:+.4f}]")


def main():
  base = load("baseline")
  print("(T) snap_trend")
  m = paired(base, load("snap_trend"))
  sub = m[m.pos.isin(["RB", "WR", "TE"]) & (m.snap_trend.abs() >= 0.15)]
  d, lo, hi, better = report(sub, "PRIMARY |snap_trend| >= 0.15")
  for sign, x in (("up", sub[sub.snap_trend > 0]), ("down", sub[sub.snap_trend < 0])):
    print(f"    snaps {sign}: rows {len(x)}  bias base {(x.proj - x.actual).mean():+.2f} -> {(x.proj_v - x.actual).mean():+.2f}")
  guards(m)
  print(f"  GATE: {'PASS' if hi < 0 and better >= 4 else 'FAIL'}")

  print("(U) absorb_snap")
  m = paired(base, load("absorb_snap"))
  aff = m[(m.proj_v - m.proj).abs() > 0.05]
  d, lo, hi, better = report(aff, "PRIMARY projection moved > 0.05")
  aff = aff.assign(bucket=pd.cut(aff.snap_pct, [0, .2, .4, .6, 1.01], labels=["<20%", "20-40%", "40-60%", "60%+"], right=False))
  for (pos, b), x in aff[aff.pos.isin(["RB", "WR", "TE"])].groupby(["pos", "bucket"], observed=True):
    if len(x) >= 15:
      print(f"    {pos} {b}: rows {len(x)}  bias {(x.proj - x.actual).mean():+.2f} -> {(x.proj_v - x.actual).mean():+.2f}")
  guards(m)
  print(f"  GATE: {'PASS' if hi < 0 and better >= 4 else 'FAIL'}")


if __name__ == "__main__":
  main()
