"""(DM2) the return model trained without the COVID reserve stints (pre-registered 2026-10-26, docs/INSIGHTS.md).

Usage: python tools/dm2_eval.py

(DM) found ReturnModel too pessimistic: 2021 by 10.6 points (the COVID-19 list, desig reserve_other, 37 points),
2022-25 by 0.4-2.8. R0 = the model as is; R2 = trained without 2020-21 reserve_other states. Walk-forward, scored on
2022-25 (2021 left out: its COVID states are not what the model faces now) and 2026 so far (untouched check).
GATE: (a) all states, Brier R2 - R0 upper 95% < +0.0005; (b) every group of 300+ states calibrated within 3 points;
(c) fantasy groups (QB RB WR TE) Brier upper < +0.0005. A remaining active-roster bias is reported, not tuned here.
"""
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

from dm_return_eval import ci, gb  # noqa: E402
from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.returns import POS_GROUP, ReturnModel, played_set  # noqa: E402

FANTASY_G = {"QB", "RB", "WR", "TE"}


def main():
  cfg = copy.deepcopy(load_config())
  cfg["data"]["history_seasons"] = 8
  data = D.load_all(cfg)
  m = ReturnModel(data, played_set(data))
  S = m.states(sorted(data.seasons))
  S["grp"] = S.position.map(POS_GROUP).fillna("other")
  covid = S.season.isin([2020, 2021]) & (S.desig == "reserve_other")
  print(f"{len(S)} states; COVID-era reserve_other states dropped from training in R2: {int(covid.sum())}")
  f = list(m.feats)
  out = []
  for s in sorted(x for x in S.season.unique() if x >= 2022):
    tr, te = S[S.season < s], S[S.season == s].copy()
    te["R0"] = gb(f).fit(tr[f], tr.back).predict_proba(te[f])[:, 1]
    t2 = tr[~covid.loc[tr.index]]
    te["R2"] = gb(f).fit(t2[f], t2.back).predict_proba(te[f])[:, 1]
    out.append(te)
  r = pd.concat(out, ignore_index=True)
  r["y"] = r.back.astype(float)
  r["cl"] = r.season.astype(str) + "-" + r.week.astype(str)
  for a in ("R0", "R2"):
    r[f"b_{a}"] = (r[a] - r.y) ** 2
  last = int(S.season.max())
  test, fresh = r[r.season < last], r[r.season == last]
  da = ci(test.b_R2 - test.b_R0, test.cl)
  fz = test[test.grp.isin(FANTASY_G)]
  dc = ci(fz.b_R2 - fz.b_R0, fz.cl)
  print(f"\n2022-{last - 1}: Brier R0 {test.b_R0.mean():.4f} R2 {test.b_R2.mean():.4f} ({da[0]:+.4f} [{da[1]:+.4f}, {da[2]:+.4f}])"
        f"; fantasy groups {fz.b_R0.mean():.4f} -> {fz.b_R2.mean():.4f} ({dc[0]:+.4f} [{dc[1]:+.4f}, {dc[2]:+.4f}])")
  ok_b = True
  print("by group: n, back, predicted R0 / R2")
  for k, x in test.groupby("grp"):
    if k == "other":
      continue
    good = abs(x.R2.mean() - x.y.mean()) <= 0.03
    if len(x) >= 300:
      ok_b &= good
    print(f"  {k:3s} n {len(x):5d}  back {x.y.mean():.3f}  pred {x.R0.mean():.3f} / {x.R2.mean():.3f}  {'' if len(x) < 300 else 'ok' if good else 'MISCALIBRATED'}")
  for col in ("season", "desig"):
    t = test.groupby(col).agg(n=("y", "size"), back=("y", "mean"), R0=("R0", "mean"), R2=("R2", "mean"))
    print(f"\nby {col}:\n" + t.round(3).to_string())
  m1 = test[test.missed == 1]
  print(f"\nafter 1 missed game: back {m1.y.mean():.3f}, R0 {m1.R0.mean():.3f}, R2 {m1.R2.mean():.3f} (n {len(m1)})")
  if len(fresh):
    print(f"\nuntouched {last} (weeks {int(fresh.week.min())}-{int(fresh.week.max())}, n {len(fresh)}): Brier R0 {fresh.b_R0.mean():.4f} "
          f"R2 {fresh.b_R2.mean():.4f}; back {fresh.y.mean():.3f}, pred {fresh.R0.mean():.3f} / {fresh.R2.mean():.3f}")
  ok = da[2] < 0.0005 and ok_b and dc[2] < 0.0005
  print(f"\n(DM2) GATE: {'PASS' if ok else 'FAIL'}  (a {'ok' if da[2] < 0.0005 else 'FAIL'}, b {'ok' if ok_b else 'FAIL'}, c {'ok' if dc[2] < 0.0005 else 'FAIL'})")


if __name__ == "__main__":
  main()
