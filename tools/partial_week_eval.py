"""Partial-week practice models (pre-registered in docs/INSIGHTS.md section 9, 2026-10-15).

Usage: python tools/partial_week_eval.py
The availability model is trained on complete report weeks, where "no game status" means the team cleared the
player. Midweek nobody has a game status yet, so it reads every player as cleared: on 2022-24 report weeks it says
86% to play after one practice day (65% did) and 76% after two. Candidate: one model per k = 1, 2 published days,
trained on report weeks truncated to their first k days (no game status, every outcome incl. eventual OUTs).
Walk-forward 2021-25, all 3-day report weeks, both states pooled, vs the current model on the same rows.
Gate: Brier lower with the 95% bootstrap CI excluding 0, lower in >= 4 of 5 seasons, mean predicted within 3 points
of actual for each k.
"""
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402

from nfledge.injuries import practice_features  # noqa: E402

TEST = [2021, 2022, 2023, 2024, 2025]
cfg = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8")).get("injuries", {})
GB = {"max_iter": int(cfg.get("gb_iterations", 200)), "learning_rate": float(cfg.get("gb_learning_rate", 0.05)),
      "max_depth": int(cfg.get("gb_max_depth", 3))}
AH = pd.concat([pd.read_parquet(ROOT / "cache" / f"availhist_{s}.parquet") for s in range(2018, max(TEST) + 1)],
               ignore_index=True)
AH["days"] = AH.days.fillna("")
FULL3 = AH[AH.days.str.len() == 3]


def truncated(d: pd.DataFrame, k: int) -> pd.DataFrame:
  return d.assign(days=d.days.str[:k], game_status="None")


def fit(d: pd.DataFrame):
  X = practice_features(d)
  return HistGradientBoostingClassifier(**GB, random_state=0).fit(X, d.played), list(X.columns)


rows = []
for s in TEST:
  full, fcols = fit(AH[(AH.season < s) & (AH.game_status != "OUT")])  # production's model
  test = FULL3[FULL3.season == s]
  for k in (1, 2):
    part, pcols = fit(truncated(FULL3[FULL3.season < s], k))
    t = truncated(test, k)
    rows.append(pd.DataFrame({"season": s, "k": k, "played": t.played.astype(float).to_numpy(),
                              "base": full.predict_proba(practice_features(t)[fcols])[:, 1],
                              "cand": part.predict_proba(practice_features(t)[pcols])[:, 1], "days": t.days.to_numpy()}))
R = pd.concat(rows, ignore_index=True)
R["sb"], R["sc"] = (R.base - R.played) ** 2, (R.cand - R.played) ** 2
d = (R.sc - R.sb).to_numpy()
rng = np.random.default_rng(0)
boot = np.array([d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)])
lo, hi = np.percentile(boot, [2.5, 97.5])
per = R.groupby("season")[["sb", "sc"]].mean()
cal = R.groupby("k").agg(n=("played", "size"), actual=("played", "mean"), cand=("cand", "mean"), base=("base", "mean"),
                         brier_base=("sb", "mean"), brier_cand=("sc", "mean"))
print("[partial] Brier by season:\n", per.round(4).to_string())
print("[partial] by k:\n", cal.round(4).to_string())
print(f"[partial] pooled Brier base {R.sb.mean():.4f} cand {R.sc.mean():.4f} diff {d.mean():+.4f} [{lo:+.4f}, {hi:+.4f}] "
      f"seasons better {(per.sc < per.sb).sum()}/{len(per)}")
ok = hi < 0 and (per.sc < per.sb).sum() >= 4 and ((cal.cand - cal.actual).abs() <= 0.03).all()
print("[partial] GATE:", "PASS" if ok else "FAIL")
print("[partial] by sequence (n >= 150):\n", R.groupby(["k", "days"]).agg(n=("played", "size"), actual=("played", "mean"),
      base=("base", "mean"), cand=("cand", "mean")).query("n >= 150").round(3).to_string())
