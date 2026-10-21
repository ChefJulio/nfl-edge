"""Vegas preseason win totals (over/under lines), every team, from Pro-Football-Reference's preseason odds pages.

Usage: python tools/win_totals_build.py [first] [last]      (default 2016 to this season)
PFR sits behind a bot check, so each season comes from the Wayback Machine's latest capture of
pro-football-reference.com/years/<season>/preseason_odds.htm. The lines are set before week 1 and don't change, so
any capture works. Writes data/history/preseason_win_totals.csv: season, team (nflverse abbreviation), win_total,
sb_odds (American odds to win the Super Bowl).
"""
import gzip
import io
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

OUT = ROOT / "data" / "history" / "preseason_win_totals.csv"
PAGE = "pro-football-reference.com/years/{}/preseason_odds.htm"


def get(url: str) -> bytes:
  with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "nfl-edge research"}), timeout=60) as r:
    b = r.read()
  return gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b


def season(y: int, names: dict) -> pd.DataFrame:
  cdx = json.loads(get(f"https://web.archive.org/cdx/search/cdx?url={PAGE.format(y)}&output=json&filter=statuscode:200"))
  if len(cdx) < 2:
    raise RuntimeError(f"{y}: no capture")
  err = None
  for row in reversed(cdx[1:][-5:]):  # latest first; a capture can fail to replay, so try a few
    try:
      html = get(f"https://web.archive.org/web/{row[1]}id_/https://www.{PAGE.format(y)}").decode("utf-8", "ignore")
      t = pd.read_html(io.StringIO(html.replace("<!--", "").replace("-->", "")), flavor="lxml")[0]
      break
    except Exception as e:  # noqa: BLE001
      err = e
  else:
    raise RuntimeError(f"{y}: no capture replayed ({err})")
  t = t[t.Tm.isin(names)]
  return pd.DataFrame({"season": y, "team": t.Tm.map(names), "win_total": t["W/L O-U"].astype(float),
                       "sb_odds": pd.to_numeric(t["Super Bowl Odds"], errors="coerce")})


def main():
  a = [int(x) for x in sys.argv[1:3]]
  first, last = (a + [2016, date.today().year])[:2] if len(a) < 2 else a
  teams = pd.read_parquet(ROOT / "cache" / "teams_all.parquet")
  names = dict(zip(teams.team_name, teams.team_abbr))
  names.update({"Washington Redskins": "WAS", "Washington Football Team": "WAS", "Oakland Raiders": "LV",
                "San Diego Chargers": "LAC", "St. Louis Rams": "LA", "Los Angeles Rams": "LA"})  # nflverse schedules use LA
  rows = []
  for y in range(first, last + 1):
    try:
      s = season(y, names)
      print(f"{y}: {len(s)} teams")
      rows.append(s)
    except Exception as e:  # noqa: BLE001
      print(f"{y}: FAILED ({e})")
  df = pd.concat(rows, ignore_index=True)
  if OUT.exists():
    old = pd.read_csv(OUT)
    df = pd.concat([old[~old.season.isin(df.season)], df]).sort_values(["season", "team"])
  df.to_csv(OUT, index=False)
  print(f"wrote {OUT.relative_to(ROOT)}: {len(df)} rows")


if __name__ == "__main__":
  main()
