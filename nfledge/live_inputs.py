"""Archive what each live build fed the model (INSIGHTS 2026-10-16, thread 1). Pipeline only: never a model input.

Backtests read Vegas lines as they stand after the game (effectively closing), pbp game wind (max over the game) and
nflverse's Friday ECR; live builds use that day's line, an Open-Meteo forecast and whatever ECR scrape exists. None of
that was kept, so how far backtest accuracy overstates live accuracy couldn't be measured. Each current-week build
writes <site>/data/live_inputs/<season>_<week>_<YYYYmmddTHHMM>.json (committed to the archive branch by CI):
  built        UTC time of the build
  ecr_scrape   the FantasyPros scrape date the build's ECR came from (None: no scrape for this week yet)
  games        game_id -> [home spread, total] as the schedule had them at build time, plus the per-team inputs the
               projections used: wind fed to the model (mph), and whether the game was already final (then the
               wind is the game's recorded wind, not a forecast)
  stats / p    gsis_id -> [proj, proj_no_inj, avail, ecr, wind_penalty, implied_pts, spread_team] as shown
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

STATS = ["proj", "proj_no_inj", "avail", "ecr", "wind_penalty", "implied_pts", "spread_team"]


def _num(v, nd=3):
  try:
    v = float(v)
  except (TypeError, ValueError):
    return None
  return None if np.isnan(v) else round(v, nd)


def write(site: Path, data, games: pd.DataFrame, proj: pd.DataFrame, season: int, week: int) -> Path:
  now = datetime.now(timezone.utc)
  e = data.ecr
  ecr_scrape = None
  if e is not None and len(e):
    sel = e[(e.season == season) & (e.week == week)]
    if len(sel):
      ecr_scrape = str(pd.to_datetime(sel.scrape_date).max().date())
  wind = proj.drop_duplicates("game_id").set_index("game_id").wind if "wind" in proj else pd.Series(dtype=float)
  g_out = {}
  for g in games.itertuples():
    g_out[g.game_id] = {"spread": _num(g.spread_line, 1), "total": _num(g.total_line, 1),
                        "wind_mph": _num(wind.get(g.game_id), 1), "final": bool(pd.notna(g.home_score))}
  cols = [c for c in STATS if c in proj]
  p = {gid: [_num(v) for v in vals] for gid, *vals in proj[["gsis_id", *cols]].itertuples(index=False)}
  out = Path(site) / "data" / "live_inputs"
  out.mkdir(parents=True, exist_ok=True)
  f = out / f"{season}_{week:02d}_{now:%Y%m%dT%H%M}.json"
  f.write_text(json.dumps({"built": now.isoformat(timespec="seconds"), "season": season, "week": week,
                           "ecr_scrape": ecr_scrape, "games": g_out, "stats": cols, "p": p},
                          separators=(",", ":")), encoding="utf-8")
  return f
