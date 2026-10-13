"""Two pre-registered follow-ups to the 2026-10-13 RB tests, on the cached 2021-2025 walk-forward backtests.

1. Goal-line share and touchdown odds: RB chance of 1+ rushing TD (Poisson, as the site shows it), Brier score,
   gl_share vs baseline on identical rows; 95% CI over season-weeks. Adopt only if the CI excludes zero.
2. Range calibration by committee tendency: share of RB actual scores inside 10-90 (target 0.80) and 25-75
   (target 0.50), by tercile of the team's as-of lead-back concentration; 95% CI over season-weeks.

Usage: python tools/rb_followups.py   (run tools/experiments.py baseline,gl_share 2021-2025 first)
"""
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
KEYS = ["season", "week", "gsis_id"]


def latest(name: str) -> pd.DataFrame:
  parts = []
  for s in SEASONS:
    files = glob.glob(str(ROOT / "cache" / "experiments" / f"{name}_{s}_*.parquet"))
    parts.append(pd.read_parquet(max(files, key=os.path.getmtime)))
  return pd.concat(parts, ignore_index=True)


def ci_mean(x: pd.Series, d: pd.DataFrame) -> tuple[float, float]:
  return week_bootstrap(x, d.season.astype(str) + "-" + d.week.astype(str))


def main():
  base, gl = latest("baseline"), latest("gl_share")
  rel = relevant(base)
  rb = rel[rel.pos == "RB"]

  # 1. Touchdown odds -------------------------------------------------------------------------------------------
  j = rb[KEYS + ["rush_td", "a_rush_td"]].merge(gl[KEYS + ["rush_td"]], on=KEYS, suffixes=("_b", "_g"))
  y = (j.a_rush_td >= 1).astype(float)
  pb, pg = 1 - np.exp(-j.rush_td_b), 1 - np.exp(-j.rush_td_g)
  bb, bg = (pb - y) ** 2, (pg - y) ** 2
  lo, hi = ci_mean(bg - bb, j)
  print(f"1. RB chance of 1+ rushing TD, {len(j)} RB-weeks 2021-2025 (actual rate {y.mean():.3f}; "
        f"mean predicted: baseline {pb.mean():.3f}, goal-line {pg.mean():.3f})")
  print(f"   Brier: baseline {bb.mean():.4f}  goal-line {bg.mean():.4f}  diff {(bg - bb).mean():+.4f} "
        f"[{lo:+.4f}, {hi:+.4f}] -> {'better' if hi < 0 else 'worse' if lo > 0 else 'no difference'}")
  # Where would it matter most: backs whose goal-line share runs well above / below their carry share.
  tilt = gl.set_index(KEYS).i10_tilt.reindex(pd.MultiIndex.from_frame(j[KEYS])).to_numpy()
  for lab, m in (("goal-line share 10+ pts above carry share", tilt >= 0.10),
                 ("10+ pts below", tilt <= -0.10)):
    m = pd.Series(m, index=j.index).fillna(False)
    if m.sum() > 50:
      lo2, hi2 = ci_mean((bg - bb)[m], j[m])
      print(f"   {lab}: n={m.sum()}, actual {y[m].mean():.3f}, baseline {pb[m].mean():.3f}, goal-line {pg[m].mean():.3f}; "
            f"Brier diff {(bg - bb)[m].mean():+.4f} [{lo2:+.4f}, {hi2:+.4f}]")

  # 2. Range calibration by committee tendency ------------------------------------------------------------------
  print("\n2. RB range calibration by team committee tendency (as-of lead-back share of RB carries)")
  rb = rb.assign(in80=((rb.actual >= rb.p10) & (rb.actual <= rb.p90)).astype(float),
                 in50=((rb.actual >= rb.p25) & (rb.actual <= rb.p75)).astype(float),
                 below=(rb.actual < rb.p10).astype(float), above=(rb.actual > rb.p90).astype(float))
  cuts = rb.team_conc.quantile([1 / 3, 2 / 3]).to_numpy()
  rb["grp"] = np.select([rb.team_conc <= cuts[0], rb.team_conc <= cuts[1]],
                        [f"committee (<= {cuts[0]:.2f})", "middle"], f"bellcow (> {cuts[1]:.2f})")
  for g, d in [("all RBs", rb)] + list(rb.groupby("grp", sort=False)):
    l80, h80 = ci_mean(d.in80, d)
    l50, h50 = ci_mean(d.in50, d)
    print(f"   {g:22s} n={len(d):4d}  10-90: {d.in80.mean():.3f} [{l80:.3f}, {h80:.3f}]  "
          f"25-75: {d.in50.mean():.3f} [{l50:.3f}, {h50:.3f}]  below floor {d.below.mean():.3f}  above ceiling {d.above.mean():.3f}")


if __name__ == "__main__":
  main()
