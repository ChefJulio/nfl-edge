"""News watch (owner 2026-10-17, after Jalen Hurts went on IR on a Saturday afternoon and the site waited for the next
scheduled build): every 30 minutes (.github/workflows/news-watch.yml) compare ESPN's injury feed with the copy the
live site was built from (data/espn_injuries/latest.json) and start a full build when a player who matters changes
status in a way that moves projections.

Who matters: anyone on the live week's board projected 8+ points (about 100 players: every starting QB, the
fantasy starters). What counts: a move to or from Doubtful, Out, injured reserve, PUP or a suspension (Questionable
<-> Active is left to the scheduled builds, which follow the practice reports). A build is skipped while one is
running or queued, or if one started in the last 30 minutes (it will pick the news up, or the next check will).

Standard library only (runs without installing the project). Usage: python tools/news_watch.py [--dry-run]
"""
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
SITE = os.environ.get("SITE_URL", "https://chefjulio.github.io/nfl-edge/").rstrip("/") + "/"
MIN_PROJ = 8.0
MIN_ROS = 5.0  # rest-of-season board: lookahead lines run lower (no Vegas lines yet); ~anyone a manager starts or stashes
SERIOUS = {"Doubtful", "Out", "Injured Reserve", "Physically Unable to Perform", "Suspension", "Reserve/Suspended"}
# (owner 2026-10-22) a relevant player gaining or losing Questionable / Day-To-Day also builds: the card's tag and
# the ESPN Questionable display change, even though the chance to play only moves with the official report
QUESTION = {"Questionable", "Day-To-Day"}
LINE_MOVE = 1.0  # points of spread or total since the live site's build that start a build
QUIET_MIN = 30
EVERY_MIN = 10   # the relay looks this often


def get(url: str):
  req = urllib.request.Request(url, headers={"User-Agent": "nfl-edge-news-watch/1.0", "Cache-Control": "no-cache"})
  with urllib.request.urlopen(req, timeout=30) as r:
    return json.load(r)


def espn_now() -> dict:
  """espn_id -> (status, name, return date or "") from the live feed (players listed nowhere are healthy)."""
  out = {}
  for team in get(ESPN).get("injuries", []):
    for i in team.get("injuries", []):
      a = i.get("athlete", {})
      href = (a.get("links") or [{}])[0].get("href", "")
      if "/id/" in href:
        out[href.split("/id/")[1].split("/")[0]] = (i.get("status") or "", a.get("displayName") or "",
                                                    str((i.get("details") or {}).get("returnDate") or "")[:10])
  return out


def built_from() -> dict:
  """espn_id -> (status, return date or "") in the feed the live site was built with."""
  rows = get(f"{SITE}data/espn_injuries/latest.json?nocache={int(datetime.now().timestamp())}")
  rows = rows if isinstance(rows, list) else rows.get("rows") or rows.get("players") or []
  return {str(r.get("espn_id")): (r.get("status") or "", str(r.get("return_date") or "")[:10]) for r in rows if r.get("espn_id")}


RET_MOVE_DAYS = 7  # a return date moving this far (about a game) changes what the model does with it


def date_moved(a: str, b: str) -> bool:
  """(owner 2026-10-20: "shouldn't we have it treat a moving return date as something worth action?") ESPN's
  estimated return date feeds the model (long-date rule, Out+ret bucket, IR floor, IR return model): a date that
  appears, disappears or moves RET_MOVE_DAYS+ (a season-ending update moves it months) is news; day-level nudges
  of a placeholder date are not."""
  if not a and not b:
    return False
  if not a or not b:
    return True
  try:
    return abs((datetime.fromisoformat(b) - datetime.fromisoformat(a)).days) >= RET_MOVE_DAYS
  except ValueError:
    return a != b


INDEX = {}  # the live site's index.json, fetched once (board + clock)


HALF_PPR = {"pass_yd": 0.04, "pass_td": 4, "interception": -2, "rush_yd": 0.1, "rush_td": 6, "reception": 0.5,
            "rec_yd": 0.1, "rec_td": 6, "fumble_lost": -2}


