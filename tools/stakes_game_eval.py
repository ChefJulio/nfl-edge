"""(BT) Playoff stakes in the game win chance (pre-registered 2026-10-20, docs/INSIGHTS.md (BT)).

Usage: python tools/stakes_game_eval.py   (needs cache/vegas_prior_eval.parquet, cache/lineup_rows.parquet,
                                            cache/playoff_odds_weekly.parquet)
SETTLED = P(playoffs) >= .99 and P(bye) >= .99 or <= .01; ELIMINATED = P(playoffs) <= .01, as of before the week.
Features (home - away, 0 before week 15): settled x [week 18], settled x [weeks 15-17], eliminated.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402

TEST = [2022, 2023, 2024, 2025]


def main():
  g = pd.read_parquet(ROOT / "cache" / "vegas_prior_eval.parquet")
  L = pd.read_parquet(ROOT / "cache" / "lineup_rows.parquet").set_index(["game_id", "team"]).report_rapm_OFF
  g["lineup"] = [L.get((i, h), np.nan) - L.get((i, a), np.nan) for i, h, a in zip(g.game_id, g.home_team, g.away_team)]
  g = g.dropna(subset=["lineup"]).copy()
  o = pd.read_parquet(ROOT / "cache" / "playoff_odds_weekly.parquet").set_index(["season", "week", "team"])
  settled = ((o.p_playoffs >= 0.99) & ((o.p_bye >= 0.99) | (o.p_bye <= 0.01))).astype(float)
  elim = (o.p_playoffs <= 0.01).astype(float)
  for side, col in (("h", "home_team"), ("a", "away_team")):
    k = list(zip(g.season, g.week, g[col]))
    g[f"set_{side}"] = [settled.get(x, 0.0) for x in k]
    g[f"elim_{side}"] = [elim.get(x, 0.0) for x in k]
  late = g.week >= 15
  g["set18"] = (g.set_h - g.set_a) * (g.week == 18)
  g["set1517"] = (g.set_h - g.set_a) * g.week.between(15, 17)
  g["elim"] = (g.elim_h - g.elim_a) * late
  ml = lambda m: np.where(m > 0, 100 / (m + 100), -m / (-m + 100))  # noqa: E731
  ph, pa = ml(g.ml_h), ml(g.ml_a)
  g["vegas"] = ph / (ph + pa)
  arms = {"base": ["home", "gap", "elo", "lineup"], "stakes": ["home", "gap", "elo", "lineup", "set18", "set1517", "elim"]}
  for s in TEST:
    tr, te = g.season < s, g.season == s
    for arm, cols in arms.items():
      m = LogisticRegression(C=1e6, fit_intercept=False, max_iter=3000).fit(g.loc[tr, cols], g.loc[tr, "y"])
      g.loc[te, arm] = m.predict_proba(g.loc[te, cols])[:, 1]
  for arm in list(arms) + ["vegas"]:
    g[f"b_{arm}"] = (g[arm] - g.y) ** 2
  T = g[g.season.isin(TEST) & late]
  flagged = g[late].groupby("week")[["set_h", "set_a", "elim_h", "elim_a"]].sum().sum(axis=1) / g[late].groupby("season").week.nunique().sum() * 0
  d = (T.b_stakes - T.b_base).to_numpy()
  bt = d[np.random.default_rng(0).integers(0, len(d), (2000, len(d)))].mean(1)
  lo, hi = np.percentile(bt, [2.5, 97.5])
  per = T.groupby("season")[["b_base", "b_stakes", "b_vegas"]].mean()
  print(f"(BT) weeks 15-18, 2022-25: {len(T)} games; Brier base {T.b_base.mean():.4f} stakes {T.b_stakes.mean():.4f} vegas {T.b_vegas.mean():.4f}")
  print(f"  stakes - base {d.mean():+.5f} [{lo:+.5f}, {hi:+.5f}]")
  print(per.round(4).to_string())
  print(T.groupby("week")[["b_base", "b_stakes", "b_vegas"]].mean().round(4).assign(n=T.groupby("week").size()).to_string())
  n = g[late & g.season.between(2021, 2025)]
  fl = pd.concat([n[["season", "week", "set_h", "elim_h"]].rename(columns={"set_h": "s", "elim_h": "e"}),
                  n[["season", "week", "set_a", "elim_a"]].rename(columns={"set_a": "s", "elim_a": "e"})])
  print("teams flagged per week (mean over 2021-25): settled", fl.groupby(["season", "week"]).s.sum().groupby("week").mean().round(1).to_dict(),
        "eliminated", fl.groupby(["season", "week"]).e.sum().groupby("week").mean().round(1).to_dict())
  m = LogisticRegression(C=1e6, fit_intercept=False, max_iter=3000).fit(g.loc[g.season <= 2025, arms["stakes"]], g.loc[g.season <= 2025, "y"])
  print("weights (fit 2021-25, reading only):", dict(zip(arms["stakes"], m.coef_[0].round(3))))
  better = int((per.b_stakes < per.b_base).sum())
  print(f"seasons better {better}/4; GATE:", "PASS (confirm on 2026 weeks 15-18)" if d.mean() <= -0.003 and hi < 0 and better >= 3 else "FAIL")


if __name__ == "__main__":
  main()
