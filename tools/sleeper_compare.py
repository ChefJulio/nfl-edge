"""Head-to-head vs Sleeper's projections, then a blend test (pre-registered, docs/INSIGHTS.md section 9, 2026-10-15).

Usage: python tools/sleeper_compare.py [--variant=baseline]

Sleeper's projections API (company = rotowire) keeps each player-week's last saved stat line back to 2019. Fetched
once per (season, week) into cache/sleeper_proj/ via nfledge/sleeper.py (kept once fetched). Scored in OUR half-PPR rules from the stat line (Sleeper's own points use INT -1 and
bonuses). Rows: the variant's walk-forward backtest, relevant rows (played, >= 2 prior games, top-N by consensus).
(1) Scoreboard: MAE ours vs Sleeper by position / season, 95% bootstrap over season-weeks. (2) Blend: final =
(1 - w) ours + w Sleeper, w per position fit on 2021-23, tested on 2024-26. GATE: all-position MAE CI upper < 0 on
2024-26, no position's CI lower > 0.
"""
import glob
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from experiments import relevant  # noqa: E402
from nfledge import sleeper as SL  # noqa: E402
from nfledge.config import load_scoring  # noqa: E402

FIT, TEST = [2021, 2022, 2023], [2024, 2025, 2026]
POS = SL.POS
STATS = SL.STATS


def fetch(season: int, week: int) -> pd.DataFrame:
  return SL.fetch(season, week, ROOT / "cache")  # cached forever: the live pipeline's last pre-game copy is kept


def id_map() -> dict:
  return SL.id_map(ROOT / "cache")


def load_ours(v: str) -> pd.DataFrame:
  fs = {}
  for f in glob.glob(str(ROOT / "cache" / "experiments" / f"{v}_20*.parquet")):
    s = int(os.path.basename(f).split("_")[-2])
    if s not in fs or os.path.getmtime(f) > os.path.getmtime(fs[s]):
      fs[s] = f
  return pd.concat([pd.read_parquet(fs[s]).assign(season=s) for s in sorted(fs)], ignore_index=True)


def ci(d: np.ndarray, g: np.ndarray):
  gs = pd.DataFrame({"d": d, "g": g}).groupby("g").d.agg(["sum", "size"])
  s_, c_ = gs["sum"].to_numpy(), gs["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(gs), (2000, len(gs)))
  bt = s_[idx].sum(1) / c_[idx].sum(1)
  return d.mean(), np.percentile(bt, 2.5), np.percentile(bt, 97.5)


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  R = load_ours(opt.get("variant", "baseline"))
  R = relevant(R)
  R = R[R.pos.isin(POS) & R.actual.notna()].copy()
  sc = load_scoring()
  sl = pd.concat([fetch(int(s), int(w)) for s, w in R[["season", "week"]].drop_duplicates().itertuples(index=False)],
                 ignore_index=True)
  print("[sleeper] companies:", sl.company.value_counts().to_dict())
  sl["gsis_id"] = sl.sleeper_id.map(id_map())
  sl["sleeper"] = sum(sl[k] * sc.weights.get(v, 0.0) for k, v in STATS.items())
  sl = sl.dropna(subset=["gsis_id"]).sort_values("sleeper").drop_duplicates(["gsis_id", "season", "week"], keep="last")
  n0 = len(R)
  R = R.merge(sl[["gsis_id", "season", "week", "sleeper", "updated_at"]], on=["gsis_id", "season", "week"], how="left")
  print(f"[sleeper] relevant rows {n0}; matched {R.sleeper.notna().sum()}; unmatched by season",
        R[R.sleeper.isna()].groupby("season").size().to_dict())
  R = R[R.sleeper.notna()].copy()
  print(f"[sleeper] rows with Sleeper projection 0 (they had him out?): {(R.sleeper <= 0).sum()}")
  R["g"] = R.season.astype(str) + "-" + R.week.astype(str)
  R["e_us"], R["e_sl"] = (R.proj - R.actual).abs(), (R.sleeper - R.actual).abs()

  print("\n(1) SCOREBOARD  MAE ours / Sleeper, diff = ours - Sleeper [95% CI]  (negative = we're better)")
  for lab, x in [("ALL", R)] + [(p, R[R.pos == p]) for p in POS]:
    m, lo, hi = ci((x.e_us - x.e_sl).to_numpy(), x.g.to_numpy())
    print(f"  {lab:4s} n={len(x):6d}  {x.e_us.mean():.3f} / {x.e_sl.mean():.3f}  {m:+.3f} [{lo:+.3f}, {hi:+.3f}]")
  print("  by season:")
  for s, x in R.groupby("season"):
    m, lo, hi = ci((x.e_us - x.e_sl).to_numpy(), x.g.to_numpy())
    pos = "  ".join(f"{p} {(y.e_us - y.e_sl).mean():+.2f}" for p, y in x.groupby("pos"))
    print(f"  {s} n={len(x):5d}  {x.e_us.mean():.3f} / {x.e_sl.mean():.3f}  {m:+.3f} [{lo:+.3f}, {hi:+.3f}]   {pos}")
  print("  rank correlation with actual (Spearman, within position-week), ours / Sleeper:")
  for p in POS:
    x = R[R.pos == p]
    cu = x.groupby("g").apply(lambda y: y.proj.corr(y.actual, method="spearman")).mean()
    cs = x.groupby("g").apply(lambda y: y.sleeper.corr(y.actual, method="spearman")).mean()
    print(f"   {p}: {cu:.3f} / {cs:.3f}")

  print("\n(2) BLEND  w per position fit on 2021-23 (MAE grid), tested 2024-26")
  grid = np.round(np.arange(0, 1.0001, 0.05), 2)
  F, T = R[R.season.isin(FIT)], R[R.season.isin(TEST)].copy()
  w = {}
  for p in POS:
    x = F[F.pos == p]
    w[p] = float(grid[np.argmin([((1 - a) * x.proj + a * x.sleeper - x.actual).abs().mean() for a in grid])])
  print("  weights:", w)
  T["blend"] = (1 - T.pos.map(w)) * T.proj + T.pos.map(w) * T.sleeper
  T["e_b"] = (T.blend - T.actual).abs()
  ok = True
  for lab, x in [("ALL", T)] + [(p, T[T.pos == p]) for p in POS]:
    m, lo, hi = ci((x.e_b - x.e_us).to_numpy(), x.g.to_numpy())
    print(f"  {lab:4s} n={len(x):6d}  MAE {x.e_us.mean():.3f} -> {x.e_b.mean():.3f}  {m:+.3f} [{lo:+.3f}, {hi:+.3f}]")
    ok &= (hi < 0) if lab == "ALL" else (lo <= 0)
  for s, x in T.groupby("season"):
    print(f"   {s}: {(x.e_b - x.e_us).mean():+.3f}")
  print("[sleeper] BLEND GATE:", "PASS" if ok else "FAIL")
  if ok:
    full = {}
    for p in POS:
      x = R[R.pos == p]
      full[p] = float(grid[np.argmin([((1 - a) * x.proj + a * x.sleeper - x.actual).abs().mean() for a in grid])])
    print("  ship weights (fit 2021-26):", full)


if __name__ == "__main__":
  main()
