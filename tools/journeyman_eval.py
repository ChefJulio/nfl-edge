"""Journeyman adjustment (pre-registered, docs/INSIGHTS.md section 9, 2026-10-15). Usage: python tools/journeyman_eval.py

Players who change teams often come in under their projections (descriptive: -0.55 pts for 0 changes in the past 5
seasons to -1.35 for 3+). k = team changes over his past 5 seasons + this one (weekly rosters, ACT), capped at 3;
his first game with a team is excluded (the newcomer discount handles it). Multiplier per k = [sum actual / sum
projected for k] / [same for k = 0], fit on 2021-23, applied to 2024-25 projections. Uses the current model's backtest
(cache/experiments/newcomer_05_*: the shipped config). Gate: (i) k >= 1 rows MAE lower, 95% CI over season-weeks
excluding 0; (ii) all rows not worse (CI upper < +0.003); (iii) no position significantly worse.
"""
import glob
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.data import team_name_fix  # noqa: E402

FIT, TEST = [2021, 2022, 2023], [2024, 2025]
c = D.Cache(ROOT / "cache")


def load(v):
  fs = {}
  for f in glob.glob(str(ROOT / "cache" / "experiments" / f"{v}_20*.parquet")):
    s = int(os.path.basename(f).split("_")[-2])
    if s not in fs or os.path.getmtime(f) > os.path.getmtime(fs[s]):
      fs[s] = f
  return pd.concat([pd.read_parquet(fs[s]).assign(season=s) for s in sorted(fs)], ignore_index=True)


def switch_counts(rows: pd.DataFrame) -> np.ndarray:
  seq = {}
  for s in range(2015, 2026):
    r = c.get("rosters", s, None, stale=False)
    if r is None:
      continue
    r = r[r.status == "ACT"].sort_values("week")
    for g, x in r.groupby("gsis_id"):
      seq[(g, s)] = [(int(w), t) for w, t in zip(x.week, x.team)]
  out = []
  for g, s, w in zip(rows.gsis_id, rows.season, rows.week):
    teams = []
    for y in range(s - 5, s + 1):
      teams += [t for wk, t in seq.get((g, y), []) if y < s or wk <= w]
    teams = [t for i, t in enumerate(teams) if i == 0 or t != teams[i - 1]]
    out.append(min(3, len(teams) - 1 if teams else 0))
  return np.array(out)


def first_games() -> set:
  import run
  sn = run.load_all(run.load_config()).snaps  # with gsis ids attached (the raw cached snap files don't carry them)
  sn = sn.dropna(subset=["gsis_id"])
  sn = sn[(sn.offense_snaps.fillna(0) + sn.defense_snaps.fillna(0) + sn.st_snaps.fillna(0)) > 0]
  sn = sn.assign(team=team_name_fix(sn.team), k=sn.season * 100 + sn.week)
  first = sn.groupby(["gsis_id", "team"]).k.min()
  return {(g, t, k // 100, k % 100) for (g, t), k in first.items()}


R = load("newcomer_05")
R = R[R.actual.notna() & R.pos.isin(["QB", "RB", "WR", "TE"]) & (R.proj >= 1)].copy()
fg = first_games()
R = R[[(g, t, s, w) not in fg for g, t, s, w in zip(R.gsis_id, R.team, R.season, R.week)]]
R["k"] = switch_counts(R)
fit = R[R.season.isin(FIT)]
base = fit[fit.k == 0].actual.sum() / fit[fit.k == 0].proj.sum()
mult = {int(k): float((x.actual.sum() / x.proj.sum()) / base) for k, x in fit.groupby("k")}
print("[journeyman] rows by k (all seasons):", R.k.value_counts().sort_index().to_dict())
print("[journeyman] multipliers fit on 2021-23:", {k: round(v, 3) for k, v in mult.items()})
T = R[R.season.isin(TEST)].copy()
T["adj"] = T.proj * T.k.map(mult)
T["e0"], T["e1"] = (T.proj - T.actual).abs(), (T.adj - T.actual).abs()


def ci(rows):
  d = (rows.e1 - rows.e0).to_numpy()
  g = (rows.season.astype(str) + "-" + rows.week.astype(str)).to_numpy()
  gs = pd.DataFrame({"d": d, "g": g}).groupby("g").d.agg(["sum", "size"])
  s_, c_ = gs["sum"].to_numpy(), gs["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(gs), (2000, len(gs)))
  bt = s_[idx].sum(1) / c_[idx].sum(1)
  return d.mean(), np.percentile(bt, 2.5), np.percentile(bt, 97.5)


m1, lo1, hi1 = ci(T[T.k >= 1])
m2, lo2, hi2 = ci(T)
print(f"[journeyman] 2024-25 k>=1 rows {int((T.k >= 1).sum())}: MAE {T[T.k >= 1].e0.mean():.3f} -> {T[T.k >= 1].e1.mean():.3f} diff {m1:+.3f} [{lo1:+.3f}, {hi1:+.3f}]")
print(f"[journeyman] 2024-25 all rows {len(T)}: diff {m2:+.3f} [{lo2:+.3f}, {hi2:+.3f}]")
pos_ok = True
for pos, x in T.groupby("pos"):
  m, lo, hi = ci(x)
  pos_ok &= lo <= 0
  print(f"   {pos}: {m:+.3f} [{lo:+.3f}, {hi:+.3f}]")
print("[journeyman] bias by k, 2024-25 (actual - proj): before", T.groupby("k").apply(lambda x: (x.actual - x.proj).mean()).round(2).to_dict(),
      "after", T.groupby("k").apply(lambda x: (x.actual - x.adj).mean()).round(2).to_dict())
ok = hi1 < 0 and hi2 < 0.003 and pos_ok
print("[journeyman] GATE:", "PASS" if ok else "FAIL")
if ok:
  full = {int(k): float((x.actual.sum() / x.proj.sum()) / (R[R.k == 0].actual.sum() / R[R.k == 0].proj.sum())) for k, x in R.groupby("k")}
  print("[journeyman] ship multipliers (fit 2021-25):", {k: round(v, 3) for k, v in full.items()})
  (ROOT / "data" / "history" / "journeyman.json").write_text(json.dumps({"source": "tools/journeyman_eval.py", "mult": full}, indent=1), encoding="utf-8")
