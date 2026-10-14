"""ESPN's public NFL injury feed (unofficial endpoint; failures are never fatal).

Two uses:
- tools/espn_snapshot.py archives it daily, to TEST its diagnoses / return dates as model inputs later.
- The live build's early-week bridge (injuries.InjuryModel.espn_bridge): between Sunday's games and the official
  Wednesday report, a player hurt in his last game has no report entry, so the model would call him healthy.
  STOPGAP (2026-10-13, owner-approved, NOT yet validated): for players whose team's report for the week is not out,
  an ESPN status updated after the team's last game is mapped to the official designation it corresponds to and
  scored with the model's learned carry-forward rates. To validate once enough daily snapshots exist: compare
  ESPN early-week statuses with who actually played, and replace the mapping with fitted rates if they differ.
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
STATUS_MAP = {"Out": "Out", "Injured Reserve": "IR", "Doubtful": "Doubtful"}


def fetch_injuries(timeout: int = 30) -> pd.DataFrame:
  """One row per listed player (empty frame on any failure)."""
  try:
    with urllib.request.urlopen(URL, timeout=timeout) as resp:
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
