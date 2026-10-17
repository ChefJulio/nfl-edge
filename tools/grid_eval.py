"""Choose / decide / confirm for a pre-registered grid of tools/experiments.py variants (fantasy MAE on relevant rows).

Reads the cached walk-forward backtests (cache/experiments/<variant>_<season>_*.parquet, newest per season):
  CHOOSE   the variant with the lowest MAE on the choose seasons (the reference 'baseline' included)
  DECIDE   chosen vs baseline: MAE diff with a 95% season-week CI excluding 0 below, better in every decide season;
           guards: no position significantly worse, start / sit gain not significantly worse (docs/INSIGHTS.md sec. 1)
  CONFIRM  same direction on the confirm seasons

  python tools/grid_eval.py td_k_25,td_k_50,... --choose=2021-2023 --decide=2024-2025 --confirm=2026
"""
from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from experiments import decision_pairs, relevant, week_bootstrap  # noqa: E402

POS = ["QB", "RB", "WR", "TE"]


def span(a: str) -> list[int]:
  lo, _, hi = a.partition("-")
  return list(range(int(lo), int(hi or lo) + 1))


def load(name: str, seasons) -> pd.DataFrame:
  fr = []
  for s in seasons:
    fs = sorted(glob.glob(str(ROOT / "cache" / "experiments" / f"{name}_{s}_*.parquet")), key=os.path.getmtime)
    if not fs:
      sys.exit(f"no cached {name} {s}: run tools/experiments.py first")
    fr.append(pd.read_parquet(fs[-1]))
  return pd.concat(fr, ignore_index=True)


def paired(name: str, seasons) -> pd.DataFrame:
  k = ["season", "week", "gsis_id"]
  b = relevant(load("baseline", seasons))
  v = load(name, seasons)[k + ["proj"]].rename(columns={"proj": "proj_v"})
  m = b.merge(v, on=k)
  m["e_b"], m["e_v"] = (m.proj - m.actual).abs(), (m.proj_v - m.actual).abs()
  m["sw"] = m.season.astype(str) + "-" + m.week.astype(str)
  return m


def diff(m: pd.DataFrame) -> tuple[float, float, float]:
  d = m.e_v - m.e_b
  lo, hi = week_bootstrap(d, m.sw)
  return d.mean(), lo, hi


def startsit(m: pd.DataFrame) -> tuple[float, float, float]:
  """Start / sit gain change: same-position pairs within 6 consensus ranks (fixed from the baseline's rows), points
  gained by starting the one projected higher, variant minus baseline."""
  pairs = decision_pairs(m)
  if not len(pairs):
    return float("nan"), float("nan"), float("nan")
  pb = dict(zip(zip(m.season, m.week, m.gsis_id), m.proj))
  pv = dict(zip(zip(m.season, m.week, m.gsis_id), m.proj_v))
  def gain(P):
    a = pd.Series([P[(s, w, x)] for s, w, x in zip(pairs.season, pairs.week, pairs.i)])
    b = pd.Series([P[(s, w, x)] for s, w, x in zip(pairs.season, pairs.week, pairs.j)])
    return ((a > b).astype(float) - (a < b).astype(float)) * pairs.da.to_numpy()
  g = gain(pv) - gain(pb)
  lo, hi = week_bootstrap(g, pairs.season.astype(str) + "-" + pairs.week.astype(str))
  return g.mean(), lo, hi


def main():
  names = sys.argv[1].split(",")
  opt = dict(a[2:].split("=", 1) for a in sys.argv[2:] if a.startswith("--"))
  choose, decide, confirm = span(opt["choose"]), span(opt["decide"]), span(opt.get("confirm", "2026"))
  print(f"CHOOSE on {choose[0]}-{choose[-1]} (MAE diff vs baseline):")
  res = {}
  for n in names:
    res[n] = diff(paired(n, choose))
    print(f"  {n}: {res[n][0]:+.4f} [{res[n][1]:+.4f}, {res[n][2]:+.4f}]")
  best = min(res, key=lambda n: res[n][0])
  if res[best][0] >= 0:
    print("  baseline is the choice -> keep it (now tested)\nGATE: FAIL (keep)")
    return
  print(f"  chosen: {best}")
  m = paired(best, decide)
  d, lo, hi = diff(m)
  per = {s: diff(x)[0] for s, x in m.groupby("season")}
  print(f"DECIDE {decide[0]}-{decide[-1]}: {d:+.4f} [{lo:+.4f}, {hi:+.4f}]  per season " + " ".join(f"{s} {v:+.4f}" for s, v in per.items()))
  bad = []
  for pos in POS:
    pd_, plo, phi = diff(m[m.pos == pos])
    print(f"    {pos}: {pd_:+.4f} [{plo:+.4f}, {phi:+.4f}]")
    if plo > 0:
      bad.append(pos)
  ss = startsit(m)
  print(f"    start / sit gain: {ss[0]:+.4f} [{ss[1]:+.4f}, {ss[2]:+.4f}]")
  ok = hi < 0 and all(v < 0 for v in per.values()) and not bad and not (ss[2] < 0)  # start / sit: not significantly worse
  print(f"  DECIDE {'PASS' if ok else 'FAIL'}")
  c = paired(best, confirm)
  cd, clo, chi = diff(c)
  print(f"CONFIRM {confirm[0]}-{confirm[-1]}: {cd:+.4f} [{clo:+.4f}, {chi:+.4f}] ({len(c)} rows) -> {'PASS' if cd < 0 else 'FAIL'}")
  print(f"GATE: {'PASS' if ok and cd < 0 else 'FAIL'}")


if __name__ == "__main__":
  main()
