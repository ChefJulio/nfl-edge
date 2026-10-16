"""Gate for injuries.scratch_carry (pre-registered 2026-10-15, docs/INSIGHTS.md section 9), weeks 1-2.

Usage: python tools/scratch_gate.py BASE_NAME VARIANT_NAME   (runs from tools/early_weeks_eval.py --name=...)
(i) week-1 Brier of availability vs played for players not on the injury report (the healthy-scratch model's
rows), CI = 95% bootstrap over team-weeks; (ii) weeks 1-2 fantasy MAE on played rows (QB/RB/WR/TE).
"""
import glob
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

OUT = ROOT / "cache" / "experiments"


def rows(name: str) -> pd.DataFrame:
  fs = {}
  for f in glob.glob(str(OUT / f"{name}_w12_20*.parquet")):
    s = int(os.path.basename(f).split("_")[-2])
    if s not in fs or os.path.getmtime(f) > os.path.getmtime(fs[s]):
      fs[s] = f
  return pd.concat([pd.read_parquet(fs[s]).assign(season=s) for s in sorted(fs)], ignore_index=True)


def ci(d: pd.Series, cl: pd.Series):
  g = pd.DataFrame({"d": d.to_numpy(), "c": cl.to_numpy()}).groupby("c").d.agg(["sum", "size"])
  s_, c_ = g["sum"].to_numpy(), g["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(g), (4000, len(g)))
  bt = s_[idx].sum(1) / c_[idx].sum(1)
  return d.mean(), np.percentile(bt, 2.5), np.percentile(bt, 97.5)


def main():
  a_name, b_name = sys.argv[1], sys.argv[2]
  k = ["season", "week", "gsis_id"]
  a, b = rows(a_name), rows(b_name)
  d = a[k + ["team", "pos", "avail", "played", "on_report", "actual", "proj"]].merge(
    b[k + ["avail", "proj"]].rename(columns={"avail": "avail_b", "proj": "proj_b"}), on=k)
  d["on_report"] = d.on_report.fillna(False).astype(bool)
  d["cl"] = d.season.astype(str) + "-" + d.week.astype(str) + "-" + d.team.astype(str)
  w1 = d[(d.week == 1) & ~d.on_report & d.played.notna()].copy()
  y = w1.played.astype(float)
  w1["diff"] = (w1.avail_b - y) ** 2 - (w1.avail - y) ** 2
  m, lo, hi = ci(w1["diff"], w1.cl)
  g1 = hi < 0
  print(f"(i)  week-1 availability Brier, not on report (n={len(w1)}): {((w1.avail - y) ** 2).mean():.4f} -> "
        f"{((w1.avail_b - y) ** 2).mean():.4f}  diff {m:+.4f} [{lo:+.4f}, {hi:+.4f}]  {'ok' if g1 else 'FAIL'}")
  for pos, x in w1.groupby("pos"):
    print(f"      {pos}: mean P(active) {x.avail.mean():.3f} -> {x.avail_b.mean():.3f}, actually played {x.played.mean():.3f}")
  pl = d[d.played.fillna(False).astype(bool) & d.actual.notna()].copy()
  pl["diff"] = (pl.proj_b - pl.actual).abs() - (pl.proj - pl.actual).abs()
  m, lo, hi = ci(pl["diff"], pl.cl)
  g2 = hi < 0.003
  print(f"(ii) weeks 1-2 fantasy MAE, played rows (n={len(pl)}): diff {m:+.4f} [{lo:+.4f}, {hi:+.4f}]  {'ok' if g2 else 'FAIL'}")
  print("weeks 1-2 parts:", "PASS" if g1 and g2 else "FAIL", "(part iii = weeks 3+ via tools/experiments.py)")


if __name__ == "__main__":
  main()
