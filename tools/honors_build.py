"""Player card > Honors tile (owner 2026-10-27: "pro bowl / all pro selections ... playoff / super bowl success ...
ROY, MVP, and POW, DPOY OPOY awards ... anything else relevant"): every player's honors since 1999, by season.
Writes data/honors.json: {"v", "built", "from", "p": {gsis: [[code, season], ...]}}.

  MVP OPOY DPOY OROY DROY CPOY SBMVP WPMOY   ESPN's award winners (sports.core.api.espn.com, by ESPN id)
  AP1 AP2                                    AP All-Pro first / second team (Wikipedia's "<season> All-Pro Team")
  PB                                         Pro Bowl: every player named, replacements included (Wikipedia's
                                             "<season + 1> Pro Bowl" / "Pro Bowl Games" rosters)
  SB                                         Super Bowl champion: on the winner's game-day roster (nflverse weekly
                                             rosters; season rosters before 2002)
  L_<stat>                                   led the league (regular season, nflverse player stats; ties shared)

  POW_O POW_D POW_S  POM_O POM_D POM_S       AFC / NFC Players of the Week / Month (Wikipedia's "<season> NFL
                                             season", about 2012 on), [code, season, week or month]
  AIR GROUND ROTW                            FedEx Air / FedEx Ground Player of the Week, Rookie of the Week (the
                                             same article's next table), [code, season, week]

Finished seasons are fetched once and kept in the repo (data/history/honors.json, committed); a build fetches only the
season under way (about ten requests). Names are matched to that season's rosters; ~1% don't match (name changes,
e.g. Chad Johnson / Ochocinco) and are left out.

  python tools/honors_build.py --site=site      (CI step "Honors", the full build)
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

V = 1
FIRST = 1999
HIST = ROOT / "data" / "history" / "honors.json"  # finished seasons, committed
UA = {"User-Agent": "nfl-edge/1.0 (https://github.com/ChefJulio/nfl-edge)"}
ESPN_AWARD = {477: "MVP", 478: "OPOY", 479: "DPOY", 480: "OROY", 481: "DROY", 483: "CPOY", 317: "SBMVP", 484: "WPMOY"}
LEADS = {"passing_yards": "pass_yds", "passing_tds": "pass_td", "rushing_yards": "rush_yds", "rushing_tds": "rush_td",
         "receptions": "rec", "receiving_yards": "rec_yds", "receiving_tds": "rec_td", "def_sacks": "sacks",
         "def_interceptions": "int"}
# team words -> nflverse codes, every name a franchise used since 1999
TEAM_WORDS = {"cardinals": "ARI", "arizona": "ARI", "falcons": "ATL", "atlanta": "ATL", "ravens": "BAL", "baltimore": "BAL",
              "bills": "BUF", "buffalo": "BUF", "panthers": "CAR", "carolina": "CAR", "bears": "CHI", "chicago": "CHI",
              "bengals": "CIN", "cincinnati": "CIN", "browns": "CLE", "cleveland": "CLE", "cowboys": "DAL", "dallas": "DAL",
              "broncos": "DEN", "denver": "DEN", "lions": "DET", "detroit": "DET", "packers": "GB", "green bay": "GB",
              "texans": "HOU", "houston": "HOU", "colts": "IND", "indianapolis": "IND", "jaguars": "JAX", "jacksonville": "JAX",
              "chiefs": "KC", "kansas city": "KC", "rams": "LA", "st. louis": "LA", "chargers": "LAC", "san diego": "LAC",
              "raiders": "LV", "oakland": "LV", "las vegas": "LV", "dolphins": "MIA", "miami": "MIA", "vikings": "MIN",
              "minnesota": "MIN", "patriots": "NE", "new england": "NE", "saints": "NO", "new orleans": "NO",
              "giants": "NYG", "jets": "NYJ", "eagles": "PHI", "philadelphia": "PHI", "steelers": "PIT", "pittsburgh": "PIT",
              "seahawks": "SEA", "seattle": "SEA", "49ers": "SF", "san francisco": "SF", "buccaneers": "TB", "tampa bay": "TB",
              "titans": "TEN", "tennessee": "TEN", "commanders": "WAS", "redskins": "WAS", "football team": "WAS",
              "washington": "WAS"}
# every older or alternate code nflverse's rosters use ("BLT": the 2012 weekly rosters' Baltimore)
CODE_ALIAS = {"STL": "LA", "LAR": "LA", "SL": "LA", "SD": "LAC", "OAK": "LV", "WSH": "WAS", "BLT": "BAL", "ARZ": "ARI",
              "CLV": "CLE", "HST": "HOU"}


def get(url: str, as_json: bool = False):
  for i in range(3):
    try:
      with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        b = r.read().decode("utf-8", errors="ignore")
      return json.loads(b) if as_json else b
    except Exception:
      if i == 2:
        raise
      time.sleep(2 * (i + 1))


def wiki(title: str, hops: int = 2) -> str | None:
  """A page's wikitext, following redirects ("2020 Pro Bowl Games" is a redirect to "2020 Pro Bowl": read as the page,
  four seasons' Pro Bowls went missing)."""
  try:
    t = get(f"https://en.wikipedia.org/w/index.php?title={urllib.parse.quote(title.replace(' ', '_'))}&action=raw")
  except Exception:
    return None
  m = re.match(r"\s*#REDIRECT\s*\[\[([^\]|#]+)", t or "", re.I)
  return wiki(m.group(1), hops - 1) if m and hops > 0 else t


