"""League tab: kicker and team-defense (D/ST) projections, data/kdst.json, this week through week 17.

Usage: python tools/kdst_build.py --site=site   (CI step after run.py --lookahead and ros_build.py)
Kickers (nfledge/kickers.py; owner-approved gate 2026-10-15: MAE 3.71 vs 4.00 for his season average, 5/5
seasons): each team's kicker = the last one who kicked for it this season; his expected kicking stat line each
week from the team's implied points in that week's page (Vegas when posted, else our game model: the same number
the player projections use). The page re-scores the lines with the league's own kicking settings.
D/ST (nfledge/defenses.py; gate 2026-10-15: MAE 4.00 vs 4.34 for its season average on ESPN standard scoring, 5/5
seasons): each defense's expected stat line + points / yards allowed distributions vs that week's opponent, the
opponent's implied points from the same page; rates from games before the current week.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge import defenses as DF  # noqa: E402
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
  sched = c.get("schedules", "since1999", None, stale=False)
  k = load_kicks(c, [season - 2, season - 1, season], sched)
  m = KickerModel().fit(k[(k.season < season) | (k.week < week)], implied_points(sched))
  cur_k = k[k.season == season].sort_values("week").groupby("team").tail(1)  # the team's latest kicker
  kick = {t: (r.player_id, r.player_display_name) for t, r in zip(cur_k.team, cur_k.itertuples())}
  # ...unless the latest roster says otherwise (owner 2026-10-16: Mevis was cut, Grupe signed, and the Rams' kicker
  # still showed as Mevis): the team's active kicker (ACT) on its latest roster week; two -> the one with more kicks
  ro = c.get("rosters", season, None, stale=False)
  if ro is not None and len(ro):
    ro = ro[ro.position == "K"].assign(team=ro.team.replace({"LAR": "LA"}))
    ro = ro[ro.week == ro.groupby("team").week.transform("max")]
    act = ro[ro.status == "ACT"].dropna(subset=["gsis_id"])
    n_k = k.groupby("player_id").size()
    for team, g in act.groupby("team"):
      best = max(g.itertuples(), key=lambda r: n_k.get(r.gsis_id, 0))
      if team not in kick or kick[team][0] != best.gsis_id:
        kick[team] = (best.gsis_id, best.full_name)
  out_k = {}
  for w, d in sorted(pages.items()):
    for team, imp in team_implied(d).items():
      if team not in kick:
        continue
      pid, name = kick[team]
      line = m.line(pid, team, imp)
      o = out_k.setdefault(team, {"pid": pid, "name": name, "w": []})
      o["w"].append([w, round(imp, 1), [round(line[x], 3) for x in LINE]])
  # D/ST
  g = DF.load_games(c, [season - 2, season - 1, season], sched)
  dm = DF.DefenseModel().fit(g[(g.season < season) | (g.week < week)], implied_points(sched))
  out_d = {}
  for w, d in sorted(pages.items()):
    imp = team_implied(d)
    for gm in d.get("games", []):
      a, h = gm["away"]["team"], gm["home"]["team"]
      for team, opp, home in ((a, h, 0), (h, a, 1)):
        if opp not in imp:
          continue
        line = dm.line(team, opp, imp[opp], (season, week))
        out_d.setdefault(team, {"w": []})["w"].append([w, opp, home, [round(line[x], 3) for x in DF.LINE]])
  out = {"season": season, "from": week, "through": THROUGH, "built": cur.get("generated"), "k_keys": LINE, "k": out_k,
         "d_keys": DF.LINE, "dst": out_d}
  (site / "data").mkdir(parents=True, exist_ok=True)
  (site / "data" / "kdst.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
  print(f"[kdst] kickers {len(out_k)} teams, defenses {len(out_d)}, weeks {week}-{THROUGH}", flush=True)


if __name__ == "__main__":
  main()
