"""Unified lookahead availability (pre-registered in docs/INSIGHTS.md section 9, 2026-10-15). See tools/ros_avail_model.py.

Usage: python tools/ros_avail_eval.py
Decision seasons 2020-25 (weeks 2-16), test 2022-25, each trained on decision seasons before it; the practice and
return models inside the features are walk-forward too. Evaluated on k = 2..12 with the game in week <= 17.
Gate: (i) pooled Brier lower, 95% bootstrap CI (2,000 player-season resamples) excluding 0, >= 3 of 4 seasons;
(ii) mean predicted within 3 points of actual for each k, and for each group (return state / on report only /
neither); (iii) the Hurts group (on report, this-week P < 0.5, not in a state) within 5 points.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import run  # noqa: E402
import ros_avail_model as RA  # noqa: E402  (tools/)

DECIDE = [2022, 2023, 2024, 2025]  # v3: post-COVID training (INSIGHTS sec. 9)
TEST = [2023, 2024, 2025]
cfg = run.load_config()
data = run.load_all(cfg)
g = cfg.get("injuries", {})
GB = {"max_iter": int(g.get("gb_iterations", 200)), "learning_rate": float(g.get("gb_learning_rate", 0.05)),
      "max_depth": int(g.get("gb_max_depth", 3))}

ALL = RA.training_rows(data, GB, DECIDE, ROOT / "cache")  # shared with production (cached per season)
print(f"[ros-avail] {len(ALL)} rows, {ALL.groupby(['season', 'week', 'gsis_id']).ngroups} decision points", flush=True)

out = []
for s in TEST:
  tr = ALL[ALL.season < s]
  m = RA.fit(tr, GB)
  te = ALL[(ALL.season == s) & (ALL.k >= 2) & (ALL.game_week <= 17)].copy()
  te["var"] = m.predict_proba(te[RA.FEATS])[:, 1]
  te["base"] = RA.baseline(te)
  out.append(te)
R = pd.concat(out, ignore_index=True)
R["grp"] = np.where(R.in_state > 0, "state", np.where(R.on_rep > 0, "report", "neither"))
R["sb"], R["sv"] = (R.base - R.y) ** 2, (R["var"] - R.y) ** 2
R["ps"] = R.season.astype(str) + "-" + R.gsis_id
ep = R.groupby("ps").agg(sb=("sb", "sum"), sv=("sv", "sum"), n=("y", "size"))
rng = np.random.default_rng(0)
boot = []
for _ in range(2000):
  e = ep.iloc[rng.integers(0, len(ep), len(ep))]
  boot.append((e.sv.sum() - e.sb.sum()) / e.n.sum())
lo, hi = np.percentile(boot, [2.5, 97.5])
per = R.groupby("season")[["sb", "sv"]].mean()
print(f"[ros-avail] pooled Brier base {R.sb.mean():.4f} variant {R.sv.mean():.4f} diff {R.sv.mean() - R.sb.mean():+.4f} "
      f"[{lo:+.4f}, {hi:+.4f}], seasons better {(per.sv < per.sb).sum()}/{len(per)}")
print(per.round(4).to_string())
byk = R.groupby("k").agg(n=("y", "size"), actual=("y", "mean"), var=("var", "mean"), base=("base", "mean"))
byg = R.groupby("grp").agg(n=("y", "size"), actual=("y", "mean"), var=("var", "mean"), base=("base", "mean"))
hurts = R[(R.on_rep > 0) & (R.p_now < 0.5) & (R.in_state == 0)]
print("[ros-avail] by k:\n", byk.round(3).to_string())
print("[ros-avail] by group:\n", byg.round(3).to_string())
print(f"[ros-avail] Hurts group n {len(hurts)}: actual {hurts.y.mean():.3f} variant {hurts['var'].mean():.3f} base {hurts.base.mean():.3f}")
R["role"] = pd.cut(R.snap3, [-0.01, 0.3, 0.7, 1.01], labels=["low", "mid", "starter"])
R["kb"] = pd.cut(R.k, [1, 4, 8, 12], labels=["2-4", "5-8", "9-12"])
cell = R.groupby(["pos", "role", "kb"], observed=True).agg(n=("y", "size"), actual=("y", "mean"), var=("var", "mean"))
cell = cell[cell.n >= 300]
cell["gap"] = 100 * (cell["var"] - cell.actual)
print("[ros-avail] (iv) position x role x k cells (n >= 300):")
print(cell.round(3).to_string())
ok = ((cell.gap.abs() <= 5).all() and hi < 0 and (per.sv < per.sb).sum() >= 2 and ((byk["var"] - byk.actual).abs() <= 0.03).all()
      and ((byg["var"] - byg.actual).abs() <= 0.03).all() and abs(hurts["var"].mean() - hurts.y.mean()) <= 0.05)
print("[ros-avail] GATE:", "PASS" if ok else "FAIL")
R.to_parquet(ROOT / "cache" / "ros_avail_eval.parquet", index=False)
