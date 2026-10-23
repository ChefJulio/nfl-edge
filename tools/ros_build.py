"""Players > Rankings > Rest of season (owner 2026-10-15): data/ros.json from this week's page + the lookahead weeks.

Usage: python tools/ros_build.py --site=site   (CI step right after run.py --lookahead)
Every build already projects each remaining week against its real opponent (run.build_lookahead: current ratings,
depth charts, Vegas lines once posted, injury returns chained week by week). This collects, per player and week
through THROUGH (17: most fantasy leagues end there; owner's pick), the expected stat line if active (score.keys
order), his chance to take the field, the matchup effect, the opponent and his injury-only chance to play. The page sums them under the viewer's scoring
(stat lines are linear in the scoring, so the total is exact), weighting each week by the chance to play, and drops
this week's game once it kicks off (kickoff times here), so a day-old build still adds up right.
A week a player is missing from is a bye, or a week he's projected to sit (under 50% to play: his volume goes to
teammates), and adds nothing.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402

THROUGH = 17
POS = {"QB", "RB", "WR", "TE"}


def kickoffs(season: int, week: int) -> dict:
  """team -> kickoff (UTC ISO) for this week's games, from the nflverse schedule (gameday + gametime, ET)."""
  s = D.Cache(ROOT / "cache").get("schedules", "since1999", None, stale=False)
  s = s[(s.season == season) & (s.week == week)]
  out = {}
  for g in s.itertuples():
    t = pd.Timestamp(f"{g.gameday} {g.gametime or '13:00'}").tz_localize("America/New_York").tz_convert("UTC")
    iso = t.strftime("%Y-%m-%dT%H:%MZ")
    out[g.home_team] = out[g.away_team] = iso
  return out


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = ROOT / opt.get("site", "site")
  cur = json.loads((site / "index.json").read_text(encoding="utf-8"))
  season, week = int(cur["season"]), int(cur["week"])
  weeks = {week: cur}
  for w in range(week + 1, THROUGH + 1):
    f = site / str(season) / f"week-{w:02d}.json"
    if f.exists():
      weeks[w] = json.loads(f.read_text(encoding="utf-8"))
  kick = kickoffs(season, week)
  players = {}
  for w, d in sorted(weeks.items()):
    for pid, p in d["players"].items():
      if p.get("pos") not in POS:
        continue
      o = players.setdefault(pid, {"w": []})
      if w == week or "name" not in o:  # identity from the earliest week he appears (this week's when listed)
        o.update({"name": p["name"], "pos": p["pos"], "team": p["team"], "espn": p.get("espn") or "", "photo": p.get("photo") or "",
                  "ss": p["sc"].get("ss"), "g": p["sc"].get("g")})  # season line so far: FP/G under any scoring
      pa = round(float(p["play"]) if p.get("play") is not None else 1.0 - float(p.get("inactive") or 0.0), 3)  # (AY3) takes the field
      # [6] injury only (1 - inactive; owner 2026-10-22 audit: the Health tile's "back ~wk N" read [1], which carries
      # healthy-scratch risk and the backup-QB rule, so a healthy backup QB read "not this season")
      o["w"].append([w, pa, round(float(p.get("mu") or 0.0), 2), p.get("opp") or "", p.get("home") or "",
                     [round(float(v), 3) for v in p["sc"]["pj"]], round(1.0 - float(p.get("inactive") or 0.0), 3)])
      if w == week and p["team"] in kick:
        o["k"] = kick[p["team"]]  # this week's kickoff: the page drops this week after it
  # byes per team through THROUGH (the schedule, so the strip can say BYE rather than blank)
  s = D.Cache(ROOT / "cache").get("schedules", "since1999", None, stale=False)
  s = s[(s.season == season) & (s.game_type == "REG") & (s.week >= week) & (s.week <= THROUGH)]
  teams = set(s.home_team) | set(s.away_team)
  byes = {t: [w for w in range(week, THROUGH + 1) if not ((s.week == w) & ((s.home_team == t) | (s.away_team == t))).any()]
          for t in sorted(teams)}
  out = {"season": season, "from": week, "through": THROUGH, "built": cur.get("generated"), "keys": cur["score"]["keys"],
         "built_w": cur["score"]["built"], "missing": [w for w in range(week, THROUGH + 1) if w not in weeks],
         "byes": byes, "players": players}
  (site / "data").mkdir(parents=True, exist_ok=True)
  (site / "data" / "ros.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
  kb = (site / "data" / "ros.json").stat().st_size / 1024
  print(f"[ros] weeks {week}-{THROUGH} ({len(weeks)} built), {len(players)} players, {kb:.0f} KB", flush=True)


if __name__ == "__main__":
  main()
