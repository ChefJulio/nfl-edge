"""(V) how much of a sitting starter's work reaches RBs (docs/INSIGHTS.md, pre-registered 2026-10-17).

Reads the cached walk-forward backtests (tools/experiments.py baseline,rb_scale_65,rb_scale_80,rb_scale_100
2021-2026): picks the RB scale on 2021-24 (MAE on RB rows whose projection moved > 0.05 pts), decides on 2025,
confirms on 2026 weeks so far.

  python tools/rb_scale_eval.py
"""
from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from experiments import relevant, week_bootstrap  # noqa: E402

GRID = {"rb_scale_65": 0.65, "rb_scale_80": 0.8, "rb_scale_100": 1.0}
CHOOSE, DECIDE, CONFIRM = range(2021, 2025), [2025], [2026]


def load(name: str, seasons) -> pd.DataFrame:
  fr = []
  for s in seasons:
    fs = sorted(glob.glob(str(ROOT / "cache" / "experiments" / f"{name}_{s}_*.parquet")), key=os.path.getmtime)
    if not fs:
      sys.exit(f"no cached {name} {s}")
    fr.append(pd.read_parquet(fs[-1]))
  return pd.concat(fr, ignore_index=True)


def paired(name: str, seasons) -> pd.DataFrame:
  k = ["season", "week", "gsis_id"]
  b = relevant(load("baseline", seasons))[k + ["pos", "proj", "actual"]]
  v = load(name, seasons)[k + ["proj"]].rename(columns={"proj": "proj_v"})
  m = b.merge(v, on=k)
  m["e_b"], m["e_v"] = (m.proj - m.actual).abs(), (m.proj_v - m.actual).abs()
  m["sw"] = m.season.astype(str) + "-" + m.week.astype(str)
  m["aff"] = (m.pos == "RB") & ((m.proj_v - m.proj).abs() > 0.05)
  return m


def line(m: pd.DataFrame, label: str):
  d = m.e_v - m.e_b
  lo, hi = week_bootstrap(d, m.sw) if len(m) else (float("nan"),) * 2
  print(f"    {label}: rows {len(m)}  MAE {m.e_b.mean():.3f} -> {m.e_v.mean():.3f}  diff {d.mean():+.4f} [{lo:+.4f}, {hi:+.4f}]"
        f"  bias {(m.proj - m.actual).mean():+.2f} -> {(m.proj_v - m.actual).mean():+.2f}")
  return d.mean(), lo, hi


def main():
  print("CHOOSE on 2021-24 (affected RB rows):")
  score = {}
  for name, v in GRID.items():
    m = paired(name, CHOOSE)
    score[name] = line(m[m.aff], f"RB scale {v}")[0]
  best = min(score, key=score.get)
  if score[best] >= 0:
    print("  no grid value beats 0.5 on 2021-24: keep 0.5 (FAIL)")
    return
  print(f"  chosen: {GRID[best]}")
  print("DECIDE on 2025:")
  m = paired(best, DECIDE)
  _, lo, hi = line(m[m.aff], "PRIMARY affected RB rows")
  _, alo, ahi = line(m, "ALL rows")
  bad = []
  for pos in ["QB", "RB", "WR", "TE"]:
    _, plo, phi = line(m[m.pos == pos], pos)
    if plo > 0:
      bad.append(pos)
  ok = hi < 0 and ahi < 0.003 and not bad
  print(f"  DECIDE: {'PASS' if ok else 'FAIL'}")
  print("CONFIRM on 2026 so far:")
  m = paired(best, CONFIRM)
  d, _, _ = line(m[m.aff], "affected RB rows")
  _, clo, _ = line(m, "ALL rows")
  print(f"  CONFIRM: {'PASS' if d < 0 and clo <= 0 else 'FAIL'}")
  print(f"GATE: {'PASS' if ok and d < 0 and clo <= 0 else 'FAIL'}")


if __name__ == "__main__":
  main()
