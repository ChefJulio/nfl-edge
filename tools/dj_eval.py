"""(DJ) the clock's pace as a curve (pre-registered 2026-10-25, docs/INSIGHTS.md). Running-clock gaps between snaps
(nfledge/calc_inputs.pace_rows), the current step table vs a smoothed surface pace(half, seconds left, margin)
(calc_inputs.clock_curve). Bandwidths picked on 2022-23 (fit 2018-21) from (10, 20, 40 s) x (1, 2, 4 points); then
refit on 2018-23 and tested on 2024-25.

GATE (all): (1) last 5:00 of either half: mean absolute error lower, 95% interval over games of the difference < 0;
(2) all gaps: not worse (upper < +0.1 s); (3) no step over 4 s between neighbouring cells within a half's last 10:00;
(4) (CJ) check (1) on the engine with the curve (run separately after 1-3).

  python tools/dj_eval.py        writes scratch/dj/curve.json (the 2018-23 fit) and scratch/dj/curve_live.json (2018-25)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import calc_inputs as C  # noqa: E402
from nfledge import winprob as W  # noqa: E402

OUT = ROOT / "scratch" / "dj"


def table(fit: pd.DataFrame):
  """The current step table (calc_inputs.clock): medians by half x band x lead with 200+ gaps, else the normal median."""
  band = lambda t: np.where(t <= 120, "two", np.where(t <= 300, "five", "normal"))  # noqa: E731
  key = lambda r: pd.Series([f"{h}:{b}:{'lead' if m > 0 else 'trail'}" for h, b, m in zip(r.half, band(r.t), r.m)], index=r.index)  # noqa: E731
  g = fit.gap.groupby(key(fit)).agg(["median", "size"])
  pace = {k: v["median"] for k, v in g.iterrows() if v["size"] >= 200}
  normal = fit.gap[band(fit.t) == "normal"].median()
  return lambda r: key(r).map(pace).fillna(normal).to_numpy(float)


def boot(a: np.ndarray, games: np.ndarray, rng, reps: int = 2000):
  ug, inv = np.unique(games, return_inverse=True)
  s, c = np.bincount(inv, a), np.bincount(inv)
  bs = [(w * s).sum() / (w * c).sum() for w in (np.bincount(rng.integers(0, len(ug), len(ug)), minlength=len(ug)) for _ in range(reps))]
  return float(a.mean()), *np.percentile(bs, [2.5, 97.5])


def main():
  d = pd.concat([pd.read_parquet(ROOT / "cache" / f"pbp_calc_{s}.parquet", columns=W.PBP_COLS) for s in range(2018, 2026)],
                ignore_index=True)
  dj2 = "--dj2" in sys.argv  # (DJ2): timeout gaps dropped (table and curve), adaptive time bandwidth, 2:00-3:00 not fit
  r = C.pace_rows(d, drop_timeouts=dj2)
  late = lambda x: x.t <= 300  # noqa: E731
  print(f"[dj] {'DJ2' if dj2 else 'DJ'}: {len(r):,} running-clock gaps 2018-25 ({late(r).sum():,} in a half's last 5:00)")
  # bandwidths on 2022-23, fit 2018-21
  f1, v1 = r[r.season <= 2021], r[r.season.between(2022, 2023)]
  vl = v1[late(v1)]
  best = None
  print("[dj] bandwidths (fit 2018-21, MAE on 2022-23's last 5:00):")
  for st in ((None,) if dj2 else (10, 20, 40)):
    for sm in (1, 2, 4):
      c = C.clock_curve(f1, st, sm)
      mae = np.abs(C.curve_pace(c, vl.half, vl.t, vl.m) - vl.gap).mean()
      print(f"  {st or 'adaptive'} s x {sm} pt: {mae:.3f}")
      if best is None or mae < best[0]:
        best = (mae, st, sm)
  _, st, sm = best
  print(f"[dj] chosen: {st} s x {sm} pt")
  fit, te = r[r.season <= 2023], r[r.season >= 2024]
  c = C.clock_curve(fit, st, sm)
  OUT.mkdir(parents=True, exist_ok=True)
  (OUT / ("curve2.json" if dj2 else "curve.json")).write_text(json.dumps({**c, "sd_t": st, "sd_m": sm}), encoding="utf-8")
  (OUT / ("curve2_live.json" if dj2 else "curve_live.json")).write_text(json.dumps({**C.clock_curve(r, st, sm), "sd_t": st, "sd_m": sm}), encoding="utf-8")
  pt, pc = table(fit)(te), C.curve_pace(c, te.half, te.t, te.m)
  et, ec = np.abs(pt - te.gap.to_numpy()), np.abs(pc - te.gap.to_numpy())
  rng = np.random.default_rng(0)
  k = late(te).to_numpy()
  m1, lo1, hi1 = boot(ec[k] - et[k], te.game_id.to_numpy()[k], rng)
  g1 = hi1 < 0
  print(f"\n[dj] (1) last 5:00 ({k.sum():,} gaps): MAE table {et[k].mean():.3f} -> curve {ec[k].mean():.3f}, {m1:+.3f} [{lo1:+.3f}, {hi1:+.3f}] -> {g1}")
  m2, lo2, hi2 = boot(ec - et, te.game_id.to_numpy(), rng)
  g2 = hi2 < 0.1
  print(f"[dj] (2) all ({len(te):,}): MAE table {et.mean():.3f} -> curve {ec.mean():.3f}, {m2:+.3f} [{lo2:+.3f}, {hi2:+.3f}] -> {g2}")
  for lab, kk in [("2:00 and in", te.t <= 120), ("2:01-5:00", te.t.between(121, 300)), ("5:01-10:00", te.t.between(301, 600)),
                  ("earlier", te.t > 600)]:
    kk = kk.to_numpy()
    print(f"    {lab:12s} n {kk.sum():6,}  table {et[kk].mean():.2f}  curve {ec[kk].mean():.2f}")
  worst = 0.0
  for h in (2, 4):
    g = np.asarray(c[f"q{h}"])[: 600 // C.CURVE_STEP + 1]
    dt = np.abs(np.diff(g, axis=0))
    if dj2:  # (DJ2) the step across the two-minute warning (cells 2:00 -> 2:15) is the rule's
      dt[120 // C.CURVE_STEP] = 0
    worst = max(worst, dt.max(), np.abs(np.diff(g, axis=1)).max())
  g3 = worst <= 4
  print(f"[dj] (3) largest step between neighbouring cells in a half's last 10:00: {worst:.1f} s -> {g3}")
  print("\n[dj] the curve (2018-23 fit), Q4 seconds between snaps, by time left x margin:")
  ms = [-14, -7, -3, 0, 3, 7, 14]
  for t in (600, 420, 300, 240, 180, 150, 120, 90, 60, 30, 0):
    print(f"  {t // 60}:{t % 60:02d}  " + "  ".join(f"{m:+d} {C.curve_pace(c, [4], [t], [m])[0]:4.1f}" for m in ms))
  print(f"\n[dj] GATE (1)-(3): (1) {g1}  (2) {g2}  (3) {g3}  -> {'PASS, now (4): CJ' if g1 and g2 and g3 else 'FAIL'}")


if __name__ == "__main__":
  main()
