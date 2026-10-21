"""(BQ) Mismatch calibration: stretch the rank gap at the extremes (pre-registered 2026-10-20, docs/INSIGHTS.md (BQ)).

Usage: python tools/mismatch_eval.py     (needs cache/vegas_prior_eval.parquet with ranks, cache/lineup_rows.parquet)
Matchups win chance as of the game's week, production's form (no intercept), walk-forward, scored 2022-25:
  BASE  = home + rank gap + Elo + lineup (offense)        QRANK = home + z gap + Elo + lineup
  z = Phi^-1((32.5 - rank) / 32), gap = z_home - z_away.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import norm  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402

TEST, CONFIRM = [2022, 2023, 2024, 2025], 2026


def main():
  g = pd.read_parquet(ROOT / "cache" / "vegas_prior_eval.parquet")
  L = pd.read_parquet(ROOT / "cache" / "lineup_rows.parquet").set_index(["game_id", "team"]).report_rapm_OFF
  g["lineup"] = [L.get((i, h), np.nan) - L.get((i, a), np.nan) for i, h, a in zip(g.game_id, g.home_team, g.away_team)]
  g = g.dropna(subset=["lineup", "rk_h", "rk_a"]).copy()
  z = lambda r: norm.ppf((32.5 - r) / 32)  # noqa: E731
  g["zgap"] = z(g.rk_h) - z(g.rk_a)
  g["netgap"] = g.net_h - g.net_a
  ml = lambda m: np.where(m > 0, 100 / (m + 100), -m / (-m + 100))  # noqa: E731
  ph, pa = ml(g.ml_h), ml(g.ml_a)
  g["vegas"] = ph / (ph + pa)
  arms = {"base": ["home", "gap", "elo", "lineup"], "qrank": ["home", "zgap", "elo", "lineup"],
          "both": ["home", "gap", "zgap", "elo", "lineup"], "net": ["home", "netgap", "elo", "lineup"]}
  for s in TEST + [CONFIRM]:
    tr, te = g.season < s, g.season == s
    for arm, cols in arms.items():
      m = LogisticRegression(C=1e6, fit_intercept=False, max_iter=3000).fit(g.loc[tr, cols], g.loc[tr, "y"])
      g.loc[te, arm] = m.predict_proba(g.loc[te, cols])[:, 1]
  for arm in list(arms) + ["vegas"]:
    g[f"b_{arm}"] = (g[arm] - g.y) ** 2
  T = g[g.season.isin(TEST)]
  rng = np.random.default_rng(0)
  print(f"(BQ) {len(T)} games 2022-25; Brier: " + "  ".join(f"{a} {T[f'b_{a}'].mean():.4f}" for a in list(arms) + ["vegas"]))
  res = {}
  for arm in ("qrank", "both", "net"):
    d = (T[f"b_{arm}"] - T.b_base).to_numpy()
    bt = d[rng.integers(0, len(d), (2000, len(d)))].mean(1)
    res[arm] = (d.mean(), *np.percentile(bt, [2.5, 97.5]))
    print(f"  {arm:6s} - base {res[arm][0]:+.5f} [{res[arm][1]:+.5f}, {res[arm][2]:+.5f}]{'   <- gate' if arm == 'qrank' else ''}")
  per = T.groupby("season")[["b_base", "b_qrank", "b_vegas"]].mean()
  print(per.round(4).to_string())

  def calib(col):
    fav = np.maximum(T[col], 1 - T[col])
    won = np.where(T[col] >= 0.5, T.y, 1 - T.y)
    rows = []
    for lo, hi in ((.5, .6), (.6, .7), (.7, .8), (.8, 1.01)):
      m = (fav >= lo) & (fav < hi)
      rows.append({"band": f"{lo:.0%}-{min(hi, 1):.0%}", "n": int(m.sum()), "said": round(float(fav[m].mean()), 3), "won": round(float(won[m].mean()), 3)})
    return pd.DataFrame(rows)

  for arm in ("base", "qrank"):
    print(f"calibration {arm}:\n{calib(arm).to_string(index=False)}")
  gap70 = {}
  for arm in ("base", "qrank"):
    fav = np.maximum(T[arm], 1 - T[arm])
    won = np.where(T[arm] >= 0.5, T.y, 1 - T.y)
    m = fav >= 0.7
    gap70[arm] = abs(float(won[m].mean() - fav[m].mean()))
  print(f"70%+ calibration gap: base {gap70['base']:.3f}, qrank {gap70['qrank']:.3f}")
  C = g[g.season == CONFIRM]
  cd = (C.b_qrank - C.b_base).mean()
  better = int((per.b_qrank < per.b_base).sum())
  m_, lo, hi = res["qrank"]
  print(f"CONFIRM {CONFIRM}: {len(C)} games, qrank - base {cd:+.5f}; seasons better {better}/4")
  ok = m_ <= -0.001 and hi < 0 and better >= 3 and gap70["qrank"] < gap70["base"] and cd < 0
  print("GATE:", "PASS" if ok else "FAIL")


if __name__ == "__main__":
  main()
