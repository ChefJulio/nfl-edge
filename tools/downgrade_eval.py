"""(AY) a last-day downgrade in the practice model (pre-registered 2026-10-18, docs/INSIGHTS.md).

Usage: python tools/downgrade_eval.py [--late]
--late: (AZ) late additions, listed on one day only while the team listed someone on 3+ days that week.
Production's practice-model features (practice + role + rest) and settings, walk-forward 2021-25, labelled weeks not
ruled Out; the variant adds last_change (last day's score minus the day before's) and downgraded (last_change < 0).
GATE: downgrade rows Brier lower (95% CI over season-weeks excluding 0) and calibrated within 5 points; all rows not
worse (CI upper < +0.0005).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.injuries import _SCORE, InjuryModel, practice_features  # noqa: E402

TEST = [2021, 2022, 2023, 2024, 2025]


def last_change(days: pd.Series) -> np.ndarray:
  def f(s):
    v = [_SCORE[c] for c in str(s or "").replace("?", "") if c in _SCORE]
    return v[-1] - v[-2] if len(v) >= 2 else 0.0
  return np.array([f(s) for s in days], dtype=float)


def ci(diff, groups):
  gs = pd.DataFrame({"d": np.asarray(diff), "g": np.asarray(groups)}).groupby("g").d.agg(["sum", "size"])
  idx = np.random.default_rng(0).integers(0, len(gs), (4000, len(gs)))
  bt = gs["sum"].to_numpy()[idx].sum(1) / gs["size"].to_numpy()[idx].sum(1)
  return float(np.mean(diff)), *np.percentile(bt, [2.5, 97.5])


def main():
  cfg = load_config()
  d = D.load_all(cfg)
  im = InjuryModel(d, None, cfg)
  base = lambda r: im._with_rest(im._with_role(practice_features(r), r), r)
  plus = lambda r: base(r).assign(last_change=last_change(r.days), downgraded=(last_change(r.days) < 0).astype(float))
  gb = lambda: HistGradientBoostingClassifier(**im._gb_params(), random_state=0)
  ah = d.avail_hist[d.avail_hist.game_status != "OUT"].copy()
  if "--late" in sys.argv:
    full = d.avail_hist.assign(n=d.avail_hist.days.fillna("").str.replace("?", "", regex=False).str.len()).groupby(["season", "week", "team"]).n.max()
    tm = [full.get((s_, w_, t_), 0) for s_, w_, t_ in zip(ah.season, ah.week, ah.team)]
    ah["late"] = ((ah.days.fillna("").str.replace("?", "", regex=False).str.len() == 1) & (pd.Series(tm, index=ah.index) >= 3)).astype(float)
    plus = lambda r: base(r).assign(late_add=r.late.to_numpy())
  rows = []
  for s in TEST:
    tr, te = ah[ah.season < s], ah[ah.season == s].copy()
    te["p0"] = gb().fit(base(tr), tr.played).predict_proba(base(te))[:, 1]
    te["p1"] = gb().fit(plus(tr), tr.played).predict_proba(plus(te))[:, 1]
    rows.append(te)
  Q = pd.concat(rows); y = Q.played.astype(float)
  Q["d"] = (Q.p1 - y) ** 2 - (Q.p0 - y) ** 2; Q["g"] = Q.season.astype(str) + "-" + Q.week.astype(str)
  Q["dg"] = (Q.late > 0) if "--late" in sys.argv else (last_change(Q.days) < 0)
  tag = "AZ" if "--late" in sys.argv else "AY"
  dg = Q[Q.dg]
  m, lo, hi = ci(dg.d, dg.g); ma, loa, hia = ci(Q.d, Q.g)
  print(f"[{tag}] downgrade rows {len(dg)} of {len(Q)}: played {dg.played.mean():.1%}; production predicted {dg.p0.mean():.1%}, variant {dg.p1.mean():.1%}")
  print(f"[{tag}] downgrade rows Brier {((dg.p0 - dg.played) ** 2).mean():.4f} -> {((dg.p1 - dg.played) ** 2).mean():.4f}, {m:+.4f} [{lo:+.4f}, {hi:+.4f}]")
  q = dg[dg.game_status.astype(str).str.upper().str.startswith("Q")]
  print(f"[{tag}] of them Questionable: {len(q)}, played {q.played.mean():.1%}; production {q.p0.mean():.1%}, variant {q.p1.mean():.1%}")
  print(f"[{tag}] all rows {ma:+.5f} [{loa:+.5f}, {hia:+.5f}]")
  ok = hi < 0 and abs(dg.p1.mean() - dg.played.mean()) <= 0.05 and hia < 0.0005
  print(f"[{tag}] GATE:", "PASS" if ok else "FAIL")


if __name__ == "__main__":
  main()
