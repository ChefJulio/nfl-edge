"""(AE) ranges from out-of-sample misses (pre-registered in docs/INSIGHTS.md 2026-10-17).

Usage: python tools/range_eval.py
Today: engine._fit_quantiles takes each position's p10..p90 offsets from projections on the training seasons, made
by a model fit on those seasons. Variant: the same binning (12 projection bins per position, >= 30 rows each, offsets
from the bin's mean projection, interpolated), fit on the walk-forward backtest's rows from every earlier test season
(cache/experiments/adopted_*: out of sample). The widening factor m is 1 in config.toml [uncertainty] (all off), so
offsets are used as they are. Scored on 2023-25 (each fit on 2021 .. s-1): mean pinball loss over the five quantiles,
played rows with projection >= 1. GATE: lower, 95% CI over season-weeks excluding 0, lower in each of 2023-25; guard:
the top three weekly tiers' 10-90% coverage no further from 80% on average.
"""
import glob
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
Q = np.array([0.10, 0.25, 0.50, 0.75, 0.90])
QC = ["p10", "p25", "p50", "p75", "p90"]
TEST = [2023, 2024, 2025]
CUT = {"QB": [0, 6, 12, 24, 99], "RB": [0, 12, 24, 36, 999], "WR": [0, 12, 24, 48, 999], "TE": [0, 6, 12, 24, 999]}

d = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(str(ROOT / "cache" / "experiments" / "adopted_*.parquet")))])
d = d[d.played & d.p10.notna() & d.pos.isin(CUT)].reset_index(drop=True)


def fit(g: pd.DataFrame) -> dict:
  """engine._fit_quantiles, on the rows given."""
  out = {}
  for pos, h in g[g.proj > 0.5].groupby("pos"):
    edges = np.unique(np.quantile(h.proj, np.linspace(0, 1, 13)))
    idx = np.digitize(h.proj, edges[1:-1])
    centers, offs = [], []
    for b in np.unique(idx):
      hb = h[idx == b]
      if len(hb) >= 30:
        centers.append(hb.proj.mean())
        offs.append(np.quantile(hb.actual, Q) - hb.proj.mean())
    if len(centers) >= 3:
      out[pos] = (np.array(centers), np.array(offs))
  return out


def apply(qm: dict, g: pd.DataFrame) -> np.ndarray:
  out = np.full((len(g), 5), np.nan)
  for pos, (c, o) in qm.items():
    sel = (g.pos == pos).to_numpy()
    x = g.proj.to_numpy()[sel]
    out[sel] = np.clip(x[:, None] + np.column_stack([np.interp(x, c, o[:, k]) for k in range(5)]), 0, None)
  return out


def pinball(q: np.ndarray, y: np.ndarray) -> np.ndarray:
  e = y[:, None] - q
  return np.mean(np.maximum(Q * e, (Q - 1) * e), axis=1)


rows = []
for s in TEST:
  qm = fit(d[d.season < s])
  t = d[(d.season == s) & (d.proj >= 1)].reset_index(drop=True)
  v = apply(qm, t)
  t["lb"], t["lv"] = pinball(t[QC].to_numpy(), t.actual.to_numpy()), pinball(v, t.actual.to_numpy())
  for k, c in enumerate(QC):
    t[f"v_{c}"] = v[:, k]
  rows.append(t)
R = pd.concat(rows, ignore_index=True)
R["wk"] = R.season.astype(str) + "-" + R.week.astype(str)
diff = (R.lv - R.lb).to_numpy()
g = pd.DataFrame({"d": diff, "g": R.wk}).groupby("g").d.agg(["sum", "size"])
idx = np.random.default_rng(0).integers(0, len(g), size=(2000, len(g)))
boot = g["sum"].to_numpy()[idx].sum(1) / g["size"].to_numpy()[idx].sum(1)
lo, hi = np.percentile(boot, [2.5, 97.5])
per = R.groupby("season")[["lb", "lv"]].mean()
print(f"pinball (mean of 5 quantiles), {len(R)} rows: today {R.lb.mean():.4f} variant {R.lv.mean():.4f} diff {diff.mean():+.4f} [{lo:+.4f}, {hi:+.4f}]")
print(per.round(4).to_string())
R["tier"] = R.groupby(["season", "week", "pos"]).proj.rank(ascending=False, method="first")
cov = []
for pos, h in R.groupby("pos"):
  h = h.assign(t=pd.cut(h.tier, CUT[pos], labels=["top", "start", "flex", "deep"]))
  for t_, x in h.groupby("t", observed=True):
    cov.append({"pos": pos, "tier": t_, "n": len(x), "today": x.actual.between(x.p10, x.p90).mean(),
                "variant": x.actual.between(x.v_p10, x.v_p90).mean(),
                "today_above90": (x.actual > x.p90).mean(), "var_above90": (x.actual > x.v_p90).mean()})
C = pd.DataFrame(cov)
print(C.round(3).to_string(index=False))
top3 = C[C.tier != "deep"]
gb, gv = (top3.today - 0.8).abs().mean(), (top3.variant - 0.8).abs().mean()
print(f"top three tiers: mean |coverage - 80%| today {gb:.3f} variant {gv:.3f}")
ok = hi < 0 and (per.lv < per.lb).all() and gv <= gb
print("GATE:", "PASS" if ok else "FAIL")
