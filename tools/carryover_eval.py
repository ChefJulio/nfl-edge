"""How much should last season carry into this season's team ratings? Scored on GAME outcomes, walk-forward.

Usage: python tools/carryover_eval.py          (~3-4 min per variant; results cached in cache/carryover/)
       python tools/carryover_eval.py --quick  (direction check: 4 variants x 3 seasons, ~10 min)

Variants of [team_model] prior_weight (last season's plays' weight at week 1), prior_decay_week (the target week by
which that weight has faded linearly to 0; 19 = never within the regular season) and half_life_weeks (in-season
recency). For each: every game 2021-26 (weeks 2+) re-rated with ranks as of the week before (tools/rank_predictor),
then walk-forward on 2022-26 games with a Vegas line: Brier of the shipped win chance (rank gap + Elo + home), of
rank gap + home, and margin MAE, each vs the current settings with a 95% CI over season-weeks, split weeks 2-8 / 9+.
(These knobs were "insensitive" for fantasy projections; they were never tested on games.)
"""
import copy
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import rank_predictor as rp  # noqa: E402
from darts import logit_fit  # noqa: E402
from nfledge import data as D, elo  # noqa: E402
from nfledge.config import load_config  # noqa: E402

OUT = ROOT / "cache" / "carryover"
VARIANTS = [(w, dk, hl) for hl in (3.0, 6.0) for w in (0.3, 0.6, 1.0) for dk in (8, 13, 19)]
BASE = (0.3, 8, 3.0)


def games_for(base: dict, v: tuple) -> pd.DataFrame:
  path = OUT / f"w{v[0]}_d{v[1]}_hl{v[2]}.parquet"
  if path.exists():
    return pd.read_parquet(path)
  cfg = copy.deepcopy(base)
  cfg["team_model"]["prior_weight"], cfg["team_model"]["prior_decay_week"], cfg["team_model"]["half_life_weeks"] = v
  with ProcessPoolExecutor(max_workers=6) as ex:
    d = pd.concat(list(ex.map(rp.season_ranks, [cfg] * 6, range(2021, 2027))), ignore_index=True)
  d = d.rename(columns={"location_x": "location"}).drop(columns=["location_y"], errors="ignore")
  OUT.mkdir(parents=True, exist_ok=True)
  d.to_parquet(path)
  return d


QUICK_VARIANTS = [(0.6, 13, 3.0), (1.0, 19, 3.0), (0.3, 8, 6.0), (1.0, 19, 6.0)]
QUICK_SEASONS = [2022, 2023, 2025]


def _job(a):
  cfg, season = a
  return rp.season_ranks(cfg, season)


def quick(base: dict):
  """Direction check: a few variants on three sample seasons, all season jobs in one pool, scored with the
  shipped (fixed) win-chance formula instead of a walk-forward refit. Current settings come from the darts cache."""
  wm = base["report"]["win_model"]
  jobs = []
  for v in QUICK_VARIANTS:
    cfg = copy.deepcopy(base)
    cfg["team_model"]["prior_weight"], cfg["team_model"]["prior_decay_week"], cfg["team_model"]["half_life_weeks"] = v
    jobs += [(cfg, s) for s in QUICK_SEASONS]
  with ProcessPoolExecutor(max_workers=6) as ex:
    parts = list(ex.map(_job, jobs))
  cfg = copy.deepcopy(base)
  cfg["data"]["history_seasons"] = 9
  g = elo.finished(D.load_all(cfg).schedules)
  elo_diff = dict(zip(g.game_id, elo.run(g, wm["elo_k"], wm["elo_hfa"], wm["elo_revert"], wm["elo_margin"])[0]))

  def prep(d):
    d = d.rename(columns={"location_x": "location"})
    d = d[d.season.isin(QUICK_SEASONS) & (d.home_score != d.away_score)].copy()
    y = (d.home_score > d.away_score).astype(float)
    home = (d.location != "Neutral").astype(float)
    gap = d.away_rank - d.home_rank
    x = wm["home"] * home + wm["rank_gap"] * gap + wm["elo_per_100"] * d.game_id.map(elo_diff) / 100
    return pd.DataFrame({"season": d.season, "week": d.week, "y": y,
                         "blend": (1 / (1 + np.exp(-x)) - y) ** 2,
                         "rank": (1 / (1 + np.exp(-(0.18 + 0.045 * gap))) - y) ** 2,
                         "mae": (d.model_margin - (d.home_score - d.away_score)).abs(),
                         "pick": ((gap > 0) == (y > 0)).astype(float)}).set_index(d.game_id)
  b = prep(pd.read_parquet(ROOT / "cache" / "darts_base.parquet"))
  sw = (b.season.astype(str) + "-" + b.week.astype(str)).to_numpy()
  keys = np.unique(sw)
  idx = [np.flatnonzero(sw == k) for k in keys]
  rng = np.random.default_rng(0)
  boot = [np.concatenate([idx[i] for i in rng.integers(0, len(keys), len(keys))]) for _ in range(2000)]
  early = (b.week <= 8).to_numpy()
  print(f"\n{len(b)} games ({', '.join(map(str, QUICK_SEASONS))}, weeks 2+). Current settings (0.3 / fades by week 8 / "
        f"half-life 3): blend Brier {b.blend.mean():.4f}, rank Brier {b['rank'].mean():.4f}, margin MAE "
        f"{b.mae.mean():.2f}, better rank won {b.pick.mean():.1%}")
  print("Diff vs current: negative = better for Brier/MAE, [95% CI], weeks 2-8 | 9+;  * = CI excludes 0\n")
  for i, v in enumerate(QUICK_VARIANTS):
    t = prep(pd.concat(parts[i * len(QUICK_SEASONS):(i + 1) * len(QUICK_SEASONS)])).reindex(b.index)
    out = [f"last season {v[0]:.1f} at wk1, fades by wk {v[1]:2d}{' (never)' if v[1] == 19 else '        '}, half-life {v[2]:.0f}"]
    for col in ("blend", "rank", "mae"):
      e = (t[col] - b[col]).to_numpy()
      bs = [e[x].mean() for x in boot]
      lo, hi = np.percentile(bs, 2.5), np.percentile(bs, 97.5)
      out.append(f"{col} {e.mean():+.4f} [{lo:+.4f},{hi:+.4f}]{'*' if hi < 0 or lo > 0 else ' '} "
                 f"{e[early].mean():+.4f}|{e[~early].mean():+.4f}")
    out.append(f"pick {t.pick.mean():.1%}")
    print("  ".join(out))


