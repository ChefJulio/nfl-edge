"""Sleeper's weekly projections (supplied to Sleeper by RotoWire) as a second opinion blended into ours.

Pre-registered and tested 2026-10-15 (docs/INSIGHTS.md section 9, tools/sleeper_compare.py): final = (1 - w) ours +
w Sleeper, w per position fit on 2021-23 and tested on 2024-26: MAE -0.020 [-0.039, -0.002], no position worse.
Shipped weights (config experiments.sleeper_blend) are refit on 2021-26. Sleeper's API keeps only each player-week's
last saved projection, so the backtest's Sleeper values may carry game-day news; live, it is always pre-game.
"""
import json
import os
import time
import urllib.request
from pathlib import Path

import pandas as pd

UA = {"User-Agent": "nfl-edge-site/1.0"}
POS = ["QB", "RB", "WR", "TE"]
# Sleeper stat key -> our scoring key
STATS = {"pass_yd": "pass_yd", "pass_td": "pass_td", "pass_int": "interception", "rush_yd": "rush_yd",
         "rush_td": "rush_td", "rec": "reception", "rec_yd": "rec_yd", "rec_td": "rec_td", "fum_lost": "fumble_lost"}


def fetch(season: int, week: int, cache_dir: Path, max_age_hours: float | None = None) -> pd.DataFrame:
  """One week's projections (QB / RB / WR / TE), cached in cache_dir/sleeper_proj/. max_age_hours None = keep the
  cached copy forever (finished weeks); the live week passes a TTL so news-driven changes come through."""
  d = Path(cache_dir) / "sleeper_proj"
  d.mkdir(parents=True, exist_ok=True)
  f = d / f"{season}_{week:02d}.parquet"
  if f.exists() and (max_age_hours is None or time.time() - f.stat().st_mtime < max_age_hours * 3600):
    return pd.read_parquet(f)
  q = "&".join(f"position[]={p}" for p in POS)
  url = f"https://api.sleeper.app/projections/nfl/{season}/{week}?season_type=regular&{q}"
  with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
    raw = json.load(r)
  rows = [{"sleeper_id": str(x["player_id"]), "company": x.get("company"), "updated_at": x.get("updated_at") or 0,
           **{k: float((x.get("stats") or {}).get(k) or 0.0) for k in STATS}} for x in raw]
  out = pd.DataFrame(rows, columns=["sleeper_id", "company", "updated_at", *STATS]).assign(season=season, week=week)
  tmp = f.with_suffix(f".{os.getpid()}.tmp")  # atomic: parallel backtest workers read these files
  out.to_parquet(tmp)
  os.replace(tmp, f)
  return out


def id_map(cache_dir: Path, rosters: pd.DataFrame | None = None) -> dict:
  """Sleeper player id -> gsis id: nflverse's fantasy id crosswalk (cached a week), weekly rosters fill gaps."""
  f = Path(cache_dir) / "sleeper_proj" / "ff_playerids.parquet"
  if not f.exists() or time.time() - f.stat().st_mtime > 7 * 86400:
    try:
      import nflreadpy as nfl
      x = nfl.load_ff_playerids()
      x = x.to_pandas() if hasattr(x, "to_pandas") else x
      f.parent.mkdir(parents=True, exist_ok=True)
      x[["sleeper_id", "gsis_id"]].astype(str).to_parquet(f)
    except Exception:  # offline: an older crosswalk (or the rosters alone) still maps nearly everyone
      if not f.exists():
        x = pd.DataFrame({"sleeper_id": [], "gsis_id": []})
        x.to_parquet(f)
  ids = pd.read_parquet(f)
  bad = ("", "nan", "None", "<NA>")
  clean = lambda v: str(v).strip().removesuffix(".0")  # noqa: E731
  out = {}
  for s, g in zip(ids.sleeper_id, ids.gsis_id):
    s, g = clean(s), clean(g)
    if s not in bad and g not in bad:
      out.setdefault(s, g)
  if rosters is not None and "sleeper_id" in rosters:
    for s, g in zip(rosters.sleeper_id, rosters.gsis_id):
      s = clean(s)
      if s not in bad and isinstance(g, str):
        out.setdefault(s, g)
  return out


def points(df: pd.DataFrame, scoring) -> pd.Series:
  """A Sleeper stat line in our scoring (Sleeper's own points use INT -1 and bonuses)."""
  w = scoring.weights
  return sum(df[k] * w.get(v, 0.0) for k, v in STATS.items())


def week_points(season: int, week: int, cache_dir: Path, scoring, rosters=None, live: bool = False) -> pd.Series:
  """gsis id -> Sleeper's projected points for the week (players Sleeper projects; others absent)."""
  sl = fetch(season, week, cache_dir, max_age_hours=3.0 if live else None)
  sl = sl.assign(gsis_id=sl.sleeper_id.map(id_map(cache_dir, rosters)), pts=points(sl, scoring)).dropna(subset=["gsis_id"])
  return sl.sort_values("pts").drop_duplicates("gsis_id", keep="last").set_index("gsis_id").pts
