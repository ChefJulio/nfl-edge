"""(DK) D/ST projections for 3-and-outs, 4th-down stops and special-teams fumbles (pre-registered 2026-10-25,
docs/INSIGHTS.md). Walk-forward 2023-25, weeks 3+ (as tools/dst_eval.py): rates from games before the week.

GATE per new stat: (1) mean projection within 10% of the mean actual; (2) MAE lower than the league rate's (a
constant). A stat failing (2) ships as the league rate. (3) The owner's Sleeper scoring (with these four): D/ST points
MAE lower with the new stats projected than without them (0).

  python tools/dk_eval.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.defenses import PBP_STATS, DefenseModel, actual_line, load_games, score  # noqa: E402
from nfledge.kickers import implied_points  # noqa: E402

TEST = [2023, 2024, 2025]
# the owner's Sleeper league (1389722050909732864), its D/ST settings, the four new ones included
OWNER = {"sack": 1, "int": 2, "fum_rec": 1, "ff": 1, "def_td": 6, "st_td": 6, "safe": 4, "blk": 3, "pass_def": 0.25,
         "tkl_loss": 0.5, "forced_punts": 0.5, "def_2pt": 4, "pts_allow": -0.1, "yds_allow": -0.01,
         "three_out": 0.5, "fourth_stop": 0.5, "st_ff": 1, "st_fum_rec": 1}
c = D.Cache(ROOT / "cache")
sched = c.get("schedules", "since1999", None, stale=False)
G = load_games(c, list(range(2021, 2026)), sched)
IMP = implied_points(sched)
imp_ix = IMP.set_index(["season", "week", "team"]).implied
print("[dk] per defense-game, 2021-25: " + ", ".join(f"{s} {G[s].mean():.3f}" for s in PBP_STATS))
rows = []
for s in TEST:
  for w in range(3, 19):
    te = G[(G.season == s) & (G.week == w)]
    if te.empty:
      continue
    tr = G[((G.season >= s - 2) & (G.season < s)) | ((G.season == s) & (G.week < w))]
    m = DefenseModel().fit(tr, IMP[IMP.season.between(s - 2, s)])
    for x in te.itertuples():
      key = (s, w, x.opponent_team)
      if key not in imp_ix.index or pd.isna(x.pa):
        continue
      ln = m.line(x.team, x.opponent_team, float(imp_ix[key]), (s, w))
      act = actual_line(x)
      r = {"season": s, "week": w, "a_own": score(act, OWNER), "m_own": score(ln, OWNER),
           "m_own0": score({**ln, **{k: 0.0 for k in PBP_STATS}}, OWNER)}
      for k in PBP_STATS:
        r[f"a_{k}"], r[f"m_{k}"], r[f"l_{k}"] = getattr(x, k), ln[k], m.league[k]
      rows.append(r)
R = pd.DataFrame(rows)
print(f"[dk] {len(R):,} defense-games, {TEST[0]}-{TEST[-1]} weeks 3+")
ok = {}
for k in PBP_STATS:
  a, mm, lg = R[f"a_{k}"], R[f"m_{k}"], R[f"l_{k}"]
  cal = abs(mm.mean() - a.mean()) <= 0.10 * max(a.mean(), 1e-9)
  em, el = (mm - a).abs().mean(), (lg - a).abs().mean()
  ok[k] = (cal, em < el)
  print(f"  {k:11s} actual {a.mean():.3f}  model {mm.mean():.3f} (1) {cal} | MAE model {em:.4f} vs league rate {el:.4f} (2) {em < el}"
        f" | corr {np.corrcoef(mm, a)[0, 1]:.3f}")
e1, e0 = (R.m_own - R.a_own).abs(), (R.m_own0 - R.a_own).abs()
d = (e1 - e0).to_numpy()
g = (R.season.astype(str) + "-" + R.week.astype(str)).to_numpy()
gs = pd.DataFrame({"d": d, "g": g}).groupby("g").d.agg(["sum", "size"])
idx = np.random.default_rng(0).integers(0, len(gs), (2000, len(gs)))
bt = gs["sum"].to_numpy()[idx].sum(1) / gs["size"].to_numpy()[idx].sum(1)
lo, hi = np.percentile(bt, [2.5, 97.5])
g3 = e1.mean() < e0.mean()
print(f"[dk] (3) owner's scoring: MAE {e0.mean():.3f} without -> {e1.mean():.3f} with, {d.mean():+.3f} [{lo:+.3f}, {hi:+.3f}]"
      f"; mean actual {R.a_own.mean():.2f}, projected {R.m_own.mean():.2f} (was {R.m_own0.mean():.2f}) -> {g3}")
print("[dk] GATE: " + "  ".join(f"{k} (1) {v[0]} (2) {v[1]}" for k, v in ok.items()) + f"  (3) {g3}")
