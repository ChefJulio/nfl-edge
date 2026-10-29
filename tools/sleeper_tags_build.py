"""Sleeper's own injury tags for the Fantasy tab's IR checks: data/sleeper_tags.json.

Usage: python tools/sleeper_tags_build.py [--site=site]     (CI: full builds and the news lane)

Sleeper decides who may sit in an IR slot from ITS tag (owner 2026-10-29: "consider how our tags differ from sleeper.
can you pull the player tags from sleeper for this part?"), so the IR suggestions read Sleeper's, not ours. The only
source is Sleeper's whole player list (/v1/players/nfl, ~5 MB), which Sleeper asks apps to fetch at most once a day
(owner 2026-10-29: "they ask once a day"): one fetch a day, the first build after FETCH_HOUR_ET (the day's practice
reports and game designations are out by then), cached in cache/sleeper_players.json between; boiled down to the players
with a tag: {sleeper id: [injury_status, body part]}. Sleeper ids are what a Sleeper roster lists.
"""
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nfledge.config import load_config  # noqa: E402

URL = "https://api.sleeper.app/v1/players/nfl"
FETCH_HOUR_ET = 18  # 6 PM Eastern: after the day's injury reports


def due(cache: Path) -> bool:
  """Fetch once a day: no copy yet, or the copy is from before today's FETCH_HOUR_ET and that hour has passed."""
  from zoneinfo import ZoneInfo
  if not cache.exists():
    return True
  et = ZoneInfo("America/New_York")
  now = datetime.now(et)
  mark = now.replace(hour=FETCH_HOUR_ET, minute=0, second=0, microsecond=0)
  if now < mark:
    mark -= timedelta(days=1)  # before 6 PM: yesterday's 6 PM is the line
  return datetime.fromtimestamp(cache.stat().st_mtime, et) < mark


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = Path(opt.get("site", "site"))
  cache = ROOT / load_config()["data"]["cache_dir"] / "sleeper_players.json"
  fresh = not due(cache)
  if not fresh:
    try:
      raw = urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": "nfl-edge-site/1.0"}), timeout=60).read()
      json.loads(raw)  # whole and parseable before it replaces the cached copy
      cache.parent.mkdir(parents=True, exist_ok=True)
      cache.write_bytes(raw)
    except Exception as e:  # Sleeper down: the cached copy, if any
      print(f"[sleeper] fetch failed ({e}); {'using the cached list' if cache.exists() else 'no tags this run'}", flush=True)
      if not cache.exists():
        return
  players = json.loads(cache.read_text(encoding="utf-8"))
  tags = {k: [p.get("injury_status"), p.get("injury_body_part")] for k, p in players.items() if p.get("injury_status")}
  fetched = datetime.fromtimestamp(cache.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
  out = site / "data" / "sleeper_tags.json"
  out.parent.mkdir(parents=True, exist_ok=True)
  out.write_text(json.dumps({"v": 1, "fetched": fetched, "tags": tags}, separators=(",", ":")), encoding="utf-8")
  print(f"[sleeper] {len(tags)} tagged players (list fetched {fetched}{', cached' if fresh else ''})", flush=True)


if __name__ == "__main__":
  main()
