"""Playoff history for Teams > Playoffs: data/playoffs/<season>.json for every season 1920 to last season + index.

Usage: python tools/playoffs_build.py [--site=site]   (CI runs it; history files are small and rebuilt each run)

Sources (all free):
- 1999 on: nflverse schedules (game_type WC / DIV / CON / SB), with game ids for the gamecast; seeds from our own
  standings / tiebreaker module (nfledge/standings.py, validated against ESPN's seeds 2014-2025).
- 1933-1998: FiveThirtyEight's nfl_games.csv (MIT license; data/history/538_playoff_games.csv, the playoff rows of
  https://raw.githubusercontent.com/fivethirtyeight/nfl-elo-game/master/data/nfl_games.csv). It uses today's franchise
  codes and mixes in AFL (1960-69) and AAFC (1946-49) games: each game is labeled with its league here.
- 1975-1998 seeds: each season's Wikipedia "NFL playoffs" page (its seeds block), fetched once into
  data/history/seeds_1975_1998.json (tools/playoffs_build.py --fetch-seeds). Seeds are not recomputed for those
  years (rules and tiebreakers differed); before 1975 no seeds are shown (home field rotated by division).
- 1920-1932: no playoffs; the champion was decided by the standings (league-recognized champions below).
Rounds come from date order within each side (conference / league), labeled per era. Seasons are keyed by season
year (Super Bowl I = 1966 season).
"""
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.standings import League, playoff_teams_per_conf  # noqa: E402

V = 1
HIST = ROOT / "data" / "history"
# 538 codes -> (first season, last season, name) eras. Defunct AAFC clubs too. Raiders = OAK, Rams = LAR in 538.
ERAS = {
  "ARI": [(1920, 1959, "Chicago Cardinals"), (1960, 1987, "St. Louis Cardinals"), (1988, 1993, "Phoenix Cardinals"), (1994, 2100, "Arizona Cardinals")],
  "ATL": [(1966, 2100, "Atlanta Falcons")], "BAL": [(1996, 2100, "Baltimore Ravens")], "BUF": [(1960, 2100, "Buffalo Bills")],
  "CAR": [(1995, 2100, "Carolina Panthers")],
  "CHI": [(1920, 1920, "Decatur Staleys"), (1921, 1921, "Chicago Staleys"), (1922, 2100, "Chicago Bears")],
  "CIN": [(1968, 2100, "Cincinnati Bengals")], "CLE": [(1946, 1995, "Cleveland Browns"), (1999, 2100, "Cleveland Browns")],
  "DAL": [(1960, 2100, "Dallas Cowboys")], "DEN": [(1960, 2100, "Denver Broncos")],
  "DET": [(1930, 1933, "Portsmouth Spartans"), (1934, 2100, "Detroit Lions")], "GB": [(1921, 2100, "Green Bay Packers")],
  "HOU": [(2002, 2100, "Houston Texans")], "IND": [(1953, 1983, "Baltimore Colts"), (1984, 2100, "Indianapolis Colts")],
  "JAX": [(1995, 2100, "Jacksonville Jaguars")], "KC": [(1960, 1962, "Dallas Texans"), (1963, 2100, "Kansas City Chiefs")],
  "LAC": [(1960, 1960, "Los Angeles Chargers"), (1961, 2016, "San Diego Chargers"), (2017, 2100, "Los Angeles Chargers")],
  "LAR": [(1937, 1945, "Cleveland Rams"), (1946, 1994, "Los Angeles Rams"), (1995, 2015, "St. Louis Rams"), (2016, 2100, "Los Angeles Rams")],
  "MIA": [(1966, 2100, "Miami Dolphins")], "MIN": [(1961, 2100, "Minnesota Vikings")],
  "NE": [(1960, 1970, "Boston Patriots"), (1971, 2100, "New England Patriots")], "NO": [(1967, 2100, "New Orleans Saints")],
  "NYG": [(1925, 2100, "New York Giants")], "NYJ": [(1960, 1962, "New York Titans"), (1963, 2100, "New York Jets")],
  "OAK": [(1960, 1981, "Oakland Raiders"), (1982, 1994, "Los Angeles Raiders"), (1995, 2019, "Oakland Raiders"), (2020, 2100, "Las Vegas Raiders")],
  "PHI": [(1933, 2100, "Philadelphia Eagles")], "PIT": [(1933, 1939, "Pittsburgh Pirates"), (1940, 2100, "Pittsburgh Steelers")],
  "SEA": [(1976, 2100, "Seattle Seahawks")], "SF": [(1946, 2100, "San Francisco 49ers")], "TB": [(1976, 2100, "Tampa Bay Buccaneers")],
  "TEN": [(1960, 1996, "Houston Oilers"), (1997, 1998, "Tennessee Oilers"), (1999, 2100, "Tennessee Titans")],
  "WSH": [(1932, 1932, "Boston Braves"), (1933, 1936, "Boston Redskins"), (1937, 2019, "Washington Redskins"),
          (2020, 2021, "Washington Football Team"), (2022, 2100, "Washington Commanders")],
  "BBA": [(1946, 1946, "Buffalo Bisons"), (1947, 1949, "Buffalo Bills (AAFC)")], "BCL": [(1947, 1950, "Baltimore Colts (AAFC)")],
  "NAA": [(1946, 1949, "New York Yankees (AAFC)")],
}
TO_SITE = {"OAK": "LV", "LAR": "LA", "WSH": "WAS"}  # 538 code -> our franchise code (logos, team pages)
CURRENT_NAME = {k: v[-1][2] for k, v in ERAS.items()}
AAFC = {"BBA", "BCL", "NAA"}
AAFC_ERA = {"CLE", "SF"}  # AAFC members 1946-49 that later joined the NFL
AFL = {"BUF", "NE", "NYJ", "TEN", "KC", "DEN", "OAK", "LAC", "MIA", "CIN"}  # AFL members 1960-69 (MIA 1966, CIN 1968)
# Recognized champions 1920-1932 (no postseason; decided by the standings, with league votes in disputed years)
CHAMPS = {1920: "Akron Pros", 1921: "Chicago Staleys", 1922: "Canton Bulldogs", 1923: "Canton Bulldogs", 1924: "Cleveland Bulldogs",
          1925: "Chicago Cardinals", 1926: "Frankford Yellow Jackets", 1927: "New York Giants", 1928: "Providence Steam Roller",
          1929: "Green Bay Packers", 1930: "Green Bay Packers", 1931: "Green Bay Packers", 1932: "Chicago Bears"}


