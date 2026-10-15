"""D/ST projections vs the defense's season-to-date average (pre-registered, docs/INSIGHTS.md section 9, 2026-10-15).

Usage: python tools/dst_eval.py
Walk-forward 2021-25, weeks 3+: rates from games before the week, distribution fits on the two prior seasons +
the season so far; opponent implied points from the Vegas lines. Scored on ESPN standard D/ST scoring (gated) and
the owner's Sleeper per-point / per-yard scoring (reported). Gate: MAE lower, 95% CI over season-weeks excluding 0,
>= 3 of 5 seasons.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.defenses import ESPN_STD, DefenseModel, actual_line, load_games, score  # noqa: E402
from nfledge.kickers import implied_points  # noqa: E402

TEST = [2021, 2022, 2023, 2024, 2025]
# the owner's Sleeper league (1389722050909732864) D/ST settings that we project
OWNER = {"sack": 1, "int": 2, "fum_rec": 1, "ff": 1, "def_td": 6, "st_td": 6, "safe": 4, "blk": 3, "pass_def": 0.25,
         "tkl_loss": 0.5, "forced_punts": 0.5, "def_2pt": 4, "pts_allow": -0.1, "yds_allow": -0.01}
c = D.Cache(ROOT / "cache")
sched = c.get("schedules", "since1999", None, stale=False)
G = load_games(c, list(range(2019, 2026)), sched)
IMP = implied_points(sched)
G["std"] = [score(actual_line(r), ESPN_STD) for r in G.itertuples()]
G["own"] = [score(actual_line(r), OWNER) for r in G.itertuples()]
imp_ix = IMP.set_index(["season", "week", "team"]).implied
rows = []
for s in TEST:
  for w in range(3, 19):
    te = G[(G.season == s) & (G.week == w)]
    if te.empty:
      continue
    tr = G[((G.season >= s - 2) & (G.season < s)) | ((G.season == s) & (G.week < w))]
    m = DefenseModel().fit(tr, IMP[IMP.season.between(s - 2, s)])
    prior = G[(G.season == s) & (G.week < w)]
    for x in te.itertuples():
      hist = prior[prior.team == x.team]
      key = (s, w, x.opponent_team)
      if len(hist) < 2 or key not in imp_ix.index or pd.isna(x.pa):
        continue
      ln = m.line(x.team, x.opponent_team, float(imp_ix[key]), (s, w))
      rows.append({"season": s, "week": w, "team": x.team, "a_std": x.std, "m_std": score(ln, ESPN_STD), "b_std": hist["std"].mean(),
                   "a_own": x.own, "m_own": score(ln, OWNER), "b_own": hist["own"].mean()})
R = pd.DataFrame(rows)


def report(tag, a, m, b, gate):
  em, eb = (R[m] - R[a]).abs(), (R[b] - R[a]).abs()
  d = (em - eb).to_numpy()
  g = (R.season.astype(str) + "-" + R.week.astype(str)).to_numpy()
  gs = pd.DataFrame({"d": d, "g": g}).groupby("g").d.agg(["sum", "size"])
  s_, c_ = gs["sum"].to_numpy(), gs["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(gs), (2000, len(gs)))
  bt = s_[idx].sum(1) / c_[idx].sum(1)
  lo, hi = np.percentile(bt, [2.5, 97.5])
  per = pd.DataFrame({"season": R.season, "em": em, "eb": eb}).groupby("season").mean()
  print(f"[dst {tag}] {len(R)} defense-games: MAE model {em.mean():.3f} vs season average {eb.mean():.3f}, diff {d.mean():+.3f} "
        f"[{lo:+.3f}, {hi:+.3f}], seasons better {(per.em < per.eb).sum()}/{len(per)}; mean actual {R[a].mean():.2f} model {R[m].mean():.2f} "
        f"base {R[b].mean():.2f}; corr model {np.corrcoef(R[m], R[a])[0, 1]:.3f} base {np.corrcoef(R[b], R[a])[0, 1]:.3f}")
  print(per.round(3).to_string())
  if gate:
    print("[dst] GATE:", "PASS (ship the model)" if hi < 0 and (per.em < per.eb).sum() >= 3 else "FAIL (ship the season average)")


report("ESPN standard", "a_std", "m_std", "b_std", True)
report("owner Sleeper", "a_own", "m_own", "b_own", False)
