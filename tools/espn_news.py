"""Daily archive of ESPN fantasy news blurbs for injured players + in-game injuries parsed from them (owner 2026-10-14).

Blurbs say what the play-by-play misses: "Jefferson ... the ankle injury that forced him out of this past Sunday's win",
"...since the second quarter of a Week 3 win in Tampa Bay, when he initially picked up a left ankle injury". The
play-by-play notes an injury only when play stops for a player down (nfledge/ingame.py); a player who walks off or is
pulled at halftime goes unnoted.

ESPN serves blurbs per player and only for the current season, so the archive is built going forward: once a day
(skipped if today's file exists), every player on ESPN's injury list (site/data/espn_injuries/latest.json, written by
tools/espn_snapshot.py just before) is fetched politely. Parsing is plain patterns, no language model.

Usage: python tools/espn_news.py [--out=site/data/espn_news]
Writes <out>/<YYYY-MM-DD>.json (raw blurbs) and <out>/ingame.json (in-game injury events, current season:
[{espn, name, team, week, q, published, text}]). Unofficial endpoint; any failure is non-fatal.
"""
import datetime as dt
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

URL = "https://site.web.api.espn.com/apis/fantasy/v2/games/ffl/news/players?days=60&playerId={}"
UA = {"User-Agent": "nfl-edge-site/1.0"}
PAUSE = 0.25  # seconds between requests
# "left / exited ... game", "did not return", "forced out", "carted off", "injured ... in the second quarter"
GAME = r"(?:game|contest|win|loss|matchup|tilt|victory|defeat)"
LEFT = re.compile(
  r"\b(?:left|exited)\b(?!\s+(?:him|her|them|it|us)\b)[^.;]{0,50}\b" + GAME + r"\b"           # left Sunday's game
  r"|\b(?:did not|didn't|was unable to|couldn't|could not|wouldn't) return\b"
  r"|\b(?:questionable|doubtful|unlikely) to return\b"
  r"|\bruled out for the (?:rest|remainder)\b"
  r"|\bforced (?:him |her )?(?:out|from)\b|\bcarted off\b"
  r"|\binjur\w* (?:his|her) \w+[^.;]{0,30}\b(?:during|in)\b[^.;]{0,40}\b" + GAME + r"\b"     # injured his finger during the loss
  r"|\binjur\w*[^.;]{0,50}\b(?:first|second|third|fourth|1st|2nd|3rd|4th) quarter\b"
  r"|\b(?:first|second|third|fourth|1st|2nd|3rd|4th) quarter\b[^.;]{0,50}\binjur\w*", re.I)
QTR = re.compile(r"\b(first|second|third|fourth|1st|2nd|3rd|4th) quarter\b|\b(halftime)\b", re.I)
QNUM = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4, "halftime": 2}
WEEK = re.compile(r"\bWeek (\d{1,2})\b")
TAG = re.compile(r"<[^>]+>")
# Practice attire (owner 2026-10-16: "non contact jerseys, something we can parse ... and test relating to active%"):
# "red non-contact jersey", "no-contact jersey", "yellow jersey". Not "non-contact injury" (an injury type).
JERSEY = re.compile(r"\b(?:non|no)-?\s?contact (?:red |yellow )?jersey|\b(?:red|yellow) (?:non-?|no-)?contact jersey"
                    r"|\b(?:red|yellow) jersey", re.I)


