"""(CI) the upgraded calculator inputs' pre-registered checks (docs/INSIGHTS.md): fitted before 2024, compared with
2024-25. (1) P(convert) on 4th downs: within 4 points per distance bucket, for favorites and underdogs (spread +-3 or
more) separately, and a lower Brier than the current logistic on the same plays. (2) Field goals: 20-59 yd within 4
points per 10-yard band; outdoors with wind 15+ mph within 6. (3) Punts: counts for the record.

  python tools/calc_check2.py
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
  m = C.conversion_gb(tr)
  old = C.conversion(tr)
  g = C._gain_rows(te)
  g = g[g.down == 4].copy()
  g["p"] = m.predict_proba(C.conv_features(g))[:, 1]
  g["p_old"] = C.conv_prob(old, g.ydstogo.to_numpy(), g.yardline_100.to_numpy())
  print("(1) 4th-down conversion, fit before 2024, 2024-25:")
  for lo, hi in [(1, 1), (2, 2), (3, 3), (4, 5), (6, 10)]:
    b = g[(g.ydstogo >= lo) & (g.ydstogo <= hi)]
    gap = b.y.mean() - b.p.mean()
    ok &= abs(gap) <= 0.04
    print(f"  {'ok ' if abs(gap) <= 0.04 else 'BAD'} {lo}-{hi}: n {len(b):4d}  new {b.p.mean():.3f}  old {b.p_old.mean():.3f}  actual {b.y.mean():.3f}  ({gap:+.3f})")
  for lab, b in (("favorites (3+)", g[g.spread >= 3]), ("underdogs (3+)", g[g.spread <= -3])):
    gap = b.y.mean() - b.p.mean()
    ok &= abs(gap) <= 0.04
    print(f"  {'ok ' if abs(gap) <= 0.04 else 'BAD'} {lab}: n {len(b):4d}  new {b.p.mean():.3f}  old {b.p_old.mean():.3f}  actual {b.y.mean():.3f}  ({gap:+.3f})")
  bn, bo = float(np.mean((g.p - g.y) ** 2)), float(np.mean((g.p_old - g.y) ** 2))
  ok &= bn < bo
  print(f"  {'ok ' if bn < bo else 'BAD'} Brier new {bn:.4f} vs current {bo:.4f}")
  f = C.fg_v3(tr)
  k = C._reg(te)
  k = k[(k.field_goal_attempt == 1) & k.kick_distance.notna()].copy()
  k["p"] = C.fg_v3_prob(f, k.kick_distance.to_numpy(), C._roof(k.roof).outdoors.to_numpy(), k.wind.to_numpy(float))
  k["y"] = (k.field_goal_result == "made").astype(float)
  print("(2) field goals, fit before 2024, 2024-25:")
  for lo in range(20, 70, 10):
    b = k[(k.kick_distance >= lo) & (k.kick_distance < lo + 10)]
    gap = b.y.mean() - b.p.mean()
    gate = lo < 60
    if gate:
      ok &= abs(gap) <= 0.04
    print(f"  {('ok ' if abs(gap) <= 0.04 else 'BAD') if gate else '   '} {lo}-{lo + 9}: n {len(b):4d}  predicted {b.p.mean():.3f}  actual {b.y.mean():.3f}  ({gap:+.3f}){'' if gate else '  (no gate: only trusted kickers try these)'}")
  wnd = k[(C._roof(k.roof).outdoors == 1) & (k.wind >= 15)]
  gap = wnd.y.mean() - wnd.p.mean()
  ok &= abs(gap) <= 0.06
  print(f"  {'ok ' if abs(gap) <= 0.06 else 'BAD'} outdoors, wind 15+: n {len(wnd)}  predicted {wnd.p.mean():.3f}  actual {wnd.y.mean():.3f}  ({gap:+.3f})")
  print("  average conditions:", {dd: round(float(C.fg_v3_prob(f, dd)[0]), 3) for dd in (30, 40, 50, 55, 60, 65)},
        " outdoors 20 mph:", {dd: round(float(C.fg_v3_prob(f, [dd], [1.0], [20.0])[0]), 3) for dd in (30, 40, 50, 55)})
  p = C.punts_v2(d)
  tot = sum(b["n"] for b in p["bands"])
  print(f"(3) punts 2018-25: {tot:,}; e.g. from own 30:", [b for b in p["bands"] if b["lo"] == 70][0])
  print(f"[calc] (CI) checks: {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
  main()
