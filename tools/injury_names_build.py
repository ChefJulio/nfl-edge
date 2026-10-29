"""Names for injuries the weekly reports never named (owner 2026-10-28: "a lot of 'undisclosed' injuries in players
histories that aren't in fact undisclosed"). A player placed on a reserve list (IR, PUP, NFI) leaves the weekly injury
report, so an episode built from reserve weeks alone had no body part: 1,880 of 38,181 episodes read "Undisclosed",
Tyron Smith's 2022 hamstring and Edelman's 2020 knee among them.

Two sources, each matched to the stint by date in tools/player_logs.py:
  wiki   the player's English Wikipedia article ("placed on injured reserve on September 28, 2020, with a torn
         biceps"), found through Wikidata's Pro Football Reference id; every season
  espn   ESPN's player news ("The Jets placed Smith (neck) on injured reserve"); the feed keeps about two seasons

Writes data/history/ir_names.json (committed): {"v", "built", "p": {gsis: [[season, "YYYY-MM-DD" or "", part, src]]},
"done": {"wiki": [gsis], "espn": {gsis: "YYYY-MM-DD"}}}. Finished seasons are fetched once; a CI run re-reads only
the news of this season's players placed in the last two weeks.

  python tools/injury_names_build.py            (CI step "Injury names", before the player pages)
  python tools/injury_names_build.py --all      (re-read every article and news feed)
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.codes import INJURY_LISTS, RESERVE as RESERVE_CODES  # noqa: E402
from nfledge.config import load_config  # noqa: E402

V = 1
FIRST = 2009  # the injury history starts with the official reports
NEWS_FROM = 2023  # ESPN's player news reaches back about this far
OUT = ROOT / "data" / "history" / "ir_names.json"
UA = {"User-Agent": "nfl-edge/1.0 (https://github.com/ChefJulio/nfl-edge)"}
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                       "september", "october", "november", "december"], 1)}

# ---- the injury, in words: an adjective (torn, broken ...) and a body part, longest first
ADJ = r"(?:(?:partially |completely |season-ending |slightly |small |minor |significant |severe |)" \
      r"(?:torn|tear(?:ing)?|broken|break|fractured|fracture|sprained|sprain|strained|strain|ruptured|rupture|dislocated|" \
      r"dislocation|bruised|bone bruise|separated|herniated|lacerated|pulled|injured|damaged|hyperextended|high ankle|" \
      r"low ankle|stress))"
PARTS = [
  ("anterior cruciate ligament", "ACL"), ("medial collateral ligament", "MCL"), ("posterior cruciate ligament", "PCL"),
  ("lateral collateral ligament", "LCL"), ("ACL", "ACL"), ("MCL", "MCL"), ("PCL", "PCL"), ("LCL", "LCL"),
  ("meniscus", "Meniscus"), ("patellar tendon", "Patellar tendon"), ("patella", "Kneecap"), ("kneecap", "Kneecap"),
  ("knee", "Knee"), ("achilles tendon", "Achilles"), ("achilles", "Achilles"), ("high ankle sprain", "High ankle sprain"),
  ("ankle", "Ankle"), ("lisfranc", "Lisfranc (foot)"), ("turf toe", "Turf toe"), ("plantar fascia", "Plantar fascia"),
  ("heel", "Heel"), ("toe", "Toe"), ("foot", "Foot"), ("fibula", "Fibula"), ("tibia", "Tibia"), ("shin", "Shin"),
  ("calf", "Calf"), ("hamstring", "Hamstring"), ("quadriceps", "Quadriceps"), ("quad", "Quadriceps"),
  ("thigh", "Thigh"), ("groin", "Groin"), ("hip flexor", "Hip flexor"), ("hip", "Hip"), ("pelvis", "Pelvis"),
  ("sports hernia", "Sports hernia"), ("core muscle", "Core muscle"), ("abdominal", "Abdomen"), ("abdomen", "Abdomen"),
  ("oblique", "Oblique"), ("lower back", "Back"), ("back", "Back"), ("spine", "Spine"), ("neck", "Neck"),
  ("stinger", "Stinger"), ("concussion", "Concussion"), ("rotator cuff", "Rotator cuff"), ("labrum", "Labrum"),
  ("ac joint", "Shoulder (AC joint)"), ("shoulder", "Shoulder"), ("collarbone", "Collarbone"), ("clavicle", "Collarbone"),
  ("pectoral", "Pectoral"), ("pec", "Pectoral"), ("chest", "Chest"), ("ribs", "Ribs"), ("rib", "Ribs"), ("sternum", "Sternum"),
  ("lung", "Lung"), ("kidney", "Kidney"), ("spleen", "Spleen"), ("biceps", "Biceps"), ("bicep", "Biceps"),
  ("triceps", "Triceps"), ("tricep", "Triceps"), ("elbow", "Elbow"), ("forearm", "Forearm"), ("wrist", "Wrist"),
  ("thumb", "Thumb"), ("finger", "Finger"), ("hand", "Hand"), ("arm", "Arm"), ("jaw", "Jaw"), ("eye", "Eye"),
  ("leg", "Leg"), ("blood clot", "Blood clots"), ("heart", "Heart"), ("illness", "Illness"),
]
PART_RX = re.compile(r"\b(?:(" + ADJ + r")\s+)?(?:(?:left|right)\s+)?(" + "|".join(re.escape(p) for p, _ in PARTS) + r")s?\b", re.I)
PART_OF = {p.lower(): n for p, n in PARTS}
ADJ_WORD = {"tear": "torn", "tearing": "torn", "break": "broken", "fracture": "fractured", "sprain": "sprained",
            "strain": "strained", "rupture": "ruptured", "dislocation": "dislocated", "pulled": "strained",
            "high ankle": "", "low ankle": "", "injured": "", "damaged": "", "stress": "stress"}
# a reserve-list move in words
LIST_RX = re.compile(r"injured reserve|reserve/injured|\bIR\b|physically unable|\bPUP\b|non-football injur|\bNFI\b", re.I)


def get(url: str, as_json: bool = False):
  for i in range(3):
    try:
      with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        b = r.read().decode("utf-8", errors="ignore")
      return json.loads(b) if as_json else b
    except Exception:
      if i == 2:
        raise
      time.sleep(2 * (i + 1))


def injury_in(text: str) -> str:
  """The first injury named in a sentence: "a torn ACL" -> "Torn ACL", "his hamstring" -> "Hamstring"."""
  for m in PART_RX.finditer(text):
    part = PART_OF.get(m.group(2).lower())
    if not part or (part == "Leg" and re.search(r"\blegal\b", text[m.start():m.end() + 2], re.I)):
      continue
    # "back" the body part, not the adverb ("moved back to injured reserve" read as a back injury)
    if part == "Back" and not (m.group(1) or re.search(r"(?:his|a|lower|upper|sore)\s+back\b|\bback\s+(?:injur|spasm|surgery|strain|issue|problem|tightness)",
                                                       text[max(0, m.start() - 8):m.end() + 12], re.I)):
      continue
    adj = (m.group(1) or "").lower().strip()
    adj = ADJ_WORD.get(adj.split()[-1] if adj else "", adj.split()[-1] if adj else "")
    if part == "High ankle sprain" or part.startswith(adj.capitalize()):
      adj = ""
    proper = part in ("ACL", "MCL", "PCL", "LCL", "Achilles", "Lisfranc (foot)")
    return f"{adj.capitalize()} {part if proper else part[0].lower() + part[1:]}" if adj else part
  return ""


# ---- Wikipedia --------------------------------------------------------------------------------------------------------
def wiki_titles() -> dict:
  """Pro Football Reference id ("SmitTy00") -> English Wikipedia title, from Wikidata (one query)."""
  q = "SELECT ?pfr ?article WHERE { ?item wdt:P3561 ?pfr . ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . }"
  j = get("https://query.wikidata.org/sparql?format=json&query=" + urllib.parse.quote(q), as_json=True)
  out = {}
  for b in j["results"]["bindings"]:
    pfr = b["pfr"]["value"].split("/")[-1]
    out[pfr] = urllib.parse.unquote(b["article"]["value"].rsplit("/", 1)[-1]).replace("_", " ")
  return out


def wiki_texts(titles: list) -> dict:
  """title -> wikitext, 50 a request (redirects followed; the asked title keys the result)."""
  out = {}
  for i in range(0, len(titles), 50):
    batch = titles[i:i + 50]
    url = ("https://en.wikipedia.org/w/api.php?action=query&prop=revisions&rvprop=content&rvslots=main&format=json"
           "&formatversion=2&redirects=1&titles=" + urllib.parse.quote("|".join(batch)))
    try:
      j = get(url, as_json=True)
    except Exception:
      continue
    q = j.get("query", {})
    back = {}
    for r in q.get("normalized", []) + q.get("redirects", []):
      back[r["to"]] = back.get(r["from"], r["from"])
    for p in q.get("pages", []):
      rev = (p.get("revisions") or [{}])[0]
      txt = ((rev.get("slots") or {}).get("main") or {}).get("content")
      if txt:
        t = p["title"]
        while t in back and back[t] != t:
          t = back[t]
        out[t] = txt
    time.sleep(0.3)
  return out


def clean_wiki(t: str) -> str:
  t = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>|<!--.*?-->", "", t, flags=re.S)
  t = re.sub(r"\{\{[^{}]*\}\}", "", t)
  t = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", t)
  return t.replace("'''", "").replace("''", "")


def wiki_entries(text: str) -> list:
  """[(season, "YYYY-MM-DD" or "", part)]: each reserve-list move the article dates, with the injury named in its
  sentence or the one before it. Seasons come from the date (Jan-Feb belong to the season before) or, undated, from
  the section heading or the last year mentioned."""
  out, year = [], None
  for line in clean_wiki(text).split("\n"):
    h = re.match(r"^=+\s*(.*?)\s*=+\s*$", line)
    if h:
      y = re.search(r"\b(20[0-3]\d)\b", h.group(1))
      year = int(y.group(1)) if y else year
      continue
    sents = re.split(r"(?<=[.!?])\s+(?=[A-Z])", line)
    for i, s in enumerate(sents):
      ys = re.findall(r"\b(20[0-3]\d)\b", s)
      if not LIST_RX.search(s):
        if ys:
          year = int(ys[-1])
        continue
      if re.search(r"activated|returned|removed|came off|designated .* return|reinstated|COVID", s, re.I) and not re.search(r"placed|moved|transferred|reverted|put on", s, re.I):
        continue
      part = injury_in(s) or (injury_in(sents[i - 1]) if i else "")
      if not part or part == "Illness":
        continue
      dm = re.search(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})(?:,\s*(20[0-3]\d))?", s, re.I)
      if dm:
        mo, dy = MONTHS[dm.group(1).lower()], int(dm.group(2))
        yr = int(dm.group(3)) if dm.group(3) else (year + 1 if year and mo <= 2 else year)
        if not yr:
          continue
        try:
          d = date(yr, mo, dy)
        except ValueError:
          continue
        out.append((yr if mo >= 3 else yr - 1, d.isoformat(), part))
      elif ys or year:
        out.append((int(ys[-1]) if ys else year, "", part))
      if ys:
        year = int(ys[-1])
  return out


# ---- ESPN player news -------------------------------------------------------------------------------------------------
def espn_entries(espn_id: str) -> list:
  """[(season, "YYYY-MM-DD", part)]: news items about a reserve-list move, the injury from the headline's "(neck)"
  or the blurb's words."""
  try:
    j = get(f"https://site.api.espn.com/apis/fantasy/v2/games/ffl/news/players?playerId={espn_id}&limit=200", as_json=True)
  except Exception:
    return []
  out = []
  for a in j.get("feed") or []:
    head, story = a.get("headline") or "", a.get("story") or a.get("description") or ""
    txt = f"{head} {story}"
    if not LIST_RX.search(txt) or not re.search(r"placed|moved|transferred|lands? on|headed|heading|going to|reverted|put on|stash", txt, re.I):
      continue
    if re.search(r"activated|designated .* to return|returned from|come off|came off", head, re.I):
      continue
    par = re.search(r"\(([a-z][a-z ]{2,24})\)", head)
    part = (injury_in(par.group(1)) if par else "") or injury_in(head) or injury_in(story[:300])
    pub = (a.get("published") or "")[:10]
    if not part or part == "Illness" or not pub:
      continue
    d = date.fromisoformat(pub)
    out.append((d.year if d.month >= 3 else d.year - 1, pub, part))
  return out