def fetch(espn_id: str) -> list:
  try:
    req = urllib.request.Request(URL.format(espn_id), headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
      feed = json.loads(r.read().decode("utf-8")).get("feed", [])
  except Exception:
    return []
  out = []
  for x in feed:
    story = TAG.sub(" ", x.get("story") or x.get("description") or "")
    if len(story) > 1200:  # long articles (lineup columns), not player blurbs
      continue
    out.append({"id": x.get("id"), "espn": str(espn_id), "published": (x.get("published") or "")[:19],
                "headline": x.get("headline") or "", "story": " ".join(story.split())})
  return out


def week_of(published: str, text: str, m, kicks: list) -> int | None:
  """The game the blurb is about: the last game HIS team kicked off before it was published (a Sunday-morning blurb
  about "last Sunday's win" is the previous week); an explicit 'Week N' only when it sits in the same sentence as the
  injury phrase ("...second quarter of a Week 3 win") and is not later (blurbs also name the upcoming week)."""
  done = [w for w, ko in kicks if ko < published]
  last = max(done) if done else None
  lo = max(text.rfind(".", 0, m.start()), text.rfind(";", 0, m.start())) + 1
  hi = min([i for i in (text.find(".", m.end()), text.find(";", m.end())) if i >= 0] or [len(text)])
  wm = WEEK.search(text[lo:hi])
  if wm and (last is None or int(wm.group(1)) <= last):
    return int(wm.group(1))
  return last


def events(blurbs: list, inj: dict, kicks_of: dict) -> list:
  """In-game injury events, one per (player, week): the earliest blurb that says so."""
  seen, out = {}, []
  for b in sorted(blurbs, key=lambda x: x["published"]):
    text = f"{b['headline']} {b['story']}"
    m = LEFT.search(text)
    if not m:
      continue
    who = inj.get(b["espn"], {})
    wk = week_of(b["published"], text, m, kicks_of.get(who.get("team"), []))
    q = QTR.search(text)
    if wk is None:
      continue
    if (b["espn"], wk) in seen:  # already have this injury: a later blurb may still name the quarter
      prev = seen[(b["espn"], wk)]
      if prev["q"] is None and q:
        prev["q"] = QNUM.get((q.group(1) or q.group(2)).lower())
      continue
    ev = {"espn": b["espn"], "name": who.get("name"), "team": who.get("team"), "week": wk,
          "q": QNUM.get((q.group(1) or q.group(2)).lower()) if q else None, "published": b["published"],
          "text": b["headline"][:240], "hit": m.group(0)[:80]}
    seen[(b["espn"], wk)] = ev
    out.append(ev)
  return out


def jerseys(blurbs: list, inj: dict, kicks_of: dict) -> list:
  """Non-contact jersey sightings, one per (player, upcoming game): the team's first kickoff after the blurb was
  published. Kept going forward for the pre-registered forward test (INSIGHTS sec. 9, non-contact jersey)."""
  seen, out = set(), []
  for b in sorted(blurbs, key=lambda x: x["published"]):
    text = f"{b['headline']} {b['story']}"
    m = JERSEY.search(text)
    if not m:
      continue
    who = inj.get(b["espn"], {})
    nxt = [w for w, ko in kicks_of.get(who.get("team"), []) if ko > b["published"]]
    wk = min(nxt) if nxt else None
    if wk is None or (b["espn"], wk) in seen:
      continue
    seen.add((b["espn"], wk))
    lo = max(0, m.start() - 160)
    out.append({"espn": b["espn"], "name": who.get("name"), "team": who.get("team"), "week": wk,
                "published": b["published"], "text": text[lo:m.end() + 80]})
  return out


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  out = Path(opt.get("out", "site/data/espn_news"))
  inj_path = Path(opt.get("injuries", "site/data/espn_injuries/latest.json"))
  if not inj_path.exists():
    print("[news] no ESPN injury list; skipped")
    return
  rows = json.loads(inj_path.read_text(encoding="utf-8")).get("rows", [])
  inj = {str(r["espn_id"]): r for r in rows if r.get("espn_id")}
  out.mkdir(parents=True, exist_ok=True)
  today = out / f"{dt.datetime.now(dt.timezone.utc):%Y-%m-%d}.json"
  if not today.exists():
    blurbs = []
    for i, e in enumerate(inj):
      blurbs += fetch(e)
      time.sleep(PAUSE)
    if not blurbs:
      print("[news] feed empty or unavailable; skipped")
      return
    today.write_text(json.dumps(blurbs, separators=(",", ":")), encoding="utf-8")
    print(f"[news] {len(inj)} players, {len(blurbs)} blurbs", flush=True)
  # every archived blurb this season (deduped by id) -> events
  import nflreadpy as nfl
  season = int(nfl.get_current_season())
  sch = nfl.load_schedules([season]).to_pandas()
  sch = sch[sch.game_type == "REG"]
  # each team's kickoffs in UTC (schedule times are US Eastern; EDT = UTC-4 through early November, EST after)
  teams = nfl.load_teams().to_pandas()
  name_of = dict(zip(teams.team_abbr, teams.team_name))
  kicks_of = {}
  for g in sch.itertuples():
    ko = dt.datetime.fromisoformat(f"{g.gameday}T{g.gametime or '13:00'}:00")
    ko += dt.timedelta(hours=4 if ko.month < 11 or (ko.month == 11 and ko.day < 2) else 5)
    for t in (g.home_team, g.away_team):
      kicks_of.setdefault(name_of.get(t, t), []).append((int(g.week), ko.strftime("%Y-%m-%dT%H:%M:%S")))
  start = f"{season}-08-01"
  allb = {}
  for f in sorted(out.glob("[0-9][0-9][0-9][0-9]-*.json")):
    if f.stem < start:
      continue
    for b in json.loads(f.read_text(encoding="utf-8")):
      if b.get("published", "") >= start:
        allb[b.get("id") or (b["espn"], b["published"])] = b
  ev = events(list(allb.values()), inj, kicks_of)
  (out / "ingame.json").write_text(json.dumps({"season": season, "events": ev}, separators=(",", ":")), encoding="utf-8")
  print(f"[news] {len(ev)} in-game injury events this season", flush=True)
  js = jerseys(list(allb.values()), inj, kicks_of)
  (out / "jersey.json").write_text(json.dumps({"season": season, "sightings": js}, separators=(",", ":")), encoding="utf-8")
  print(f"[news] {len(js)} non-contact jersey sightings this season", flush=True)


if __name__ == "__main__":
  main()