def era_name(code: str, season: int) -> str:
  for a, b, n in ERAS.get(code, []):
    if a <= season <= b:
      return n
  return code


def team_ref(code: str, season: int) -> dict:
  """Display info: the era's name; a logo only when the era's name is today's (else a text badge)."""
  name = era_name(code, season)
  site = TO_SITE.get(code, code)
  return {"code": code, "site": site, "name": name, "modern": name == CURRENT_NAME.get(code) and code not in AAFC}


def league_of(t1: str, t2: str, season: int) -> str:
  if 1946 <= season <= 1949 and ({t1, t2} & AAFC or {t1, t2} <= AAFC_ERA | AAFC):
    return "AAFC"
  if 1960 <= season <= 1969 and t1 in AFL and t2 in AFL:
    return "AFL"
  return "NFL"


def fetch_seeds() -> dict:
  """Seeds 1975-1998 from each season's Wikipedia 'NFL playoffs' page (its '| AFC 1 = Team' block)."""
  name_to_code = {}
  for code, eras in ERAS.items():
    for a, b, n in eras:
      name_to_code[(n, a, b)] = code
  out = {}
  for season in range(1975, 1999):
    title = f"{season}–{str(season + 1)[-2:]} NFL playoffs"
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({"action": "parse", "page": title, "prop": "wikitext",
                                                                         "format": "json", "formatversion": 2, "redirects": 1})
    for attempt in range(6):  # Wikipedia rate-limits bursts (HTTP 429): pause between pages, back off on refusal
      try:
        t = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "nfl-edge-site/1.0"}), timeout=30))["parse"]["wikitext"]
        break
      except urllib.error.HTTPError as e:
        if e.code != 429 or attempt == 5:
          raise
        time.sleep(10 * (attempt + 1))
    time.sleep(2)
    seeds = {}
    for conf, seed, team in re.findall(r"\|\s*(AFC|NFC)\s*(\d)\s*=\s*\[*([^\n|\]]+)", t):
      team = team.strip()
      code = next((c for (n, a, b), c in name_to_code.items() if n == team and a <= season <= b), None)
      if code:
        seeds[code] = {"conf": conf, "seed": int(seed)}
    out[str(season)] = seeds
    print(f"[seeds] {season}: {len(seeds)} teams", flush=True)
  return out


def side_rounds(games: list[dict], season: int) -> list[dict]:
  """Group one side's games into rounds by date (a new round when the gap is 4+ days)."""
  games = sorted(games, key=lambda g: g["date"])
  rounds, last = [], None
  for g in games:
    d = pd.Timestamp(g["date"])
    if last is None or (d - last).days >= 4:
      rounds.append([])
    rounds[-1].append(g)
    last = d
  return rounds


def labels(n: int, season: int, side: str) -> list[str]:
  if season == 1982:
    return ["First round", "Second round", f"{side} Championship"][-n:]
  if season >= 1970:
    return ["Wild Card", "Divisional", f"{side} Championship"][-n:]
  if side == "AFL":
    return (["Divisional"] if season == 1969 else ["Division tiebreaker"]) * (n - 1) + ["AFL Championship"]
  if side == "NFL" and season >= 1967:
    return ["Conference Championship", "NFL Championship"][-n:]
  if side == "AAFC":
    return (["Semifinal"] if season == 1949 else ["Division tiebreaker"]) * (n - 1) + ["AAFC Championship"]
  return ["Division tiebreaker"] * (n - 1) + ["NFL Championship"]


