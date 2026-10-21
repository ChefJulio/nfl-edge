"""(BY) Team-specific home field (pre-registered 2026-10-20, docs/INSIGHTS.md (BY)).

Usage: python tools/hfa_eval.py
BASE = home + rank gap + Elo + lineup; TEAM = BASE + home x team (32 indicators, L2-shrunk toward 0 = the league term;
the penalty chosen by leave-one-season-out within the training seasons). Walk-forward, scored 2022-25.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402

TEST, CONFIRM = [2022, 2023, 2024, 2025], 2026
BASE = ["home", "gap", "elo", "lineup"]


def fit_team(tr: pd.DataFrame, teams: list, lam: float):
  """Logistic with BASE unpenalized (scaled up so the L2 barely touches them) and team-home terms penalized."""
  X = np.c_[tr[BASE].to_numpy() * 100.0, np.stack([(tr.home_team == t).to_numpy() * tr.home.to_numpy() for t in teams], 1)]
  m = LogisticRegression(C=1.0 / lam, fit_intercept=False, max_iter=5000).fit(X, tr.y)
  return m


def design(d: pd.DataFrame, teams: list) -> np.ndarray:
  return np.c_[d[BASE].to_numpy() * 100.0, np.stack([(d.home_team == t).to_numpy() * d.home.to_numpy() for t in teams], 1)]


def main():
  g = pd.read_parquet(ROOT / "cache" / "vegas_prior_eval.parquet")
  L = pd.read_parquet(ROOT / "cache" / "lineup_rows.parquet").set_index(["game_id", "team"]).report_rapm_OFF
  g["lineup"] = [L.get((i, h), np.nan) - L.get((i, a), np.nan) for i, h, a in zip(g.game_id, g.home_team, g.away_team)]
  g = g.dropna(subset=["lineup"]).copy()
  teams = sorted(g.home_team.unique())
  for s in TEST + [CONFIRM]:
    tr, te = g[g.season < s], g.season == s
    g.loc[te, "base"] = LogisticRegression(C=1e6, fit_intercept=False, max_iter=3000).fit(tr[BASE], tr.y).predict_proba(g.loc[te, BASE])[:, 1]
    best, bl = None, np.inf
    for lam in (0.3, 1.0, 3.0, 10.0, 30.0):
      loss = []
      for v in sorted(tr.season.unique()):
        a, b = tr[tr.season != v], tr[tr.season == v]
        if a.season.nunique() < 1 or not len(b):
          continue
        p = fit_team(a, teams, lam).predict_proba(design(b, teams))[:, 1]
        loss.append(np.mean((p - b.y) ** 2))
      if loss and np.mean(loss) < bl:
        best, bl = lam, np.mean(loss)
    best = best if best is not None else 3.0  # one training season (2021 for 2022): no left-out season to choose with
    m = fit_team(tr, teams, best)
    g.loc[te, "team"] = m.predict_proba(design(g[te], teams))[:, 1]
    if s == TEST[-1]:
      hf = pd.Series(m.coef_[0][len(BASE):], index=teams).sort_values()
      print(f"  (fit for {s}, penalty {best}) largest home edges beyond the league's: {hf.tail(4).round(3).to_dict()}; smallest {hf.head(3).round(3).to_dict()}")
  for arm in ("base", "team"):
    g[f"b_{arm}"] = (g[arm] - g.y) ** 2
  T = g[g.season.isin(TEST)]
  d = (T.b_team - T.b_base).to_numpy()
  bt = d[np.random.default_rng(0).integers(0, len(d), (2000, len(d)))].mean(1)
  lo, hi = np.percentile(bt, [2.5, 97.5])
  per = T.groupby("season")[["b_base", "b_team"]].mean()
  better = int((per.b_team < per.b_base).sum())
  C = g[g.season == CONFIRM]
  cd = (C.b_team - C.b_base).mean()
  print(f"(BY) {len(T)} games 2022-25: base {T.b_base.mean():.4f} team {T.b_team.mean():.4f}, {d.mean():+.5f} [{lo:+.5f}, {hi:+.5f}], "
        f"better {better}/4, 2026 {cd:+.5f}")
  print("GATE:", "PASS" if d.mean() <= -0.001 and hi < 0 and better >= 3 and cd < 0 else "FAIL")


if __name__ == "__main__":
  main()
