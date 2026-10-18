"""(AX) players who open the season on a reserve list get a return timeline (pre-registered 2026-10-18, INSIGHTS).

Usage: python tools/opened_out_eval.py [--dedicated]
--dedicated (AX2, second look): opened-out episodes get their own direct model (return_timing's, + prior_g), trained
only on opened-out episodes from 2021 on; in-season episodes keep production's models (identical by construction).
Walk-forward 2022-25: each test season's return models (the chain, and return_timing's direct model for IR) fit on
the seasons before, with and without injuries.opened_out. Scored on skill players' states in the test season,
P(back by his k-th next game), k = 1..8, combined as production does (direct model for IR, the chain otherwise,
stay 1, step 1 = the practice estimate when on the report). GATE: (i) new (opened-out) episodes: Brier lower than a
per-code base rate (share back by game k in earlier seasons' opened-out episodes, same designation and k), 95% CI
by episode excluding 0, lower in >= 3 of 4 seasons; (ii) new episodes: designation x k-bucket cells with n >= 150
within 5 points; (iii) in-season episodes not worse: Brier CI upper < +0.002.
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

TEST = [2022, 2023, 2024, 2025]
H = RT.H
cfg = run.load_config()
data = run.load_all(cfg)
GB = run.gb_cfg(cfg)
CACHE = ROOT / cfg["data"]["cache_dir"]
played = played_set(data)
SKILL = {"QB", "RB", "WR", "TE"}
DEDICATED = "--dedicated" in sys.argv


def predict(flag: bool, season: int) -> pd.DataFrame:
  """Labelled state x k rows of `season` (skill players) with production's hybrid prediction ("p")."""
  m = ReturnModel(data, played, opened_out=flag)
  st = m.states(sorted(data.seasons))
  m.fit_frame(st[st.season < season])
  train = RT.training_rows(data, m, GB, [s for s in range(RT.FIRST_SEASON, season) if s in data.seasons], CACHE)
  rt = RT.fit(train, opened_out=flag)
  xk = RT.training_rows(data, m, GB, [season], CACHE)
  xk = xk[xk.position.map(POS_GROUP).isin(SKILL)].copy()
  state = xk.drop_duplicates("src").sort_values("src").reset_index(drop=True)
  row = {s_: i for i, s_ in enumerate(state.src)}
  pc = m.p_active(state, H, first=state.p_now.to_numpy(), stay=1.0)
  pr = RT.predict(rt, state, H)
  i = xk.src.map(row).to_numpy()
  k = xk.k.to_numpy().astype(int) - 1
  xk["p"] = np.where(xk.desig.to_numpy() == "ir", pr[i, k], pc[i, k])
  xk["ep"] = xk.season.astype(str) + "-" + xk.gsis_id + "-" + (xk.week - xk.missed).astype(int).astype(str)
  return xk, train


def dedicated(season: int) -> pd.DataFrame:
  """(AX2) opened-out rows of `season` predicted by a direct model fit on earlier opened-out episodes (2021 on)."""
  from sklearn.ensemble import HistGradientBoostingClassifier
  m = ReturnModel(data, played, opened_out=True)
  m.states(sorted(data.seasons))  # schedule tables for active_after
  allx = RT.training_rows(data, m, GB, [s for s in range(RT.FIRST_SEASON, season + 1) if s in data.seasons], CACHE)
  allx = allx[(allx.opened_out == 1) & allx.position.map(POS_GROUP).isin(SKILL)]
  tr = allx[(allx.season >= 2021) & (allx.season < season)]
  feats = [c for c in RT.FEATS + ["prior_g"] if tr[c].notna().any() and tr[c].nunique() > 1]
  cat = [feats.index(c) for c in ("inj_code", "pos_code") if c in feats]
  md = HistGradientBoostingClassifier(**RT.GB, random_state=0, categorical_features=cat or None).fit(tr[feats], tr.y)
  md.cols_ = feats
  te = allx[allx.season == season].copy()
  state = te.drop_duplicates("src").sort_values("src").reset_index(drop=True)
  row = {s_: i for i, s_ in enumerate(state.src)}
  pr = RT.predict(md, state, H)
  te["p"] = pr[te.src.map(row).to_numpy(), te.k.to_numpy().astype(int) - 1]
  te["ep"] = te.season.astype(str) + "-" + te.gsis_id + "-" + (te.week - te.missed).astype(int).astype(str)
  return te, tr


