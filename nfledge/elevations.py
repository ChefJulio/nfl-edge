"""Practice-squad elevations for this week's games (owner 2026-10-21: Jawhar Jordan, elevated by Houston for week 6
with David Montgomery out, read nothing in week 7: "seems like a huge gap").

The board is built from nflverse's weekly rosters, where an elevated player shows as practice squad (DEV) until after
the game, so a back called up for the week was never projected. Teams announce elevations by 4 p.m. ET the day before a
game. Sources (researched 2026-10-21):
  - ProFootballRumors' daily "Minor NFL Transactions" post (www.profootballrumors.com/<yyyy>/<mm>/minor-nfl-
    transactions-<mm>-<dd>-<yy>): every team's moves under a team heading, one line "Elevated: CB Bryce Hall, RB
    Jawhar Jordan" (its 2026-10-17 post has Jordan). The main source.
  - ESPN's transactions feed: logs only some elevations (2 league-wide for week 6, 2026); a supplement.
  - Not usable: NFL.com's transactions pages (no elevations listed; pages past the first need the site's script) and
    api.nfl.com rosters (a current snapshot: an elevated player stays DEV).
Names link to gsis ids with the Moves parser's linker (tools/transactions_build.py). Live builds only: backtests
never see elevations. Any failure leaves the board as it was.
"""
from __future__ import annotations

import importlib
import html
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PFR = "https://www.profootballrumors.com/{y}/{m:02d}/minor-nfl-transactions-{m:02d}-{d:02d}-{yy:02d}"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/transactions?season={s}&limit=100&page={p}"
UA = {"User-Agent": "Mozilla/5.0 (nfl-edge site)"}
POSITIONS = {"QB", "RB", "FB", "HB", "WR", "TE", "K", "PK"}
ONE = re.compile(r"\b(QB|RB|FB|HB|WR|TE|K|PK|OL|OT|OG|G|T|C|DL|DT|DE|NT|EDGE|LB|ILB|OLB|CB|S|FS|SS|DB|P|LS)\s+([A-Z][\w.'\- ]+?)(?=,|$| and )")


def _tb():
  """The Moves parser (tools/transactions_build.py), imported on demand."""
  if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))
  return importlib.import_module("transactions_build")


def _get(url: str, tries: int = 3) -> str | None:
  import time
  for k in range(tries):
    try:
      return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
      if e.code == 404:
        return None
      if k == tries - 1:
        raise
    except (urllib.error.URLError, TimeoutError):
      if k == tries - 1:
        raise
    time.sleep(2 * (k + 1))
  return None


_DOWN = False
CACHE = ROOT / "cache" / "pfr_minor"  # one parsed day per file (every move); days 2+ back are final, never refetched


def pfr_cached(day: date) -> bool:
  """Whether that day is cached for good (2+ days old): pfr_lines returns it without a request."""
  return (CACHE / f"{day.isoformat()}.json").exists() and (date.today() - day).days >= 2


def pfr_lines(day: date, fetch: bool = True) -> list[tuple[str, str, str, str]]:
  """(team full name, move label, position, player name) for every move in that day's ProFootballRumors post
  ("Elevated: RB Jawhar Jordan" -> label "Elevated"); also the Moves page's source (tools/transactions_build.py).
  Parsed days are cached (the site can be unreachable: 2026-10-21 it refused connections for hours); the last two
  days are refetched (a post grows during its day). Unreachable and uncached: [] (the caller notes it)."""
  CACHE.mkdir(parents=True, exist_ok=True)
  path = CACHE / f"{day.isoformat()}.json"
  if path.exists() and (date.today() - day).days >= 2:
    return [tuple(x) for x in json.loads(path.read_text(encoding="utf-8"))]
  global _DOWN
  try:
    if _DOWN or not fetch:
      raise ConnectionError("source unreachable earlier in this run")
    s = _get(PFR.format(y=day.year, m=day.month, d=day.day, yy=day.year % 100))
  except Exception:
    _DOWN = True  # one failure: no more tries this run (each costs ~1.5 min of retries)
    return [tuple(x) for x in json.loads(path.read_text(encoding="utf-8"))] if path.exists() else []
  out = parse_post(s) if s else []
  path.write_text(json.dumps(out), encoding="utf-8")
  return out


