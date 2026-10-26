"""Coaching staffs from Wikipedia (owner 2026-10-26: a Coaches tile on team pages, coordinators included).

ESPN and nflverse name head coaches only. Wikipedia keeps every club's staff: "Template:<Team> staff" (the current
staff) and "<season> <Team> season" (that year's staff, 1999 on with a few gaps). Both list roles as bullets,
"*Offensive coordinator – [[Eric Bieniemy]]". Content is CC BY-SA: the tile credits Wikipedia.

staff(text) -> {hc, oc, dc, st}: head coach and the offensive / defensive / special teams coordinators (a role absent
is left out: Tampa Bay 2026 has no defensive coordinator, Todd Bowles runs the defense).
"""
import re
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "nfl-edge/1.0 (https://chefjulio.github.io/nfl-edge/; site data build)"
ROLES = ("hc", "oc", "dc", "st")

NAME = {"ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens", "BUF": "Buffalo Bills",
        "CAR": "Carolina Panthers", "CHI": "Chicago Bears", "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns",
        "DAL": "Dallas Cowboys", "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
        "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars", "KC": "Kansas City Chiefs",
        "LA": "Los Angeles Rams", "LAC": "Los Angeles Chargers", "LV": "Las Vegas Raiders", "MIA": "Miami Dolphins",
        "MIN": "Minnesota Vikings", "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants",
        "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers", "SEA": "Seattle Seahawks",
        "SF": "San Francisco 49ers", "TB": "Tampa Bay Buccaneers", "TEN": "Tennessee Titans", "WAS": "Washington Commanders"}


def name_in(team: str, season: int) -> str | None:
  """The club's name that season (season article titles use it); None before the club existed."""
  if team == "HOU" and season < 2002: return None
  if team == "LA" and season < 2016: return "St. Louis Rams"
  if team == "LAC" and season < 2017: return "San Diego Chargers"
  if team == "LV" and season < 2020: return "Oakland Raiders"
  if team == "WAS": return "Washington Redskins" if season < 2020 else "Washington Football Team" if season < 2022 else NAME[team]
  return NAME[team]


def raw(title: str, tries: int = 3) -> str:
  """A page's wikitext (redirects followed); '' when the page does not exist."""
  for hop in range(3):
    u = "https://en.wikipedia.org/w/index.php?" + urllib.parse.urlencode({"title": title, "action": "raw"})
    for i in range(tries):
      try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=20) as r:
          text = r.read().decode("utf-8")
        break
      except urllib.error.HTTPError as e:
        if e.code == 404: return ""
        if i == tries - 1: raise
        time.sleep(2 * (i + 1))
      except OSError:
        if i == tries - 1: raise
        time.sleep(2 * (i + 1))
    m = re.match(r"\s*#REDIRECT\s*\[\[([^\]|#]+)", text, re.I)
    if not m: return text
    title = m.group(1)
  return ""


def _clean(s: str) -> str:
  s = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", s)
  s = re.sub(r"\{\{[^{}]*\}\}", "", s)
  s = re.sub(r"<[^>]+>", "", s)
  s = re.sub(r"'{2,}", "", s)
  return re.sub(r"\s+", " ", s).strip(" -,")


def clean_name(who: str) -> str:
  """A name without the page's notes: "Urban Meyer (fired mid season)", "Josh McDaniels; fired on October 31",
  "John Bonamego fired on October 5th"."""
  who = re.sub(r"\s*\([^)]*\)", "", who).split(";")[0]
  return re.sub(r"\s+(fired|resigned|left|promoted|demoted|reassigned|dismissed)\b.*$", "", who, flags=re.I).strip(" ,;")


def staff(text: str) -> dict:
  """{hc, oc, dc, st} from a staff list; the first listed holder of each role (an interim later in a season page
  is the second line)."""
  out = {}
  for m in re.finditer(r"^\*\s*(.+?)\s+[–—-]\s+(.+)$", text, re.M):
    role, who = _clean(m.group(1)).lower(), _clean(m.group(2))
    who = clean_name(who)
    if not who or len(who) > 40: continue
    bare = role.replace("assistant head coach", "")
    # one line can hold two jobs ("Interim head coach/offensive coordinator", Darrell Bevell, Detroit 2020), so each
    # role is matched on its own; "Head coach/executive vice president" (Pete Carroll) is the head coach
    if re.search(r"(^|/)(interim )?head coach\b", role) and "assistant head coach" not in role: out.setdefault("hc", who)
    if "assistant" in bare or "senior" in bare: continue
    if "offensive coordinator" in role: out.setdefault("oc", who)
    if "defensive coordinator" in role: out.setdefault("dc", who)
    if "special teams coordinator" in role: out.setdefault("st", who)
  return out


def current(team: str) -> dict:
  return staff(raw(f"Template:{NAME[team]} staff"))


def season_staff(team: str, season: int) -> dict:
  nm = name_in(team, season)
  return staff(raw(f"{season} {nm} season")) if nm else {}
