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
import os
import sys
import time
from pathlib import Path

# Parallel workers each get an equal share of the cores for the math libraries; left alone, every worker's BLAS
# grabs all cores and they thrash (3 workers x 16 threads made small dense solves crawl). Must run before numpy
# is imported; worker processes re-run this module top, so they inherit it.
_jobs = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--jobs=")), None)
if _jobs is None:
  _jobs = int(os.environ.get("NFLEDGE_JOBS", "1"))
os.environ["NFLEDGE_JOBS"] = str(_jobs)
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
  os.environ.setdefault(_v, str(max(1, (os.cpu_count() or 4) // max(_jobs, 1))))

import numpy as np  # noqa: E402
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
  "depth_per_team": variant(experiments__depth_per_team=True),  # (AR) 2026-10-18
  # --- previously decided on 1-2 seasons; re-checked on 5 ---
  "no_implied_total": variant(experiments__implied_total=False),
  "def_drop": variant(experiments__def_terms="drop"),
  "def_sign": variant(experiments__def_terms="sign"),
  "coach_aggr": variant(experiments__coach_aggr=True),
  "rz_struct": variant(experiments__rz_struct=True),
  "age_input": variant(experiments__age_input=True),
  "age_rbwr": variant(experiments__age_input=["RB", "WR"]),
  "age_rbwr_quad": variant(experiments__age_input=["RB", "WR"], experiments__age_shape="quadratic"),
  "air_yards": variant(experiments__air_yards=True),
  "snap_input": variant(experiments__snap_input=True),
  "route_input": variant(experiments__route_input=True),
  "debut_prior": variant(experiments__debut_prior=True),
  "debut_d12": variant(experiments__debut_prior="d12"),
  "practice_role": variant(injuries__practice_role=True),
  "scratch_carry": variant(injuries__scratch_carry=True),
  "practice_role_skill": variant(injuries__practice_role=["RB", "WR", "TE"]),
  "job_security": variant(injuries__job_security=True),
  "share_quality": variant(experiments__share_quality=True),
  "practice_rest": variant(injuries__practice_rest=True),
  "practice_rest_age": variant(injuries__practice_rest="age"),
  "grade_prior": variant(experiments__grade_prior=True),
  "practice_reason": variant(injuries__practice_reason=True),
  "practice_prev": variant(injuries__practice_prev=True),
  "tuesday_prior": variant(injuries__tuesday_prior=True),
  "week_model": variant(injuries__week_model=True),
  "stakes_scratch": variant(injuries__stakes_scratch=True),
  "no_sleeper": variant(experiments__sleeper_blend={}),
  "share_hl_3": variant(player_model__share_half_life_weeks=3.0),
  "share_hl_8": variant(player_model__share_half_life_weeks=8.0),
  "team_hl_2": variant(team_model__half_life_weeks=2.0),
  "team_hl_5": variant(team_model__half_life_weeks=5.0),
  "snap_map_rosters": variant(experiments__snap_map="rosters"),
  # charting stats (owner, 2026-10-14): over-expected skill from nflverse's cp / xyac models
  "croe": variant(experiments__croe=True),
  "yacoe": variant(experiments__yacoe=True),
  "cpoe": variant(experiments__cpoe=True),
  "oe_all": variant(experiments__croe=True, experiments__yacoe=True, experiments__cpoe=True),  # the old snap id map (A/B for the 2026-10-14 fix)
  "td_k_50": variant(player_model__td_blend_k=50),
  "td_k_400": variant(player_model__td_blend_k=400),
  "no_qb_effects": variant(team_model__qb_effects=False),
  "qb_newteam": variant(team_model__qb_newteam_dropbacks=150),  # INSIGHTS (R)
  "qb_a100": variant(team_model__qb_alpha_grid=[100]),  # INSIGHTS (BB): less QB shrinkage
  "qb_a30": variant(team_model__qb_alpha_grid=[30]),  # INSIGHTS (BB)
  "qb_run": variant(team_model__qb_rush_effects=True),  # INSIGHTS (BB) qbrun
  "qb_prior": variant(team_model__qb_prior_scale="tune"),  # INSIGHTS (BC) qbprior
  "qb_edge": variant(game_model__qb_career_edge=True),  # INSIGHTS (BC) qbedge
  "return_role": variant(experiments__return_role=True),  # INSIGHTS (BF)
  "return_starters": variant(experiments__return_role="starters"),  # INSIGHTS (BH)
  "redistribution_0": variant(injuries__redistribution_scale=0.0),
  "redistribution_1": variant(injuries__redistribution_scale=1.0),
  "redist_conserve": variant(injuries__redistribute_conserve=True),
  "absorb_snap": variant(injuries__absorb_snap=True),  # INSIGHTS (U)
  "snap_trend": variant(experiments__snap_trend=True),  # INSIGHTS (T)
  # INSIGHTS (V): how much of a sitting starter's work reaches RBs (others stay 0.5)
  "rb_scale_65": variant(injuries__redistribution_scale={"RB": 0.65, "default": 0.5}),
  "rb_scale_80": variant(injuries__redistribution_scale={"RB": 0.8, "default": 0.5}),
  "rb_scale_100": variant(injuries__redistribution_scale={"RB": 1.0, "default": 0.5}),
  # INSIGHTS (Z): the TD blend k (weight on actual TDs = n / (n + k)); 1e9 = expected TDs only
  **{f"td_k_{k}": variant(player_model__td_blend_k=k) for k in (25, 50, 100, 300, 600)},
  "td_k_xtd": variant(player_model__td_blend_k=1e9),
  # (AG) season weights in player efficiency (INSIGHTS, pre-registered 2026-10-17): last x two back; today 0.6 / 0.3
  **{f"effw_{int(a * 10)}_{int(b * 10)}": variant(player_model__eff_season_weights=[1.0, a, b])
     for a in (0.3, 0.6, 1.0) for b in (0.0, 0.3, 0.6)},
  # INSIGHTS (AC): the redistribution trigger, smallest share handed out (today tgt .08, carry .15)
  **{f"minshare_{int(t * 100)}_{int(c * 100)}": variant(injuries__redistribute_min_share={"tgt_share": t, "carry_share": c})
     for t in (0.04, 0.06, 0.08, 0.12) for c in (0.08, 0.15, 0.25) if (t, c) != (0.08, 0.15)},
  "newcomer_05": variant(experiments__newcomer_scale=0.5),
  # (AK) explosiveness in WR receiving TDs (INSIGHTS, pre-registered 2026-10-17)
  "wr_td_explosive": variant(experiments__wr_td_explosive=True),
  # (AJ) the shrinkage cap (INSIGHTS, pre-registered 2026-10-17); today 2000
  **{f"kmax_{int(k)}": variant(player_model__shrink_k_max=k) for k in (500, 1000, 5000, 100000)},
  # (AI) the newcomer multiplier grid (INSIGHTS, pre-registered 2026-10-17); today 0.5
  **{f"newcomer_s{int(x * 10)}": variant(experiments__newcomer_scale=x) for x in (0.3, 0.4, 0.6, 0.7)},
  "ecr_blend_all": variant(experiments__ecr_blend_positions=["QB", "RB", "WR", "TE"]),
  "ecr_blend_none": variant(experiments__ecr_blend_positions=[]),
  # --- previously hand-set, never tested ---
  "train_3": variant(data__train_seasons=3),
  "train_4": variant(data__train_seasons=4),
  "wind_linear": variant(experiments__wind_mode="linear"),
  "wind_quadratic": variant(experiments__wind_mode="quadratic"),
  "wind_off": variant(player_model__wind_penalty_per_mph=0.0),
  "prior_weight_0": variant(team_model__prior_weight=0.0),
  "prior_weight_06": variant(team_model__prior_weight=0.6),
  "prior_decay_4": variant(team_model__prior_decay_week=4),
  "prior_decay_12": variant(team_model__prior_decay_week=12),
  "eff_weights_flat": variant(player_model__eff_season_weights=[1.0, 1.0, 1.0]),
  "eff_weights_steep": variant(player_model__eff_season_weights=[1.0, 0.3, 0.1]),
  "minor_fitted": variant(player_model__minor_priors="fitted"),
  "starter_fitted": variant(player_model__starter_share="fitted"),
  "qb_inexp_100": variant(team_model__qb_inexp_dropbacks=100),
  "qb_inexp_300": variant(team_model__qb_inexp_dropbacks=300),
  "qb_inexp_alpha_10": variant(team_model__qb_inexp_alpha=10.0),
  "redist_min_low": variant(injuries__redistribute_min_share={"tgt_share": 0.05, "carry_share": 0.10}),
  "redist_min_high": variant(injuries__redistribute_min_share={"tgt_share": 0.12, "carry_share": 0.20}),
  "gb_small": variant(injuries__gb_iterations=100, injuries__gb_max_depth=2),
  "gb_large": variant(injuries__gb_iterations=300, injuries__gb_max_depth=5),
  "ranges_plain": variant(uncertainty__games_factor=0.0, uncertainty__low_sample_widen=1.0,
                          uncertainty__injury_boost_widen=1.0),
  # --- round 2: wind penalty grid (threshold mph x slope per mph; cap 25%), per-position share half-life,
  # game-script (spread-aware) shares ---
  **{f"wind_t{t}_s{int(s * 100)}": variant(player_model__wind_threshold_mph=t, player_model__wind_penalty_per_mph=s)
     for t in (10, 15, 20) for s in (0.01, 0.02, 0.03) if (t, s) != (15, 0.02)},
  # round 4: extend the wind grid past its edge (round 2 best at threshold 10, slope 3%)
  **{f"wind_t{t}_s{int(s * 100)}_c{int(c * 100)}": variant(player_model__wind_threshold_mph=t,
                                                          player_model__wind_penalty_per_mph=s,
                                                          player_model__wind_penalty_cap=c)
     for t in (0, 5, 10) for s in (0.02, 0.03, 0.04) for c in (0.25, 0.40)},
  "hl_te5": variant(player_model__share_half_life_weeks={"default": 3.0, "TE": 5.0}),
  "hl_te5_wr5": variant(player_model__share_half_life_weeks={"default": 3.0, "TE": 5.0, "WR": 5.0}),
  "hl_qb5_te5": variant(player_model__share_half_life_weeks={"default": 3.0, "TE": 5.0, "QB": 5.0}),
  "spread_shares": variant(experiments__spread_shares=True),
  # rookie / backup priors: draft tiers by overall pick instead of round
  "draft_picks_fine": variant(player_model__draft_tier_picks=[10, 32, 64, 100, 160]),
  "draft_picks_mid": variant(player_model__draft_tier_picks=[32, 100]),
  # usage shares: pull each team's projected target / carry totals toward the measured typical total
  "share_norm_05": variant(experiments__share_normalize=0.5),
  "share_norm_10": variant(experiments__share_normalize=1.0),
  "share_norm_03": variant(experiments__share_normalize=0.3),
  "share_norm_07": variant(experiments__share_normalize=0.7),
  "share_norm_tgt05": variant(experiments__share_normalize_tgt=0.5),
  "share_norm_car05": variant(experiments__share_normalize_carries=0.5),
  "share_norm_car07_tgt03": variant(experiments__share_normalize_carries=0.7, experiments__share_normalize_tgt=0.3),
  # final per-position linear calibration of projections (too extreme at both ends)
  "calib_linear": variant(experiments__player_calibration="linear"),
  # 2026-10-13 owner ideas. RB: team committee tendency in the carry-share model; goal-line (inside-10) share
  # tilt in the rush-TD model; both. Team ratings: plays against elite opposing UNITS weighted up (top-K with
  # boost b per elite side, or a linear ramp by opponent percentile).
  "rbbc": variant(experiments__rbbc=True),
  "gl_share": variant(experiments__gl_share=True),
  "rb_both": variant(experiments__rbbc=True, experiments__gl_share=True),
  # owner follow-up: goal-line role scaled by how often the team reaches the goal line (structural, not flat)
  "gl_struct": variant(experiments__gl_struct=True),
  # owner follow-up: QB rushing TDs by run type (scrambles vs designed runs; team scoring boosts designed only)
  "qb_rush_split": variant(experiments__qb_rush_split=True),
  "elite_t8_b05": variant(experiments__elite_boost=0.5, experiments__elite_top=8),
  "elite_t8_b1": variant(experiments__elite_boost=1.0, experiments__elite_top=8),
  "elite_t5_b1": variant(experiments__elite_boost=1.0, experiments__elite_top=5),
  "elite_t12_b05": variant(experiments__elite_boost=0.5, experiments__elite_top=12),
  "elite_lin_1": variant(experiments__elite_boost=1.0, experiments__elite_mode="linear"),
  # owner follow-up: "elite" = top 5 or top 3 only, at lighter and heavier boosts
  "elite_t5_b025": variant(experiments__elite_boost=0.25, experiments__elite_top=5),
  "elite_t5_b05": variant(experiments__elite_boost=0.5, experiments__elite_top=5),
  "elite_t3_b025": variant(experiments__elite_boost=0.25, experiments__elite_top=3),
  "elite_t3_b05": variant(experiments__elite_boost=0.5, experiments__elite_top=3),
  "elite_t3_b1": variant(experiments__elite_boost=1.0, experiments__elite_top=3),
  # 2026-10-12 audit outcome, tested together for interactions before adopting
  "adopted": variant(player_model__share_half_life_weeks=3.0, uncertainty__games_factor=0.0,
                     uncertainty__low_sample_widen=1.0, uncertainty__injury_boost_widen=1.0,
                     experiments__wind_mode="linear", player_model__minor_priors="fitted"),
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
  # The fitted points-formula weights for this season's training, so their stability can be checked over seasons.
  for c, v in zip(eng.gm.points.cols, eng.gm.points.coef[1:]):
    res[f"fit_points_{c}"] = float(v)
  res["fit_alpha_st"] = float(eng.tm.alphas.get("st", np.nan))
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
  """95% CI of the mean of diff, resampling whole groups: season-weeks (the default use), or players (gsis_id)."""
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
        # the same interval resampling whole players instead (a player's games share his errors; INSIGHTS thread 8)
        plo, phi = week_bootstrap(d, m.gsis_id)
        row.update({"d_mae": d.mean(), "ci_lo": lo, "ci_hi": hi, "pl_lo": plo, "pl_hi": phi,
                    "verdict": "better" if hi < 0 else "worse" if lo > 0 else "no difference"})
      rows.append(row)
  return pd.DataFrame(rows)


def decision_pairs(ref_rows: pd.DataFrame, within: float = 6.0) -> pd.DataFrame:
  """Start / sit decisions (INSIGHTS thread 4, 2026-10-16): every pair of the reference's relevant rows at the same
  season / week / position whose consensus ranks are within `within`. Fixed once, so every variant decides the same
  pairs. Columns: season, week, pos, i, j (keys into gsis ids), a_i - a_j."""
  out = []
  for (s, w, pos), g in ref_rows.sort_values("crank").groupby(["season", "week", "pos"]):
    ids, cr, a = g.gsis_id.to_numpy(), g.crank.to_numpy(), g.actual.to_numpy()
    for x in range(len(g)):
      for y in range(x + 1, len(g)):
        if cr[y] - cr[x] > within:
          break
        out.append((s, w, pos, ids[x], ids[y], a[x] - a[y]))
  return pd.DataFrame(out, columns=["season", "week", "pos", "i", "j", "da"])


def decision_table(results: dict[str, pd.DataFrame], ref: str) -> pd.DataFrame:
  """Points gained per pair over a coin flip by starting the player a variant projects higher: sign(p_i - p_j) x
  (a_i - a_j) / 2 (ties count 0). Next to MAE in every comparison; differences vs the reference with a 95% CI over
  season-weeks."""
  pairs = decision_pairs(relevant(results[ref]))
  keys = ["season", "week", "gsis_id"]
  gains = {}
  for name, res in results.items():
    p = res[keys + ["proj"]].drop_duplicates(keys).set_index(keys).proj
    pi = p.reindex(pd.MultiIndex.from_arrays([pairs.season, pairs.week, pairs.i])).to_numpy()
    pj = p.reindex(pd.MultiIndex.from_arrays([pairs.season, pairs.week, pairs.j])).to_numpy()
    gains[name] = np.nan_to_num(np.sign(pi - pj)) * pairs.da.to_numpy() / 2
  rows, wk = [], pairs.season.astype(str) + "-" + pairs.week.astype(str)
  for name in results:
    for pos in POS + ["ALL"]:
      m = (pairs.pos == pos).to_numpy() if pos != "ALL" else np.ones(len(pairs), bool)
      row = {"variant": name, "pos": pos, "pairs": int(m.sum()), "gain": gains[name][m].mean()}
      if name != ref:
        d = pd.Series(gains[name][m] - gains[ref][m])
        lo, hi = week_bootstrap(d, wk[m].reset_index(drop=True))
        row.update({"d_gain": d.mean(), "ci_lo": lo, "ci_hi": hi,
                    "verdict": "better" if lo > 0 else "worse" if hi < 0 else "no difference"})
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
  print()
  print("Range calibration (share of actuals inside; targets 0.80 and 0.50) and availability Brier (players on "
        "the injury report; lower is better):")
  for name, res in results.items():
    d = relevant(res)
    cov80 = ((d.actual >= d.p10) & (d.actual <= d.p90)).mean()
    cov50 = ((d.actual >= d.p25) & (d.actual <= d.p75)).mean()
    rep = res[res.status.fillna("").ne("")]
    brier = float(((rep.avail - rep.played.astype(float)) ** 2).mean()) if len(rep) else float("nan")
    print(f"  {name:22s} 10-90: {cov80:.3f}  25-75: {cov50:.3f}  avail Brier: {brier:.4f} (n={len(rep)})")
  print(f"\nSeasons {seasons}; reference = {names[0]}; relevant rows of the reference; MAE in fantasy points.")
  print(out.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
  print("\nStart / sit decisions: pairs of the reference's relevant players within 6 consensus ranks (same week and "
        "position); points gained per pair over a coin flip by starting the one projected higher (higher = better).")
  print(decision_table(results, names[0]).to_string(index=False, float_format=lambda x: f"{x:.3f}"))
  for s in seasons:
    by = compare({k: v[v.season == s] for k, v in results.items()}, names[0])
    by = by[by.pos == "ALL"]
    print(f"\n{s}: " + "  ".join(f"{r.variant} {r.mae:.3f}" + (f" ({r.d_mae:+.3f})" if r.variant != names[0] else "")
                                 for r in by.itertuples()))


if __name__ == "__main__":
  main()
