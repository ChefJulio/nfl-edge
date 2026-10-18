"""Daily snapshot of ESPN's public NFL injury feed, kept so its diagnoses and estimated return dates can be TESTED
as inputs to the return-timing model (nfledge/returns.py) once enough injuries have resolved.

ESPN only serves the current season (no history), so the archive has to be built going forward. Nothing here is
used by the model until a walk-forward test shows it helps; the snapshot is evidence, not a source of truth.

Usage: python tools/espn_snapshot.py [--out=site/data/espn_injuries]
Writes <out>/<YYYY-MM-DD>.csv (one row per listed player; an existing file for today is overwritten) and
<out>/latest.json (the same rows, for the Players > Injuries tab).
Unofficial public endpoint (like the NFL.com practice feed): may change without notice; failures are non-fatal.
"""
import datetime as dt
from zoneinfo import ZoneInfo
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nfledge.espn import fetch_injuries  # noqa: E402


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  out = Path(opt.get("out", "site/data/espn_injuries"))
  df = fetch_injuries()  # never fails the site build: empty on any error
  if df.empty:
    print("[espn] snapshot skipped: empty or unavailable feed")
    return
  out.mkdir(parents=True, exist_ok=True)
  path = out / f"{dt.datetime.now(ZoneInfo("America/New_York")):%Y-%m-%d}.csv"  # the Eastern date (week clock, owner 2026-10-18): a UTC date was already tomorrow after 8 pm ET
  df.to_csv(path, index=False)
  latest = {"v": 1, "fetched": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
            "rows": json.loads(df.to_json(orient="records"))}
  (out / "latest.json").write_text(json.dumps(latest, separators=(",", ":")), encoding="utf-8")
  print(f"[espn] {len(df)} injury entries -> {path} (+ latest.json)")


if __name__ == "__main__":
  main()
