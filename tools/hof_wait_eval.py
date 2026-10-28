"""(DP3) what sets the wait for the Hall of Fame (pre-registered 2026-10-28, docs/INSIGHTS.md).

Usage: python tools/hof_wait_eval.py

A discrete-time hazard over ballot years: every drafted player whose career ended by 2015 with a DP2 out-of-fold chance
of 2%+, one row per class from his first (last season + 6) until he is inducted or through 2026; outcome: inducted that
year. Base: logit(chance) + log(1 + years waited). Candidates: backlog (the other same-group players still waiting
that year, their chances summed, standardized), backlog x logit(chance) (the owner's hypothesis), career length.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from hof_eval import FEATS, ci, frame, ll, oof  # noqa: E402

LAST_CLASS = 2026


def rows() -> pd.DataFrame:
  import nflreadpy as nfl
  d = frame(nfl, LAST_CLASS - 1)
  tr = d[d.to <= 2015].reset_index(drop=True)
  tr["p"] = oof(tr, [c for v in FEATS.values() for c in v], tr.season.to_numpy())
  h = pd.read_csv(ROOT / "data" / "history" / "hof.csv")[["gsis_id", "cls"]]
  tr = tr.merge(h, on="gsis_id", how="left")
  tr = tr[tr.p >= 0.02].copy()
  tr["first"] = (tr.to + 6).astype(int)
  tr["end"] = np.where(tr.hof & tr.cls.notna(), tr.cls, LAST_CLASS).astype(int)
  tr = tr[tr["end"] >= tr["first"]]  # (an inductee before his computed first class: the data's last season is off)
  tr["pid"] = tr.pfr_player_id.fillna(pd.Series(tr.index.astype(str), index=tr.index))  # older rows lack a gsis id
  out = []
  for r in tr.itertuples():
    for c in range(r.first, r.end + 1):
      out.append((r.pid, r.g, c, c - r.first, r.p, int(r.hof and c == r.cls), r.to - r.season + 1))
  x = pd.DataFrame(out, columns=["pid", "g", "cls", "waited", "p", "y", "seasons"])
  # backlog: the others at his position group on that ballot (eligible by then, not yet in), chances summed
  bl = x.groupby(["g", "cls"]).p.transform("sum") - x.p
  x["backlog"] = (bl - bl.mean()) / bl.std()
  x["lp"] = np.log(x.p / (1 - x.p))
  x["lw"] = np.log1p(x.waited)
  x["inter"] = x.backlog * x.lp
  x["career"] = np.log(x.seasons.clip(lower=1))
  return x


def fit_oof(x: pd.DataFrame, cols) -> np.ndarray:
  from sklearn.linear_model import LogisticRegression
  from sklearn.model_selection import GroupKFold
  X, y, p = x[cols].to_numpy(float), x.y.to_numpy(int), np.zeros(len(x))
  for a, b in GroupKFold(5).split(X, y, x.pid):
    p[b] = LogisticRegression(C=1e6, max_iter=5000).fit(X[a], y[a]).predict_proba(X[b])[:, 1]
  return np.clip(p, 1e-5, 1 - 1e-5)


def by_player(x, a):
  """Per-player sums (the bootstrap resamples players, not ballot rows)."""
  return pd.Series(a).groupby(x.pid.to_numpy()).sum().to_numpy()


def main():
  from sklearn.linear_model import LogisticRegression
  x = rows()
  y = x.y.to_numpy(int)
  print(f"[DP3] {x.pid.nunique()} players, {len(x):,} ballot years, {y.sum()} inductions")
  base = ["lp", "lw"]
  L = {k: ll(y, fit_oof(x, c)) for k, c in (("base", base), ("backlog", base + ["backlog"]),
                                           ("inter", base + ["backlog", "inter"]), ("career", base + ["career"]))}
  n = x.pid.nunique()
  def gate(a, b, lab):
    m, lo, hi = ci(by_player(x, L[a] - L[b]) * n / len(x))
    print(f"  {lab:34s} {m:+.5f} [{lo:+.5f}, {hi:+.5f}]  {'PASS' if hi < 0 else 'FAIL'}")
  print("Out-of-fold log loss per ballot year, new - old (gate: interval below 0):")
  gate("backlog", "base", "(1) + backlog vs base")
  gate("inter", "backlog", "(2) + backlog x chance vs + backlog")
  gate("career", "base", "(3) + career length vs base")
  full = base + ["backlog", "inter", "career"]
  m = LogisticRegression(C=1e6, max_iter=5000).fit(x[full], y)
  print("Fit on all rows:", ", ".join(f"{c} {v:+.3f}" for c, v in zip(full, m.coef_[0])))
  # the interaction's sign, bootstrap over players
  rng, pids, bs = np.random.default_rng(0), x.pid.unique(), []
  g = {p: i for p, i in x.groupby("pid").indices.items()}
  for _ in range(400):
    idx = np.concatenate([g[p] for p in rng.choice(pids, len(pids))])
    bs.append(LogisticRegression(C=1e6, max_iter=5000).fit(x.iloc[idx][base + ["backlog", "inter"]], y[idx]).coef_[0][3])
  print(f"  interaction coefficient {np.mean(bs):+.3f} [{np.percentile(bs, 2.5):+.3f}, {np.percentile(bs, 97.5):+.3f}]"
        " (positive: the backlog's drag shrinks as the chance rises)")
  # what the backlog does to the expected wait, by chance level (fit with backlog and interaction)
  mi = LogisticRegression(C=1e6, max_iter=5000).fit(x[base + ["backlog", "inter"]], y)
  print("Expected wait (years past first eligibility, among those who get in within 20), light vs heavy backlog:")
  for p in (0.5, 0.8, 0.95):
    out = []
    for b in (-1.0, 1.0):
      surv, ew, mass = 1.0, 0.0, 0.0
      for w in range(21):
        lp = np.log(p / (1 - p))
        h = mi.predict_proba(pd.DataFrame([[lp, np.log1p(w), b, b * lp]], columns=base + ["backlog", "inter"]))[0, 1]
        ew += w * surv * h
        mass += surv * h
        surv *= 1 - h
      out.append((ew / mass if mass else float("nan"), mass))
    print(f"  chance {p:.0%}: light backlog {out[0][0]:.1f} yrs (in within 20: {out[0][1]:.0%}), heavy {out[1][0]:.1f} yrs ({out[1][1]:.0%})")


if __name__ == "__main__":
  main()
