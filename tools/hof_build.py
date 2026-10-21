"""Pro Football Hall of Fame players -> data/history/hof.csv (gsis_id, name, cls, first, last), for the HOF badge on the
player card and the finder (owner 2026-10-21: "a HOF badge on HOF players").

Usage: python tools/hof_build.py   (CI runs it with the build; a class is elected each February)
Source: Wikipedia's "List of Pro Football Hall of Fame inductees" (players table: one row per team stint, so a
player's years = the span of his rows). Matched to nflverse's player table by name and overlapping years (two Jerry
Rices: 1985-2004 and 2014). Inductees from before nflverse's ids (no gsis id) are left out: the site has no page for
them. The CSV is committed; a fetch that parses fewer players than it holds leaves it as is (a page-format change
never empties the list).
"""
import io
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "history" / "hof.csv"
URL = "https://en.wikipedia.org/wiki/List_of_Pro_Football_Hall_of_Fame_inductees"
UA = "nfl-edge/1.0 (https://github.com/ChefJulio/nfl-edge)"


def norm(t: str) -> str:
  t = unicodedata.normalize("NFD", str(t or ""))
  t = "".join(ch for ch in t if not unicodedata.combining(ch)).lower()
  t = re.sub(r"\[.*?\]", "", t)  # footnotes
  t = re.sub(r"[.'’]", "", t)
  t = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", t)
  return re.sub(r"[^a-z0-9]+", " ", t).strip()


def inductees() -> pd.DataFrame:
  """name, cls, first, last per inducted player (contributors and coaches have no playing position row here)."""
  html = urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": UA}), timeout=30).read().decode("utf-8")
  tables = [t for t in pd.read_html(io.StringIO(html)) if {"Inductee", "Class", "Position", "Years"} <= set(map(str, t.columns))]
  if not tables:
    raise RuntimeError("no inductee table")
  t = max(tables, key=len)
  t = t.assign(name=t.Inductee.astype(str).str.replace(r"[*†‡§^#]+", "", regex=True).str.strip())
  yrs = t.Years.astype(str).str.findall(r"(?:18|19|20)\d\d")
  t = t.assign(y0=yrs.map(lambda v: int(min(v)) if v else None), y1=yrs.map(lambda v: int(max(v)) if v else None))
  t = t.dropna(subset=["y0"])
  return (t.groupby("name").agg(cls=("Class", "first"), first=("y0", "min"), last=("y1", "max")).reset_index()
          .astype({"first": int, "last": int}))


def main():
  import nflreadpy as nfl
  hof = inductees()
  pl = nfl.load_players().to_pandas()[["gsis_id", "display_name", "rookie_season", "last_season"]].dropna(subset=["gsis_id"])
  pl["n"] = pl.display_name.map(norm)
  by = {k: g for k, g in pl.groupby("n")}
  rows = []
  for h in hof.itertuples():
    c = by.get(norm(h.name))
    if c is None:
      continue
    a, b = pd.to_numeric(c.rookie_season, errors="coerce"), pd.to_numeric(c.last_season, errors="coerce")
    ok = c[(a.fillna(h.first) <= h.last + 1) & (b.fillna(h.last) >= h.first - 1)]  # careers overlap (a year of slack)
    if len(ok) > 1:  # namesakes in the same years (Joe Thomas, Reggie White): the one whose career matches closest
      d = ((pd.to_numeric(ok.rookie_season, errors="coerce") - h.first).abs() + (pd.to_numeric(ok.last_season, errors="coerce") - h.last).abs()).fillna(99)
      ok = ok[d == d.min()] if (d == d.min()).sum() == 1 else ok.iloc[:0]
    if len(ok) == 1:
      rows.append([ok.gsis_id.iloc[0], h.name, int(re.sub(r"\D", "", str(h.cls))[:4]), h.first, h.last])
  out = pd.DataFrame(rows, columns=["gsis_id", "name", "cls", "first", "last"]).sort_values(["cls", "name"])
  old = len(pd.read_csv(OUT)) if OUT.exists() else 0
  if len(out) < old:
    print(f"[hof] parsed {len(out)} < {old} on file: kept the file", flush=True)
    return
  OUT.parent.mkdir(parents=True, exist_ok=True)
  out.to_csv(OUT, index=False)
  print(f"[hof] {len(out)} Hall of Fame players with ids ({len(hof)} inducted players listed)", flush=True)


if __name__ == "__main__":
  sys.exit(main())