def boot(d: pd.DataFrame, a: str, b: str) -> tuple[float, float, float]:
  """Mean (Brier a - Brier b) and its 95% CI resampling whole episodes."""
  x = d.assign(da=(d[a] - d.y) ** 2, db=(d[b] - d.y) ** 2).groupby("ep").agg(da=("da", "sum"), db=("db", "sum"), n=("y", "size"))
  idx = np.random.default_rng(0).integers(0, len(x), (2000, len(x)))
  diff = (x.da.to_numpy()[idx].sum(1) - x.db.to_numpy()[idx].sum(1)) / x.n.to_numpy()[idx].sum(1)
  return (x.da.sum() - x.db.sum()) / x.n.sum(), *np.percentile(diff, [2.5, 97.5])


def main():
  new_rows, old_rows = [], []
  for s in TEST:
    a, _ = predict(False, s)
    if DEDICATED:
      nb_, tr = dedicated(s)
      b = pd.concat([nb_, a.assign(opened_out=0.0)], ignore_index=True)
    else:
      b, train = predict(True, s)
      tr = train[(train.opened_out == 1) & train.position.map(POS_GROUP).isin(SKILL)]
    base = tr.groupby(["desig", "k"]).y.mean()
    nb = b[b.opened_out == 1].copy()
    nb["base"] = [base.get((d_, k_), tr[tr.k == k_].y.mean()) for d_, k_ in zip(nb.desig, nb.k)]
    nb["prod"] = 0.0
    new_rows.append(nb)
    key = ["gsis_id", "week", "k"]
    j = b[b.opened_out == 0][key + ["p", "y", "ep", "season", "desig"]].merge(a[key + ["p"]], on=key, suffixes=("", "_old"))
    old_rows.append(j)
    print(f"[AX] {s}: opened-out rows {len(nb)} ({nb.ep.nunique()} episodes); in-season rows {len(j)} (of {len(a)} before)", flush=True)
  N, O = pd.concat(new_rows, ignore_index=True), pd.concat(old_rows, ignore_index=True)
  print(f"\n[AX] (i) opened-out episodes: {len(N)} rows, {N.ep.nunique()} episodes; back by game k: actual {N.y.mean():.1%}, "
        f"model {N.p.mean():.1%}, base rate {N.base.mean():.1%}")
  d, lo, hi = boot(N, "p", "base")
  print(f"  Brier model {((N.p - N.y) ** 2).mean():.4f} | base rate {((N.base - N.y) ** 2).mean():.4f} | production (never back) "
        f"{((N['prod'] - N.y) ** 2).mean():.4f}; model - base {d:+.4f} [{lo:+.4f}, {hi:+.4f}]")
  per = N.assign(e1=(N.p - N.y) ** 2, e0=(N.base - N.y) ** 2).groupby("season")[["e1", "e0"]].mean()
  print(per.round(4).to_string())
  g1 = hi < 0 and (per.e1 < per.e0).sum() >= 3
  N["kb"] = pd.cut(N.k, [0, 2, 4, 8], labels=["1-2", "3-4", "5-8"])
  c = N.groupby(["desig", "kb"], observed=True).agg(n=("y", "size"), actual=("y", "mean"), model=("p", "mean"), base=("base", "mean"))
  c["gap"] = 100 * (c.model - c.actual)
  print("  (ii) calibration (points, model - actual):\n" + c.round(3).to_string())
  big = c[c.n >= 150]
  g2 = bool((big.gap.abs() <= 5).all())
  d3, lo3, hi3 = boot(O, "p", "p_old")
  print(f"\n[AX] (iii) in-season episodes: {len(O)} rows; Brier {((O.p_old - O.y) ** 2).mean():.4f} -> {((O.p - O.y) ** 2).mean():.4f}, "
        f"{d3:+.5f} [{lo3:+.5f}, {hi3:+.5f}]")
  g3 = hi3 < 0.002
  print(f"\n[AX] GATE: (i) {'PASS' if g1 else 'FAIL'} (ii) {'PASS' if g2 else 'FAIL'} (iii) {'PASS' if g3 else 'FAIL'} -> "
        f"{'PASS' if g1 and g2 and g3 else 'FAIL'}")


if __name__ == "__main__":
  main()