if __name__ == "__main__":
  base = load_config()
  if "--quick" in sys.argv:
    quick(base)
    sys.exit()
  wm = base["report"]["win_model"]
  cfg = copy.deepcopy(base)
  cfg["data"]["history_seasons"] = 9
  g = elo.finished(D.load_all(cfg).schedules)
  elo_diff = dict(zip(g.game_id, elo.run(g, wm["elo_k"], wm["elo_hfa"], wm["elo_revert"], wm["elo_margin"])[0]))
  test = list(range(2022, 2027))
  res, rows = {}, []
  for v in VARIANTS:
    d = games_for(base, v)
    print(f"variant weight {v[0]}, fades by week {v[1]}, half-life {v[2]}: {len(d)} games", flush=True)
    d = d[d.home_score != d.away_score].copy()
    d["won"] = (d.home_score > d.away_score).astype(float)
    d["home"] = (d.location != "Neutral").astype(float)
    d["rank_gap"] = d.away_rank - d.home_rank
    d["elo"] = d.game_id.map(elo_diff) / 100
    d["abs_err"] = (d.model_margin - (d.home_score - d.away_score)).abs()
    for name, cols in (("blend", ["home", "rank_gap", "elo"]), ("rank", ["home", "rank_gap"])):
      d[f"p_{name}"] = np.nan
      for s in test:
        tr, m = d[d.season < s], (d.season == s)
        w = logit_fit(tr[cols].to_numpy(float), tr.won.to_numpy(float))
        d.loc[m, f"p_{name}"] = 1 / (1 + np.exp(-d.loc[m, cols].to_numpy(float) @ w))
    te = d[d.season.isin(test) & d.spread_line.notna()].set_index("game_id")
    res[v] = te
  b = res[BASE]
  sw = (b.season.astype(str) + "-" + b.week.astype(str)).to_numpy()
  keys = np.unique(sw)
  idx = [np.flatnonzero(sw == k) for k in keys]
  rng = np.random.default_rng(0)
  boot = [np.concatenate([idx[i] for i in rng.integers(0, len(keys), len(keys))]) for _ in range(2000)]
  y = b.won.to_numpy()
  early = (b.week <= 8).to_numpy()

  def cmp(v, col):
    t = res[v].reindex(b.index)
    if col == "abs_err":
      e = t.abs_err.to_numpy() - b.abs_err.to_numpy()
    else:
      e = (t[col].to_numpy() - y) ** 2 - (b[col].to_numpy() - y) ** 2
    bs = [e[x].mean() for x in boot]
    return e.mean(), np.percentile(bs, 2.5), np.percentile(bs, 97.5), e[early].mean(), e[~early].mean()

  print(f"\n{len(b)} test games 2022-2026. Each diff vs current settings (0.3 / week 8 / half-life 3): negative = "
        f"better, [95% CI], then weeks 2-8 | 9+\n")
  for v in VARIANTS:
    out = [f"w {v[0]:.1f} fade {v[1]:2d} hl {v[2]:.0f}"]
    for col, label in (("p_blend", "blend Brier"), ("p_rank", "rank Brier"), ("abs_err", "margin MAE")):
      m, lo, hi, e1, e2 = cmp(v, col)
      flag = "*" if hi < 0 else ("x" if lo > 0 else " ")
      out.append(f"{label} {m:+.4f} [{lo:+.4f},{hi:+.4f}]{flag} {e1:+.4f}|{e2:+.4f}")
    print("  ".join(out))
  print(f"\nbase levels: blend Brier {((b.p_blend - y) ** 2).mean():.4f}, rank Brier {((b.p_rank - y) ** 2).mean():.4f}, "
        f"margin MAE {b.abs_err.mean():.2f}.  * = CI excludes 0 (better), x = worse")
