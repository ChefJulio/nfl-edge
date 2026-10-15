"""Re-runs the hybrid's pre-registered 2021-22 check through the production code (nfledge/return_timing.py), so what
ships is what passed (docs/INSIGHTS.md section 9). Usage: python tools/return_timing_check.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import run  # noqa: E402
from nfledge import return_timing as RT  # noqa: E402
from nfledge.returns import POS_GROUP, ReturnModel, played_set  # noqa: E402

cfg = run.load_config()
data = run.load_all(cfg)
g = cfg.get("injuries", {})
GB = {"max_iter": int(g.get("gb_iterations", 200)), "learning_rate": float(g.get("gb_learning_rate", 0.05)),
      "max_depth": int(g.get("gb_max_depth", 3))}
played = played_set(data)
base = ReturnModel(data, played)
ST0 = base.states(sorted(data.seasons))
XK = RT.training_rows(data, base, GB, list(range(RT.FIRST_SEASON, 2026)), ROOT / "cache")
rows = []
for season in (2021, 2022):
  m = RT.fit(XK[XK.season < season])
  b = ReturnModel(data, played); b._nxt = base._nxt; b.fit_frame(ST0[ST0.season < season])
  te = XK[(XK.season == season) & XK.position.map(POS_GROUP).isin(["QB", "RB", "WR", "TE"])]
  src = te.drop_duplicates("src").set_index("src")
  st = src.drop(columns=["k", "y", "impossible"])
  pb = b.p_active(st.reset_index(drop=True), RT.H, first=st.p_now.to_numpy(), stay=1.0)
  pv = RT.predict(m, st.reset_index(drop=True), RT.H)
  pos = {s: j for j, s in enumerate(st.index)}
  te = te.assign(base=[pb[pos[s], k - 1] for s, k in zip(te.src, te.k)], new=[pv[pos[s], k - 1] for s, k in zip(te.src, te.k)])
  te["hybrid"] = np.where(te.desig == "ir", te.new, te.base)
  te["ep"] = te.season.astype(str) + "-" + te.gsis_id + "-" + (te.week - te.missed).astype(int).astype(str)
  rows.append(te)
R = pd.concat(rows)
IR = R[R.desig == "ir"].copy()
IR["sb"], IR["sv"] = (IR.base - IR.y) ** 2, (IR.hybrid - IR.y) ** 2
e = IR.groupby("ep").agg(sb=("sb", "sum"), sv=("sv", "sum"), n=("y", "size"))
rng = np.random.default_rng(0)
boot = [(lambda z: (z.sv.sum() - z.sb.sum()) / z.n.sum())(e.iloc[rng.integers(0, len(e), len(e))]) for _ in range(2000)]
lo, hi = np.percentile(boot, [2.5, 97.5])
per = IR.groupby("season")[["sb", "sv"]].mean()
IR["kb"] = pd.cut(IR.k, [0, 2, 4, 8], labels=["1-2", "3-4", "5-8"])
c = IR.groupby("kb", observed=True).agg(n=("y", "size"), actual=("y", "mean"), chain=("base", "mean"), hybrid=("hybrid", "mean"))
print(f"[rt-check] IR rows {len(IR)}: Brier chain {IR.sb.mean():.4f} hybrid {IR.sv.mean():.4f} [{lo:+.4f}, {hi:+.4f}], "
      f"seasons better {(per.sv < per.sb).sum()}/2")
print(c.round(3).to_string())
ok = hi < 0 and (per.sv < per.sb).all() and ((c.hybrid - c.actual).abs() <= 0.05).all()
print("[rt-check] GATE (as pre-registered):", "PASS" if ok else "FAIL")
