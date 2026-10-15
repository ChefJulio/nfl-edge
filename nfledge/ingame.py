"""In-game injuries from the official play-by-play text (owner 2026-10-14).

Gamebooks note an injury stoppage on the play: "LAC-15-L.McConkey was injured during the play." nflverse keeps that
text (desc). Team + jersey number -> gsis via that week's roster (falls back to "F.Last" on the team). ~3 notes a game
since ~2010, ~1 in 2003. INCOMPLETE by nature: a player hurt who walks off after the play or is pulled at halftime is
often not noted (Justin Jefferson, 2026 week 3) -- so this adds to the snap-share signal, it doesn't replace it.
"""
from __future__ import annotations

import re

import pandas as pd

from . import data as D

NOTE = re.compile(r"\b([A-Z]{2,3})-(\d{1,2})-([A-Z][A-Za-z.'\- ]+?) was injured during the play", re.S)
ROSTER_TEAM = {"LAR": "LA", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU", "SL": "LA"}


def notes(pbp: pd.DataFrame) -> pd.DataFrame:
  """Every injury note: game_id, play_id, season, week, qtr, time, team, jersey, name (one row per player noted)."""
  p = pbp[pbp.desc.str.contains("was injured during the play", na=False)]
  rows = []
  for r in p.itertuples(index=False):
    for team, num, name in NOTE.findall(r.desc):
      rows.append((r.game_id, r.play_id, int(r.season), int(r.week), r.season_type, r.qtr, r.time,
                   D.RELOCATED.get(team, ROSTER_TEAM.get(team, team)), int(num), name.strip()))
  return pd.DataFrame(rows, columns=["game_id", "play_id", "season", "week", "season_type", "qtr", "time", "team",
                                     "jersey", "name"])


def link(n: pd.DataFrame, rosters: pd.DataFrame) -> pd.DataFrame:
  """Adds gsis_id: (season, week, team, jersey) on that week's roster, else (team, 'F.Last') that season."""
  if n.empty:
    return n.assign(gsis_id=pd.Series(dtype=str))
  r = rosters.dropna(subset=["gsis_id"]).copy()
  r["team"] = r.team.replace({**D.RELOCATED, **ROSTER_TEAM})
  r["jersey"] = pd.to_numeric(r.jersey_number, errors="coerce")
  byj = r.dropna(subset=["jersey"]).drop_duplicates(["season", "week", "team", "jersey"]).set_index(
    ["season", "week", "team", "jersey"]).gsis_id
  r["abbr"] = r.first_name.fillna("").str[:1] + "." + r.last_name.fillna("")
  byn = r.drop_duplicates(["season", "team", "abbr"]).set_index(["season", "team", "abbr"]).gsis_id
  key = pd.MultiIndex.from_frame(n[["season", "week", "team", "jersey"]].astype({"jersey": float}))
  g = pd.Series(byj.reindex(key).to_numpy(), index=n.index)
  last = n.name.str.replace(r"^[A-Z][a-z]?\.", "", regex=True)  # "Bi.Robinson" -> "Robinson"
  alt = pd.Series(byn.reindex(pd.MultiIndex.from_arrays([n.season, n.team, n.name.str[:1] + "." + last])).to_numpy(), index=n.index)
  return n.assign(gsis_id=g.fillna(alt))


def load(cache, nfl, season: int, rosters: pd.DataFrame, stale: bool = False) -> pd.DataFrame | None:
  """Cached per season (cache name 'ingame'): linked notes."""
  def fetch():
    pbp = nfl.load_pbp([season]).select(["game_id", "play_id", "season", "week", "season_type", "qtr", "time", "desc"]).to_pandas()
    return link(notes(pbp), rosters[rosters.season == season] if "season" in rosters else rosters)
  return cache.get("ingame", season, fetch, stale=stale)
