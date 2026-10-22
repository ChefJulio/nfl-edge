"""Early-week ECR, the pre-registered forward test (docs/INSIGHTS.md, 2026-10-15; season-average fallback folded in
2026-10-21). Tue / Wed / Thu builds run without the expert blend (nflverse keeps only Friday's ECR). Would blending
that day's ECR (DynastyProcess scrape, archived daily by tools/ecr_snapshot.py) have helped?

Per game week (2026 week 7 on) and ET day Tue / Wed / Thu: the day's last live build (archive branch
data/live_inputs/<season>_<week>_<stamp>.json, its published proj = the model's calibrated projection, no blend),
before the player's kickoff. Variants, re-blended with the CURRENT trained engine's ecr_map / blend (the Friday fit):
  day   - that day's ECR snapshot (data/ecr_snapshots/<season>_<date>.json)
  avg   - the player's season-average expert rank so far (mean log of earlier weeks' Friday ECR, nflverse)
Rows: relevant RB / WR / TE (tools/experiments.relevant on the cached 2026 baseline: actual points, played, 2+ prior
games, top-N). GATE (day): MAE better than published with a 95% CI over team-weeks excluding 0 on the pooled Tue-Thu
rows, and no position worse; needs 4+ weeks.

  python tools/ecr_early_eval.py [--season=2026] [--from-week=7]
"""
import glob
import json
import os
import pickle
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from experiments import relevant  # noqa: E402

POS = ("RB", "WR", "TE")
DAYS = {1: "Tue", 2: "Wed", 3: "Thu"}  # pandas dayofweek


def git_show(path: str) -> str:
  return subprocess.run(["git", "show", f"origin/archive:{path}"], cwd=ROOT, capture_output=True, text=True,
                        encoding="utf-8").stdout


def archive_list(prefix: str) -> list[str]:
  out = subprocess.run(["git", "ls-tree", "-r", "--name-only", "origin/archive", prefix], cwd=ROOT,
                       capture_output=True, text=True).stdout
  return out.split()


def trained_engine():
  fs = sorted(glob.glob(str(ROOT / "cache" / "engine_*.pkl")) + glob.glob(str(ROOT / "cache" / "model_*.pkl")),
              key=os.path.getmtime)
  with open(fs[-1], "rb") as f:
    obj = pickle.load(f)
  return obj[0] if isinstance(obj, tuple) else obj


def reblend(eng, df: pd.DataFrame, ecr_col: str) -> pd.Series:
  out = df.proj.copy()
  for pos in POS:
    sel = (df.pos == pos) & df[ecr_col].notna()
    if sel.any() and pos in eng.ecr_map and pos in eng.blend:
      g = df[sel].assign(log_ecr=np.log(df.loc[sel, ecr_col]))
      g = g.assign(ecr_pts=eng.ecr_map[pos].predict(g))
      out[sel] = np.clip(eng.blend[pos].predict(g), 0, None)
  return out


