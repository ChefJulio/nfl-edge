"""(DU) QB-change kinds in the Matchups win chance (pre-registered 2026-10-29, docs/INSIGHTS.md).

Usage: python tools/qb_kind_eval.py   (needs (DS)'s caches: cache/vegas_prior_eval.parquet, lineup_rows.parquet,
                                       playoff_odds_weekly.parquet; builds the kinds from the play-by-play, ~2 min)
FULL = production's form (tools/ablation_eval.py); QBK = FULL + home-minus-away flags for backup in / new arrival /
inexperienced / starter back (tools/qb_swing_eval.team_games, (BB)'s kinds).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402

from nfledge.config import load_config  # noqa: E402
from qb_swing_eval import team_games  # noqa: E402

TEST, CONFIRM = [2022, 2023, 2024, 2025], 2026
BASE = ["home", "gap", "elo", "lineup"]
KINDS = ["backup in", "new arrival", "inexperienced", "starter back"]
KCOL = {k: "k_" + k.replace(" ", "_") for k in KINDS}


def main():
  settled_w = float(load_config()["report"]["win_model"].get("final_week_settled", 0))
  g = pd.read_parquet(ROOT / "cache" / "vegas_prior_eval.parquet")
  L = pd.read_parquet(ROOT / "cache" / "lineup_rows.parquet").set_index(["game_id", "team"]).report_rapm_OFF
  g["lineup"] = [L.get((i, h), np.nan) - L.get((i, a), np.nan) for i, h, a in zip(g.game_id, g.home_team, g.away_team)]
  g = g.dropna(subset=["lineup"]).copy()
  o = pd.read_parquet(ROOT / "cache" / "playoff_odds_weekly.parquet").set_index(["season", "week", "team"])
  settled = ((o.p_playoffs >= 0.99) & ((o.p_bye >= 0.99) | (o.p_bye <= 0.01))).astype(float)
  g["settled"] = np.where(g.week == 18, np.array([settled.get((s, w, h), 0.0) - settled.get((s, w, a), 0.0)
                                                  for s, w, h, a in zip(g.season, g.week, g.home_team, g.away_team)]), 0.0)
  ml = lambda m: np.where(m > 0, 100 / (m + 100), -m / (-m + 100))  # noqa: E731
  ph, pa = ml(g.ml_h), ml(g.ml_a)
  g["vegas"] = ph / (ph + pa)

  tg = team_games()
  kind = dict(zip(zip(tg.game_id, tg.team), tg.kind))
  g["kh"] = [kind.get((i, h), "same") for i, h in zip(g.game_id, g.home_team)]
  g["ka"] = [kind.get((i, a), "same") for i, a in zip(g.game_id, g.away_team)]
  for k, c in KCOL.items():
    g[c] = (g.kh == k).astype(float) - (g.ka == k).astype(float)
  g["qbchg"] = g.kh.isin(KINDS) | g.ka.isin(KINDS)

  arms = {"FULL": BASE, "QBK": BASE + list(KCOL.values())}
  for s in TEST + [CONFIRM]:
    tr, te = g.season < s, g.season == s
    for arm, cols in arms.items():
      m = LogisticRegression(C=1e6, fit_intercept=False, max_iter=3000).fit(g.loc[tr, cols], g.loc[tr, "y"])
      z = g.loc[te, cols].to_numpy(float) @ m.coef_[0] + settled_w * g.loc[te, "settled"].to_numpy()
      g.loc[te, arm] = 1 / (1 + np.exp(-z))
  for arm in list(arms) + ["vegas"]:
    g[f"b_{arm}"] = (g[arm] - g.y) ** 2
  T, C = g[g.season.isin(TEST)], g[g.season == CONFIRM]

  # diagnostic: each kind's bias from that team's side (FULL)
  print(f"(DU) {len(T)} games 2022-25; QB-change games {int(T.qbchg.sum())} ({T.qbchg.mean():.1%})")
  print("  bias by kind (FULL, from that team's side): chance - result, chance - Vegas")
  for k in ["same"] + KINDS:
    side = [(r.FULL, r.y, r.vegas) for r in T.itertuples() if r.kh == k] + [(1 - r.FULL, 1 - r.y, 1 - r.vegas) for r in T.itertuples() if r.ka == k]
    if not side:
      continue
    a = np.array(side)
    e = a[:, 0] - a[:, 1]
    print(f"    {k:14s} {len(a):5d} team-games   chance - result {e.mean():+.3f} +- {1.96 * e.std() / np.sqrt(len(a)):.3f}   "
          f"chance - Vegas {(a[:, 0] - a[:, 2]).mean():+.3f}")
  rng = np.random.default_rng(0)

  def cmp(D, label):
    d = (D.b_QBK - D.b_FULL).to_numpy()
    bt = d[rng.integers(0, len(d), (2000, len(d)))].mean(1)
    lo, hi = np.percentile(bt, [2.5, 97.5])
    print(f"  {label:26s} n {len(D):5d}  FULL {D.b_FULL.mean():.4f}  QBK {D.b_QBK.mean():.4f}  Vegas {D.b_vegas.mean():.4f}  "
          f"QBK - FULL {d.mean():+.5f} [{lo:+.5f}, {hi:+.5f}]")
    return d.mean(), lo, hi
  print("  scores:")
  dq, lq, hq = cmp(T[T.qbchg], "QB-change games 2022-25")
  da, la, ha = cmp(T, "all games 2022-25")
  per = T[T.qbchg].groupby("season")[["b_FULL", "b_QBK"]].mean()
  better = int((per.b_QBK < per.b_FULL).sum())
  CC = C[C.qbchg]
  c26 = (CC.b_QBK - CC.b_FULL).mean() if len(CC) else float("nan")
  print(f"  QB-change games better in {better}/4 seasons; 2026 QB-change games ({len(CC)}) {c26:+.5f}")
  ok = dq <= -0.002 and hq < 0 and ha < 0.0005 and better >= 3 and c26 < 0
  print(f"  GATE: {'PASS' if ok else 'FAIL'}")
  F = g[g.season <= 2025]
  m = LogisticRegression(C=1e6, fit_intercept=False, max_iter=3000).fit(F[arms["QBK"]], F.y)
  print(f"  weights (fit 2021-25, log-odds, reading only): {dict(zip(KINDS, m.coef_[0][len(BASE):].round(3)))}")


if __name__ == "__main__":
  main()
