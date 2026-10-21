"""(BT2) Final-week "settled" teams, confirmed on 2002-19 (pre-registered 2026-10-20, docs/INSIGHTS.md (BT2)).

Usage: python tools/stakes_final_eval.py
Last regular-season week of 2002-2019: settled = P(playoffs) >= .99 and P(bye) >= .99 or <= .01 from the playoff
simulation before that week (Elo ranks, no lines, 2,000 seasons). Base = home + Elo gap; STAKES = base + settled gap.
Leave-one-season-out logistic (production's form, no intercept).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402

import playoff_odds as PO  # noqa: E402
from nfledge import elo  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.standings import RELOCATED  # noqa: E402

SEASONS = list(range(2002, 2020))


def main():
  cfg = load_config()
  wm, drift = cfg["report"]["win_model"], float(cfg["report"].get("playoff_drift", 0.0))
  sched = pd.read_parquet(ROOT / "cache" / "schedules_since1999.parquet")
  teams = pd.read_parquet(ROOT / "cache" / "teams_all.parquet")
  rows = []
  for s in SEASONS:
    reg = sched[(sched.season == s) & (sched.game_type == "REG")]
    wk = int(reg.week.max())
    el = elo.ratings_before(sched, s, wk, wm)
    mapped = {RELOCATED.get(t, t): v for t, v in el.items()}
    rk = pd.Series(mapped).rank(ascending=False, method="min").astype(int).to_dict()
    res = PO.simulate(sched, teams, s, wk, rk, wm, 2000, np.random.default_rng(s), lines_weeks=set(), drift=drift)
    st = {r["team"]: float(r["p_playoffs"] >= 0.99 and (r["p_bye"] >= 0.99 or r["p_bye"] <= 0.01)) for r in res["rows"]}
    for x in reg[(reg.week == wk) & reg.result.notna() & (reg.result != 0)].itertuples():
      h, a = RELOCATED.get(x.home_team, x.home_team), RELOCATED.get(x.away_team, x.away_team)
      rows.append({"season": s, "home": float(x.location != "Neutral"), "elo": (mapped.get(h, elo.MEAN) - mapped.get(a, elo.MEAN)) / 100,
                   "settled": st.get(h, 0.0) - st.get(a, 0.0), "n_set": st.get(h, 0.0) + st.get(a, 0.0), "y": int(x.result > 0)})
    print(f"[final] {s} week {wk}: settled teams {int(sum(st.values()))}", flush=True)
  g = pd.DataFrame(rows)
  weights = []
  for s in SEASONS:
    tr, te = g.season != s, g.season == s
    for arm, cols in (("base", ["home", "elo"]), ("stakes", ["home", "elo", "settled"])):
      m = LogisticRegression(C=1e6, fit_intercept=False, max_iter=3000).fit(g.loc[tr, cols], g.loc[tr, "y"])
      g.loc[te, arm] = m.predict_proba(g.loc[te, cols])[:, 1]
      if arm == "stakes":
        weights.append(float(m.coef_[0][2]))
  for arm in ("base", "stakes"):
    g[f"b_{arm}"] = (g[arm] - g.y) ** 2
  d = (g.b_stakes - g.b_base).to_numpy()
  bt = d[np.random.default_rng(0).integers(0, len(d), (2000, len(d)))].mean(1)
  lo, hi = np.percentile(bt, [2.5, 97.5])
  per = g.groupby("season")[["b_base", "b_stakes"]].mean()
  better = int((per.b_stakes < per.b_base).sum())
  inv = g[g.n_set > 0]
  print(f"(BT2) {len(g)} final-week games 2002-19 ({len(inv)} involve a settled team): Brier base {g.b_base.mean():.4f} stakes {g.b_stakes.mean():.4f}")
  print(f"  stakes - base {d.mean():+.5f} [{lo:+.5f}, {hi:+.5f}]; on games with a settled team {(inv.b_stakes - inv.b_base).mean():+.5f}")
  print(f"  settled weight by fold: min {min(weights):+.3f} max {max(weights):+.3f}; seasons better {better}/18")
  t = g[g.settled != 0]
  print(f"  settled team won {np.where(t.settled > 0, t.y, 1 - t.y).mean():.3f} of {len(t)} games vs one side settled; base said {np.where(t.settled > 0, t.base, 1 - t.base).mean():.3f}")
  ok = d.mean() <= -0.003 and hi < 0 and max(weights) < 0 and better >= 10
  print("GATE:", "PASS" if ok else "FAIL")


if __name__ == "__main__":
  main()
