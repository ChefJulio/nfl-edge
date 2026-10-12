"""Walk-forward backtest: adjusted model vs raw stats vs Vegas-scaled raw, predicting next-week fantasy points.

For every test week, everything the model uses is as-of the prior week, and every learned component is trained
only on seasons before the test season. Evaluation set: players who actually played that week and had >= 2 games
earlier in the season (so the raw-stats baseline exists).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

RELEVANT_TOP = {"QB": 24, "RB": 48, "WR": 60, "TE": 24}


def raw_baselines(engine, season: int, week: int) -> pd.DataFrame:
  a = engine.actual
  prior = a[(a.season == season) & (a.week < week)]
  raw = prior.groupby("gsis_id").agg(raw_fpg=("actual", "mean"), raw_games=("actual", "size"),
                                     raw_team=("team", "last"))
  tl = engine.team_ledger
  team_ppg = tl[(tl.season == season) & (tl.week < week)].groupby("team").points.mean()
  g = engine.games(season, week)
  implied = {}
  for _, x in g.iterrows():
    if pd.notna(x.total_line) and pd.notna(x.spread_line):
      implied[x.home_team] = x.total_line / 2 + x.spread_line / 2
      implied[x.away_team] = x.total_line / 2 - x.spread_line / 2
  return raw, team_ppg, implied


def run(engine, seasons: list[int], start_week: int = 3, use_injuries: bool = False,
        weeks: dict | None = None) -> pd.DataFrame:
  out = []
  for s in seasons:
    engine.train(s, use_injuries=use_injuries)
    last = engine.data.completed_weeks(s)
    for w in (weeks or {}).get(s, range(start_week, last + 1)):
      p = engine.project_week(s, w, use_injuries=use_injuries, quiet=True)
      p = engine.attach_actuals(p, s, w)
      raw, team_ppg, implied = raw_baselines(engine, s, w)
      p = p.join(raw, on="gsis_id")
      scale = p.team.map(implied) / p.team.map(team_ppg)
      p["vegas"] = p.raw_fpg * scale.fillna(1.0)
      out.append(p)
  return pd.concat(out, ignore_index=True)


def evaluate(res: pd.DataFrame, positions, min_games: int = 2, ecr_only: bool = False) -> pd.DataFrame:
  """ecr_only=True restricts to player-weeks with a pre-kickoff expert rank so all five methods compare on
  identical rows."""
  d = res[res.played & (res.raw_games >= min_games) & res.pos.isin(positions)].copy()
  if ecr_only:
    d = d[d.ecr_pts.notna()]
  d["consensus"] = d[["proj", "raw_fpg", "vegas"]].mean(axis=1)
  d["crank"] = d.groupby(["season", "week", "pos"]).consensus.rank(ascending=False)
  rows = []
  for pos in positions:
    for subset, g in (("all", d[d.pos == pos]),
                      ("relevant", d[(d.pos == pos) & (d.crank <= RELEVANT_TOP.get(pos, 50))])):
      if g.empty:
        continue
      row = {"pos": pos, "subset": subset, "n": len(g)}
      for name, col in (("model", "proj"), ("raw", "raw_fpg"), ("vegas", "vegas"), ("modelonly", "proj_model"),
                        ("ecr", "ecr_pts")):
        if col not in g or g[col].isna().any():
          continue
        err = g.actual - g[col]
        row[f"mae_{name}"] = err.abs().mean()
        row[f"rmse_{name}"] = np.sqrt((err ** 2).mean())
        row[f"r_{name}"] = g[[col, "actual"]].corr().iloc[0, 1]
        row[f"rank_{name}"] = g.groupby(["season", "week"]).apply(
          lambda x: x[col].corr(x.actual, method="spearman") if len(x) > 4 else np.nan, include_groups=False).mean()
      rows.append(row)
  return pd.DataFrame(rows)


def format_table(ev: pd.DataFrame, methods=("model", "raw", "vegas")) -> str:
  cols = ["pos", "subset", "n"] + [f"{k}_{m}" for k in ("mae", "r", "rank") for m in methods]
  return ev[[c for c in cols if c in ev]].to_string(index=False, float_format=lambda x: f"{x:.3f}")
