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
    # the general manager (owner 2026-10-26: "a specially important role"): "General manager", "Senior vice president &
    # general manager" (Joe Schoen), "Executive vice president/general manager"; not an assistant GM
    if re.search(r"(^|/|&|\s)general manager\b", role) and not re.search(r"assistant(\s+\w+)?\s+general manager", role):
      found.append("gm")
    # a club without one (New England, Cincinnati): its top player-personnel / football-operations executive
    elif links is not None and re.search(r"player personnel|football operations", role) and "assistant" not in role:
      rk = 0 if "executive vice president" in role else 1 if "vice president" in role else 2 if "director" in role else 3
      if rk < 3 and ("_ops" not in out or rk < out["_ops"][0]):
        out["_ops"] = (rk, who, m.group(1).strip(), lk.group(1).strip() if lk else None)
    # the owner (owner 2026-10-26: "let's add owners"): the front office's principal owner. Strongest claim first: a
    # controlling / principal owner or partner, a managing partner (Amy Adams Strunk over "Owner - KSA Industries"; the
    # Haslams; Josh Harris); then "owner"; then a chairman or a president / CEO when no owner is named (John Mara; Green
    # Bay is publicly held: its president). Never a vice chairman, limited partner, or owner emeritus / in memoriam.
    if links is not None and re.search(r"owner|chairman|partner|president", role) \
       and not re.search(r"vice[ -]chair|limited|emerit|memoriam|founder|\b19\d\d|partner/", role):
      rk = -1 if re.search(r"controlling owner|principal (owner|partner)|managing partner", role) else 0 if "owner" in role \
        else 1 if "chairman" in role or ("president" in role and "ceo" in role) else None
      if rk is not None and ("_own" not in out or rk < out["_own"][0]):
        out["_own"] = (rk, who, m.group(1).strip(), lk.group(1).strip() if lk else None)
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
def code_of(team: str) -> str:
  """Our code for an NFL club name, a combined one ("St. Louis / Los Angeles Rams") by its last name."""
  return CODE_OF.get(team) or CODE_OF.get(team.split("/")[-1].strip(), "")


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
  # his photo: the infobox's file, served by Special:FilePath (commons or local); coordinators have no ESPN headshot
  img = re.sub(r"<!--.*?-->", "", _field(text, "image"), flags=re.S).strip()
  img = re.sub(r"^\[\[(?:File|Image):([^|\]]+).*", r"\1", img).strip()
  out["img"] = img if re.search(r"\.(jpe?g|png|webp|gif)$", img, re.I) else ""
  for line in _field(text, "pastteams").splitlines():
    if not line.strip().startswith("*"): continue
    # a trailing "*": offseason and / or practice squad only (Kevin O'Connell: Detroit 2009, Miami 2011, San Diego 2012)
    ps = bool(re.search(r"\)\s*'*\*\s*(<ref|$)", line.strip()))
    t = _plain(line).rstrip("*").strip()
    a, b, team = _span(t)
    team = team.split(" | ")[0].strip()
    if team and a: out["played"].append([team, code_of(team), a, b, ps])
  out["coached"] = _career(_field(text, "pastcoaching"))
  out["exec"] = _career(_field(text, "pastexecutive"))
  return out


def _career(field: str) -> list:
  """[[team, code, from, to, role]] from an infobox career list (pastcoaching / pastexecutive): "* Team (years)<br/>Role",
  nested "** Role (years)" lines belonging to the team above."""
  rows, last = [], None
  for line in field.splitlines():
    s = line.strip()
    if not s.startswith("*"): continue
    nested = s.startswith("**")
    t = _plain(s)
    if nested and last:
      a, b, role = _span(t)
      if role: rows.append([last[0], last[1], a or last[2], b if a else last[3], role])
      continue
    parts = [p.strip() for p in t.split(" | ")]
    a, b, team = _span(parts[0])
    team = team.strip()
    last = [team, code_of(team), a, b]
    role = " / ".join(p for p in parts[1:] if p)
    if team and a: rows.append([team, last[1], a, b, role])
  # a team line whose roles are on its nested lines carries no role itself: dropped when a nested role covers it
  return [c for c in rows if c[4] or not any(d is not c and d[0] == c[0] and d[4] and d[2] >= c[2] and (d[3] or 9999) <= (c[3] or 9999) for d in rows)]


def staff_full(text: str) -> list:
  """The whole coaching staff as listed, [[group, role, name]] in order (owner 2026-10-26: "another full list ... of
  the team's entire coaching staff"): the template's ";Offensive coaches" headings (or "|Offensive Coaches=") group
  the bullets; the front office is left out."""
  out, group = [], ""
  for line in text.splitlines():
    s = line.strip()
    h = re.match(r"^;\s*(.+)$", s) or re.match(r"^\|\s*([A-Za-z &/]+?)\s*=\s*$", s)
    if h:
      group = _clean(h.group(1))
      continue
    m = re.match(r"^\*\s*(.+?)\s+[–—-]\s+(.+)$", s)
    if not m or re.search(r"front office|executive|personnel|scouting|ownership", group, re.I):
      continue
    role, who = _clean(m.group(1)), clean_name(_clean(m.group(2)))
    # a template without headings (Minnesota) lists the front office too: its roles are dropped by title, unless the
    # job coaches ("Director of football research" goes, "Assistant head coach" stays)
    if re.search(r"owner|chairman|president|general manager|chief|personnel|scout|advisor|administration|counsel|salary|"
                 r"\bdirector\b|operations|executive|business|communications|cap\b", role, re.I) \
       and not re.search(r"coach|coordinator|strength|conditioning|quality control", role, re.I):
      continue
    if who and len(who) <= 60:
      out.append([group or "Staff", role, who])
  return out


