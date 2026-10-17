"""(AA) the availability models' gradient-boosting settings (docs/INSIGHTS.md, pre-registered 2026-10-17).

Grid per model (leaves x iterations x min leaf), the live pipeline walk-forward: choose on 2021-23 by Brier, decide on
2024-25 against today's settings, confirm on 2026 so far.

  python tools/avail_grid_eval.py week|tuesday
"""
import itertools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge import tuesday as T  # noqa: E402
from nfledge.config import load_config  # noqa: E402

GRID = list(itertools.product((7, 15, 31, 63), (200, 400), (20, 40, 80)))


def ece(p, y):
  b = np.minimum((p * 10).astype(int), 9)
  return sum(abs(p[b == k].mean() - y[b == k].mean()) * (b == k).sum() for k in range(10) if (b == k).any()) / len(y)


def preds(which, rows, s, gb):
  (T.WEEK_GB if which == "week" else T.TUE_GB).update(gb)
  te = rows[rows.season == s]
  if which == "week":
    return T.week_predict(T.week_model(rows, s), te)
  return T.fit(rows[rows.season < s]).predict_proba(T.features(te))[:, 1]


def main():
  which = sys.argv[1]
  cfg = load_config()
  d = D.load_all(cfg)
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  rep, hurt = T.report_rows(d), T.hurt_notes(d, cache)
  if which == "week":
    rows = T.week_rows(d, rep, hurt).dropna(subset=["y"])
    rows = rows[~((rows.stage == 3) & (rows.gs_now == "Out"))]
  else:
    rows = T.build_rows(d, rep, hurt).dropna(subset=["y"])
  base = dict(T.WEEK_GB if which == "week" else T.TUE_GB)
  keep = (lambda x: x.stage.isin([1, 2, 3])) if which == "week" else (lambda x: pd.Series(True, index=x.index))
  seasons = sorted(int(x) for x in rows.season.unique() if x >= 2021)
  cache_p = {}

  def run(gb, s):
    k = (tuple(sorted(gb.items())), s)
    if k not in cache_p:
      g = dict(base); g.update(gb)
      te = rows[rows.season == s]
      cache_p[k] = pd.Series(preds(which, rows, s, g), index=te.index)
    return cache_p[k]

  def brier(gb, ss):
    out = []
    for s in ss:
      te = rows[rows.season == s]
      m = keep(te)
      out.append(((run(gb, s)[m] - te.y[m]) ** 2))
    return pd.concat(out)

  today = {k: base[k] for k in ("max_leaf_nodes", "max_iter", "min_samples_leaf")}
  combos = [dict(max_leaf_nodes=a, max_iter=b, min_samples_leaf=c) for a, b, c in GRID]
  if today not in combos:  # today's settings are always a candidate (the Tuesday model's 300 iterations aren't on the grid)
    combos.append(dict(today))
  print(f"{which}: {len(rows)} rows; today {today}", flush=True)
  sc = {}
  for gb in combos:
    sc[tuple(gb.values())] = brier(gb, [2021, 2022, 2023]).mean()
    print(f"  {gb}: Brier 2021-23 {sc[tuple(gb.values())]:.5f}", flush=True)
  best = dict(zip(("max_leaf_nodes", "max_iter", "min_samples_leaf"), min(sc, key=sc.get)))
  print(f"CHOOSE: {best} ({sc[tuple(best.values())]:.5f}) vs today {sc[tuple(today.values())]:.5f}")
  if best == today:
    print("GATE: today's settings are the choice -> keep (now tested)")
    return
  te = rows[rows.season.isin([2024, 2025])]
  m = keep(te)
  bn, bb = brier(best, [2024, 2025]), brier(today, [2024, 2025])
  diff = (bn - bb)
  cl = (te.gsis_id.astype(str) + "-" + te.season.astype(str) + "-" + te.week.astype(str))[m] if "gsis_id" in te else pd.Series(range(len(diff)))
  g = pd.DataFrame({"d": diff.to_numpy(), "c": cl.to_numpy()}).groupby("c").d.agg(["sum", "size"])
  idx = np.random.default_rng(0).integers(0, len(g), (2000, len(g)))
  bt = g["sum"].to_numpy()[idx].sum(1) / g["size"].to_numpy()[idx].sum(1)
  lo, hi = np.percentile(bt, [2.5, 97.5])
  per = {s: (brier(best, [s]) - brier(today, [s])).mean() for s in (2024, 2025)}
  y = te.y[m].to_numpy()
  # aligned to te's rows (rows aren't sorted by season, so a plain concat would pair predictions with other outcomes)
  pn = pd.concat([run(best, s) for s in (2024, 2025)]).reindex(te.index)[m].to_numpy()
  pb = pd.concat([run(today, s) for s in (2024, 2025)]).reindex(te.index)[m].to_numpy()
  en, eb = ece(pn, y), ece(pb, y)
  ok = hi < 0 and all(v < 0 for v in per.values()) and en <= eb + 0.005
  print(f"DECIDE 2024-25: Brier diff {diff.mean():+.5f} [{lo:+.5f}, {hi:+.5f}], per season " + " ".join(f"{s} {v:+.5f}" for s, v in per.items())
        + f"; ECE {eb:.4f} -> {en:.4f} -> {'PASS' if ok else 'FAIL'}")
  if 2026 in seasons:
    c = (brier(best, [2026]) - brier(today, [2026])).mean()
    print(f"CONFIRM 2026: {c:+.5f} -> {'PASS' if c < 0 else 'FAIL'}")
    ok = ok and c < 0
  print(f"GATE: {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
  main()
