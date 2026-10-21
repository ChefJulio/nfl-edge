"""(BR) Arrivals in the lineup term (pre-registered 2026-10-20, docs/INSIGHTS.md (BR)).

Usage: python tools/arrivals_eval.py      (needs cache/vegas_prior_eval.parquet, cache/lineup_rows.parquet)
BASE = home + rank gap + Elo + lineup (shipped); ARRIVE = the same with arrivals in the lineup sums. Production's
form (no intercept), walk-forward, scored 2022-25; gate on weeks 1-6.
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
  for c, k in (("lineup", "report_rapm_OFF"), ("lineup_arr", "report_rapmarr_OFF")):
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

  E, A = T[T.week <= 6], T
  e, a = ci(E), ci(A)
  print(f"(BR) 2022-25: {len(E)} games weeks 1-6, {len(A)} all")
  print(f"  weeks 1-6: base {E.b_base.mean():.4f} arrive {E.b_arrive.mean():.4f} vegas {E.b_vegas.mean():.4f}; {e[0]:+.5f} [{e[1]:+.5f}, {e[2]:+.5f}]")
  L7 = T[T.week >= 7]
  l7 = ci(L7)
  print(f"  weeks 7+:  base {L7.b_base.mean():.4f} arrive {L7.b_arrive.mean():.4f}; {l7[0]:+.5f} [{l7[1]:+.5f}, {l7[2]:+.5f}]")
  print(f"  all weeks: {a[0]:+.5f} [{a[1]:+.5f}, {a[2]:+.5f}]")
  wk1 = T[T.week == 1]
  print(f"  week 1 alone ({len(wk1)} games): base {wk1.b_base.mean():.4f} arrive {wk1.b_arrive.mean():.4f}")
  per = E.groupby("season")[["b_base", "b_arrive"]].mean()
  print(per.round(4).to_string())
  C = g[(g.season == CONFIRM) & (g.week <= 6)]
  cd = (C.b_arrive - C.b_base).mean()
  better = int((per.b_arrive < per.b_base).sum())
  print(f"CONFIRM {CONFIRM} weeks 1-6: {len(C)} games, {cd:+.5f}; seasons better {better}/4")
  ok = e[0] <= -0.002 and e[2] < 0 and better >= 3 and a[2] < 0.0005 and cd < 0
  print("GATE:", "PASS" if ok else "FAIL")


if __name__ == "__main__":
  main()
