"""Walk-forward A/B of config variants across several seasons, with confidence intervals on every difference.

Usage: python tools/experiments.py VARIANTS [SEASONS] [--history N]
  VARIANTS  comma list from VARIANTS below; the first one is the reference the others are compared with
  SEASONS   e.g. 2025 | 2021-2025 | 2023,2025 (default 2025)
  --history=N  seasons of data loaded before the current one (default: config; 2021-2025 needs 8 -> 2018+)
  --jobs=N     run (variant, season) backtests in N parallel processes (each holds its own copy of the data)

Each (variant, season) backtest is cached in cache/experiments/ keyed by its config, the data window and the
model code, so re-running a comparison only computes what changed. Results are on the 'relevant' rows (players
who played, >= 2 prior games, top-N by consensus) of the REFERENCE variant, joined player-week by player-week,
so every variant is scored on identical rows. The CI is a 95% bootstrap over season-weeks (weeks are resampled
whole, since errors within a week share game environments): if it excludes 0, the difference is real.
"""
import copy
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from error_breakdown import attach_actual_usage  # noqa: E402
from nfledge import backtest as B  # noqa: E402
from nfledge import data as D  # noqa: E402
from nfledge.config import load_config, load_scoring  # noqa: E402
from nfledge.engine import Engine  # noqa: E402

pd.set_option("display.width", 250)
POS = ["QB", "RB", "WR", "TE"]
OUT = ROOT / "cache" / "experiments"


def variant(**kw):
  """Config overrides keyed 'section__key'."""
  def apply(base):
    c = copy.deepcopy(base)
    for k, v in kw.items():
      sec, key = k.split("__")
      c.setdefault(sec, {})[key] = v
    return c
  return apply


VARIANTS = {
  "baseline": variant(),
  "no_implied_total": variant(experiments__implied_total=False),
  "air_yards": variant(experiments__air_yards=True),
  "snap_input": variant(experiments__snap_input=True),
  "share_hl_3": variant(player_model__share_half_life_weeks=3.0),
  "share_hl_8": variant(player_model__share_half_life_weeks=8.0),
  "team_hl_5": variant(team_model__half_life_weeks=5.0),
  "td_k_50": variant(player_model__td_blend_k=50),
  "td_k_400": variant(player_model__td_blend_k=400),
  "no_qb_effects": variant(team_model__qb_effects=False),
  "redistribution_0": variant(injuries__redistribution_scale=0.0),
  "redistribution_1": variant(injuries__redistribution_scale=1.0),
}


def parse_seasons(s: str) -> list[int]:
  out = []
  for part in s.split(","):
    a, _, b = part.partition("-")
    out += list(range(int(a), int(b or a) + 1))
  return out


def model_code() -> str:
  return "".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "nfledge").glob("*.py"))
                 if p.name not in ("report.py", "docs.py"))


def run_cached(name: str, cfg: dict, data, scoring, season: int) -> pd.DataFrame:
  key = hashlib.sha1(json.dumps([cfg, season, sorted(map(int, data.pbp.season.unique())), data.latest_week,
                                 model_code()], sort_keys=True, default=str).encode()).hexdigest()[:12]
  path = OUT / f"{name}_{season}_{key}.parquet"
  if path.exists():
    return pd.read_parquet(path)
  t = time.time()
  eng = Engine(data, cfg, scoring, positions=POS)
  res = B.run(eng, [season], use_injuries=True)
  # What actually happened (opportunities, stats, team volume) for tools/error_breakdown.py.
  res = attach_actual_usage(res, eng.pm.ledger, eng.team_ledger)
  OUT.mkdir(parents=True, exist_ok=True)
  res.to_parquet(path)
  print(f"  {name} {season}: {time.time() - t:.0f}s", flush=True)
  return res


def relevant(res: pd.DataFrame) -> pd.DataFrame:
  d = res[res.played & (res.raw_games >= 2) & res.pos.isin(POS)].copy()
  d["consensus"] = d[["proj", "raw_fpg", "vegas"]].mean(axis=1)
  d["crank"] = d.groupby(["season", "week", "pos"]).consensus.rank(ascending=False)
  return d[d.crank <= d.pos.map(B.RELEVANT_TOP)]


