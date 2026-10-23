"""(CK) key-number features, the late-game checks (docs/INSIGHTS.md); (1)-(3) are tools/wp_eval.py.

  python tools/wp_keys_eval.py late    (4): fit 2006-18 with and without the KEYS features; 2019-25 4th-quarter 1st downs in
                                       the last 8:00, leads -3..+4 x time bands (cells of 40+): mean absolute gap
  node tools/calc_cli.mjs ...          (5) is run on a model file through 2025 (see main's printout)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import winprob as W  # noqa: E402


def fit_cols(r: pd.DataFrame, cols: list):
  from sklearn.ensemble import HistGradientBoostingClassifier
  cst = [W.MONOTONIC.get(f, 0) for f in cols]
  return HistGradientBoostingClassifier(monotonic_cst=cst, **W.PARAMS).fit(W.features(r)[cols], r.y.astype(int))


def late():
  d = pd.concat([pd.read_parquet(ROOT / "cache" / f"pbp_calc_{s}.parquet") for s in range(2006, 2026)], ignore_index=True)
  r = W.rows(d)
  tr = r[r.season <= 2018]
  te = r[(r.season >= 2019) & (r.game_sec <= 480) & (r.down == 1) & r.score_diff.between(-3, 4)].copy()
  base = [f for f in W.FEATURES if f not in W.KEYS]
  te["old"] = fit_cols(tr, base).predict_proba(W.features(te)[base])[:, 1]
  te["new"] = fit_cols(tr, W.FEATURES).predict_proba(W.features(te)[W.FEATURES])[:, 1]
  te["tb"] = pd.cut(te.game_sec, [60, 180, 300, 480], labels=["1:00-3:00", "3:00-5:00", "5:00-8:00"])
  g = te.dropna(subset=["tb"]).groupby(["tb", "score_diff"], observed=True).agg(n=("y", "size"), won=("y", "mean"), old=("old", "mean"),
                                                                                 new=("new", "mean"), nflfastR=("vegas_wp", "mean"))
  g = g[g.n >= 40]
  g["gap_old"], g["gap_new"] = (g.old - g.won).abs(), (g.new - g.won).abs()
  print(g.round(3).to_string())
  a, b = float(g.gap_old.mean()), float(g.gap_new.mean())
  print(f"[keys] (4) mean absolute gap over {len(g)} cells: current {a:.3f}, with key numbers {b:.3f} -> {'PASS' if b < a else 'FAIL'}")


if __name__ == "__main__":
  late()