def pfr_day(day: date) -> list[tuple[str, str, str]]:
  """(team full name, position, player name) for each elevation in that day's post."""
  return [(t, pos, name) for t, label, pos, name in pfr_lines(day) if re.match(r"Elevated\b", label, re.I)]


def parse_post(s: str) -> list[tuple[str, str, str, str]]:
  out = []
  for team, block in re.findall(r"<p><strong>([^<]+)</strong></p>\s*<ul>(.*?)</ul>", s, re.S):
    for li in re.findall(r"<li>(.*?)</li>", block, re.S):
      label, _, rest = html.unescape(re.sub(r"<[^>]+>", "", li)).strip().partition(":")
      rest = re.sub(r"\s*\([^)]*\)", "", rest).replace("’", "'").strip()  # "(story)", "(one-year deal)"; curly '
      for pos, name in ONE.findall(rest):
        out.append((html.unescape(team).strip(), label.strip(), pos, name.strip()))
  return out


def espn_since(season: int, since: str, max_pages: int = 4) -> list[dict]:
  out = []
  for page in range(1, max_pages + 1):
    d = json.loads(_get(ESPN.format(s=season, p=page)) or "{}")
    t = d.get("transactions", [])
    out += [{"date": (x.get("date") or "")[:10], "team": (x.get("team") or {}).get("abbreviation"), "text": x.get("description") or ""}
            for x in t]
    if not t or min((x.get("date") or "")[:10] for x in t) < since or page >= int(d.get("pageCount") or 1):
      break
  return out


def this_week(data, season: int, week: int) -> pd.DataFrame:
  """gsis_id, team, pos, full_name for skill players elevated for this week's game (announced after the team's
  previous game, on or before this week's game day). Empty on any failure."""
  cols = ["gsis_id", "team", "pos", "full_name"]
  try:
    import nflreadpy as nfl
    tb = _tb()
    sch = data.schedules[(data.schedules.season == season) & (data.schedules.game_type == "REG")]
    gd, prev = {}, {}
    for g in sch[sch.week == week].itertuples():
      gd[g.home_team] = gd[g.away_team] = str(g.gameday)[:10]
    for g in sch[(sch.week < week) & sch.home_score.notna()].itertuples():
      for t in (g.home_team, g.away_team):
        prev[t] = max(prev.get(t, ""), str(g.gameday)[:10])
    if not gd:
      return pd.DataFrame(columns=cols)
    first = min(prev.get(t, min(gd.values())) for t in gd)
    last = min(max(gd.values()), date.today().isoformat())
    link = tb.Linker(season, [data.rosters[data.rosters.season == season], data.rosters[data.rosters.season == season - 1]],
                     nfl.load_players().to_pandas())
    names = {}
    if getattr(data, "teams", None) is not None and "team_name" in data.teams:
      names = {str(n): str(a) for n, a in zip(data.teams.team_name, data.teams.team_abbr)}
    found = []  # (day, team, pos, name)
    d0, d1 = date.fromisoformat(first) + timedelta(days=1), date.fromisoformat(last)
    day = d0
    while day <= d1:
      for team, pos, name in pfr_day(day):
        found.append((day.isoformat(), names.get(team, team), pos, name))
      day += timedelta(days=1)
    for e in espn_since(season, first):
      for sent in tb.sentences(e["text"]):
        kind, ps = tb.parse(sent)
        if kind == "ps_elevated":
          found += [(e["date"], tb.ESPN_TEAM.get(e["team"], e["team"]), pos, name) for pos, name in ps]
    rows = []
    for d_, team, pos, name in found:
      team = {"LAR": "LA", "WSH": "WAS", "JAC": "JAX"}.get(team, team)
      if team not in gd or not (prev.get(team, "0000") < d_ <= gd[team]) or pos not in POSITIONS:
        continue
      pos = {"FB": "RB", "HB": "RB", "PK": "K"}.get(pos, pos)
      g = link(name, team, pos)
      if g:
        rows.append([g, team, pos, name])
    return pd.DataFrame(rows, columns=cols).drop_duplicates("gsis_id")
  except Exception as ex:  # a source down or reformatted: the board as before
    print(f"[elevations] skipped ({type(ex).__name__}: {str(ex)[:80]})", flush=True)
    return pd.DataFrame(columns=cols)