def relevant() -> dict:
  """espn_id -> 'Name (POS, TEAM, proj)' for the live week's board, projected MIN_PROJ+, plus (owner 2026-10-20:
  Terry McLaurin's season-ending news came in his team's bye week, when he is on no board) everyone on the rest-of-
  season board (data/ros.json) whose expected line if he plays averages MIN_PROJ+ half-PPR points over his next
  three games (MIN_ROS: lookahead lines run lower than this week's board)."""
  d = INDEX.setdefault("d", get(f"{SITE}index.json?nocache={int(datetime.now().timestamp())}"))
  out = {str(p["espn"]): f"{p.get('name')} ({p.get('pos')}, {p.get('team')}, {p.get('proj', 0):.1f})"
         for p in (d.get("players") or {}).values() if p.get("espn") and (p.get("proj") or 0) >= MIN_PROJ}
  try:
    ros = get(f"{SITE}data/ros.json?nocache={int(datetime.now().timestamp())}")
  except Exception as e:  # the board alone still works
    print(f"[watch] couldn't read ros.json ({e})")
    return out
  keys = ros.get("keys") or []
  for p in (ros.get("players") or {}).values():
    if not p.get("espn") or str(p["espn"]) in out:
      continue
    lines = [w[5] for w in (p.get("w") or [])[:3] if len(w) > 5 and w[5]]
    if not lines:
      continue
    pts = sum(sum(HALF_PPR.get(k, 0) * v for k, v in zip(keys, ln)) for ln in lines) / len(lines)
    if pts >= MIN_ROS:
      out[str(p["espn"])] = f"{p.get('name')} ({p.get('pos')}, {p.get('team')}, {pts:.1f} ros)"
  return out


# Week-clock events (owner 2026-10-18: "make every day of the week a day where we expect things"): the live site's
# clock (week_clock.py, index.json "clock") lists every team's report deadlines, kickoffs and the rollover; a build
# starts once one of these has passed since the site was built.
REPORT_LAG_MIN = 45     # NFL.com / ESPN publish a team's report up to ~45 minutes after its 4 p.m. ET deadline
INACTIVES_MIN = 75      # inactives are posted 90 minutes before kickoff; build 75 minutes before
ROLLOVER_LAG_MIN = 10


def clock_events(clock: dict) -> list:
  """[(when, label)] for the week: report deadlines (+lag, one per time), inactives per kickoff slot, rollover."""
  ev = {}
  for t, x in (clock.get("teams") or {}).items():
    for r in x.get("reports", []):
      ev.setdefault(datetime.fromisoformat(r["due"]) + timedelta(minutes=REPORT_LAG_MIN), f"practice reports due {r['date']}")
    if x.get("kick") and not x.get("final"):
      ev.setdefault(datetime.fromisoformat(x["kick"]) - timedelta(minutes=INACTIVES_MIN),
                    f"inactives for the {x['kick'][11:16]} ET kickoff on {x['kick'][:10]}")
  if clock.get("rollover"):
    ev.setdefault(datetime.fromisoformat(clock["rollover"]) + timedelta(minutes=ROLLOVER_LAG_MIN), "the week rolls over")
  return sorted(ev.items())


def due_events(clock: dict, now) -> list:
  """Clock events that have passed since the site was built (clock["built"])."""
  if not clock.get("built"):
    return []
  b = datetime.fromisoformat(clock["built"])
  return [lbl for w, lbl in clock_events(clock) if b < w <= now]


PBP = "https://api.github.com/repos/nflverse/nflverse-data/releases/tags/pbp"


def sunday_pbp_due(d: dict) -> list:
  """Monday refit (owner 2026-10-19, nfledge/team_model.py sunday_refit): once every game of the week through its
  last Sunday is final and nflverse has republished the season's play-by-play since the live site was built, a build
  takes Sunday's games into the ratings. Quiet once the site has them (index.json "refit") or before Sunday is over."""
  c = d.get("clock") or {}
  if d.get("refit") or not c.get("built"):
    return []
  kicks = [(x["kick"], bool(x.get("final"))) for x in (c.get("teams") or {}).values() if x.get("kick")]
  suns = [k for k, _ in kicks if datetime.fromisoformat(k).weekday() == 6]
  if not suns:
    return []
  last_sun = max(datetime.fromisoformat(k).date() for k in suns)
  if not all(f for k, f in kicks if datetime.fromisoformat(k).date() <= last_sun):
    return []
  try:
    season = int(d.get("season"))
    up = [a["updated_at"] for a in get(PBP).get("assets", []) if a.get("name") == f"play_by_play_{season}.parquet"]
  except Exception as e:  # can't tell: the scheduled builds pick it up
    print(f"[watch] couldn't read nflverse's play-by-play release ({e})")
    return []
  if up and datetime.fromisoformat(up[0].replace("Z", "+00:00")) > datetime.fromisoformat(c["built"]):
    return [f"nflverse play-by-play updated {up[0]} (Sunday's games into the ratings)"]
  return []


