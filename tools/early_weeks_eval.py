"""Weeks 1-2 walk-forward backtest (the standard backtest starts at week 3, so the season's opening weeks, where
rookies and new roles have no history, were never measured). 2026-10-15.

Usage: python tools/early_weeks_eval.py [--seasons=2021-2026] [--set=section.key=value ...] [--name=early]
Caches each season's rows in cache/experiments/{name}_w12_{season}_{hash}.parquet (same keying as experiments.py).
Prints MAE / bias for rookies vs veterans by position and draft tier, our MAE vs the expert consensus
(pre-kickoff ranks) on identical rows.
"""
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from experiments import model_code, parse_seasons  # noqa: E402
from nfledge import backtest as B  # noqa: E402
from nfledge import data as D  # noqa: E402
from nfledge.config import load_config, load_scoring  # noqa: E402
from nfledge.engine import Engine  # noqa: E402

POS = ["QB", "RB", "WR", "TE"]
OUT = ROOT / "cache" / "experiments"


def set_cfg(cfg: dict, items: list[str]) -> dict:
  for it in items:
    k, v = it.split("=", 1)
    sec, key = k.split(".", 1)
    cfg.setdefault(sec, {})[key] = json.loads(v)
  return cfg


def run(name: str, cfg: dict, data, scoring, season: int) -> pd.DataFrame:
  key = hashlib.sha1(json.dumps([cfg, season, "w12", sorted(map(int, data.pbp.season.unique())), data.latest_week,
                                 model_code()], sort_keys=True, default=str).encode()).hexdigest()[:12]
  path = OUT / f"{name}_w12_{season}_{key}.parquet"
  if path.exists():
    return pd.read_parquet(path)
  t = time.time()
  res = B.run(Engine(data, cfg, scoring, positions=POS), [season], use_injuries=True, weeks={season: [1, 2]})
  OUT.mkdir(parents=True, exist_ok=True)
  res.to_parquet(path)
  print(f"  {name} w1-2 {season}: {time.time() - t:.0f}s", flush=True)
  return res


def rookie_years(cache) -> dict:
  ry = {}
  for s in range(2012, 2027):
    r = cache.get("rosters", s, None, stale=False)
    if r is not None:
      for g, y in zip(r.gsis_id, r.rookie_year):
        if isinstance(g, str) and pd.notna(y):
          ry[g] = int(y)
  return ry


def main():
  opt = {a[2:].split("=", 1)[0]: a[2:].split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--") and "=" in a}
  sets = [a[6:] for a in sys.argv[1:] if a.startswith("--set=")]
  seasons = parse_seasons(opt.get("seasons", "2021-2026"))
  cfg = set_cfg(load_config(), sets)
  data, scoring = D.load_all(cfg), load_scoring()
  R = pd.concat([run(opt.get("name", "early"), cfg, data, scoring, s).assign(season=s) for s in seasons], ignore_index=True)
  R = R[R.played & R.pos.isin(POS) & R.actual.notna()].copy()
  ry = rookie_years(D.Cache(ROOT / "cache"))
  R["rook"] = R.gsis_id.map(ry) == R.season
  R["err"], R["ae"] = R.actual - R.proj, (R.actual - R.proj).abs()
  R["ae_x"] = (R.actual - R.ecr_pts).abs()
  # relevant rows the way experiments.py picks them, minus the >= 2 games rule (there are no games yet)
  R["crank"] = R.groupby(["season", "week", "pos"]).proj.rank(ascending=False)
  R["rel"] = R.crank <= R.pos.map(B.RELEVANT_TOP)
  pd.set_option("display.width", 220)

  def tab(d, by):
    g = d.groupby(by, observed=True)
    return pd.DataFrame({"n": g.size(), "proj": g.proj.mean(), "actual": g.actual.mean(), "bias": g.err.mean(),
                         "mae": g.ae.mean(), "n_ecr": g.ecr_pts.count(),
                         "us_on_ecr": g.apply(lambda y: y[y.ecr_pts.notna()].ae.mean(), include_groups=False),
                         "ecr": g.apply(lambda y: y.ae_x[y.ecr_pts.notna()].mean(), include_groups=False)}).round(2)
  print(f"\nWeeks 1-2, {seasons}: {len(R)} played rows; MAE ours vs expert consensus on rows with a pre-kickoff rank")
  print(tab(R, ["rook", "pos"]))
  print("\nRookies by position x draft tier:")
  t = tab(R[R.rook], ["pos", "tier"])
  print(t[t.n >= 10])
  print("\nRelevant rows (top-N by our projection):")
  print(tab(R[R.rel], ["rook", "pos"]))
  print("\nRookies who mattered (actual >= 10) we projected under 5:")
  x = R[R.rook & (R.actual >= 10) & (R.proj < 5)]
  print(len(x), "of", int((R.rook & (R.actual >= 10)).sum()))
  print(x[["season", "week", "full_name", "pos", "tier", "proj", "ecr_pts", "actual"]].sort_values("actual", ascending=False)
        .head(25).round(1).to_string(index=False))
  R.to_parquet(OUT / f"{opt.get('name', 'early')}_w12_eval_rows.parquet")


if __name__ == "__main__":
  main()
