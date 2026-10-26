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


def staff(text: str, links: dict | None = None) -> dict:
  """{hc, oc, dc, st} from a staff list; the first listed holder of each role (an interim later in a season page
  is the second line). links (optional, filled): role -> the person's page title ("Kevin O'Connell (American
  football)": the plain name is often a disambiguation page)."""
  out = {}
  for m in re.finditer(r"^\*\s*(.+?)\s+[–—-]\s+(.+)$", text, re.M):
    role, who = _clean(m.group(1)).lower(), _clean(m.group(2))
    who = clean_name(who)
    if not who or len(who) > 40: continue
    lk = re.search(r"\[\[([^|\]#]+)", m.group(2))
    bare = role.replace("assistant head coach", "")
    found = []
    # one line can hold two jobs ("Interim head coach/offensive coordinator", Darrell Bevell, Detroit 2020), so each
    # role is matched on its own; "Head coach/executive vice president" (Pete Carroll) is the head coach
    if re.search(r"(^|/)(interim )?head coach\b", role) and "assistant head coach" not in role: found.append("hc")
    if not ("assistant" in bare or "senior" in bare):
      found += [r for r, k in (("oc", "offensive coordinator"), ("dc", "defensive coordinator"), ("st", "special teams coordinator")) if k in role]
    for r in found:
      if r not in out:
        out[r] = who
        if links is not None and lk: links[r] = lk.group(1).strip()
  return out


# ---- a coach's own page: the infobox's coaching and playing careers (owner 2026-10-26: "it doesn't show coaching
# history, like o'connell was with the rams as a qb coach ... doesn't list them as former players") ----
CODE_OF = {v: k for k, v in NAME.items()} | {"Oakland Raiders": "LV", "San Diego Chargers": "LAC", "St. Louis Rams": "LA",
                                             "Washington Redskins": "WAS", "Washington Football Team": "WAS",
                                             "Los Angeles Raiders": "LV", "Houston Oilers": "TEN", "Tennessee Oilers": "TEN",
                                             "Phoenix Cardinals": "ARI", "St. Louis Cardinals": "ARI", "Baltimore Colts": "IND",
                                             "Los Angeles Rams (1946–1994)": "LA", "Boston Patriots": "NE"}
_YEAR_T = re.compile(r"\{\{\s*(?:nfly|nfl year|nfl season|cfby|cfb year|cfb season|cfl year|afl year|ufl year|year|nflyr)\s*\|\s*(\d{4})(?:\s*\|\s*(\d{2,4}))?[^{}]*\}\}", re.I)


def _years_text(s: str) -> str:
  """Year templates to plain text: {{nfly|2017|2019}} -> 2017–2019, {{NFL Year|2009}} -> 2009."""
  def y(m):
    a, b = m.group(1), m.group(2)
    if b and len(b) == 2: b = a[:2] + b
    return f"{a}–{b}" if b else a
  return _YEAR_T.sub(y, s)


def _plain(s: str) -> str:
  s = _years_text(s)
  s = re.sub(r"\{\{\s*(?:ubl|unbulleted list|plainlist|nowrap)\s*\|", "", s, flags=re.I)
  s = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", s)
  s = re.sub(r"\{\{[^{}]*\}\}", "", s).replace("}}", "").replace("{{", "")
  s = re.sub(r"<br\s*/?>", " | ", s, flags=re.I)
  s = re.sub(r"<[^>]+>", "", s)
  s = re.sub(r"'{2,}", "", s)
  return re.sub(r"\s+", " ", s).strip(" *-,")


_SPAN = re.compile(r"\((\d{4})(?:\s*[–—-]\s*(\d{4}|present))?\)")


def _span(s: str):
  m = _SPAN.search(s)
  if not m: return None, None, s
  a = int(m.group(1)); b = m.group(2)
  return a, (None if b == "present" else int(b) if b else a), (s[:m.start()] + s[m.end():]).strip()


def _field(text: str, key: str) -> str:
  """An infobox parameter's raw value (to the next top-level "| key =" line)."""
  m = re.search(rf"^\s*\|\s*{key}\s*=(.*?)(?=^\s*\|\s*[a-z_0-9]+\s*=|^\}}\}})", text, re.M | re.S | re.I)
  return m.group(1).strip() if m else ""