def current_links(team: str) -> tuple[dict, dict, list]:
  """(today's staff, role -> page title, the whole coaching staff)."""
  links = {}
  text = raw(f"Template:{NAME[team]} staff")
  return staff(text, links), links, staff_full(text)


# ---- the clubs' own staff pages (owner 2026-10-26: photos; "it's your call"): every club site runs the NFL's one
# platform, each coach a card with his official headshot on static.clubs.nfl.com. Linked from there (not copied), read
# once a day by the builder. Coaches page, front office page (the GM's photo; some clubs have none).
CLUB_SITE = {"ARI": "azcardinals.com", "ATL": "atlantafalcons.com", "BAL": "baltimoreravens.com", "BUF": "buffalobills.com",
             "CAR": "panthers.com", "CHI": "chicagobears.com", "CIN": "bengals.com", "CLE": "clevelandbrowns.com",
             "DAL": "dallascowboys.com", "DEN": "denverbroncos.com", "DET": "detroitlions.com", "GB": "packers.com",
             "HOU": "houstontexans.com", "IND": "colts.com", "JAX": "jaguars.com", "KC": "chiefs.com", "LA": "therams.com",
             "LAC": "chargers.com", "LV": "raiders.com", "MIA": "miamidolphins.com", "MIN": "vikings.com", "NE": "patriots.com",
             "NO": "neworleanssaints.com", "NYG": "giants.com", "NYJ": "newyorkjets.com", "PHI": "philadelphiaeagles.com",
             "PIT": "steelers.com", "SEA": "seahawks.com", "SF": "49ers.com", "TB": "buccaneers.com", "TEN": "tennesseetitans.com",
             "WAS": "commanders.com"}
CLUB_PATHS = {"CHI": ("team/coaches/", "team/front-office/")}
_CLUB_IMG = re.compile(r'(?:data-src|src)="(https://static\.clubs\.nfl\.com/image/(private|upload)/[^"]*?/(?:v\d+/)?'
                       r'([a-z0-9]+/[a-z0-9_-]+\.(?:jpg|jpeg|png)))"', re.I)
_CLUB_NAME = re.compile(r'd3-o-media-object__title">\s*([^<]+?)\s*</h3>')


def club_people(page: str) -> dict:
  """name -> square headshot URL from a club staff page: each card's name heading and the image just before it."""
  import html as H
  out = {}
  for m in _CLUB_NAME.finditer(page):
    name = H.unescape(m.group(1)).strip()
    before = page[max(0, m.start() - 6000):m.start()]
    prev = before.rfind("d3-o-media-object__title")  # the card's own image comes after the previous card's name
    imgs = [x for x in _CLUB_IMG.finditer(before) if x.start() > prev]
    if imgs and len(name) <= 40:
      x = imgs[-1]
      out.setdefault(name, f"https://static.clubs.nfl.com/image/{x.group(2)}/t_headshot_desktop/f_auto/{x.group(3)}")
  return out


def club_photos(team: str) -> dict:
  """name -> headshot for a club's coaches and front office ({} when its pages can't be read)."""
  out = {}
  for path in CLUB_PATHS.get(team, ("team/coaches-roster/", "team/front-office-roster/")):
    try:
      req = urllib.request.Request(f"https://www.{CLUB_SITE[team]}/{path}",
                                   headers={"User-Agent": f"Mozilla/5.0 (compatible; {UA})"})
      with urllib.request.urlopen(req, timeout=20) as r:
        page = r.read().decode("utf-8", "ignore")
    except Exception:
      continue
    for k, v in club_people(page).items():
      out.setdefault(k, v)
    time.sleep(0.3)
  return out


def _norm(name: str) -> str:
  import unicodedata
  s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
  s = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", s)
  return " ".join(re.sub(r"[^a-z ]", "", s).split())


def photo_for(name: str, people: dict) -> str | None:
  """His photo from a club's people: the same name, else the same last name with a first name sharing its first three
  letters (Nate / Nathan Scheelhaase). Not a first initial alone: the 49ers' GM John Lynch got staffer Jake Lynch's
  photo (owner 2026-10-26, "is that his picture?")."""
  if not name or not people:
    return None
  n = _norm(name)
  byn = {_norm(k): v for k, v in people.items()}
  if n in byn:
    return byn[n]
  parts = n.split()
  if len(parts) < 2:
    return None
  near = [v for k, v in byn.items() if len(k.split()) >= 2 and k.split()[-1] == parts[-1] and k.split()[0][:3] == parts[0][:3]]
  return near[0] if len(near) == 1 else None


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
