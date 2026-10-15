"""Backfill ESPN's injury table (status + estimated return date) from the Wayback Machine, to measure how good its
return dates are and calibrate the early-week bridge on past seasons (nfledge/espn_calib.py).

Usage: python tools/espn_wayback.py [--seasons=2022-2025] [--days=0,1] [--out=cache/espn_injury_history.parquet]
--days: weekdays to fetch (0 = Mon). The midweek ruling test (INSIGHTS sec. 9, 2026-10-15) uses
--days=2,3,4 --out=cache/espn_injury_midweek.parquet, so the Mon/Tue calibration file stays as it is.
ESPN's public injuries page (espn.com/nfl/injuries) was captured almost daily 2022-24 (and on ~130 days of 2025).
Each capture's embedded page data lists every injured player: ESPN id, position, status, estimated return date.
This fetches the Monday and Tuesday captures of each regular season (the early-week window the bridge covers),
politely (one request every ~1.5 s), caches the raw pages in cache/wayback/, and writes
cache/espn_injury_history.parquet: capture time, espn_id, name, pos, status, ret (estimated return date).
Raw pages are archived copies of a public page, used for measurement only; nothing from them is republished.
"""
import datetime as dt
import gzip
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

UA = {"User-Agent": "nfl-edge-site/1.0 (research backfill)"}
CDX = "http://web.archive.org/cdx/search/cdx?url=espn.com/nfl/injuries&from={a}&to={b}&output=json&fl=timestamp&filter=statuscode:200&collapse=timestamp:8"
RAW = "http://web.archive.org/web/{ts}id_/https://www.espn.com/nfl/injuries"
OUT = ROOT / "cache" / "wayback"


def get(url: str, tries: int = 5) -> bytes:
  for k in range(tries):
    try:
      with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()
    except Exception:
      time.sleep(5 * (k + 1))
  raise RuntimeError(url)


def parse(html: str, ts: str) -> list[dict]:
  m = re.search(r"window\[.__espnfitt__.\]=(\{.*?\});</script>", html, re.S)
  if not m:
    return []
  d = json.loads(m.group(1))
  teams = (((d.get("page") or {}).get("content") or {}).get("injuries")) or []
  cap = dt.datetime.strptime(ts[:8], "%Y%m%d").date()
  rows = []
  for t in teams:
    for it in t.get("items", []):
      a = it.get("athlete") or {}
      mid = re.search(r"/id/(\d+)", a.get("href") or "")
      ret = None
      if it.get("date"):
        try:  # "Oct 21": the year is the capture's, or the next one when the month has wrapped (Dec -> Jan)
          r = dt.datetime.strptime(f"{it['date']} {cap.year}", "%b %d %Y").date()
          ret = r.replace(year=cap.year + 1) if r < cap - dt.timedelta(days=60) else r
        except ValueError:
          pass
      rows.append({"ts": ts, "captured": cap, "team": t.get("displayName"), "espn_id": mid.group(1) if mid else None,
                   "name": a.get("name"), "pos": a.get("position"), "status": it.get("statusDesc") or (it.get("type") or {}).get("description"),
                   "ret": ret})
  return rows


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  a, _, b = opt.get("seasons", "2022-2025").partition("-")
  dows = tuple(int(x) for x in opt.get("days", "0,1").split(","))
  out_file = ROOT / opt.get("out", "cache/espn_injury_history.parquet")
  OUT.mkdir(parents=True, exist_ok=True)
  rows = []
  for season in range(int(a), int(b or a) + 1):
    caps = json.loads(get(CDX.format(a=f"{season}0901", b=f"{season + 1}0110")))[1:]
    picks = [c[0] for c in caps if dt.datetime.strptime(c[0][:8], "%Y%m%d").weekday() in dows]
    print(f"[wayback] {season}: {len(caps)} daily captures, {len(picks)} on weekdays {dows}", flush=True)
    for ts in picks:
      f = OUT / f"espn_injuries_{ts}.html.gz"
      if not f.exists():
        try:
          f.write_bytes(gzip.compress(get(RAW.format(ts=ts))))
        except RuntimeError:
          print(f"[wayback] {ts}: fetch failed", flush=True)
          continue
        time.sleep(1.5)
      rows += [dict(r, season=season) for r in parse(gzip.decompress(f.read_bytes()).decode("utf-8", "ignore"), ts)]
  df = pd.DataFrame(rows)
  df.to_parquet(out_file, index=False)
  print(f"[wayback] {len(df)} rows, {df.ts.nunique()} captures, {df.ret.notna().mean():.0%} with a return date", flush=True)


if __name__ == "__main__":
  main()
