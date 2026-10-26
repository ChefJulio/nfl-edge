"""(DM) the return model for every position, by position group (pre-registered 2026-10-26, docs/INSIGHTS.md).

Usage: python tools/dm_return_eval.py [--first=2021] [--last=2025]

The return half of (DM). ReturnModel (nfledge/returns.py) already trains on every rostered position with a position
group input (pos_code); the site applies it to fantasy players only. Walk-forward (season s trains on every earlier
loaded season), every injured-out player-week: R0 = the model as is; R1 = the same without pos_code (does position
carry anything?). Scored: P(plays his team's next game), Brier and log loss by group.
GATE (pre-registered): (4) each group with 300+ test states: R0's mean predicted within 3 points of the share back;
(5) report R0 vs R1 by group; R0 stays unless R1 is no worse (then the simpler). Groups passing (4) get the return
week on the Injuries tile.
"""
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.returns import POS_GROUP, ReturnModel, played_set  # noqa: E402

FANTASY = {"QB", "RB", "FB", "WR", "TE", "K"}


def gb(feats):
  from sklearn.ensemble import HistGradientBoostingClassifier
  cat = [feats.index(c) for c in ("inj_code", "pos_code") if c in feats]
  return HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_depth=3, random_state=0, categorical_features=cat)


def ci(diff: pd.Series, cl: pd.Series):
  gr = pd.DataFrame({"d": diff.to_numpy(), "c": cl.to_numpy()}).groupby("c").d.agg(["sum", "size"])
  s_, n_ = gr["sum"].to_numpy(), gr["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(gr), (4000, len(gr)))
  bt = s_[idx].sum(1) / n_[idx].sum(1)
  return diff.mean(), np.percentile(bt, 2.5), np.percentile(bt, 97.5)


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  first, last = int(opt.get("first", 2021)), int(opt.get("last", 2025))
  cfg = copy.deepcopy(load_config())
  cfg["data"]["history_seasons"] = 8
  data = D.load_all(cfg)
  m = ReturnModel(data, played_set(data))
  S = m.states(sorted(data.seasons))
  S["grp"] = S.position.map(POS_GROUP).fillna("other")
  print(f"{len(S)} injured-out player-weeks; by group: " + ", ".join(f"{k} {v}" for k, v in S.grp.value_counts().items()))
  f0 = list(m.feats)
  f1 = [c for c in f0 if c != "pos_code"]
  out = []
  for s in range(first, last + 1):
    tr, te = S[S.season < s], S[S.season == s].copy()
    if not len(te):
      continue
    te["R0"] = gb(f0).fit(tr[f0], tr.back).predict_proba(te[f0])[:, 1]
    te["R1"] = gb(f1).fit(tr[f1], tr.back).predict_proba(te[f1])[:, 1]
    out.append(te)
  r = pd.concat(out, ignore_index=True)
  r["y"] = r.back.astype(float)
  r["cl"] = r.season.astype(str) + "-" + r.week.astype(str)
  eps = 1e-6
  for a in ("R0", "R1"):
    r[f"b_{a}"] = (r[a] - r.y) ** 2
    p = r[a].clip(eps, 1 - eps)
    r[f"l_{a}"] = -(r.y * np.log(p) + (1 - r.y) * np.log(1 - p))
  ok4 = True
  print("\nby group: n, share back next game, R0 predicted, Brier R0 / R1, log loss R0 / R1 (R1 - R0 [95%])")
  for k, x in r.groupby("grp"):
    if k == "other":
      continue
    bias = x.R0.mean() - x.y.mean()
    gate = len(x) >= 300
    ok = abs(bias) <= 0.03 if gate else None
    if gate:
      ok4 &= ok
    dl = ci(x.l_R1 - x.l_R0, x.cl)
    print(f"  {k:3s} n {len(x):5d}  back {x.y.mean():.3f}  pred {x.R0.mean():.3f}  "
          f"Brier {x.b_R0.mean():.4f} / {x.b_R1.mean():.4f}  logloss {x.l_R0.mean():.4f} / {x.l_R1.mean():.4f} "
          f"({dl[0]:+.4f} [{dl[1]:+.4f}, {dl[2]:+.4f}])  {'' if ok is None else 'calibrated' if ok else 'MISCALIBRATED'}")
  dl = ci(r.l_R1 - r.l_R0, r.cl)
  db = ci(r.b_R1 - r.b_R0, r.cl)
  print(f"\nall: Brier R0 {r.b_R0.mean():.4f} R1 {r.b_R1.mean():.4f} ({db[0]:+.4f} [{db[1]:+.4f}, {db[2]:+.4f}]); "
        f"log loss R0 {r.l_R0.mean():.4f} R1 {r.l_R1.mean():.4f} ({dl[0]:+.4f} [{dl[1]:+.4f}, {dl[2]:+.4f}])")
  keep = "R1 (position adds nothing: the simpler)" if db[2] <= 0 else "R0 (position helps)" if db[1] > 0 else "R0 (no clear difference; the model as is)"
  print(f"(5) position in the return model: {keep}")
  # where the bias lives (2026-10-26: R0 read 3-6 points low in 8 of 9 groups): by season, designation, games missed
  for col in ("season", "desig", "missed"):
    x = r.assign(missed=r.missed.clip(upper=5))
    t = x.groupby(col).agg(n=("y", "size"), back=("y", "mean"), pred=("R0", "mean"))
    t["bias"] = t.pred - t.back
    print(f"\nR0 bias by {col}:\n" + t.round(3).to_string())
  tr_rate = S.groupby("season").back.mean().round(3)
  print("\nshare back next game, every season loaded:\n" + tr_rate.to_string())
  # games out per episode by group and the commonest injuries (the owner's question, descriptive)
  ep = r[r.missed == 1]
  print("\nP(back after one missed game), by group x injury (n >= 60):")
  t = ep.groupby(["injury", "grp"]).y.agg(["mean", "size"]).query("size >= 60").unstack("grp")
  if len(t):
    print((t["mean"] * 100).round(0).to_string())
  print(f"\n(DM) RETURN GATE (4): {'PASS' if ok4 else 'FAIL'}")


if __name__ == "__main__":
  main()
