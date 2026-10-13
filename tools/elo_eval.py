"""Fit Elo to our data and find the best in-house win chance. Walk-forward on 2022-26 (games with a Vegas line).

Usage: python tools/elo_eval.py        (needs cache/darts_base.parquet from tools/darts.py; ~1 min)

Elo: pre-game rating per team, updated after every game (playoffs included) by
  K x mult x (result - expected),  expected = 1 / (1 + 10^(-(diff + HFA x home) / 400)),
  mult = ln(|margin| + 1) x 2.2 / (winner's rating edge x 0.001 + 2.2) with margin, else 1,
and pulled a share `revert` back toward 1505 every offseason. For each test season, (K, HFA, revert, margin) are
chosen by log loss on regular-season games of the seasons before it (2019 on, after warm-up), never the test year.
Candidates are then logistic regressions fit on prior seasons, scored by Brier against the site's current chance
(model margin, no intercept) and rank gap + home, with 95% CIs over season-weeks.
"""
import copy
import itertools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from darts import logit_fit  # noqa: E402
from nfledge import data as D, elo  # noqa: E402
from nfledge.config import load_config  # noqa: E402

GRID = list(itertools.product([8, 12, 16, 20, 25, 30, 40], [0, 25, 40, 55, 70], [0.0, 0.25, 1 / 3, 0.5, 0.75],
                              [False, True]))


def run_elo(g: pd.DataFrame, k: float, hfa: float, revert: float, mov: bool) -> np.ndarray:
  """Pre-game home-minus-away Elo difference for every game in g (sorted by date): the site's own Elo."""
  return elo.run(g, k, hfa, revert, mov)[0]


def brier(p, y):
  return float(((p - y) ** 2).mean())


