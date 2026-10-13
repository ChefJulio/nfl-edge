"""Daily snapshot of ESPN's public NFL injury feed, kept so its diagnoses and estimated return dates can be TESTED
as inputs to the return-timing model (nfledge/returns.py) once enough injuries have resolved.

ESPN only serves the current season (no history), so the archive has to be built going forward. Nothing here is
used by the model until a walk-forward test shows it helps; the snapshot is evidence, not a source of truth.

Usage: python tools/espn_snapshot.py [--out=site/data/espn_injuries]
Writes <out>/<YYYY-MM-DD>.csv (one row per listed player; an existing file for today is overwritten).
Unofficial public endpoint (like the NFL.com practice feed): may change without notice; failures are non-fatal.
"""
import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path

import pandas as pd

URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  out = Path(opt.get("out", "site/data/espn_injuries"))
  try:
    with urllib.request.urlopen(URL, timeout=30) as resp:
      feed = json.load(resp)
  except Exception as e:  # never fail the site build over this
    print(f"[espn] snapshot skipped: {e}")
    return
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
  if not rows:
    print("[espn] snapshot skipped: empty feed")
    return
  out.mkdir(parents=True, exist_ok=True)
  path = out / f"{dt.datetime.now(dt.timezone.utc):%Y-%m-%d}.csv"
  pd.DataFrame(rows).to_csv(path, index=False)
  print(f"[espn] {len(rows)} injury entries -> {path}")


if __name__ == "__main__":
  main()
