"""Walk-forward test of the GAME model (team ratings -> predicted score), scored on real game results.

Usage: python tools/game_eval.py [SEASONS] [--history=N] [--jobs=N] [--only=fitted] [--set=sec.key=val;...] [--save=path]
  --set     config overrides (removal tests, 2026-10-15: e.g. --set="team_model.qb_effects=false")
  --only    restrict the points-formula variants; --save writes every game prediction (parquet) for paired comparisons

For each test season: tune the team-rating penalties and build the points-formula training rows on the two
seasons before it (exactly as the site trains), then predict every regular-season game week by week from data
before that week, model-only (no Vegas inputs), for each variant of the points formula:
  fitted   least squares chooses the special-teams weight (the live default)
  st_X     special-teams weight fixed at X points per point of net special-teams EPA edge (per team)
Scores: margin MAE (home - away), total MAE, winner accuracy, and Vegas's closing-line margin MAE for reference.
Differences vs 'fitted' get a 95% bootstrap CI over season-weeks. The fitted weight per season is printed too
(is it stable?). Ratings and training rows don't depend on the weight, so they are computed once per season.
"""
import copy
import os
import sys
import time
from pathlib import Path

_jobs = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--jobs=")), 1)
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
  os.environ.setdefault(_v, str(max(1, (os.cpu_count() or 4) // max(_jobs, 1))))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.team_model import GameModel, TeamModel, game_lines, team_game_ledger, team_volume_features  # noqa: E402

pd.set_option("display.width", 200)
# name -> (special-teams weight, seasons the points formula trains on; 2 = the training window)
VARIANTS = {"fitted": ("fitted", 2), "st_0": (0.0, 2), "st_1": (1.0, 2), "st_1.5": (1.5, 2), "st_2.5": (2.5, 2),
            "fitted_4yr": ("fitted", 4), "fitted_6yr": ("fitted", 6)}
# --only / --set travel by environment so parallel worker processes (which re-import this module) see them too
_opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
for _k in ("only", "set"):
  if _k in _opt:
    os.environ[f"GAME_EVAL_{_k.upper()}"] = _opt[_k]
if os.environ.get("GAME_EVAL_ONLY"):
  VARIANTS = {k: v for k, v in VARIANTS.items() if k in os.environ["GAME_EVAL_ONLY"].split(",")}


def overrides(cfg: dict) -> dict:
  for part in filter(None, os.environ.get("GAME_EVAL_SET", "").split(";")):
    key, _, val = part.partition("=")
    sec, k = key.split(".")
    v = {"true": True, "false": False}.get(val.lower(), val)
    if isinstance(v, str):
      try:
        v = float(v)
      except ValueError:
        pass
    cfg.setdefault(sec, {})[k] = v
  return cfg


def season_games(base: dict, history: int, season: int) -> tuple[pd.DataFrame, dict]:
  cfg = overrides(copy.deepcopy(base))
  cfg["data"]["history_seasons"] = history
  data = D.load_all(cfg)
  t0 = time.time()
  train = [s for s in data.seasons if s < season and s - 1 in data.seasons][-int(cfg["data"].get("train_seasons", 2)):]
  tm = TeamModel(data.pbp, cfg, data.qb_career)
  tm.tune_alphas([(s, w) for s in train for w in range(4, data.completed_weeks(s) + 1)])
  ledger = team_game_ledger(data.pbp, data.schedules)
  rows = GameModel(cfg).training_rows(tm, ledger, train)
  prior = [s for s in data.seasons if s < season and s - 1 in data.seasons]
  extra_rows = {s: GameModel(cfg).training_rows(tm, ledger, [s]) for s in prior if s not in train}
  sched = data.schedules
  sched = sched[(sched.season == season) & (sched.game_type == "REG") & sched.home_score.notna()]
  out, fitted_w = [], {}
  for name, (w, n_pts) in VARIANTS.items():
    c = copy.deepcopy(cfg)
    c["team_model"]["points_st_weight"] = w
    extra = [extra_rows[s] for s in prior[-n_pts:] if s in extra_rows]
    gm = GameModel(c).fit(rows, pd.concat(extra + [rows]) if extra else None)
    if w == "fitted":
      fitted_w.update({f"{k}@{n_pts}yr": v for k, v in zip(gm.points.cols, gm.points.coef[1:])})
    for wk in sorted(sched.week.unique()):
      if wk < 2:
        continue
      games = sched[sched.week == wk]
      r = tm.fit(season, int(wk))
      vf = team_volume_features(ledger, season, int(wk), c)
      # Each team's most recent starting QB before this week (knowable pre-game; the live site uses the projected
      # starter). Without this the QB effects drop out of the margin entirely.
      past = ledger[(ledger.season == season) & (ledger.week < wk) | (ledger.season < season)]
      starters = past.dropna(subset=["qb"]).sort_values(["season", "week"]).groupby("team").qb.last().to_dict()
      gl = game_lines(gm.predict(games, r, vf, use_vegas=False, starters=starters), games)
      gl = gl.merge(games[["game_id", "home_score", "away_score"]], on="game_id")
      gl["variant"], gl["season"] = name, season
      out.append(gl)
  print(f"  {season}: {time.time() - t0:.0f}s; fitted weights {', '.join(f'{k}={v:.2f}' for k, v in fitted_w.items())}",
        flush=True)
  return pd.concat(out, ignore_index=True), {"season": season, **fitted_w}


def boot_ci(diff: np.ndarray, groups: np.ndarray, n: int = 2000) -> tuple[float, float]:
  g = pd.DataFrame({"d": diff, "g": groups}).groupby("g").d.agg(["sum", "size"])
  s, c = g["sum"].to_numpy(), g["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(g), size=(n, len(g)))
  m = s[idx].sum(1) / c[idx].sum(1)
  return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def main():
  args = [a for a in sys.argv[1:] if not a.startswith("--")]
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  history = int(opt.get("history", 8))
  rng = args[0] if args else "2021-2025"
  a, _, b = rng.partition("-")
  seasons = list(range(int(a), int(b or a) + 1))
  base = load_config()
  if _jobs > 1:
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(max_workers=_jobs) as ex:
      parts = list(ex.map(season_games, [base] * len(seasons), [history] * len(seasons), seasons))
  else:
    parts = [season_games(base, history, s) for s in seasons]
  d = pd.concat([p[0] for p in parts], ignore_index=True)
  d["actual_margin"] = d.home_score - d.away_score
  d["actual_total"] = d.home_score + d.away_score
  d["err_m"] = (d.model_margin - d.actual_margin).abs()
  d["err_t"] = (d.model_total - d.actual_total).abs()
  d["win"] = np.sign(d.model_margin) == np.sign(d.actual_margin)
  d["wk"] = d.season.astype(str) + "-" + d.week.astype(str)
  if opt.get("save"):
    d.to_parquet(opt["save"], index=False)
  ref = d[d.variant == "fitted"].set_index("game_id")
  vegas = (d[d.variant == "fitted"].spread_line - d[d.variant == "fitted"].actual_margin).abs().mean()
  rows = []
  for name in VARIANTS:
    v = d[d.variant == name].set_index("game_id")
    diff = (v.err_m - ref.err_m.reindex(v.index)).to_numpy()
    lo, hi = boot_ci(diff, v.wk.to_numpy()) if name != "fitted" else (np.nan, np.nan)
    rows.append({"variant": name, "games": len(v), "margin_mae": v.err_m.mean(), "total_mae": v.err_t.mean(),
                 "winner_acc": v.win.mean(), "d_margin_vs_fitted": diff.mean(), "ci_lo": lo, "ci_hi": hi})
  print(f"\nGame model, seasons {seasons} (model-only, no Vegas inputs). Vegas closing-line margin MAE: {vegas:.3f}")
  print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:.3f}"))
  print("\nFitted points-formula weights by season (stability):")
  print(pd.DataFrame([p[1] for p in parts]).to_string(index=False, float_format=lambda x: f"{x:.3f}"))
  for s in seasons:
    by = d[d.season == s].groupby("variant").err_m.mean()
    print(f"  {s}: " + "  ".join(f"{k} {by[k]:.2f}" for k in VARIANTS))


if __name__ == "__main__":
  main()