if __name__ == "__main__":
  cfg = copy.deepcopy(load_config())
  cfg["data"]["history_seasons"] = 9
  sched = D.load_all(cfg).schedules
  g = elo.finished(sched)
  g["neutral"] = g.location == "Neutral"
  g["won"] = np.where(g.home_score > g.away_score, 1.0, np.where(g.home_score < g.away_score, 0.0, np.nan))
  sel = (g.game_type == "REG") & (g.week >= 2) & g.won.notna()
  print(f"Elo grid: {len(GRID)} settings over {len(g)} games {g.season.min()}-{g.season.max()}", flush=True)
  diffs = {p: run_elo(g, *p) for p in GRID}
  g_home = (~g.neutral).astype(float).to_numpy()

  def elo_ll(p, seasons):
    m = (sel & g.season.isin(seasons)).to_numpy()
    e = diffs[p][m] + p[1] * g_home[m]
    q = (1 / (1 + 10 ** (-e / 400))).clip(1e-9, 1 - 1e-9)
    y = g.won.to_numpy()[m]
    return -float((y * np.log(q) + (1 - y) * np.log(1 - q)).mean())

  test = list(range(2022, 2027))
  chosen = {}
  for s in test:
    chosen[s] = min(GRID, key=lambda p: elo_ll(p, range(2019, s)))
  print("Elo settings chosen per test season (K, HFA, revert, margin):")
  for s, p in chosen.items():
    print(f"  {s}: K {p[0]}, HFA {p[1]}, revert {p[2]:.2f}, margin {'yes' if p[3] else 'no'}")
  best_all = min(GRID, key=lambda p: elo_ll(p, range(2019, 2027)))
  print(f"  fit on every season 2019-2026: K {best_all[0]}, HFA {best_all[1]}, revert {best_all[2]:.2f}, "
        f"margin {'yes' if best_all[3] else 'no'}")

  d = pd.read_parquet(ROOT / "cache" / "darts_base.parquet")
  d = d.rename(columns={"location_x": "location"})
  d = d[d.home_score != d.away_score].reset_index(drop=True)
  d["won"] = (d.home_score > d.away_score).astype(float)
  d["home"] = (d.location != "Neutral").astype(float)
  d["rank_gap"] = d.away_rank - d.home_rank
  d["net_diff"] = d.home_net - d.away_net
  gid = {gi: i for i, gi in enumerate(g.game_id)}
  # Elo for each game with the settings chosen for its season (training seasons use the settings of the test
  # season they train for, so nothing from the test year leaks into the choice).
  cands = {
    "site now: model margin (no home term)": ["model_margin"],
    "rank gap + home": ["home", "rank_gap"],
    "Elo + home": ["home", "elo"],
    "rank gap + Elo + home": ["home", "rank_gap", "elo"],
    "net rating gap + Elo + home": ["home", "net_diff", "elo"],
    "model margin + Elo + home": ["home", "model_margin", "elo"],
    "rank gap + net gap + Elo + home": ["home", "rank_gap", "net_diff", "elo"],
  }
  preds = {c: pd.Series(np.nan, index=d.index) for c in cands}
  for s in test:
    dd = d.copy()
    dd["elo"] = [diffs[chosen[s]][gid[x]] / 100 for x in dd.game_id]  # per 100 Elo points
    tr, te = dd[dd.season < s], dd[(dd.season == s) & dd.spread_line.notna()]
    for c, cols in cands.items():
      w = logit_fit(tr[cols].to_numpy(float), tr.won.to_numpy(float))
      preds[c].loc[te.index] = 1 / (1 + np.exp(-te[cols].to_numpy(float) @ w))
  te = d[d.season.isin(test) & d.spread_line.notna()]
  y = te.won.to_numpy()
  sw = (te.season.astype(str) + "-" + te.week.astype(str)).to_numpy()
  keys = np.unique(sw)
  idx = [np.flatnonzero(sw == k) for k in keys]
  rng = np.random.default_rng(0)
  boot = [np.concatenate([idx[i] for i in rng.integers(0, len(keys), len(keys))]) for _ in range(2000)]

  def vs(a, b):
    e = (preds[a].loc[te.index].to_numpy() - y) ** 2 - (preds[b].loc[te.index].to_numpy() - y) ** 2
    bs = [e[x].mean() for x in boot]
    return f"{e.mean():+.4f} [{np.percentile(bs, 2.5):+.4f}, {np.percentile(bs, 97.5):+.4f}]"

  print(f"\n{len(te)} test games 2022-2026 with a Vegas line. Brier (lower = better); diffs with 95% CI, negative = "
        f"better than the comparison")
  early = (te.week <= 6).to_numpy()
  print(f"{'candidate':34s} {'Brier':>7s} {'wk2-6':>7s} {'wk7+':>7s} {'right':>6s}   vs site now               "
        f"vs rank gap + home")
  for c in cands:
    p = preds[c].loc[te.index].to_numpy()
    print(f"{c:34s} {brier(p, y):.4f} {brier(p[early], y[early]):.4f} {brier(p[~early], y[~early]):.4f} "
          f"{((p > .5) == (y > .5)).mean():6.1%}   {vs(c, 'site now: model margin (no home term)')}   "
          f"{vs(c, 'rank gap + home')}")
  # Values for config.toml [report.win_model]: Elo settings and the rank gap + Elo + home coefficients, both fit
  # on every season available.
  d["elo"] = [diffs[best_all][gid[x]] / 100 for x in d.game_id]
  w = logit_fit(d[["home", "rank_gap", "elo"]].to_numpy(float), d.won.to_numpy(float))
  print(f"\nconfig.toml [report.win_model]: elo_k = {best_all[0]}, elo_hfa = {best_all[1]}, "
        f"elo_revert = {best_all[2]:.2f}, elo_margin = {str(best_all[3]).lower()}, "
        f"home = {w[0]:.4f}, rank_gap = {w[1]:.4f}, elo_per_100 = {w[2]:.4f}")
  vg = 1 / (1 + np.exp(-0.13 * te.spread_line.to_numpy()))
  print(f"{'Vegas (k 0.13)':34s} {brier(vg, y):.4f} {brier(vg[early], y[early]):.4f} {brier(vg[~early], y[~early]):.4f} "
        f"{((vg > .5) == (y > .5)).mean():6.1%}")
