"""Do elite pass defenses take more from star receivers than our flat matchup adjustment says? (owner's friend
2026-10-21: outliers aren't equal; "when the WR1 for the opposing team is like WR40".) Descriptive, before any model
change.

Cached baseline backtests 2021-25 (tools/experiments.py relevant rows: played, 2+ prior games), weeks 4+, WRs. Tier =
his season-to-date FP/G rank among WRs that week (top 12 / 13-36 / 37+). Defense = the opponent's pass-defense rating
(def_pass, the team model's coefficient: lower = fewer passing EPA allowed) in thirds per week (tough / middle / soft;
the sign is checked against what WRs scored). Cell = mean actual minus projected (the model's miss) with a 95% CI
over season-weeks. The model already shifts every WR by the same defense effect; a tier x defense pattern in the
misses is what it leaves out.

  python tools/tier_x_defense.py
"""
import glob
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from experiments import relevant  # noqa: E402


def ci(x: pd.DataFrame):
  gr = x.groupby("sw").res.agg(["sum", "size"])
  s_, n_ = gr["sum"].to_numpy(), gr["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(gr), (3000, len(gr)))
  bt = s_[idx].sum(1) / n_[idx].sum(1)
  return x.res.mean(), np.percentile(bt, 2.5), np.percentile(bt, 97.5)


def main():
  fr = []
  for s in range(2021, 2026):
    fs = sorted(glob.glob(str(ROOT / "cache" / "experiments" / f"baseline_{s}_*.parquet")), key=os.path.getmtime)
    fr.append(relevant(pd.read_parquet(fs[-1])))
  d = pd.concat(fr, ignore_index=True)
  d = d[(d.pos == "WR") & (d.week >= 4) & (d.raw_games >= 3) & d.def_pass.notna()].copy()
  d["res"] = d.actual - d.proj
  d["sw"] = d.season.astype(str) + "-" + d.week.astype(str)
  d["rk"] = d.groupby(["season", "week"]).raw_fpg.rank(ascending=False, method="first")
  d["tier"] = pd.cut(d.rk, [0, 12, 36, 999], labels=["top 12", "13-36", "37+"])
  d["dq"] = d.groupby(["season", "week"]).def_pass.transform(lambda x: pd.qcut(x.rank(method="first"), 3, labels=False))
  # orient: the third where WRs scored least relative to their own season average is "tough"
  lvl = d.assign(rel=d.actual - d.raw_fpg).groupby("dq").rel.mean()
  order = lvl.sort_values().index.tolist()
  d["defense"] = d.dq.map({order[0]: "tough", order[1]: "middle", order[2]: "soft"})
  print(f"WR rows {len(d)} (2021-25, weeks 4+). Actual minus season FP/G by defense third: "
        + ", ".join(f"{k} {v:+.2f}" for k, v in d.assign(rel=d.actual - d.raw_fpg).groupby("defense").rel.mean().items()))
  print("\nthe model's miss (actual - projected), by receiver tier x opposing pass defense:")
  print(f"{'tier':<8}" + "".join(f"{c:>30}" for c in ("tough", "middle", "soft")))
  for t in ("top 12", "13-36", "37+"):
    cells = []
    for c in ("tough", "middle", "soft"):
      x = d[(d.tier == t) & (d.defense == c)]
      m, lo, hi = ci(x)
      cells.append(f"{m:+.2f} [{lo:+.2f},{hi:+.2f}] n{len(x)}")
    print(f"{t:<8}" + "".join(f"{c:>30}" for c in cells))
  # the interaction itself: (top 12 tough - top 12 soft) - (rest tough - rest soft)
  def cell(t, c):
    return d[(d.tier.isin(t)) & (d.defense == c)].res.mean()
  inter = (cell(["top 12"], "tough") - cell(["top 12"], "soft")) - (cell(["13-36", "37+"], "tough") - cell(["13-36", "37+"], "soft"))
  sws = d.sw.unique()
  rng = np.random.default_rng(1)
  boots = []
  for _ in range(1000):
    pick = rng.choice(sws, len(sws))
    b = pd.concat([d[d.sw == s] for s in pick[:0]]) if False else d.set_index("sw").loc[pick].reset_index()
    f = lambda t, c: b[(b.tier.isin(t)) & (b.defense == c)].res.mean()  # noqa: E731
    boots.append((f(["top 12"], "tough") - f(["top 12"], "soft")) - (f(["13-36", "37+"], "tough") - f(["13-36", "37+"], "soft")))
  print(f"\ninteraction (stars' tough-minus-soft miss beyond everyone else's): {inter:+.2f} pts [{np.percentile(boots, 2.5):+.2f}, {np.percentile(boots, 97.5):+.2f}]")


if __name__ == "__main__":
  main()