# Overdue reports (owner 2026-10-22, nfledge/chronology.py): the live site lists report days past their deadline (+
# grace) that weren't on NFL.com when it was built (index.json "chrono": days whose state is "overdue"). Each look
# asks NFL.com whether one has arrived since, and builds the moment it has. Same public client as nfledge/data.py (stdlib only here: the watcher
# runs from a sparse checkout without the package).
NFL_CLIENT = {"clientKey": "4cFUW6DmwJpzT9L7LrG3qRAcABG5s04g", "clientSecret": "CZuvCL49d9OwfGsR"}


def _nfl(url: str, body: dict | None = None, token: str | None = None) -> dict:
  h = {"User-Agent": "nfl-edge-site/1.0", "Content-Type": "application/json"}
  if token:
    h["Authorization"] = "Bearer " + token
  req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None, headers=h)
  with urllib.request.urlopen(req, timeout=30) as r:
    return json.load(r)


def missing_arrived(d: dict) -> list:
  """Report days the live site doesn't have (past their deadline: "due" or "overdue") that NFL.com has now: [label].
  "due" too (2026-10-23, owner: Judkins's Friday shown "not in yet" hours after it was filed): the deadline build at
  +45 min often finds NFL.com's copy not yet posted, and a day still "due" then never triggered a rebuild when it
  landed, so the site waited for the next scheduled build."""
  od = {t: [x for x, st in c.get("days", []) if st in ("due", "overdue")] for t, c in (d.get("chrono") or {}).items()}
  od = {t: v for t, v in od.items() if v} or d.get("overdue") or {}  # (a page built before "chrono": its "overdue")
  if not od:
    return []
  import uuid
  try:
    tok = _nfl("https://api.nfl.com/identity/v3/token", {**NFL_CLIENT, "deviceId": str(uuid.uuid4()), "deviceInfo": "",
                                                          "networkType": "other", "nflClaims": None})["accessToken"]
    url = f"https://api.nfl.com/football/v2/injuries?limit=500&season={int(d['season'])}&seasonType=REG"
    seen, page = {}, None
    for _ in range(20):
      r = _nfl(url + (f"&pageToken={page}" if page else ""), token=tok)
      for i in r.get("injuries") or []:
        if i.get("week") == d.get("week"):
          name = (i.get("team") or {}).get("fullName")
          seen.setdefault(name, set()).update(str(x.get("date") or "")[:10] for x in i.get("practiceDays") or [])
      nxt = (r.get("pagination") or {}).get("token")
      if not r.get("injuries") or not nxt or nxt == page:
        break
      page = nxt
  except Exception as e:  # can't tell: the scheduled builds pick it up
    print(f"[watch] couldn't read NFL.com's report ({e})")
    return []
  names = {t: (x or {}).get("name") for t, x in (d.get("teams") or {}).items()}
  out = []
  for t, ds in od.items():
    got = [x for x in ds if x in seen.get(names.get(t), set())]
    if got:
      out.append(f"{t}'s report for {', '.join(got)} is on NFL.com now")
  return out


GAMES = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"


def lines_moved(d: dict) -> list:
  """Games of the live site's week whose Vegas spread or total (nflverse's schedule file: the source the build reads)
  moved LINE_MOVE+ points since the site was built (index.json games: vegas_line "CHI -3.0", vegas_total)."""
  import csv
  import io
  games = {g.get("id"): g for g in d.get("games") or [] if not g.get("final")}
  if not games:
    return []
  try:
    with urllib.request.urlopen(urllib.request.Request(GAMES, headers={"User-Agent": "nfl-edge-site/1.0"}), timeout=60) as r:
      rows = list(csv.DictReader(io.StringIO(r.read().decode("utf-8"))))
  except Exception as e:  # can't tell: the scheduled builds pick it up
    print(f"[watch] couldn't read nflverse's schedule file ({e})")
    return []
  out = []
  for row in rows:
    g = games.get(row.get("game_id"))
    if g is None or not row.get("spread_line"):
      continue
    try:
      new_sp, new_tot = float(row["spread_line"]), float(row["total_line"]) if row.get("total_line") else None
    except ValueError:
      continue
    old_sp = None
    vl = str(g.get("vegas_line") or "").split()
    if len(vl) == 2:  # "CHI -3.0": the favorite and its spread; the schedule's spread_line is the home team's edge
      try:
        x = -float(vl[1])
        old_sp = x if vl[0] == row["home_team"] else -x if vl[0] == row["away_team"] else None
      except ValueError:
        old_sp = None
    old_tot = g.get("vegas_total")
    moved = []
    if old_sp is None or abs(new_sp - old_sp) >= LINE_MOVE:
      moved.append(f"spread {old_sp if old_sp is not None else 'none'} -> {new_sp:+g} (home)")
    if new_tot is not None and (old_tot is None or abs(new_tot - float(old_tot)) >= LINE_MOVE):
      moved.append(f"total {old_tot if old_tot is not None else 'none'} -> {new_tot:g}")
    if moved:
      out.append(f"{row['away_team']} @ {row['home_team']}: " + ", ".join(moved))
  return out


