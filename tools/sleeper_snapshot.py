"""Timestamped snapshots of Sleeper's projections for the week being played (forward test, 2026-10-15).

Usage: python tools/sleeper_snapshot.py [--out=site/data/sleeper_proj]   (CI step; failures never fail the build)

Why: Sleeper's API keeps only each player-week's LAST saved projection, and that gets edited after games (players
hurt in-game are zeroed: Chase / Barkley / Mariota 2026 wk 4), so the backtest of a Sleeper blend was contaminated
(docs/INSIGHTS.md section 9). Each CI run saves what Sleeper shows right now; the clean test takes, per player, the
last snapshot before his game's kickoff. Writes <out>/<season>_<week>_<YYYYmmddTHHMM>.json:
{"fetched": ISO time, "season", "week", "p": {sleeper_id: [pass_yd, pass_td, pass_int, rush_yd, rush_td, rec, rec_yd,
rec_td, fum_lost]}} for players with any projected stat (~350, ~30 KB).
"""
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nfledge import sleeper as SL  # noqa: E402


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  out = Path(opt.get("out", str(ROOT / "site" / "data" / "sleeper_proj")))
  with urllib.request.urlopen(urllib.request.Request("https://api.sleeper.app/v1/state/nfl", headers=SL.UA), timeout=30) as r:
    st = json.load(r)
  if st.get("season_type") != "regular":
    print(f"[sleeper-snapshot] season type {st.get('season_type')}: nothing to save")
    return
  season, week = int(st["season"]), int(st["week"])
  now = datetime.now(timezone.utc)
  d = SL.fetch(season, week, Path(opt.get("cache", str(ROOT / "cache"))), max_age_hours=0.0)  # always fresh
  keys = list(SL.STATS)
  p = {sid: [round(float(v), 3) for v in vals] for sid, *vals in d[["sleeper_id", *keys]].itertuples(index=False)
       if any(vals)}
  out.mkdir(parents=True, exist_ok=True)
  f = out / f"{season}_{week:02d}_{now:%Y%m%dT%H%M}.json"
  f.write_text(json.dumps({"fetched": now.isoformat(timespec="seconds"), "season": season, "week": week,
                           "stats": keys, "p": p}, separators=(",", ":")), encoding="utf-8")
  print(f"[sleeper-snapshot] {season} wk {week}: {len(p)} players -> {f.name} ({f.stat().st_size // 1024} KB)")


if __name__ == "__main__":
  main()