def bio(text: str) -> dict:
  """{pos, college, draft, pfr, played: [[team, code, from, to]], coached: [[team, code, from, to, role]]} from an
  "Infobox NFL biography" (to is None while it lasts). Nested lines (** role (years)) belong to the team above."""
  out = {"pos": "", "college": "", "draft": None, "pfr": "", "played": [], "coached": []}
  if "Infobox" not in text:
    return out
  pos = _field(text, "career_position") or re.sub(r"<!--.*?-->", "", _field(text, "position"), flags=re.S)
  out["pos"] = _plain(pos).upper() if len(_plain(pos)) <= 3 else _plain(pos)
  out["college"] = re.sub(r"\s*\(.*", "", _plain(_field(text, "college")))
  dy, dr, dp = (_plain(_field(text, k)) for k in ("draftyear", "draftround", "draftpick"))
  if dy.isdigit():
    out["draft"] = [int(dy), int(dr) if dr.isdigit() else None, int(dp) if dp.isdigit() else None]
  out["pfr"] = _plain(_field(text, "pfr"))
  for line in _field(text, "pastteams").splitlines():
    if not line.strip().startswith("*"): continue
    t = _plain(line).rstrip("*").strip()
    a, b, team = _span(t)
    team = team.split(" | ")[0].strip()
    if team and a: out["played"].append([team, CODE_OF.get(team, ""), a, b])
  last = None
  for line in _field(text, "pastcoaching").splitlines():
    s = line.strip()
    if not s.startswith("*"): continue
    nested = s.startswith("**")
    t = _plain(s)
    if nested and last:
      a, b, role = _span(t)
      if role: out["coached"].append([last[0], last[1], a or last[2], b if a else last[3], role])
      continue
    parts = [p.strip() for p in t.split(" | ")]
    a, b, team = _span(parts[0])
    team = team.strip()
    last = [team, CODE_OF.get(team, ""), a, b]
    role = " / ".join(p for p in parts[1:] if p)
    if team and a: out["coached"].append([team, last[1], a, b, role])
  # a team line whose roles are on its nested lines carries no role itself: dropped when a nested role covers it
  out["coached"] = [c for c in out["coached"] if c[4] or not any(d is not c and d[0] == c[0] and d[4] and d[2] >= c[2] and (d[3] or 9999) <= (c[3] or 9999) for d in out["coached"])]
  return out


def current_links(team: str) -> tuple[dict, dict]:
  """(today's staff, role -> page title)."""
  links = {}
  return staff(raw(f"Template:{NAME[team]} staff"), links), links


ESPN_CODE = {"LAR": "LA", "WSH": "WAS"}


def _get_json(url: str):
  import json
  with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20) as r:
    return json.load(r)


def espn_heads(season: int) -> dict:
  """team -> {name, photo, exp}: the head coaches ESPN lists this season ({} on failure)."""
  out = {}
  try:
    ids = {str(t["team"]["id"]): ESPN_CODE.get(t["team"]["abbreviation"], t["team"]["abbreviation"])
           for t in _get_json("https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams")["sports"][0]["leagues"][0]["teams"]}
    refs = _get_json(f"https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/{season}/coaches?limit=100")["items"]
    for r in refs:
      c = _get_json(r["$ref"].replace("http://", "https://"))
      tid = re.search(r"/teams/(\d+)", (c.get("team") or {}).get("$ref", ""))
      t = tid and ids.get(tid.group(1))
      if t:
        out[t] = {"name": f"{c.get('firstName', '')} {c.get('lastName', '')}".strip(),
                  "photo": (c.get("headshot") or {}).get("href"), "exp": c.get("experience")}
  except Exception as e:
    print(f"[coaches] ESPN head coaches unavailable: {e}", flush=True)
  return out


def head_coaches(season: int, heads: dict | None = None) -> dict:
  """team -> today's head coach: ESPN's, else Wikipedia's staff template (team left out if neither answers)."""
  heads = espn_heads(season) if heads is None else heads
  out = {t: v["name"] for t, v in heads.items() if v.get("name")}
  for t in NAME:
    if t not in out:
      try:
        hc = current(t).get("hc")
        if hc: out[t] = hc
      except Exception:
        pass
  return out


def fix_current(df, season: int, current_season: int, hc: dict, relocated: dict | None = None):
  """nflverse's home_coach / away_coach run a season behind for the current one (2026-10-26: Jonathan Gannon still
  Arizona's head coach though he is Green Bay's DC; "Klint Kubliak"): this season's rows get today's head coach.
  Limitation: a mid-season change credits the whole season to today's coach (no per-game source names him)."""
  if season != current_season or not hc:
    return df
  df = df.copy()
  for side in ("home", "away"):
    team = df[f"{side}_team"].replace(relocated or {})
    df[f"{side}_coach"] = team.map(hc).fillna(df[f"{side}_coach"])
  return df


def current(team: str) -> dict:
  return staff(raw(f"Template:{NAME[team]} staff"))


def season_staff(team: str, season: int) -> dict:
  nm = name_in(team, season)
  return staff(raw(f"{season} {nm} season")) if nm else {}