def ci(d: pd.Series, cl: pd.Series, reps=4000):
  gr = pd.DataFrame({"v": d.to_numpy(), "c": cl.to_numpy()}).groupby("c").v.agg(["sum", "size"])
  s_, n_ = gr["sum"].to_numpy(), gr["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(gr), (reps, len(gr)))
  bt = s_[idx].sum(1) / n_[idx].sum(1)
  return d.mean(), np.percentile(bt, 2.5), np.percentile(bt, 97.5)


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  season, w0 = int(opt.get("season", 2026)), int(opt.get("from-week", 7))
  subprocess.run(["git", "fetch", "-q", "origin", "archive"], cwd=ROOT)
  fs = sorted(glob.glob(str(ROOT / "cache" / "experiments" / f"baseline_{season}_*.parquet")), key=os.path.getmtime)
  base = relevant(pd.read_parquet(fs[-1]))
  base = base[base.pos.isin(POS) & (base.week >= w0)][["week", "gsis_id", "team", "pos", "actual"]]
  sch = pd.read_parquet(ROOT / "cache" / "schedules_all.parquet")
  sch = sch[(sch.season == season) & (sch.game_type == "REG")]
  kick = {}
  for g in sch.itertuples():
    t = pd.Timestamp(f"{g.gameday} {g.gametime or '13:00'}", tz="America/New_York")
    kick[(g.week, g.home_team)] = kick[(g.week, g.away_team)] = t
  # Friday ECR by week (nflverse, as the model sees it) for the season-average variant
  ecr = pd.read_parquet(sorted(glob.glob(str(ROOT / "cache" / "ecr*.parquet")), key=os.path.getmtime)[-1])
  ecr = ecr[ecr.season == season]
  eng = trained_engine()
  import nflreadpy as nfl
  ids = nfl.load_ff_playerids().to_pandas()[["fantasypros_id", "gsis_id"]].dropna()
  fp = dict(zip(ids.fantasypros_id.astype("int64").astype(str), ids.gsis_id))
  snaps = {}
  for f in archive_list("data/live_inputs"):
    name = Path(f).stem
    if not name.startswith(f"{season}_"):
      continue
    _, wk, stamp = name.split("_")
    t = pd.Timestamp(stamp, tz="UTC").tz_convert("America/New_York")
    if int(wk) >= w0 and t.dayofweek in DAYS:
      snaps[(int(wk), t.date())] = max(snaps.get((int(wk), t.date()), (t, f)), (t, f))
  rows = []
  for (wk, day), (t, f) in sorted(snaps.items()):
    d = json.loads(git_show(f))
    if d.get("ecr_scrape"):  # this build already had the week's ECR (not an early-week build)
      continue
    p = pd.DataFrame([[g, *v] for g, v in d["p"].items()], columns=["gsis_id", *d["stats"]])[["gsis_id", "proj"]]
    es = git_show(f"data/ecr_snapshots/{season}_{day}.json")
    day_ecr = {g: v[1] for g, v in json.loads(es)["p"].items()} if es else {}
    x = base[base.week == wk].merge(p, on="gsis_id")
    x = x[[t < kick.get((wk, tm), t) for tm in x.team]]
    x["ecr_day"] = x.gsis_id.map({fp[k]: v for k, v in day_ecr.items() if k in fp})
    past = ecr[ecr.week < wk].assign(l=np.log(ecr.ecr)).groupby("gsis_id").l.mean()
    x["ecr_avg"] = np.exp(x.gsis_id.map(past))
    x["day"], x["dow"] = str(day), DAYS[t.dayofweek]
    x["p_day"], x["p_avg"] = reblend(eng, x, "ecr_day"), reblend(eng, x, "ecr_avg")
    rows.append(x)
  if not rows:
    sys.exit("no early-week builds yet")
  x = pd.concat(rows, ignore_index=True)
  x["cl"] = x.week.astype(str) + "-" + x.team
  print(f"{season} weeks {sorted(x.week.unique())}; early-week rows {len(x)} ({x.ecr_day.notna().mean():.0%} with the day's ECR)")
  e0 = (x.actual - x.proj).abs()
  res = {}
  for v in ("p_day", "p_avg"):
    dlt = (x.actual - x[v]).abs() - e0
    m, lo, hi = ci(dlt, x.cl)
    res[v] = hi
    per = {pos: dlt[x.pos == pos].mean() for pos in POS}
    print(f"  {v}: MAE {(x.actual - x[v]).abs().mean():.3f} vs published {e0.mean():.3f}: {m:+.3f} [{lo:+.3f}, {hi:+.3f}]; "
          + ", ".join(f"{k} {v_:+.3f}" for k, v_ in per.items()) + "; by day " +
          ", ".join(f"{d_} {dlt[x.dow == d_].mean():+.3f}" for d_ in DAYS.values()))
  weeks = x.week.nunique()
  per_day = {pos: ((x.actual - x.p_day).abs() - e0)[x.pos == pos].mean() for pos in POS}
  gate = weeks >= 4 and res["p_day"] < 0 and all(v <= 0 for v in per_day.values())
  print(f"\nGATE (day ECR): {'PASS' if gate else 'FAIL' if weeks >= 4 else f'NOT YET ({weeks} of 4 weeks)'}")


if __name__ == "__main__":
  main()