def recent_build() -> str | None:
  """Why not to start a build now (one running, queued or just started), else None."""
  try:
    runs = json.loads(subprocess.run(["gh", "run", "list", "--workflow", "deploy.yml", "--limit", "5",
                                      "--json", "status,createdAt"], capture_output=True, text=True, check=True).stdout)
  except Exception as e:  # can't tell: build anyway (the deploy's concurrency group queues it behind a running one)
    print(f"[watch] couldn't list runs ({e})")
    return None
  now = datetime.now(timezone.utc)
  for r in runs:
    if r["status"] in ("in_progress", "queued", "waiting", "pending"):
      return f"a build is {r['status']}"
    if now - datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00")) < timedelta(minutes=QUIET_MIN):
      return f"a build started at {r['createdAt']}"
  return None


def check(dry: bool) -> None:
  """One look: status changes and week-clock events since the last build; start a build if any (cooldown aside)."""
  INDEX.clear()  # the live site's index.json can change between looks (a build finished)
  try:
    now, then, who = espn_now(), built_from(), relevant()
  except Exception as e:
    print(f"[watch] couldn't read a source ({e}); nothing to do")
    return
  changes = []
  for eid, label in who.items():
    a, ra = then.get(eid, ("", ""))
    b, rb = now.get(eid, ("", "", ""))[0], now.get(eid, ("", "", ""))[2]
    if a != b and (a in SERIOUS or b in SERIOUS or a in QUESTION or b in QUESTION):
      changes.append(f"{label}: {a or 'healthy'} -> {b or 'healthy'}")
    elif (a in SERIOUS or b in SERIOUS) and date_moved(ra, rb):
      changes.append(f"{label}: {b} return date {ra or 'none'} -> {rb or 'none'}")
  due = due_events(INDEX.get("d", {}).get("clock") or {}, datetime.now(timezone.utc)) + sunday_pbp_due(INDEX.get("d", {}))     + missing_arrived(INDEX.get("d", {})) + lines_moved(INDEX.get("d", {}))
  if due:
    print("[watch] week clock: " + "; ".join(due))
  if not changes and not due:
    print(f"[watch] no status changes for {len(who)} relevant players and no clock events since the last build")
    return
  if changes:
    print("[watch] since the last build:\n  " + "\n  ".join(changes))
  why = recent_build()
  if why:
    print(f"[watch] not starting a build: {why}")
    return
  if dry:
    print("[watch] --dry-run: would start a build")
    return
  subprocess.run(["gh", "workflow", "run", "deploy.yml"], check=True)
  print("[watch] started a full build")


def others_running() -> bool:
  """Another watcher run already in progress (this run excluded)."""
  me = os.environ.get("GITHUB_RUN_ID", "")
  try:
    runs = json.loads(subprocess.run(["gh", "run", "list", "--workflow", "news-watch.yml", "--limit", "10",
                                      "--json", "databaseId,status"], capture_output=True, text=True, check=True).stdout)
  except Exception:
    return False
  return any(r["status"] in ("in_progress", "queued") and str(r["databaseId"]) != me for r in runs)


def main():
  """--loop=MINUTES (owner 2026-10-18: GitHub's scheduler ran the 30-minute check twice in a day): look every
  EVERY_MIN minutes for MINUTES, then start the next watcher run (a relay; a running job isn't subject to the
  scheduler). A cron-started run that finds a watcher already running exits: the cron is only the backstop."""
  dry = "--dry-run" in sys.argv
  loop = next((int(a.split("=", 1)[1]) for a in sys.argv if a.startswith("--loop=")), 0)
  if not loop:
    check(dry)
    return
  if others_running():
    print("[watch] a watcher is already running; this one stops")
    return
  import time
  end = time.time() + loop * 60
  while True:
    try:
      check(dry)
    except Exception as e:  # one bad look never ends the relay
      print(f"[watch] check failed ({e})")
    if time.time() + EVERY_MIN * 60 >= end:
      break
    time.sleep(EVERY_MIN * 60)
  if not dry:
    subprocess.run(["gh", "workflow", "run", "news-watch.yml"], check=False)
    print("[watch] relay: started the next watcher")


if __name__ == "__main__":
  main()
