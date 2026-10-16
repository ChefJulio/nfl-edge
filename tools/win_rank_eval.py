"""Which rank feeds the Matchups win chance (pre-registered 2026-10-16, docs/INSIGHTS.md (Q)).

Usage: python tools/win_rank_eval.py      (needs cache/power_c.parquet from tools/power_c.py, with the N column)
Win chance = logistic(home + rank_gap x (away rank - home rank) + elo_per_100 x Elo diff / 100), the live form. Ranks
per season-week from the site's own code: A = net with the previous starter, N = net with this game's starter, C =
rest-of-season (live). For each, the coefficients are refit walk-forward (seasons before the test season, 2021 on) and
scored by Brier on 2022-26 games with a Vegas line; then refit on every season for config.toml [report.win_model].
"""
import copy
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

VARIANTS = ("A", "N", "C")


def main():
  cfg = copy.deepcopy(load_config())
  cfg["data"]["history_seasons"] = 9
  wm = cfg["report"]["win_model"]
  g = elo.finished(D.load_all(cfg).schedules).reset_index(drop=True)
  g["elo"] = elo.run(g, wm["elo_k"], wm["elo_hfa"], wm["elo_revert"], wm["elo_margin"])[0] / 100
  g = g[(g.game_type == "REG") & (g.week >= 2) & (g.season >= 2021) & (g.home_score != g.away_score)].copy()
  g["won"] = (g.home_score > g.away_score).astype(float)
  g["home"] = (g.location != "Neutral").astype(float)
  p = pd.read_parquet(ROOT / "cache" / "power_c.parquet")
  rk = {v: p.assign(r=p.groupby(["season", "week"])[v].rank(ascending=False, method="min"))
        .set_index(["season", "week", "team"]).r for v in VARIANTS}
  out_ = p.set_index(["season", "week", "team"]).usual_out
  rel = lambda t: D.RELOCATED.get(t, t)  # noqa: E731
  for v in VARIANTS:
    h = [rk[v].get((s, w, rel(t)), np.nan) for s, w, t in zip(g.season, g.week, g.home_team)]
    a = [rk[v].get((s, w, rel(t)), np.nan) for s, w, t in zip(g.season, g.week, g.away_team)]
    g[f"gap_{v}"] = np.array(a) - np.array(h)
  g["either_out"] = [bool(out_.get((s, w, rel(h)), False)) or bool(out_.get((s, w, rel(a)), False))
                     for s, w, h, a in zip(g.season, g.week, g.home_team, g.away_team)]
  g = g.dropna(subset=[f"gap_{v}" for v in VARIANTS]).reset_index(drop=True)
  pred = {v: pd.Series(np.nan, index=g.index) for v in VARIANTS}
  test = sorted(s for s in g.season.unique() if s >= 2022)
  for s in test:
    tr, te = g[g.season < s], g[(g.season == s) & g.spread_line.notna()]
    for v in VARIANTS:
      cols = ["home", f"gap_{v}", "elo"]
      w = logit_fit(tr[cols].to_numpy(float), tr.won.to_numpy(float))
      pred[v].loc[te.index] = 1 / (1 + np.exp(-te[cols].to_numpy(float) @ w))
  te = g[g.season.isin(test) & g.spread_line.notna()]
  y = te.won.to_numpy()
  sw = (te.season.astype(str) + "-" + te.week.astype(str)).to_numpy()
  keys = np.unique(sw)
  idx = [np.flatnonzero(sw == k) for k in keys]
  rng = np.random.default_rng(0)
  boot = [np.concatenate([idx[i] for i in rng.integers(0, len(keys), len(keys))]) for _ in range(4000)]
  err = {v: (pred[v].loc[te.index].to_numpy() - y) ** 2 for v in VARIANTS}

  def diff(a, b, m=None):
    e = err[a] - err[b]
    m = np.ones(len(e), bool) if m is None else m
    bs = [e[x][m[x]].mean() for x in boot]
    return f"{e[m].mean():+.4f} [{np.percentile(bs, 2.5):+.4f}, {np.percentile(bs, 97.5):+.4f}]", np.percentile(bs, 97.5)
  vg = 1 / (1 + np.exp(-0.13 * te.spread_line.to_numpy()))
  out = te.either_out.to_numpy()
  print(f"{len(te)} test games {test[0]}-{test[-1]} with a Vegas line ({out.sum()} with a usual starter out)")
  for v in VARIANTS:
    print(f"  {v}: Brier {err[v].mean():.4f}   usual starter out {err[v][out].mean():.4f}")
  print(f"  Vegas: {((vg - y) ** 2).mean():.4f}   usual starter out {((vg - y) ** 2)[out].mean():.4f}")
  s_cn, hi_cn = diff("C", "N")
  print(f"C - N all games {s_cn}   usual starter out {diff('C', 'N', out)[0]}")
  print(f"N - A all games {diff('N', 'A')[0]}   usual starter out {diff('N', 'A', out)[0]}")
  for s in test:
    m = te.season.to_numpy() == s
    print(f"  {s}: " + "  ".join(f"{v} {err[v][m].mean():.4f}" for v in VARIANTS))
  print("GATE:", "C beats N -> keep C" if hi_cn < 0 else "switch Matchups to N")
  for v in ("N", "C"):
    w = logit_fit(g[["home", f"gap_{v}", "elo"]].to_numpy(float), g.won.to_numpy(float))
    print(f"[report.win_model] on {v}, every season 2021-26: home = {w[0]:.4f}, rank_gap = {w[1]:.4f}, elo_per_100 = {w[2]:.4f}")


if __name__ == "__main__":
  main()
