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
SERIOUS = {"Doubtful", "Out", "Injured Reserve", "Physically Unable to Perform", "Suspension", "Reserve/Suspended"}
QUIET_MIN = 30
EVERY_MIN = 10   # the relay looks this often


def get(url: str):
  req = urllib.request.Request(url, headers={"User-Agent": "nfl-edge-news-watch/1.0", "Cache-Control": "no-cache"})
  with urllib.request.urlopen(req, timeout=30) as r:
    return json.load(r)


def espn_now() -> dict:
  """espn_id -> (status, name) from the live feed (players listed nowhere are healthy)."""
  out = {}
  for team in get(ESPN).get("injuries", []):
    for i in team.get("injuries", []):
      a = i.get("athlete", {})
      href = (a.get("links") or [{}])[0].get("href", "")
      if "/id/" in href:
        out[href.split("/id/")[1].split("/")[0]] = (i.get("status") or "", a.get("displayName") or "")
  return out


def built_from() -> dict:
  """espn_id -> status in the feed the live site was built with."""
  rows = get(f"{SITE}data/espn_injuries/latest.json?nocache={int(datetime.now().timestamp())}")
  rows = rows if isinstance(rows, list) else rows.get("rows") or rows.get("players") or []
  return {str(r.get("espn_id")): r.get("status") or "" for r in rows if r.get("espn_id")}


INDEX = {}  # the live site's index.json, fetched once (board + clock)


def relevant() -> dict:
  """espn_id -> 'Name (POS, TEAM, proj)' for the live week's board, projected MIN_PROJ+."""
  d = INDEX.setdefault("d", get(f"{SITE}index.json?nocache={int(datetime.now().timestamp())}"))
  return {str(p["espn"]): f"{p.get('name')} ({p.get('pos')}, {p.get('team')}, {p.get('proj', 0):.1f})"
          for p in (d.get("players") or {}).values() if p.get("espn") and (p.get("proj") or 0) >= MIN_PROJ}


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
    a = then.get(eid, "")
    b = now.get(eid, ("", ""))[0]
    if a != b and (a in SERIOUS or b in SERIOUS):
      changes.append(f"{label}: {a or 'healthy'} -> {b or 'healthy'}")
  due = due_events(INDEX.get("d", {}).get("clock") or {}, datetime.now(timezone.utc))
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
