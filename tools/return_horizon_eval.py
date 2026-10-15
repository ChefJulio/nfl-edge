"""Lookahead availability beyond the next game (diagnostic, 2026-10-15; owner: "keep going").

Usage: python tools/return_horizon_eval.py
The rest-of-season rankings use returns.lookahead_availability out to week 17: for a player who missed his team's
last game, the return-timing model's chained P(active) in each of his next games. That model was validated on the
NEXT game only (Brier 0.132 vs 0.137). Two questions, walk-forward (fit on seasons before the test season):
  1. Calibration by horizon: mean predicted vs actual P(active) in his k-th next game, k = 1..6.
  2. This week's news: the chain starts from the state after the missed game and ignores this week's practice
     report. Variant: replace the first step with the practice model's P(plays) for that game (the final report;
     production midweek uses the partial-week model), then chain the hazard as usual. Compared on states whose
     next game has a practice row.
"""
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402

import run  # noqa: E402
from nfledge.injuries import practice_features  # noqa: E402
from nfledge.returns import ReturnModel, played_set  # noqa: E402

TEST = [2022, 2023, 2024, 2025]
H = 6
cfg = run.load_config()
data = run.load_all(cfg)
gb = cfg.get("injuries", {})
GB = {"max_iter": int(gb.get("gb_iterations", 200)), "learning_rate": float(gb.get("gb_learning_rate", 0.05)),
      "max_depth": int(gb.get("gb_max_depth", 3))}
AH = data.avail_hist.copy()
m = ReturnModel(data, played_set(data))
ST = m.states(sorted(s for s in data.seasons if s <= max(TEST)))


def chain(model, state: pd.DataFrame, first: np.ndarray | None) -> np.ndarray:
  """returns.ReturnModel.p_active, optionally with the first step's P(back) replaced by `first`."""
  s = state.copy()
  out = np.zeros((len(s), H))
  still = np.ones(len(s))
  for h in range(H):
    p = first if (h == 0 and first is not None) else model.hazard(s)
    out[:, h] = (1 - still) * getattr(model, "stay_active", 1.0) + still * p
    still = still * (1 - p)
    s["missed"] = s.missed + 1
    s["week"] = s.week + 1
    s["missed_x_ir"] = s.missed * (s.desig_ir + s.desig_pup)
    s["report"] = np.where(s.report > 0, 3, 0)
  return out


rows = []
for season in TEST:
  m.fit_frame(ST[ST.season < season])
  t = ST[ST.season == season].reset_index(drop=True)
  base = chain(m, t, None)
  # practice model for the next game (walk-forward), where he's on that week's report
  d = AH[(AH.season < season) & (AH.game_status != "OUT")]
  X = practice_features(d)
  pm = HistGradientBoostingClassifier(**GB, random_state=0).fit(X, d.played)
  ah = AH[AH.season == season].drop_duplicates(["week", "gsis_id"], keep="last").set_index(["week", "gsis_id"])
  first = np.full(len(t), np.nan)
  idx = [(int(w), g) in ah.index for w, g in zip(t.next_week, t.gsis_id)]
  if any(idx):
    sub = ah.loc[[(int(w), g) for (w, g), ok in zip(zip(t.next_week, t.gsis_id), idx) if ok]]
    p = pm.predict_proba(practice_features(sub.reset_index())[list(X.columns)])[:, 1]
    p = np.where(sub.game_status.to_numpy() == "OUT", 0.0, p)
    first[np.array(idx)] = p
  cond = chain(m, t, np.where(np.isnan(first), 0.0, first))
  for i, x in enumerate(t.itertuples()):
    for k in range(1, H + 1):
      lab = m.active_after(season, x.gsis_id, x.team, int(x.week), k)
      if lab is None:
        continue
      rows.append({"season": season, "k": k, "y": float(lab), "base": base[i, k - 1], "has_prac": not np.isnan(first[i]),
                   "cond": cond[i, k - 1] if not np.isnan(first[i]) else np.nan, "missed": int(x.missed),
                   "desig": x.desig, "pos": x.position})
R = pd.DataFrame(rows)
R.to_parquet(ROOT / "cache" / "return_horizon_eval.parquet", index=False)
print("[horizon] 1. calibration by horizon (all states):")
print(R.groupby("k").agg(n=("y", "size"), actual=("y", "mean"), pred=("base", "mean"),
                          brier=("base", lambda s: float(((s - R.loc[s.index, "y"]) ** 2).mean()))).round(3).to_string())
print("[horizon] by designation x horizon (actual / pred):")
g = R.groupby(["desig", "k"]).agg(n=("y", "size"), actual=("y", "mean"), pred=("base", "mean")).round(3)
print(g[g.n >= 100].to_string())
P = R[R.has_prac]
print(f"[horizon] 2. with this week's practice report (n {len(P)}):")
print(P.groupby("k").agg(n=("y", "size"), actual=("y", "mean"), base=("base", "mean"), cond=("cond", "mean"),
                          brier_base=("base", lambda s: float(((s - P.loc[s.index, "y"]) ** 2).mean())),
                          brier_cond=("cond", lambda s: float(((s - P.loc[s.index, "y"]) ** 2).mean()))).round(4).to_string())
