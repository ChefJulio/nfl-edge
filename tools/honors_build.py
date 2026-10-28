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
  n = unicodedata.normalize("NFKD", n or "").encode("ascii", "ignore").decode()  # Tré -> Tre, Gramática -> Gramatica
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
  """'[[Name]], [[Team]]' / '[[Name]], Team' pairs in a wikitext block -> [(name, team code, rest of the item)]."""
  out = []
  for item in re.split(r"<br\s*/?>|\n", block):
    # the drafted-teams years (2014-16 games): "{{NFLplayer|12| Andrew Luck |([[Indianapolis Colts]])}}"
    for m in re.finditer(r"\{\{NFLplayer\|[^|]*\|\s*([^|]+?)\s*\|\s*\(([^)]*)\)", item):
      out.append((m.group(1), team_of(m.group(2)), item[m.end():]))
    for m in ENTRY.finditer(item):
      name = m.group(2)
      out.append((name, team_of(m.group(3)), item[m.end():]))
    # an unlinked repeat ("LaDainian Tomlinson, San Diego Chargers (AP-2)") on All-Pro pages
    if not ENTRY.search(item):
      m = re.match(r"\s*\|?\s*([A-Z][A-Za-z.'\- ]+?),\s*([A-Z][A-Za-z. ]+?)\s*(\(.*)$", item)
      if m and team_of(m.group(2)):
        out.append((m.group(1), team_of(m.group(2)), m.group(3)))
  return out


class Names:
  """(season, name) -> gsis, through that season's rosters; a shared name settles on the team."""
  def __init__(self, rosters: pd.DataFrame):
    r = rosters.dropna(subset=["gsis_id", "full_name"]).copy()
    r["team"] = r.team.replace(CODE_ALIAS)
    r["k"] = r.full_name.map(norm)
    self.by = {}
    for s, k, t, g in zip(r.season, r.k, r.team, r.gsis_id):
      self.by.setdefault((int(s), k), {}).setdefault(g, set()).add(t)
    self.miss = []

  def __call__(self, season: int, name: str, team: str | None) -> str | None:
    c = self.by.get((season, norm(name))) or {}
    if len(c) > 1 and team:
      c = {g: t for g, t in c.items() if team in t} or c
    if len(c) == 1:
      return next(iter(c))
    self.miss.append((season, name, team, len(c)))
    return None


def build(site: Path) -> None:
  import nflreadpy as nfl
  current = int(nfl.get_current_season())
  out_f = site / "data" / "honors.json"
  # finished seasons (their Super Bowl played) never change: kept in the repo (owner 2026-10-27: "most of this data we
  # just need to get once and we can store it in the repo"), so a build fetches only the season under way
  hist = json.loads(HIST.read_text(encoding="utf-8")) if HIST.exists() else {}
  keep = hist.get("seasons") if hist.get("v") == V else {}
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
      for name, team, rest in entries(ap):
        tags = re.search(r"\(([^)]*)\)", rest or "")
        tags = [t.strip() for t in tags.group(1).split(",")] if tags else []
        code = "AP1" if "AP" in tags else "AP2" if "AP-2" in tags else None
        if code:
          g = names(s, name, team)
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
            t = re.sub(r"^\s*(?:'{2,3})?[A-Z]{1,4}\s+(?=\[\[|[A-Z][a-z])", "", t)  # a leading position ("QB [[...")
            m = re.match(r"\s*(?:'{2,3})?(?:\[\[(?:[^\]|]+\|)?([^\]]+)\]\]|([A-Z][A-Za-z.'\- ]+?))(?=(?:'{2,3})?\s*(?:,|<br|\s[A-Z]{1,4}\b|$))", t)
            if m:
              g = names(s, m.group(1) or m.group(2), team_of(t[m.end():]))
              if g:
                rows.append([code, g, wk])
    # Pro Bowl: the rosters named for that season (the game is played the next calendar year)
    pb = wiki(f"{s + 1} Pro Bowl Games") or wiki(f"{s + 1} Pro Bowl")
    if pb:
      i = re.search(r"^==\s*(AFC roster|Rosters?|AFC rosters?|Selections)\s*==", pb, re.M | re.I)
      blk = pb[i.start():] if i else ""
      j = re.search(r"^==\s*(Number of selections|Selections per team|References|Notes|See also|External links|Broadcast)", blk, re.M | re.I)
      blk = blk[:j.start()] if j else blk
      for name, team, _ in entries(blk):
        g = names(s, name, team)
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
  build(ROOT / opt.get("site", "site"))
