"""ESPN's public NFL injury feed (unofficial endpoint; failures are never fatal).

Two uses:
- tools/espn_snapshot.py archives it daily, to TEST its diagnoses / return dates as model inputs later.
- The live build's early-week bridge (injuries.InjuryModel.espn_bridge): between Sunday's games and the official
  Wednesday report, a player hurt in his last game has no report entry, so the model would call him healthy. For
  players whose team's report for the week is not out, an ESPN status updated after the team's last game puts him
  in a bucket (espn_calib.py: Out with a return date after the game / Out / Doubtful / IR) whose P(active) is
  learned from the archived snapshots' outcomes, starting from the official designation's carry-forward rate.
"""
from __future__ import annotations

import json
import urllib.request

import pandas as pd

URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"

# ESPN status -> the official designation whose learned carry-forward rate it borrows. Strong statuses only: ESPN
# keeps "Questionable" / "Day-To-Day" on many players who played through something on Sunday (first live run:
# 28 such entries, CeeDee Lamb and Saquon Barkley among them), a far weaker signal than an official Questionable,
# so those wait for the official report.
# Injured reserve is a roster rule, not a designation: a player placed on IR misses at least four games, so it maps
# to "IR" = certainly inactive this week (not to Out's carry-forward rate, under which a third of players return).
from .codes import ESPN_STATUS as STATUS_MAP  # noqa: E402 (nfledge/codes.py)


def gameday_rulings(data, feed: pd.DataFrame | None, now=None, saved: dict | None = None) -> dict:
  """(AU, {#gameday}) gsis -> ("INA" | "ACT", ESPN update time) for players on teams past their inactives time
  (week_clock: kickoff - 90 min). ESPN marks a declared inactive fantasy status INACTIVE (status Out) and flips a
  listed player who dresses to Active; only updates on game day count (an Active from earlier in the week is not a
  ruling). Matched through the rosters' ESPN ids.
  A ruling is a fact about the week, so it holds after the final whistle too (owner 2026-10-18: Tyler Warren, ruled
  inactive Sunday morning, read "Questionable" again once his game ended, because ESPN's entry moves on and nflverse's
  rosters mark INA a day or two later). saved: this week's archived rulings (run.py's gameday_<season>_<week>.json,
  gsis -> {"ruling", "at", "team"}): they fill in for any player the feed no longer rules on."""
  from .week_clock import Clock, ET
  c = Clock(data.schedules, now)
  week = c.current_week(data.current_season)
  teams = {t: tw for t, tw in c.teams(data.current_season, week).items() if tw.inactives_in(c.now)}
  if not teams:
    return {}
  out = {g: (v["ruling"], v["at"]) for g, v in (saved or {}).items() if v.get("team") in teams}
  if feed is None or not len(feed) or "status" not in feed:
    return out
  ab = {}  # ESPN team display name -> our code
  if getattr(data, "teams", None) is not None and "team_name" in data.teams:
    ab = dict(zip(data.teams.team_name, data.teams.team_abbr))
  from .data import espn_gsis
  gs = espn_gsis(data.rosters)
  for x in feed.dropna(subset=["espn_id"]).itertuples():
    t = D_RELOC(ab.get(x.team, ""))
    tw = teams.get(t)
    g = gs.get(str(x.espn_id))
    if tw is None or not isinstance(g, str):
      continue
    up = pd.to_datetime(x.updated, errors="coerce", utc=True)
    if pd.isna(up) or up.tz_convert(ET).date() != tw.kick.date():
      continue  # not updated on game day: not this game's ruling
    fs = str(getattr(x, "fantasy_status", "") or "")
    if fs == "INACTIVE":
      out[g] = ("INA", up.isoformat())
    elif x.status == "Active":
      out[g] = ("ACT", up.isoformat())
  return out


def D_RELOC(t: str) -> str:
  from .data import RELOCATED
  return RELOCATED.get(t, t)


def fetch_injuries(timeout: int = 30) -> pd.DataFrame:
  """One row per listed player (empty frame on any failure)."""
  try:
    with urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": "nfl-edge-site/1.0"}),
                                timeout=timeout) as resp:
      feed = json.load(resp)
  except Exception as e:
    print(f"[espn] injury feed unavailable: {e}", flush=True)
    return pd.DataFrame()
  rows = []
  for team in feed.get("injuries", []):
    for i in team.get("injuries", []):
      a, det = i.get("athlete", {}), i.get("details", {}) or {}
      href = (a.get("links") or [{}])[0].get("href", "")
      espn_id = href.split("/id/")[1].split("/")[0] if "/id/" in href else None
      rows.append({"espn_id": espn_id, "name": a.get("displayName"), "team": team.get("displayName"),
                   "status": i.get("status"), "updated": i.get("date"), "type": det.get("type"),
                   "detail": det.get("detail"), "side": det.get("side"), "return_date": det.get("returnDate"),
                   "fantasy_status": (det.get("fantasyStatus") or {}).get("abbreviation"),
                   "comment": (i.get("shortComment") or "")[:300]})
  return pd.DataFrame(rows)
