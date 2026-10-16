"""Gate for the debut usage prior, weeks 1-2 (pre-registered 2026-10-15, docs/INSIGHTS.md section 9).
Usage: python tools/debut_gate.py [BASE_NAME VARIANT_NAME]   (defaults early debut; names given to tools/early_weeks_eval.py --name)
Joins the two runs player-week by player-week (played rows, QB/RB/WR/TE); CI = 95% bootstrap over team-weeks.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

OUT = ROOT / "cache" / "experiments"
k = ["season", "week", "gsis_id"]
names = [x for x in sys.argv[1:] if not x.startswith("--")] or ["early", "debut"]
a = pd.read_parquet(OUT / f"{names[0]}_w12_eval_rows.parquet")
b = pd.read_parquet(OUT / f"{names[1]}_w12_eval_rows.parquet")
d = a[k + ["pos", "team", "actual", "proj", "rook"]].merge(b[k + ["proj", "debut"]].rename(columns={"proj": "proj_d"}), on=k)
d["debut"] = d.debut.fillna(False).astype(bool)
d["diff"] = (d.proj_d - d.actual).abs() - (d.proj - d.actual).abs()
d["cl"] = d.season.astype(str) + "-" + d.week.astype(str) + "-" + d.team.astype(str)


def ci(x):
  g = x.groupby("cl")["diff"].agg(["sum", "size"])
  s_, c_ = g["sum"].to_numpy(), g["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(g), (4000, len(g)))
  bt = s_[idx].sum(1) / c_[idx].sum(1)
  return x["diff"].mean(), np.percentile(bt, 2.5), np.percentile(bt, 97.5)


print(f"rows {len(d)}; debut rows {int(d.debut.sum())} (rookies {int((d.debut & d.rook).sum())})")
m, lo, hi = ci(d[d.debut]); g1 = hi < 0
print(f"(i)  debut rows   n={int(d.debut.sum()):5d}  {m:+.3f} [{lo:+.3f}, {hi:+.3f}]  {'ok' if g1 else 'FAIL'}")
m, lo, hi = ci(d); g2 = hi < 0.003
print(f"(ii) all rows     n={len(d):5d}  {m:+.3f} [{lo:+.3f}, {hi:+.3f}]  {'ok' if g2 else 'FAIL'}")
for pos, x in d.groupby("pos"):
  m, lo, hi = ci(x); g2 &= lo <= 0
  print(f"      {pos}  n={len(x):5d}  {m:+.3f} [{lo:+.3f}, {hi:+.3f}]")
nd = d[~d.debut]
m, lo, hi = ci(nd)
print(f"     non-debut rows (teammates)  {m:+.3f} [{lo:+.3f}, {hi:+.3f}]")
print(f"     by season (all rows):", d.groupby("season")["diff"].mean().round(3).to_dict())
print("weeks 1-2 parts:", "PASS" if g1 and g2 else "FAIL", "(part iii = weeks 3+ via tools/experiments.py)")
