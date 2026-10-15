"""League tab: kicker (and later team-defense) projections, data/kdst.json, this week through week 17.

Usage: python tools/kdst_build.py --site=site   (CI step after run.py --lookahead and ros_build.py)
Kickers (nfledge/kickers.py; owner-approved gate 2026-10-15: MAE 3.71 vs 4.00 for his season average, 5/5
seasons): each team's kicker = the last one who kicked for it this season; his expected kicking stat line each
week from the team's implied points in that week's page (Vegas when posted, else our game model: the same number
the player projections use). The page re-scores the lines with the league's own kicking settings.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.kickers import LINE, KickerModel, implied_points, load_kicks  # noqa: E402

THROUGH = 17


def team_implied(week_json: dict) -> dict:
  """team -> implied points for that page's game, from its players' 'imp' (what the projections used)."""
  out = {}
  for p in week_json["players"].values():
    if p.get("imp") is not None and p.get("team"):
      out.setdefault(p["team"], float(p["imp"]))
  return out


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = ROOT / opt.get("site", "site")
  cur = json.loads((site / "index.json").read_text(encoding="utf-8"))
  season, week = int(cur["season"]), int(cur["week"])
  pages = {week: cur}
  for w in range(week + 1, THROUGH + 1):
    f = site / str(season) / f"week-{w:02d}.json"
    if f.exists():
      pages[w] = json.loads(f.read_text(encoding="utf-8"))
  c = D.Cache(ROOT / "cache")
  k = load_kicks(c, [season - 2, season - 1, season])
  sched = c.get("schedules", "since1999", None, stale=False)
  m = KickerModel().fit(k[(k.season < season) | (k.week < week)], implied_points(sched))
  cur_k = k[k.season == season].sort_values("week").groupby("team").tail(1)  # the team's latest kicker
  kick = {t: (r.player_id, r.player_display_name) for t, r in zip(cur_k.team, cur_k.itertuples())}
  out_k = {}
  for w, d in sorted(pages.items()):
    for team, imp in team_implied(d).items():
      if team not in kick:
        continue
      pid, name = kick[team]
      line = m.line(pid, team, imp)
      o = out_k.setdefault(team, {"pid": pid, "name": name, "w": []})
      o["w"].append([w, round(imp, 1), [round(line[x], 3) for x in LINE]])
  out = {"season": season, "from": week, "through": THROUGH, "built": cur.get("generated"), "k_keys": LINE, "k": out_k}
  (site / "data").mkdir(parents=True, exist_ok=True)
  (site / "data" / "kdst.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
  print(f"[kdst] kickers {len(out_k)} teams, weeks {week}-{THROUGH}", flush=True)


if __name__ == "__main__":
  main()