def season_doc(season: int, rows: list[dict], seeds: dict) -> dict:
  if season < 1933:
    return {"v": V, "season": season, "era": "standings", "champion": CHAMPS.get(season), "groups": [], "final": None}
  final = None
  if season >= 1966:  # Super Bowl: the last game of the season
    last = max(rows, key=lambda g: g["date"])
    final = {"label": "Super Bowl", "games": [last]}
    rows = [g for g in rows if g is not last]
  sides = {}
  for g in rows:
    if season >= 1970:
      s = g.get("conf") or "AFC"
    else:
      s = g["league"]
    sides.setdefault(s, []).append(g)
  order = ["AFC", "NFC"] if season >= 1970 else ["NFL", "AFL", "AAFC"]
  groups = []
  for s in [x for x in order if x in sides]:
    rds = side_rounds(sides[s], season)
    lab = labels(len(rds), season, s)
    groups.append({"title": s, "rounds": [{"label": lab[i] if i < len(lab) else f"Round {i + 1}", "games": rd} for i, rd in enumerate(rds)]})
  era = "conference" if season >= 1970 else "two-league" if season >= 1960 or 1946 <= season <= 1949 else "single"
  return {"v": V, "season": season, "era": era, "groups": groups, "final": final, "seeded": bool(seeds)}


def game(season, date, t1, t2, s1, s2, neutral, seeds, gid=None, conf_of=None) -> dict:
  g = {"date": str(date)[:10], "home": team_ref(t1, season), "away": team_ref(t2, season), "hs": int(s1), "as": int(s2),
       "neutral": bool(neutral), "league": league_of(t1, t2, season)}
  for side, code in (("home", t1), ("away", t2)):
    sd = seeds.get(TO_SITE.get(code, code)) or seeds.get(code)
    if sd:
      g[side]["seed"] = sd["seed"]
      g["conf"] = sd["conf"]
  if conf_of and "conf" not in g:
    g["conf"] = conf_of.get(TO_SITE.get(t1, t1)) or conf_of.get(TO_SITE.get(t2, t2))
  if gid:
    g["gid"] = gid
  return g


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = Path(opt.get("site", "site"))
  if "--fetch-seeds" in sys.argv:
    (HIST / "seeds_1975_1998.json").write_text(json.dumps(fetch_seeds(), indent=0), encoding="utf-8")
    return
  import nflreadpy as nfl
  cfg = load_config()
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  current = int(nfl.get_current_season())
  sched = cache.get("schedules", "since1999", lambda: nfl.load_schedules(list(range(1999, current + 1))),
                    stale=cache.age_hours("schedules", "since1999") > 6)
  teams = cache.get("teams", "all", lambda: nfl.load_teams(), stale=False)
  conf_of = dict(zip(teams.team_abbr, teams.team_conf))
  old = pd.read_csv(HIST / "538_playoff_games.csv")
  seeds75 = json.loads((HIST / "seeds_1975_1998.json").read_text(encoding="utf-8"))
  out = site / "data" / "playoffs"
  out.mkdir(parents=True, exist_ok=True)
  last = int(sched[(sched.game_type == "SB") & sched.home_score.notna()].season.max())
  seasons = list(range(1920, last + 1))
  for s in seasons:
    if s < 1999:
      seeds = seeds75.get(str(s), {}) if s >= 1975 else {}
      rows = [game(s, r.date, r.team1, r.team2, r.score1, r.score2, r.neutral, seeds) for r in old[old.season == s].itertuples()]
    else:
      L = League.from_schedule(sched, teams, s)
      seeds = {t: {"conf": c, "seed": i + 1} for c, order in L.seeds(playoff_teams_per_conf(s)).items() for i, t in enumerate(order)}
      g = sched[(sched.season == s) & (sched.game_type != "REG") & sched.home_score.notna()]
      inv = {v: k for k, v in TO_SITE.items()}
      rows = [game(s, r.gameday, inv.get(r.home_team, r.home_team), inv.get(r.away_team, r.away_team), r.home_score, r.away_score,
                   r.location == "Neutral", seeds, gid=r.game_id, conf_of=conf_of) for r in g.itertuples()]
    doc = season_doc(s, rows, {k: v for k, v in (seeds if s >= 1975 else {}).items()})
    (out / f"{s}.json").write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
  (out / "index.json").write_text(json.dumps({"v": V, "seasons": seasons, "current": current}), encoding="utf-8")
  print(f"[playoffs] {len(seasons)} seasons -> {out}", flush=True)


if __name__ == "__main__":
  main()
