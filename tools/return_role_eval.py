"""(BF) a role for players returning to an empty recent-usage window (pre-registered 2026-10-20, docs/INSIGHTS.md (BF)).

Usage: python tools/experiments.py baseline,return_role 2021-2025 --history=8 --jobs=5   (gate 2: the ALL row)
       python tools/return_role_eval.py                                                 (gates 1 and 3)
Reads the newest cached backtests (cache/experiments/baseline_<season>_*.parquet, return_role_<season>_*.parquet).
Touched rows: the baseline's recent shares (db / carry / tgt) are all empty (stored as 0) and the variant filled them;
he played. GATE (1) touched rows MAE lower, 95% CI over season-weeks upper < 0, improvement >= 0.5 points; (3) touched
rows, mean projection within 1.5 points of mean actual.
"""
import glob
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

KEY = ["gsis_id", "season", "week"]


def newest(prefix: str, season: int) -> pd.DataFrame:
  fs = glob.glob(str(ROOT / "cache" / "experiments" / f"{prefix}_{season}_*.parquet"))
  if not fs:
    sys.exit(f"no cached backtest {prefix} {season}: run tools/experiments.py baseline,return_role 2021-2025 first")
  return pd.read_parquet(max(fs, key=os.path.getmtime))


def ci(diff: np.ndarray, cl: np.ndarray):
  gr = pd.DataFrame({"d": diff, "c": cl}).groupby("c").d.agg(["sum", "size"])
  s_, n_ = gr["sum"].to_numpy(), gr["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(gr), (4000, len(gr)))
  bt = s_[idx].sum(1) / n_[idx].sum(1)
  return float(diff.mean()), float(np.percentile(bt, 2.5)), float(np.percentile(bt, 97.5))


def main():
  rows = []
  for s in range(2021, 2026):
    b, v = newest("baseline", s), newest("return_role", s)
    sh = ["db_share", "carry_share", "tgt_share"]
    m = b[KEY + sh + ["pos", "full_name", "proj", "actual", "last_season", "played"]].merge(
      v[KEY + sh + ["proj"]].rename(columns={"proj": "proj_v", **{c: c + "_v" for c in sh}}), on=KEY, how="inner")
    # touched: the variant filled his empty recent shares (the cache stores empty shares as 0)
    touched = (m[sh].fillna(0).abs().sum(axis=1) == 0) & (m[[c + "_v" for c in sh]].fillna(0).abs().sum(axis=1) > 0)
    t = m[touched & m.played.astype(bool)]
    rows.append(t)
  r = pd.concat(rows, ignore_index=True).dropna(subset=["actual"])
  r["eb"], r["ev"] = (r.proj - r.actual).abs(), (r.proj_v - r.actual).abs()
  r["kind"] = np.where(r.last_season < r.season - 1, "after a lost season", "mid-season return")
  cl = (r.season.astype(str) + "-" + r.week.astype(str)).to_numpy()
  g1 = ci((r.ev - r.eb).to_numpy(), cl)
  print(f"touched rows 2021-25: {len(r)} (played)")
  print(f"(1) MAE {r.eb.mean():.3f} -> {r.ev.mean():.3f}, {g1[0]:+.3f} [{g1[1]:+.3f}, {g1[2]:+.3f}]  "
        f"{'PASS' if g1[2] < 0 and g1[0] <= -0.5 else 'FAIL'}")
  gap = abs(r.proj_v.mean() - r.actual.mean())
  print(f"(3) mean projection {r.proj.mean():.2f} -> {r.proj_v.mean():.2f}, actual {r.actual.mean():.2f}: "
        f"{'PASS' if gap <= 1.5 else 'FAIL'}")
  print(r.groupby(["kind", "pos"]).agg(n=("actual", "size"), actual=("actual", "mean"), today=("proj", "mean"),
                                       variant=("proj_v", "mean"), mae_today=("eb", "mean"), mae_var=("ev", "mean")).round(2).to_string())
  print("gate (2): tools/experiments.py ALL row (CI upper < +0.003)")


if __name__ == "__main__":
  main()
