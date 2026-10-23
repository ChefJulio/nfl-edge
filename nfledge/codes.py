"""Shared codes (owner 2026-10-22 injury audit: "consolidate any systems that could be combined ... less surface for
bugs"): one place for the code maps that several modules used to keep their own copies of (and that had drifted:
suspension read SSPD on the board, SUSP on depth charts, "Res" in the practice timeline).

  team(t)        - any source's team code -> ours (the schedule's current franchise code: LV, LAC, LA)
  RESERVE        - weekly rosters' reserve-list code (status_description_abbr) -> the tag the site shows
  reserve(abbr)  - the same, "Res" for any other reserve list
  ESPN_STATUS    - ESPN injury feed status -> the bucket our ESPN models use (espn.py, espn_calib.py)
"""
from __future__ import annotations

# rosters' old club codes and relocated franchises -> our code (the schedule's: OAK -> LV, SD -> LAC, STL / LAR -> LA)
TEAM = {"BLT": "BAL", "CLV": "CLE", "HST": "HOU", "ARZ": "ARI", "SL": "LA", "STL": "LA", "OAK": "LV", "SD": "LAC", "LAR": "LA"}

# R01 injured reserve, R48 injured reserve (designated to return), R04 PUP, R05 non-football injury, R40 suspended
RESERVE = {"R01": "IR", "R48": "IR", "R04": "PUP", "R05": "NFI", "R40": "SSPD"}
INJURY_LISTS = {"IR", "PUP", "NFI"}  # the reserve lists that are injuries (a suspension isn't)

ESPN_STATUS = {"Out": "Out", "Injured Reserve": "IR", "Doubtful": "Doubtful"}


def team(t):
  return TEAM.get(t, t)


def reserve(abbr) -> str:
  return RESERVE.get(abbr, "Res")
