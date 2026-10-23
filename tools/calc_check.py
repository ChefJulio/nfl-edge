"""(CG) the calculator inputs' pre-registered checks (docs/INSIGHTS.md): fitted on seasons before 2024, compared with
2024-25. Conversion: within 4 points per distance bucket 1 / 2 / 3 / 4-5 / 6-10, on 4th-down tries (the calculator's
use) and on 3rd and 4th downs together; field goal: within 4 points per 10-yard band. Also prints the punt, onside,
try and clock inputs for the record.

  python tools/calc_check.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import calc_inputs as C  # noqa: E402


def main():
  d = pd.concat([pd.read_parquet(ROOT / "cache" / f"pbp_calc_{s}.parquet") for s in range(2006, 2026)], ignore_index=True)
  tr, te = d[d.season < 2024], d[d.season >= 2024]
  ok = True
  c = C.conversion(tr)
  x = C._snaps34(te)
  x = x.assign(y=C._conv_y(x), p=C.conv_prob(c, x.ydstogo, x.yardline_100, x.down.to_numpy()) if False else 0.0)
  x["p"] = C.conv_prob(c, x.ydstogo.to_numpy(), x.yardline_100.to_numpy())
  print("conversion (fit: 4th downs 2021-23, test 2024-25):")
  for lab, sub in (("4th downs", x[x.down == 4]), ("3rd + 4th", x)):
    for lo, hi in [(1, 1), (2, 2), (3, 3), (4, 5), (6, 10)]:
      b = sub[(sub.ydstogo >= lo) & (sub.ydstogo <= hi)]
      gap = b.y.mean() - b.p.mean()
      flag = abs(gap) <= 0.04
      ok &= flag
      print(f"  {'ok ' if flag else 'BAD'} {lab:9s} {lo}-{hi:<2d}: n {len(b):5d}  predicted {b.p.mean():.3f}  actual {b.y.mean():.3f}  ({gap:+.3f})")
  f = C.fg(tr)
  k = C._reg(te)
  k = k[(k.field_goal_attempt == 1) & k.kick_distance.notna()]
  k = k.assign(p=C.fg_prob(f, k.kick_distance), y=(k.field_goal_result == "made").astype(float))
  print("field goal (fit 2022-23, test 2024-25):")
  for lo in range(20, 70, 10):
    b = k[(k.kick_distance >= lo) & (k.kick_distance < lo + 10)]
    if len(b) < 20:
      continue
    gap = b.y.mean() - b.p.mean()
    flag = abs(gap) <= 0.04
    ok &= flag
    print(f"  {'ok ' if flag else 'BAD'} {lo}-{lo + 9}: n {len(b):4d}  predicted {b.p.mean():.3f}  actual {b.y.mean():.3f}  ({gap:+.3f})")
  print("for the record:", {k_: v for k_, v in C.build(d).items() if k_ in ("onside", "tries", "clock", "kickoff")})
  print(f"[calc] input checks: {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
  main()
