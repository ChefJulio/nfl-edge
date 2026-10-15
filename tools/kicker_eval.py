"""Kicker projections vs the kicker's season-to-date average (pre-registered, docs/INSIGHTS.md section 9, 2026-10-15).

Usage: python tools/kicker_eval.py
Walk-forward 2021-25, weeks 3+: for each week, fit nfledge.kickers.KickerModel on the two prior seasons + this
season before the week, project every kicker who kicked (his team, the game's Vegas implied total), score both
with standard scoring (FG 3 / 4 at 40-49 / 5 at 50+, PAT 1, misses -1). Baseline: his season-to-date average
(>= 2 prior games). Gate: MAE lower, 95% CI over season-weeks excluding 0, better in >= 3 of 5 seasons.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.kickers import STANDARD, KickerModel, implied_points, load_kicks, score  # noqa: E402

TEST = [2021, 2022, 2023, 2024, 2025]
c = D.Cache(ROOT / "cache")
K = load_kicks(c, list(range(2019, 2026)))
sched = c.get("schedules", "since1999", None, stale=False)
IMP = implied_points(sched)
K["pts"] = [score(r, STANDARD) for r in K[[*STANDARD]].to_dict("records")]
rows = []
for s in TEST:
  for w in range(3, 19):
    tr = K[((K.season >= s - 2) & (K.season < s)) | ((K.season == s) & (K.week < w))]
    te = K[(K.season == s) & (K.week == w)]
    if te.empty:
      continue
    m = KickerModel().fit(tr, IMP)
    imp = IMP[(IMP.season == s) & (IMP.week == w)].set_index("team").implied
    prior = K[(K.season == s) & (K.week < w)]
    for x in te.itertuples():
      hist = prior[prior.player_id == x.player_id]
      if len(hist) < 2 or x.team not in imp.index:
        continue
      proj = score(m.line(x.player_id, x.team, float(imp[x.team])), STANDARD)
      rows.append({"season": s, "week": w, "kicker": x.player_display_name, "actual": x.pts, "model": proj, "base": hist.pts.mean()})
R = pd.DataFrame(rows)
R["em"], R["eb"] = (R.model - R.actual).abs(), (R.base - R.actual).abs()
d = (R.em - R.eb).to_numpy()
g = (R.season.astype(str) + "-" + R.week.astype(str)).to_numpy()
gs = pd.DataFrame({"d": d, "g": g}).groupby("g").d.agg(["sum", "size"])
s_, c_ = gs["sum"].to_numpy(), gs["size"].to_numpy()
idx = np.random.default_rng(0).integers(0, len(gs), (2000, len(gs)))
bt = s_[idx].sum(1) / c_[idx].sum(1)
lo, hi = np.percentile(bt, [2.5, 97.5])
per = R.groupby("season")[["em", "eb"]].mean()
print(f"[kickers] {len(R)} kicker-games: MAE model {R.em.mean():.3f} vs season average {R.eb.mean():.3f}, diff {d.mean():+.3f} [{lo:+.3f}, {hi:+.3f}], "
      f"seasons better {(per.em < per.eb).sum()}/{len(per)}")
print(per.round(3).to_string())
print(f"[kickers] mean actual {R.actual.mean():.2f}, model {R.model.mean():.2f}, baseline {R.base.mean():.2f}; corr model {R[['model', 'actual']].corr().iloc[0, 1]:.3f} base {R[['base', 'actual']].corr().iloc[0, 1]:.3f}")
ok = hi < 0 and (per.em < per.eb).sum() >= 3
print("[kickers] GATE:", "PASS (ship the model)" if ok else "FAIL (ship the season average)")