def norm(n: str) -> str:
  import unicodedata
  n = n if isinstance(n, str) else ""  # a roster row with no name (NaN)
  n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode()  # Tré -> Tre, Gramática -> Gramatica
  n = re.sub(r"\(.*?\)", "", n).lower()
  n = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", n)
  return re.sub(r"[^a-z]", "", n)


def team_of(text: str) -> str | None:
  t = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text or "").lower()
  t = re.sub(r"\d{4}|season", "", t)
  for w in sorted(TEAM_WORDS, key=len, reverse=True):  # "new york" alone is ambiguous: giants / jets by nickname
    if w in t:
      return TEAM_WORDS[w]
  return None


ENTRY = re.compile(r"(?:'{2,3})?(?:\{\{[Ss]mall\|[^}]*\}\}\s*)?(?:'{2,3})?\[\[(?:([^\]|]+)\|)?([^\]]+)\]\](?:'{2,3})?\s*,\s*"
                   r"(\[\[[^\]]+\]\]|[A-Z][A-Za-z. ]+)")


def entries(block: str):
  """'[[Name]], [[Team]]' / '[[Name]], Team' pairs in a wikitext block -> [(name, team code, rest of the item, the
  link's target: its disambiguation, "(wide receiver, born 1993)", tells two players of one name apart)]."""
  out = []
  for item in re.split(r"<br\s*/?>|\n", block):
    # the drafted-teams years (2014-16 games): "{{NFLplayer|12| Andrew Luck |([[Indianapolis Colts]])}}"
    for m in re.finditer(r"\{\{NFLplayer\|[^|]*\|\s*([^|]+?)\s*\|\s*\(([^)]*)\)", item):
      out.append((m.group(1), team_of(m.group(2)), item[m.end():], None))
    for m in ENTRY.finditer(item):
      # a position where the team goes ("[[Kyle Fuller]], [[Cornerback]]", 2018's second table) serves as the hint
      tm = team_of(m.group(3))
      out.append((m.group(2), tm, item[m.end():], m.group(1) or (None if tm else m.group(3))))
    # an unlinked repeat ("LaDainian Tomlinson, San Diego Chargers (AP-2)") on All-Pro pages
    if not ENTRY.search(item):
      m = re.match(r"\s*\|?\s*([A-Z][A-Za-z.'\- ]+?),\s*([A-Z][A-Za-z. ]+?)\s*(\(.*)$", item)
      if m and team_of(m.group(2)):
        out.append((m.group(1), team_of(m.group(2)), m.group(3), None))
  return out


# Wikipedia's name -> the rosters' (normalized), where neither the full, first or football name matches (2026-10-27
# audit of every miss, 1999-2025); and one-off fixes by (season, name, team)
ALIAS = {"andresborregales": "andyborregales", "anthonyhargrove": "tonyhargrove", "bamknight": "zonovanknight",
         "bertrandberry": "bertberry", "chadjohnson": "chadochocinco", "foyesadeoluokun": "foyeoluokun",
         "gregoryrousseau": "gregrousseau", "iketaylor": "ivantaylor", "jeffwilson": "jefferywilson",
         "johnhekker": "johnnyhekker", "jonweeks": "jonathanweeks", "joshcribbs": "joshuacribbs",
         "mattmcgloin": "matthewmcgloin", "matthewjudon": "mattjudon", "matthewslater": "mattslater",
         "michaelbadgley": "mikebadgley", "nnamdimadubuike": "justinmadubuike", "patricksurtain": "patsurtain",
         "rodcoleman": "roderickcoleman", "saucegardner": "ahmadgardner", "shaquilleleonard": "dariusleonard",
         "stevenhauschka": "stephenhauschka"}
