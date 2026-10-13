"""Do team ratings get better at predicting the future when plays against elite opposing units count more?

Usage: python tools/elite_eval.py [SEASONS] [--variants=a,b,...]   (default 2021-2025; variants from experiments.py)

Walk-forward, the way the site uses the ratings: for each week of each test season, fit ratings on everything
before that week (penalties tuned on the two prior seasons, as the engine does), predict every team-game's EPA per
play in that week (offense + opposing defense + home + quarterback), and score the play-weighted squared error.
Each variant is compared with baseline on identical team-games; the 95% CI resamples whole season-weeks.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from experiments import VARIANTS, parse_seasons, week_bootstrap  # noqa: E402
from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.team_model import UNITS, TeamModel  # noqa: E402


def predict_unit(r, plays: pd.DataFrame, u: str) -> np.ndarray:
  pred = (r.intercept[u] + plays.posteam.map(r.off[u]).fillna(0).to_numpy()
          + plays.defteam.map(r.dfn[u]).fillna(0).to_numpy()
          + (r.home[u] + r.home_div.get(u, 0.0) * plays["div"].to_numpy(float)) * plays.home.to_numpy(float))
  if u == "pass" and r.qb is not None and "qb" in plays:
    prior = plays.qb.map(r.qb_prior).fillna(0.0) if r.qb_prior is not None else 0.0
    pred = pred + plays.qb.map(r.qb).fillna(0.0).to_numpy() + r.qb_inexp * (prior < r.inexp_cut).to_numpy(float)
  return pred


def season_errors(tm: TeamModel, data, season: int) -> pd.DataFrame:
  prior = [s for s in data.seasons if s < season][-2:]
  tm.tune_alphas([(s, w) for s in prior for w in range(4, data.completed_weeks(s) + 1)])
  rows = []
  for wk in range(2, data.completed_weeks(season) + 1):
    r = tm.fit(season, wk)
    for u in UNITS:
      p = tm.plays[u]
      t = p[(p.season == season) & (p.week == wk)]
      if t.empty:
        continue
      g = t.assign(pred=predict_unit(r, t, u)).groupby(["game_id", "posteam"]).agg(
        epa=("epa", "mean"), pred=("pred", "mean"), n=("epa", "size")).reset_index()
      g["unit"], g["season"], g["week"] = u, season, wk
      rows.append(g)
  d = pd.concat(rows, ignore_index=True)
  d["sq"] = d.n * (d.epa - d.pred) ** 2
  return d


def main():
  args = [a for a in sys.argv[1:] if not a.startswith("--")]
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  seasons = parse_seasons(args[0]) if args else list(range(2021, 2026))
  names = ["baseline"] + opt.get("variants", "elite_t8_b05,elite_t8_b1,elite_t5_b1,elite_t12_b05,elite_lin_1").split(",")
  base = load_config()
  base["data"]["history_seasons"] = 8
  data = D.load_all(base)
  res = {}
  for n in names:
    cfg = VARIANTS[n](base)
    tm = TeamModel(data.pbp, cfg, data.qb_career)
    res[n] = pd.concat([season_errors(tm, data, s) for s in seasons], ignore_index=True)
    print(f"  {n}: done", flush=True)
  keys = ["season", "week", "game_id", "posteam", "unit"]
  ref = res["baseline"]
  print(f"\nSeasons {seasons}. Next-week team-game EPA/play prediction, play-weighted MSE x 1000 (lower = better).")
  print(f"{'variant':16s} {'unit':6s} {'mse':>8s} {'diff':>8s} {'95% CI':>20s}  verdict")
  for n in names:
    j = ref.merge(res[n][keys + ["sq"]], on=keys, suffixes=("_ref", ""))
    for u in list(UNITS) + ["ALL"]:
      m = j if u == "ALL" else j[j.unit == u]
      wsum = m.n.sum()
      mse = 1000 * m.sq.sum() / wsum
      if n == "baseline":
        print(f"{n:16s} {u:6s} {mse:8.3f}")
        continue
      # Per team-game difference in squared error, scaled so its mean equals the MSE difference shown.
      d = 1000 * (m.sq - m.sq_ref) / m.n.mean()
      lo, hi = week_bootstrap(d, m.season.astype(str) + "-" + m.week.astype(str))
      verdict = "better" if hi < 0 else "worse" if lo > 0 else "no difference"
      print(f"{n:16s} {u:6s} {mse:8.3f} {d.mean():+8.3f} {f'[{lo:+.3f}, {hi:+.3f}]':>20s}  {verdict}")


if __name__ == "__main__":
  main()
