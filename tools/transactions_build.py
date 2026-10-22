"""Transactions for Players > Moves: data/transactions/<season>.json (2002 on) + index.json.

Usage: python tools/transactions_build.py [--site=site] [--seasons=2002-2026]   (CI runs it daily)
Source: ESPN's public transactions feed (site.api.espn.com/apis/site/v2/sports/football/nfl/transactions; paginated,
100 per page; coverage thin before 2003). Raw pages are cached per season (cache/transactions_<season>.json); past
seasons are fetched once, the current season every run. Each entry is free text that can hold several moves
("Signed LB Michael Danna. Waived CB Anthony Kendall."): split into sentences, typed, and every "POS Name" (or
"WRs A and B") pulled out and matched to our player ids (gsis): by name + team on that season's or the previous
season's rosters first, then by name among players active that season (position family breaks namesake ties).
Unparsed sentences keep their raw text; nothing is guessed when a name stays ambiguous.
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.report import ROSTER_TEAM  # noqa: E402

V = 1
URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/transactions?season={s}&limit=100&page={p}"
ESPN_TEAM = {"LAR": "LA", "WSH": "WAS", "OAK": "LV", "SD": "LAC", "STL": "LA"}
POS = r"(?:QB|RB|FB|WR|TE|OT|OG|LT|RT|LG|RG|T|G|C|OL|DL|DE|DT|NT|LB|ILB|OLB|MLB|CB|S|SS|FS|DB|K|PK|P|LS|KR|PR|EDGE|ATH)"
# position families for telling namesakes apart; DE/OLB/EDGE count as both DL and LB (teams label them either way)
FAM = {"QB": {"QB"}, "RB": {"RB"}, "FB": {"RB"}, "WR": {"WR"}, "TE": {"TE"}, "K": {"K"}, "PK": {"K"}, "P": {"P"}, "LS": {"LS"},
       **{k: {"OL"} for k in "OT OG LT RT LG RG T G C OL".split()}, **{k: {"DL"} for k in "DL DT NT".split()},
       **{k: {"LB"} for k in "LB ILB MLB".split()}, **{k: {"DB"} for k in "CB S SS FS DB".split()},
       **{k: {"DL", "LB"} for k in "DE OLB EDGE".split()}}
# sentence type: first matching rule wins (order matters: staff/contract words, then practice-squad and injury
# variants, then plain verbs)
TYPES = [
  ("staff", r"\b(?:hired|fired|coordinator|head coach|coach|general manager|scout|trainer)\b"),
  ("option", r"\boption"), ("tendered", r"\btender"), ("extended", r"\bextension\b|\bextend"),
  ("free_agent", r"\bdeclared free agent"), ("retired", r"\bretire"), ("suspended", r"\bsuspend"), ("reinstated", r"\breinstat"),
  ("ps_elevated", r"\belevat"), ("promoted", r"\bpromot|\bsign\w*\b.*\bfrom\b.*\bpractice squad"),
  ("ps_signed", r"\bsign\w*\b.*\bpractice squad"),
  ("ps_released", r"\b(?:releas|waiv)\w*\b.*\bpractice squad"),
  ("designated", r"\bdesignated\b.*\breturn"), ("activated", r"\bactivat"),  # "Activated X off the PUP list"
  ("ir", r"\binjured reserve\b|\bIR\b"), ("pup", r"\bPUP\b|physically unable"), ("nfi", r"\bNFI\b|non-football"),
  ("traded", r"\btrad"), ("claimed", r"\bclaim|\bawarded\b"), ("re_signed", r"\bre-?sign"), ("signed", r"\bsign|\bagreed to terms"),
  ("waived", r"\bwaiv"), ("released", r"\breleas|\bcut\b|\bterminat"), ("acquired", r"\bacquir"),
  ("reserve", r"\breserve\b|\bplaced\b"), ("other", r"."),
]
CASED = {"ir", "pup", "nfi"}
# Before ~2009 ESPN spelled positions out ("Signed linebacker Zeke Moreno; released tackles A and B"): word -> abbr
WORDS = {"quarterback": "QB", "running back": "RB", "halfback": "RB", "fullback": "FB", "wide receiver": "WR",
         "receiver": "WR", "tight end": "TE", "offensive tackle": "OT", "tackle": "T", "offensive guard": "G", "guard": "G",
         "center": "C", "offensive lineman": "OL", "defensive end": "DE", "defensive tackle": "DT", "nose tackle": "NT",
         "defensive lineman": "DL", "linebacker": "LB", "inside linebacker": "ILB", "outside linebacker": "OLB",
         "middle linebacker": "MLB", "cornerback": "CB", "safety": "S", "free safety": "FS", "strong safety": "SS",
         "defensive back": "DB", "kicker": "K", "placekicker": "K", "punter": "P", "long snapper": "LS"}
PLURAL = lambda w: w[:-1] + "ies" if w.endswith("ty") else w[:-3] + "men" if w.endswith("man") else w + "s"  # noqa: E731
TOKPOS = {**{w: (a, False) for w, a in WORDS.items()}, **{PLURAL(w): (a, True) for w, a in WORDS.items()}}
POSWORD = "(?i:" + "|".join(sorted(map(re.escape, TOKPOS), key=len, reverse=True)) + ")"  # "Guard Will Shields" too
TOK = rf"(?!{POS}(?:'?s)?(?![\w.'’\-]))[A-Z][\w.'’\-]+"  # a capitalized word that is not itself a position ("and RB Jerome Ford")
NAME = rf"{TOK}(?:\s+(?:{TOK}|de|Van|van|St\.|Jr\.?|Sr\.?|II|III|IV|V)\b)+"
PLAYER = re.compile(rf"\b({POS}(?:'?s)?|{POSWORD})\s+({NAME}(?:(?:,\s*(?:and\s+)?|\s+and\s+){NAME})*)")


def get_page(season: int, page: int, limit: int) -> dict | None:
  """One feed page; None when ESPN answers 404 (a bad record 404s every page holding it: 2003, records 501-600)."""
  url = URL.format(s=season, p=page).replace("limit=100", f"limit={limit}")
  for attempt in range(5):
    try:
      return json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "nfl-edge-site/1.0"}), timeout=30))
    except urllib.error.HTTPError as e:
      if e.code == 404:
        return None
      time.sleep(3 * (attempt + 1))
    except Exception:
      time.sleep(3 * (attempt + 1))
  raise RuntimeError(f"transactions {season} page {page}")


def fetch_season(season: int) -> list:
  rows, page, skipped = [], 1, 0

  def keep(d):
    rows.extend({"date": t.get("date"), "team": (t.get("team") or {}).get("abbreviation"), "text": t.get("description") or ""}
                for t in d.get("transactions", []))

  def split(first: int, n: int, limit: int):  # records first..first+n-1 again in smaller pages; drop only the bad ones
    nonlocal skipped
    for k in range(n // limit):
      d = get_page(season, first // limit + k + 1, limit)
      if d is not None:
        keep(d)
      elif limit > 1:
        split(first + k * limit, limit, 1)
      else:
        skipped += 1
      time.sleep(0.2)

  while True:
    d = get_page(season, page, 100)
    if d is None:
      split((page - 1) * 100, 100, 10)
      last = get_page(season, 1, 100)
      count = int((last or {}).get("pageCount") or page)
    else:
      keep(d)
      count = int(d.get("pageCount") or 1)
    if page >= count:
      if skipped:
        print(f"[moves] {season}: skipped {skipped} records ESPN can't serve", flush=True)
      return rows
    page += 1
    time.sleep(0.4)


def sentences(text: str) -> list[str]:
  # split on ". " unless the period closes an initial ("A.J.") or a suffix/abbreviation; older entries chain moves
  # with "; " (each clause is its own move)
  parts = re.split(r"(?<!\b[A-Z])(?<!\bJr)(?<!\bSr)(?<!\bSt)\.\s+(?=[A-Z])|;\s+", re.sub(r"\s+", " ", text.strip()))
  return [p[0].upper() + p[1:] for p in (p.strip().rstrip(".") for p in parts) if len(p) > 3]


def parse(sentence: str) -> tuple[str, list[tuple[str, str]]]:
  kind = next(k for k, rx in TYPES if re.search(rx, sentence, 0 if k in CASED else re.I))
  players = []
  for m in PLAYER.finditer(sentence):
    tok = m.group(1)
    pos, many = TOKPOS.get(tok.lower()) or ((re.sub(r"'?s$", "", tok), True) if re.search(r"[A-Z]'?s$", tok) else (tok, False))
    names = re.findall(NAME, m.group(2))
    names = names if many else names[:1]  # plural position ("WRs A and B", "tackles A and B"): every listed name
    players += [(pos, re.sub(r"\s+(?:to|from|off|on|and|with|in)$", "", n).strip()) for n in names]
  return kind, players


def norm(n) -> str:
  n = n if isinstance(n, str) else ""
  return re.sub(r"[^a-z]", "", re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", n.lower()))


class Linker:
  """Name -> gsis for one season. Order: same name on this team's roster (this season, then last season); a name
  unique among players active this season; among namesakes, the one whose position family fits. Else None."""

  def __init__(self, season, rosters, players):
    self.by_nt, self.cands = {}, {}
    for ros in rosters:
      if ros is None or not len(ros):
        continue
      for x in ros.dropna(subset=["gsis_id"]).drop_duplicates(["gsis_id", "team"]).itertuples():
        self.by_nt.setdefault((norm(x.full_name), ROSTER_TEAM.get(x.team, ESPN_TEAM.get(x.team, x.team))), x.gsis_id)
    act = players[(players.rookie_season.fillna(0) <= season + 1) & (players.last_season.fillna(9999) >= season - 1)]
    for x in act.dropna(subset=["gsis_id"]).itertuples():
      fam = FAM.get(str(x.position), {str(x.position_group)})
      for nm in {norm(x.display_name), norm(f"{x.first_name} {x.last_name}"), norm(f"{x.football_name} {x.last_name}")}:
        self.cands.setdefault(nm, {})[x.gsis_id] = fam

  def __call__(self, name, team, pos):
    nm = norm(name)
    if (nm, team) in self.by_nt:
      return self.by_nt[(nm, team)]
    c = self.cands.get(nm, {})
    if len(c) > 1:
      want = FAM.get(pos, set())
      c = {g: f for g, f in c.items() if f & want}
    return next(iter(c)) if len(c) == 1 else None


PFR_BUDGET, PFR_PAUSE = 25, 3.0
# Moves that are the same event when ESPN and ProFootballRumors both log them (kinds differ by wording)
FAMILY = {**{k: "sign" for k in ("signed", "re_signed", "ps_signed", "promoted", "claimed", "acquired")},
          **{k: "out" for k in ("waived", "released", "ps_released")}, **{k: "res" for k in ("ir", "pup", "nfi", "reserve")}}


def pfr_moves(season: int, link, names: dict, have: list) -> list:
  """This season's moves from ProFootballRumors' daily "Minor NFL Transactions" posts (nfledge/elevations.pfr_lines;
  league year from Mar 1 to today), minus the ones ESPN already logged (same team, player and move family within
  3 days). ESPN's feed misses most practice-squad elevations (2 league-wide for week 6, 2026); these posts list them.
  The site throttles bursts (2026-10-21: timeouts after 6 quick requests), so each run fetches at most PFR_BUDGET
  uncached days, newest first, PFR_PAUSE seconds apart; the season backfills over a few runs, and days already
  cached are final."""
  from datetime import date, timedelta
  from nfledge import elevations as E
  seen = {}
  for r in have:
    if r[4]:
      seen.setdefault((r[1], r[5] or norm(r[4]), FAMILY.get(r[2], r[2])), []).append(date.fromisoformat(r[0]))
  first, last = date(season, 3, 1), min(date.today(), date(season + 1, 2, 28))
  days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
  todo = [d for d in reversed(days) if not E.pfr_cached(d)][:PFR_BUDGET]
  for i, d in enumerate(todo):
    if i:
      time.sleep(PFR_PAUSE)
    E.pfr_lines(d)
  missing = sum(not E.pfr_cached(d) for d in days if (date.today() - d).days >= 2)
  if missing:
    print(f"[moves] ProFootballRumors: {missing} days not fetched yet (next runs)", flush=True)
  out = []
  for day in days:
    for team_name, label, pos, name in E.pfr_lines(day, fetch=False):
      team = names.get(team_name)
      if not team:
        continue
      kind = next(k for k, rx in TYPES if re.search(rx, label, 0 if k in CASED else re.I))
      pid = link(name, team, pos)
      k = (team, pid or norm(name), FAMILY.get(kind, kind))
      if any(abs((day - d).days) <= 3 for d in seen.get(k, [])):
        continue
      seen.setdefault(k, []).append(day)
      out.append([day.isoformat(), team, kind, pos, name, pid, f"{label}: {pos} {name}", "pfr"])
  return out


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = Path(opt.get("site", "site"))
  import nflreadpy as nfl
  cfg = load_config()
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  current = int(nfl.get_current_season())
  a, _, b = opt.get("seasons", f"2002-{current}").partition("-")
  seasons = list(range(int(a), int(b or a) + 1))
  out = site / "data" / "transactions"
  out.mkdir(parents=True, exist_ok=True)
  players = cache.get("players", "all", lambda: nfl.load_players(), stale=cache.age_hours("players", "all") > 24 * 7)
  ros = {}
  t = cache.get("teams", "all", lambda: nfl.load_teams(), stale=False).drop_duplicates("team_abbr").set_index("team_abbr")
  full = {str(n): ROSTER_TEAM.get(a, ESPN_TEAM.get(a, a)) for a, n in zip(t.index, t.team_name)}

  def roster(s):
    if s not in ros:
      ros[s] = cache.get("rosters", s, lambda: nfl.load_rosters_weekly([s]), stale=s == current and cache.age_hours("rosters", s) > 24)
    return ros[s]

  for s in seasons:
    raw_path = ROOT / cfg["data"]["cache_dir"] / f"transactions_{s}.json"
    if raw_path.exists() and s != current:
      raw = json.loads(raw_path.read_text(encoding="utf-8"))
    else:
      try:
        raw = fetch_season(s)
        raw_path.write_text(json.dumps(raw, separators=(",", ":")), encoding="utf-8")
      except Exception as e:  # feed down: keep the cached copy (or skip the season)
        print(f"[moves] {s}: fetch failed ({e})", flush=True)
        if not raw_path.exists():
          continue
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
    cache.save_meta()
    link = Linker(s, [roster(s), roster(s - 1) if s > 2002 else None], players)
    moves, n_sent, n_parsed, n_linked, n_players = [], 0, 0, 0, 0
    for e in sorted(raw, key=lambda e: e["date"] or "", reverse=True):
      team = ESPN_TEAM.get(e["team"], e["team"])
      day = (e["date"] or "")[:10]
      prev = None
      for sent in sentences(e["text"]):
        n_sent += 1
        kind, found = parse(sent)
        if kind == "other" and found and prev:  # a list continuing the last move ("Signed rookies. QB A, WR B")
          kind = prev
        prev = kind if kind != "other" else prev
        n_parsed += kind != "other" and (bool(found) or kind == "staff")
        if not found:
          moves.append([day, team, kind, "", "", None, sent, "espn"])
          continue
        for pos, name in found:
          pid = link(name, team, pos)
          n_players += 1
          n_linked += pid is not None
          moves.append([day, team, kind, pos, name, pid, sent, "espn"])
    if s == current:
      extra = pfr_moves(s, link, full, moves)
      print(f"[moves] {s}: +{len(extra)} from ProFootballRumors", flush=True)
      moves = sorted(moves + extra, key=lambda r: r[0], reverse=True)
    cov = {"sentences": n_sent, "parsed": n_parsed, "players": n_players, "linked": n_linked}
    doc = {"v": V, "season": s, "cols": ["date", "team", "type", "pos", "name", "pid", "text", "src"], "rows": moves, "coverage": cov}
    (out / f"{s}.json").write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    print(f"[moves] {s}: {len(raw)} entries, {n_sent} moves, parsed {n_parsed / max(n_sent, 1):.0%}, "
          f"players linked {n_linked / max(n_players, 1):.0%}", flush=True)
  done = sorted(int(p.stem) for p in out.glob("[0-9][0-9][0-9][0-9].json"))
  teams = {a: {"nick": t.at[a, "team_nick"], "logo": t.at[a, "team_logo_espn"], "color": t.at[a, "team_color"]}
           for a in t.index if a not in ESPN_TEAM}
  (out / "index.json").write_text(json.dumps({"v": V, "seasons": done, "current": current, "teams": teams}), encoding="utf-8")


if __name__ == "__main__":
  main()