FIX = {(2003, "brennan", "PIT"): "00-0005058",  # 2004 Pro Bowl page: #66 Pittsburgh guard Alan Faneca, mislabeled
       # 2018 All-Pro's teamless table: two Chris Joneses on defensive lines (SF, KC); "(born 1994)" is Kansas City's
       (2018, "chrisjones", None): "00-0032762"}
# a link's disambiguation ("Chris Jones (defensive tackle, born 1994)") -> roster positions, for a shared name
POS_HINT = {"quarterback": {"QB"}, "running back": {"RB", "FB", "HB"}, "fullback": {"FB", "RB"}, "wide receiver": {"WR"},
            "tight end": {"TE"}, "defensive end": {"DE", "DL", "OLB", "EDGE"}, "defensive tackle": {"DT", "DL", "NT"},
            "linebacker": {"LB", "OLB", "ILB", "MLB"}, "cornerback": {"CB", "DB"}, "safety": {"S", "SS", "FS", "DB"},
            "defensive back": {"CB", "S", "SS", "FS", "DB"}, "offensive tackle": {"T", "OT", "OL"},
            "guard": {"G", "OG", "OL"}, "center": {"C", "OL"}, "kicker": {"K"}, "punter": {"P"}, "long snapper": {"LS"}}


class Names:
  """(season, name) -> gsis, through that season's rosters (full name, first + last, football name + last); a shared
  name settles on the team, then on the link's position hint."""
  def __init__(self, rosters: pd.DataFrame):
    r = rosters.dropna(subset=["gsis_id"]).copy()
    r["team"] = r.team.replace(CODE_ALIAS)
    self.by, self.pos = {}, {}
    cols = [c for c in ("full_name", "first_name", "football_name", "last_name") if c in r]
    for row in r[["season", "team", "gsis_id", "position", *cols]].itertuples(index=False):
      d = row._asdict()
      keys = {norm(d.get("full_name") or "")}
      for f in ("first_name", "football_name"):
        if isinstance(d.get(f), str) and isinstance(d.get("last_name"), str):
          keys.add(norm(f"{d[f]} {d['last_name']}"))
      for k in keys - {""}:
        self.by.setdefault((int(d["season"]), k), {}).setdefault(d["gsis_id"], set()).add(d["team"])
      self.pos.setdefault(d["gsis_id"], set()).add(d.get("position"))
    self.miss = []

  def __call__(self, season: int, name: str, team: str | None, hint: str | None = None) -> str | None:
    k = norm(name)
    if (season, k, team) in FIX:
      return FIX[(season, k, team)]
    c = self.by.get((season, k)) or self.by.get((season, ALIAS.get(k, ""))) or {}
    if len(c) > 1 and team:
      c = {g: t for g, t in c.items() if team in t} or c
    if len(c) > 1 and hint:
      want = set().union(*(v for w, v in POS_HINT.items() if w in hint.lower())) if any(w in hint.lower() for w in POS_HINT) else set()
      c = {g: t for g, t in c.items() if self.pos.get(g, set()) & want} or c
    if len(c) == 1:
      return next(iter(c))
    self.miss.append((season, name, team, len(c)))
    return None