def week_bootstrap(diff: pd.Series, weeks: pd.Series, n: int = 2000, seed: int = 0) -> tuple[float, float]:
  """95% CI of the mean of diff, resampling whole season-weeks."""
  g = pd.DataFrame({"d": diff.to_numpy(), "w": weeks.to_numpy()}).groupby("w").d.agg(["sum", "size"])
  s, c = g["sum"].to_numpy(), g["size"].to_numpy()
  rng = np.random.default_rng(seed)
  idx = rng.integers(0, len(g), size=(n, len(g)))
  means = s[idx].sum(axis=1) / c[idx].sum(axis=1)
  return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def compare(results: dict[str, pd.DataFrame], ref: str) -> pd.DataFrame:
  keys = ["season", "week", "gsis_id"]
  base = relevant(results[ref])[keys + ["pos", "actual", "proj"]]
  rows = []
  for name, res in results.items():
    j = base.merge(res[keys + ["proj"]].drop_duplicates(keys), on=keys, how="left", suffixes=("_ref", ""))
    j["proj"] = j.proj.fillna(j.proj_ref)  # a variant that dropped a player is scored with the reference value
    for pos in POS + ["ALL"]:
      m = j if pos == "ALL" else j[j.pos == pos]
      err, err_ref = (m.actual - m.proj).abs(), (m.actual - m.proj_ref).abs()
      row = {"variant": name, "pos": pos, "n": len(m), "mae": err.mean(),
             "rank": m.groupby(["season", "week", "pos"]).apply(
               lambda x: x.proj.corr(x.actual, method="spearman") if len(x) > 4 else np.nan,
               include_groups=False).mean()}
      if name != ref:
        d = err - err_ref
        lo, hi = week_bootstrap(d, m.season.astype(str) + "-" + m.week.astype(str))
        row.update({"d_mae": d.mean(), "ci_lo": lo, "ci_hi": hi,
                    "verdict": "better" if hi < 0 else "worse" if lo > 0 else "no difference"})
      rows.append(row)
  return pd.DataFrame(rows)


_DATA = {}


def _job(name: str, season: int, history: int | None) -> pd.DataFrame:
  """One (variant, season) backtest. Each worker process loads the data once (from the local cache) and reuses
  it for every job it is handed."""
  base = load_config()
  if history is not None:
    base["data"]["history_seasons"] = history
  if "data" not in _DATA:
    _DATA["data"], _DATA["scoring"] = D.load_all(base), load_scoring()
  return run_cached(name, VARIANTS[name](base), _DATA["data"], _DATA["scoring"], season)


def main():
  args = [a for a in sys.argv[1:] if not a.startswith("--")]
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  history = int(opt["history"]) if "history" in opt else None
  jobs = int(opt.get("jobs", 1))
  names = args[0].split(",") if args else ["baseline"]
  seasons = parse_seasons(args[1]) if len(args) > 1 else [2025]
  todo = [(n, s) for n in names for s in seasons]
  if jobs > 1:
    # Seasons are independent (each trains only on earlier seasons), so they run in parallel processes. Each
    # process holds its own copy of the data (~1-2 GB with 2018+ history): size --jobs to free memory.
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(max_workers=jobs) as ex:
      done = dict(zip(todo, ex.map(_job, *zip(*todo), [history] * len(todo))))
  else:
    done = {t: _job(*t, history) for t in todo}
  results = {n: pd.concat([done[(n, s)] for s in seasons], ignore_index=True) for n in names}
  out = compare(results, names[0])
  print(f"\nSeasons {seasons}; reference = {names[0]}; relevant rows of the reference; MAE in fantasy points.")
  print(out.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
  for s in seasons:
    by = compare({k: v[v.season == s] for k, v in results.items()}, names[0])
    by = by[by.pos == "ALL"]
    print(f"\n{s}: " + "  ".join(f"{r.variant} {r.mae:.3f}" + (f" ({r.d_mae:+.3f})" if r.variant != names[0] else "")
                                 for r in by.itertuples()))


if __name__ == "__main__":
  main()
