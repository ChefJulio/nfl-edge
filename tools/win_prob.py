"""Win probabilities from predicted margins, walk-forward, and how well calibrated they are.

Usage: python tools/win_prob.py        (2021 to now, ~3 min)

P(home wins) = logistic(k x margin) with k fit on earlier seasons (margins from the model, or Vegas spreads). Prints
per-source Brier score and log loss (lower = better), accuracy, and a calibration table (predicted vs actual win
rate by probability band), plus pick accuracy by how confident the source was, to set a data-driven "tossup" band.
"""
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import game_eval as ge  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.report import fit_win_k as fit_k  # noqa: E402

pd.set_option("display.width", 200)


if __name__ == "__main__":
  base = load_config()
  seasons = list(range(2021, 2027))
  with ProcessPoolExecutor(max_workers=6) as ex:
    parts = list(ex.map(ge.season_games, [base] * len(seasons), [8] * len(seasons), seasons))
  d = pd.concat([p[0] for p in parts], ignore_index=True)
  d = d[(d.variant == "fitted_6yr") & d.spread_line.notna()].copy()
  d["actual"] = d.home_score - d.away_score
  d = d[d.actual != 0]
  d["won"] = (d.actual > 0).astype(float)
  out = []
  for s in seasons[1:]:  # each season's k fit on earlier seasons
    tr, te = d[d.season < s], d[d.season == s].copy()
    for src, col in (("model", "model_margin"), ("vegas", "spread_line")):
      k = fit_k(tr[col].to_numpy(), tr.won.to_numpy())
      te[f"p_{src}"] = 1 / (1 + np.exp(-k * te[col]))
      te[f"k_{src}"] = k
    out.append(te)
  o = pd.concat(out)
  print(f"Test seasons 2022-2026: {len(o)} games. Fitted k: model {o.k_model.min():.3f}-{o.k_model.max():.3f}, "
        f"Vegas {o.k_vegas.min():.3f}-{o.k_vegas.max():.3f} (P = 1 / (1 + exp(-k x margin)))")
  for src in ("model", "vegas"):
    p, y = o[f"p_{src}"].clip(1e-6, 1 - 1e-6), o.won
    brier, ll = ((p - y) ** 2).mean(), -(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()
    print(f"  {src:6s} Brier {brier:.4f}  log loss {ll:.4f}  picks right {((p > .5) == (y > .5)).mean():.1%}")
  base_rate = d[d.season < 2022].won.mean()
  print(f"  home-team-always ({base_rate:.0%}) Brier {((base_rate - o.won) ** 2).mean():.4f}")
  print("\nCalibration (favorite's predicted chance vs how often the favorite won):")
  for src in ("model", "vegas"):
    fav = np.maximum(o[f"p_{src}"], 1 - o[f"p_{src}"])
    fav_won = np.where(o[f"p_{src}"] >= .5, o.won, 1 - o.won)
    bands = pd.cut(fav, [.5, .55, .6, .65, .7, .8, .9, 1.0], include_lowest=True)
    t = pd.DataFrame({"band": bands, "pred": fav, "won": fav_won}).groupby("band", observed=True).agg(
      games=("won", "size"), predicted=("pred", "mean"), actual=("won", "mean"))
    print(f"  {src}:"); print(t.round(3).to_string())
  # blend: logistic in both margins, fit walk-forward
  bl = []
  for s in seasons[1:]:
    tr, te = d[d.season < s], d[d.season == s]
    best, bw = 1e9, 0.0
    for w in np.linspace(0, 1, 21):  # weight on the model margin, k refit for each mix
      m = w * tr.model_margin + (1 - w) * tr.spread_line
      k = fit_k(m.to_numpy(), tr.won.to_numpy())
      p = (1 / (1 + np.exp(-k * m))).clip(1e-6, 1 - 1e-6)
      ll = -(tr.won * np.log(p) + (1 - tr.won) * np.log(1 - p)).mean()
      if ll < best:
        best, bw, bk = ll, w, k
    m = bw * te.model_margin + (1 - bw) * te.spread_line
    bl.append(pd.DataFrame({"p": 1 / (1 + np.exp(-bk * m)), "won": te.won, "w": bw}))
  b = pd.concat(bl)
  p = b.p.clip(1e-6, 1 - 1e-6)
  print(f"\nBlend (weight on model {b.w.min():.2f}-{b.w.max():.2f}): Brier {((p - b.won) ** 2).mean():.4f}  "
        f"log loss {-(b.won * np.log(p) + (1 - b.won) * np.log(1 - p)).mean():.4f}")
  # tossup band: favorite's chance in 1-point steps, with 90% intervals on how often favorites won
  print("\nFavorite win rate by predicted chance (cumulative from 50%: games with favorite under X):")
  for src in ("model", "vegas"):
    fav = np.maximum(o[f"p_{src}"], 1 - o[f"p_{src}"]).to_numpy()
    fav_won = np.where(o[f"p_{src}"] >= .5, o.won, 1 - o.won)
    print(f"  {src}:")
    for x in (.52, .54, .56, .58, .60, .62, .65):
      sel = fav < x
      n, r = int(sel.sum()), fav_won[sel].mean() if sel.any() else np.nan
      se = np.sqrt(.25 / max(n, 1))
      print(f"    under {x:.0%}: {n:4d} games ({n / len(o):.0%}), favorite won {r:.1%} +/- {1.645 * se:.1%}")
  # Values for config.toml [report]: the model's k on every game so far, and the tossup line = the largest
  # favorite chance (1-point grid) under which the market's favorites won at a rate a coin flip explains (90%).
  k_all = fit_k(d.model_margin.to_numpy(), d.won.to_numpy())
  fav = np.maximum(o.p_vegas, 1 - o.p_vegas).to_numpy()
  fav_won = np.where(o.p_vegas >= .5, o.won, 1 - o.won)
  tossup = .5
  for x in np.arange(.51, .70, .01):
    sel = fav < x
    if sel.sum() >= 30 and fav_won[sel].mean() - 1.645 * np.sqrt(.25 / sel.sum()) <= .5:
      tossup = round(float(x), 2)
  print(f"\nconfig.toml [report]: model_win_k = {k_all:.3f}   tossup_below = {tossup:.2f}")