def build(site: Path, refetch: bool = False) -> None:
  import nflreadpy as nfl
  current = int(nfl.get_current_season())
  out_f = site / "data" / "honors.json"
  # finished seasons (their Super Bowl played) never change: kept in the repo (owner 2026-10-27: "most of this data we
  # just need to get once and we can store it in the repo"), so a build fetches only the season under way
  hist = json.loads(HIST.read_text(encoding="utf-8")) if HIST.exists() else {}
  keep = hist.get("seasons") if hist.get("v") == V and not refetch else {}  # --refetch=1: every season again
  keep = keep or {}
  seasons = list(range(FIRST, current + 1))
  sched = nfl.load_schedules(seasons).to_pandas()
  done = set(sched[(sched.game_type == "SB") & sched.result.notna()].season.astype(int))
  todo = [s for s in seasons if not (str(s) in keep and s in done)]
  ros = nfl.load_rosters(todo).to_pandas() if todo else pd.DataFrame(columns=["season", "team", "full_name", "gsis_id", "status"])
  names = Names(ros)
  players = nfl.load_players().to_pandas()
  espn = {str(int(e)): g for e, g in zip(players.espn_id, players.gsis_id) if pd.notna(e) and isinstance(g, str)}
  by = {}
  for s in seasons:
    if s not in todo:
      by[s] = keep[str(s)]
      continue
    rows = []
    # ESPN's awards
    try:
      lst = get(f"https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/{s}/awards?limit=100", True)
      for it in lst.get("items", []):
        aid = int(re.search(r"/awards/(\d+)", it["$ref"]).group(1))
        if aid not in ESPN_AWARD:
          continue
        a = get(it["$ref"].replace("http://", "https://"), True)
        for w in a.get("winners", []):
          ref = (w.get("athlete") or {}).get("$ref", "")
          m = re.search(r"/athletes/(\d+)", ref)
          if m and m.group(1) in espn:
            rows.append([ESPN_AWARD[aid], espn[m.group(1)]])
    except Exception as e:
      print(f"[honors] {s}: ESPN awards unavailable ({e})", flush=True)
    # All-Pro (AP first / second team)
    ap = wiki(f"{s} All-Pro Team")
    if ap:
      for name, team, rest, hint in entries(ap):
        tags = re.search(r"\(([^)]*)\)", rest or "")
        tags = [t.strip() for t in tags.group(1).split(",")] if tags else []
        code = "AP1" if "AP" in tags else "AP2" if "AP-2" in tags else None
        if code:
          g = names(s, name, team, hint)
          if g:
            rows.append([code, g])
    # Players of the Week / Month (owner 2026-10-27, pointing at Wikipedia when told there was no source): the season
    # article's table, a row per week (or month), six cells: offense AFC / NFC, defense AFC / NFC, special teams AFC /
    # NFC, each "[[Name]] POS<br />(Team)". Wikipedia carries it from about 2012 (patchy before).
    # The table right after it (2014 on, roughly): FedEx Air / FedEx Ground Players of the Week and Rookie of the Week,
    # three cells a week. A name already linked higher up the article comes unlinked ("Josh Allen QB<br />(Buffalo)").
    art = wiki(f"{s} NFL season")
    i = re.search(r"^=+.*Players of the Week", art or "", re.I | re.M)  # the section, not a mention in the text
    if i:
      sec = art[i.start():]
      nxt = re.search(r"^==[^=]", sec[3:], re.M)
      sec = sec[:nxt.start() + 3] if nxt else sec
      for tbl in re.findall(r"\{\|.*?\n\|\}", sec, re.S):
        fedex = "FedEx" in tbl[:600]
        if not fedex and not re.search(r"Offensive", tbl[:600]):
          continue  # the rookie-of-the-month table and the like
        cols = ["AIR", "GROUND", "ROTW"] if fedex else ["POW_O", "POW_O", "POW_D", "POW_D", "POW_S", "POW_S"]
        for row in re.split(r"\n\|-", tbl)[1:]:
          # a row's cells, one per "!" / "|" line ("a || b" split too); the first is its label ("5", "Sept."). Three
          # layouts over the years: "[[Name]] POS<br />(Team)" (2018 on), "[[Name]], Team" (2014), "QB [[Name]],
          # [[Team]]" with the week as a plain cell (2010). A month's row starts with its style line.
          lines = [x for ln in row.split("\n") if ln[:1] and ln[0] in "!|" and not ln.startswith("|-")
                   for x in re.split(r"\s*(?:\|\||!!)\s*", ln[1:])]
          if len(lines) < len(cols) + 1:
            continue
          lab = re.sub(r"<ref.*|\{\{.*", "", lines[0]).strip()
          month = re.match(r"(Sep|Oct|Nov|Dec|Jan)", lab)
          if not (re.match(r"\d+$", lab) or (month and not fedex)):
            continue
          wk = int(lab) if lab.isdigit() else lab[:3]
          for c, code in zip(lines[1:len(cols) + 1], cols):
            if month:
              code = code.replace("POW", "POM")  # a month's row: Player of the Month
            t = re.sub(r"\{\{[^}]*\}\}|<ref.*?(</ref>|/>)", "", c)
            # a leading position ("QB [[...", "WR-PR Jacoby Jones")
            t = re.sub(r"^\s*(?:'{2,3})?[A-Z]{1,4}(?:[-/][A-Z]{1,4})?\s+(?=\[\[|[A-Z][a-z])", "", t)
            # the name: a link, else plain text up to its position, a comma or the line break ("A. J. Brown WR<br />":
            # the position must end its token, so "J." isn't read as one)
            m = re.match(r"\s*(?:'{2,3})?(?:\[\[(?:([^\]|]+)\|)?([^\]]+)\]\]|([A-Z][A-Za-z.'\- ]+?))"
                         r"(?=(?:'{2,3})?\s*(?:,|<br|\s[A-Z]{1,4}(?:[-/][A-Z]{1,4})?\s*(?:<br|\(|$)|$))", t)
            if m:
              g = names(s, m.group(2) or m.group(3), team_of(t[m.end():]), m.group(1))
              if g:
                rows.append([code, g, wk])
    # Pro Bowl: the rosters named for that season (the game is played the next calendar year)
    pb = wiki(f"{s + 1} Pro Bowl Games") or wiki(f"{s + 1} Pro Bowl")
    if pb:
      i = re.search(r"^==\s*(AFC roster|Rosters?|AFC rosters?|Selections)\s*==", pb, re.M | re.I)
      blk = pb[i.start():] if i else ""
      j = re.search(r"^==\s*(Number of selections|Selections per team|References|Notes|See also|External links|Broadcast)", blk, re.M | re.I)
      blk = blk[:j.start()] if j else blk
      for name, team, _, hint in entries(blk):
        g = names(s, name, team, hint)
        if g:
          rows.append(["PB", g])
    # Super Bowl champion: the winner's game-day roster
    sb = sched[(sched.season == s) & (sched.game_type == "SB") & sched.result.notna()]
    if len(sb):
      r0 = sb.iloc[0]
      win = (r0.home_team if r0.result > 0 else r0.away_team)
      win = CODE_ALIAS.get(win, win)
      try:
        w = nfl.load_rosters_weekly([s]).to_pandas() if s >= 2002 else None
      except Exception:
        w = None
      if w is not None and "game_type" in w and (w.game_type == "SB").any():
        x = w[(w.game_type == "SB") & (w.team.replace(CODE_ALIAS) == win) & w.status.isin(["ACT", "INA"])]
      else:
        x = ros[(ros.season == s) & (ros.team.replace(CODE_ALIAS) == win) & (ros.status == "ACT")]
      rows += [["SB", g] for g in x.gsis_id.dropna().unique()]
    by[s] = rows
    time.sleep(0.5)
  # league leaders, the fetched seasons whose regular season is over (a kept season already has them)
  lead = [s for s in todo if s in done]
  st = nfl.load_player_stats(lead).to_pandas() if lead else pd.DataFrame(columns=["season_type"])
  st = st[st.season_type == "REG"]
  for col, code in LEADS.items():
    if col not in st:
      continue
    tot = st.groupby(["season", "player_id"])[col].sum().reset_index()
    for s, g in tot.groupby("season"):
      top = g[col].max()
      if top and top > 0:
        by.setdefault(int(s), [])
        by[int(s)] += [[f"L_{code}", pid] for pid in g[g[col] == top].player_id]
  p = {}
  for s, rows in by.items():
    for code, g, *wk in rows:
      p.setdefault(g, []).append([code, int(s), *wk])  # [code, season] or, weekly / monthly, [code, season, week]
  for g in p:
    p[g] = [list(x) for x in sorted({tuple(x) for x in p[g]}, key=lambda x: (x[1], x[0], str(x[2:])))]
  if names.miss:
    print(f"[honors] {len(names.miss)} names not matched to a roster, e.g. {names.miss[:5]}", flush=True)
    # every miss with that season's roster candidates (same team and last name), for the ALIAS list
    (ROOT / "scratch").mkdir(exist_ok=True)
    rk = ros.dropna(subset=["full_name"]).assign(team=lambda r: r.team.replace(CODE_ALIAS))
    with open(ROOT / "scratch" / "honors_miss.txt", "w", encoding="utf-8") as f:
      for s, n, t, k in sorted(set(names.miss), key=lambda x: (x[1], x[0])):
        last = norm(n.split()[-1]) if n.split() else ""
        c = rk[(rk.season == s) & ((rk.team == t) if t else True)]
        c = c[c.full_name.map(lambda x: norm(x.split()[-1]) == last if x.split() else False)]
        f.write(f"{s}\t{n}\t{t}\t{k}\t{' | '.join(f'{a} {b}' for a, b in zip(c.full_name, c.gsis_id))}\n")
  new = {str(s): by[s] for s in todo if s in done}
  if new:  # a season just finished (or a new V): into the repo's history (committed from a local run)
    HIST.parent.mkdir(parents=True, exist_ok=True)
    HIST.write_text(json.dumps({"v": V, "seasons": {**keep, **new}}, separators=(",", ":")), encoding="utf-8")
    print(f"[honors] history: added {sorted(new)}", flush=True)
  doc = {"v": V, "built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "from": FIRST, "p": p}
  out_f.parent.mkdir(parents=True, exist_ok=True)
  out_f.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
  print(f"[honors] wrote {out_f} ({len(p)} players, {sum(len(v) for v in p.values())} honors)", flush=True)


if __name__ == "__main__":
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  build(ROOT / opt.get("site", "site"), refetch=opt.get("refetch") == "1")
