"""(BW) Questionable players at their real chance to play (pre-registered 2026-10-20, docs/INSIGHTS.md (BW)).

Usage: python tools/questionable_eval.py      (needs cache/vegas_prior_eval.parquet, cache/lineup_rows.parquet)
BASE = home + rank gap + Elo + lineup (shipped); QUEST = Questionable regulars counted at the measured play share. Production's
form (no intercept), walk-forward, scored 2022-25; gate on all weeks.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402

TEST, CONFIRM = [2022, 2023, 2024, 2025], 2026


def main():
  g = pd.read_parquet(ROOT / "cache" / "vegas_prior_eval.parquet")
  L = pd.read_parquet(ROOT / "cache" / "lineup_rows.parquet").set_index(["game_id", "team"])
  for c, k in (("lineup", "report_rapm_OFF"), ("lineup_arr", "report_rapmq_OFF")):
    g[c] = [L[k].get((i, h), np.nan) - L[k].get((i, a), np.nan) for i, h, a in zip(g.game_id, g.home_team, g.away_team)]
  g = g.dropna(subset=["lineup", "lineup_arr"]).copy()
  ml = lambda m: np.where(m > 0, 100 / (m + 100), -m / (-m + 100))  # noqa: E731
  ph, pa = ml(g.ml_h), ml(g.ml_a)
  g["vegas"] = ph / (ph + pa)
  arms = {"base": ["home", "gap", "elo", "lineup"], "arrive": ["home", "gap", "elo", "lineup_arr"]}
  for s in TEST + [CONFIRM]:
    tr, te = g.season < s, g.season == s
    for arm, cols in arms.items():
      m = LogisticRegression(C=1e6, fit_intercept=False, max_iter=3000).fit(g.loc[tr, cols], g.loc[tr, "y"])
      g.loc[te, arm] = m.predict_proba(g.loc[te, cols])[:, 1]
  for arm in list(arms) + ["vegas"]:
    g[f"b_{arm}"] = (g[arm] - g.y) ** 2
  T = g[g.season.isin(TEST)]
  rng = np.random.default_rng(0)

  def ci(t):
    d = (t.b_arrive - t.b_base).to_numpy()
    bt = d[rng.integers(0, len(d), (2000, len(d)))].mean(1)
    return d.mean(), *np.percentile(bt, [2.5, 97.5])

  a = ci(T)
  per = T.groupby("season")[["b_base", "b_arrive"]].mean()
  C = g[g.season == CONFIRM]
  cd = (C.b_arrive - C.b_base).mean()
  better = int((per.b_arrive < per.b_base).sum())
  print(f"(BW) 2022-25: {len(T)} games; base {T.b_base.mean():.4f} quest {T.b_arrive.mean():.4f} vegas {T.b_vegas.mean():.4f}")
  print(f"  quest - base {a[0]:+.5f} [{a[1]:+.5f}, {a[2]:+.5f}]")
  print(per.round(4).to_string())
  print(f"CONFIRM {CONFIRM}: {len(C)} games, {cd:+.5f}; seasons better {better}/4")
  print("GATE:", "PASS" if a[0] <= -0.001 and a[2] < 0 and better >= 3 and cd < 0 else "FAIL")


if __name__ == "__main__":
  main()