# ---- who to look up ---------------------------------------------------------------------------------------------------
def reserve_stints(cache, nfl, cur: int) -> pd.DataFrame:
  """(gsis, season) pairs with any week on an injury reserve list (IR, PUP, NFI), 2009 on."""
  inj_codes = {k for k, v in RESERVE_CODES.items() if v in INJURY_LISTS}
  rows = []
  for s in range(FIRST, cur + 1):
    r = cache.get("rosters", s, lambda: nfl.load_rosters_weekly([s]), stale=False)
    if r is None or not len(r):
      continue
    r = r[(r.status == "RES") & r.status_description_abbr.isin(inj_codes)].dropna(subset=["gsis_id"])
    rows.append(r[["gsis_id", "season", "week"]].drop_duplicates())  # every reserve week
  return pd.concat(rows, ignore_index=True)


def build(all_: bool = False) -> None:
  cfg = load_config()
  import nflreadpy as nfl
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  cur = int(nfl.get_current_season())
  doc = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() and not all_ else {}
  if doc.get("v") != V:
    doc = {"v": V, "p": {}, "done": {"wiki": [], "espn": {}}}
  P, done = doc["p"], doc["done"]
  st = reserve_stints(cache, nfl, cur)
  pl = cache.get("players", "all", lambda: nfl.load_players(), stale=False)
  pl = pl.dropna(subset=["gsis_id"]).drop_duplicates("gsis_id").set_index("gsis_id")
  who = sorted(set(st.gsis_id))
  print(f"[irnames] {len(who)} players with reserve-list stints since {FIRST}", flush=True)

  def put(g, entries, src):
    keep = [e for e in P.get(g, []) if e[3] != src]
    P[g] = keep + [[s, d, part, src] for s, d, part in sorted(set(entries))]
    if not P[g]:
      P.pop(g)

  # Wikipedia: every such player once (articles are re-read only with --all)
  titles = wiki_titles()
  todo = {}
  for g in who:
    if g in done["wiki"]:
      continue
    pfr = pl.at[g, "pfr_id"] if g in pl.index and "pfr_id" in pl.columns else None
    if isinstance(pfr, str) and pfr in titles:
      todo[g] = titles[pfr]
  texts = wiki_texts(sorted(set(todo.values())))
  n_wiki = 0
  for g, t in todo.items():
    ents = wiki_entries(texts[t]) if t in texts else []
    put(g, [e for e in ents if FIRST <= e[0] <= cur], "wiki")
    n_wiki += len(ents)
    done["wiki"].append(g)
  print(f"[irnames] wikipedia: {len(todo)} articles read, {n_wiki} named reserve moves", flush=True)

  # ESPN news: players with stints from NEWS_FROM, once; and every run, this season's players with a reserve week in
  # the last two weeks (new placements: the fetch dates aren't committed by CI, so "a week since" would mean every run)
  today = date.today()
  recent = st[st.season >= NEWS_FROM]
  now = recent[recent.season == cur]
  wk = int(now.week.max()) if len(now) else 0
  fresh = set(now[now.week == wk].gsis_id) - set(now[now.week <= wk - 2].gsis_id)  # on a list now, not two weeks ago
  n_news = 0
  for g in sorted(set(recent.gsis_id)):
    if done["espn"].get(g) and g not in fresh:
      continue
    e = pl.at[g, "espn_id"] if g in pl.index and "espn_id" in pl.columns else None
    if e is None or pd.isna(e):
      continue
    ents = espn_entries(str(e).replace(".0", ""))
    put(g, [x for x in ents if x[0] >= NEWS_FROM], "espn")
    n_news += len(ents)
    done["espn"][g] = today.isoformat()
    time.sleep(0.15)
  print(f"[irnames] espn news: {n_news} named reserve moves", flush=True)

  doc["built"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
  done["wiki"] = sorted(set(done["wiki"]))
  OUT.parent.mkdir(parents=True, exist_ok=True)
  OUT.write_text(json.dumps(doc, separators=(",", ":"), sort_keys=True), encoding="utf-8")
  print(f"[irnames] wrote {OUT.name}: {len(P)} players", flush=True)


if __name__ == "__main__":
  build(all_="--all" in sys.argv)
