"""Early-season check: ESPN's chart vs usage, by week 1-6 (2025 + 2026). Usage = snap leaders over the team's last
up-to-3 games this season (week 1: last season's final 3 games), only players on the team's roster that week and not
Out / on a reserve list; score = share of predicted starters among that game's top-N snaps at the position."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # run: python tools/depth_week1.py
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402

GROUP = {"QB": "QB", "RB": "RB", "FB": "RB", "HB": "RB", "WR": "WR", "TE": "TE", **{p: "OL" for p in "T OT G OG C OL".split()},
         **{p: "DL" for p in "DE DT NT DL".split()}, **{p: "LB" for p in "LB ILB OLB MLB".split()}, "CB": "CB",
         **{p: "S" for p in "S SS FS SAF DB".split()}}
c = D.Cache(ROOT / "cache")
players = c.get("players", "all", None, stale=False)
pfr = players.dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates("pfr_id").set_index("pfr_id").gsis_id
pos_of = players.dropna(subset=["gsis_id"]).drop_duplicates("gsis_id").set_index("gsis_id").position
sched = c.get("schedules", "since1999", None, stale=False)


def snaps(season):
  sn = c.get("snaps", season, None, stale=False)
  sn = sn[sn.game_type == "REG"].copy()
  sn["gsis_id"] = sn.pfr_player_id.map(pfr)
  sn["snaps"] = sn[["offense_snaps", "defense_snaps"]].max(axis=1)
  sn["grp"] = sn.position.map(GROUP)
  sn["team"] = sn.team.replace({"LAR": "LA", "OAK": "LV", "SD": "LAC", "STL": "LA"})
  return sn.dropna(subset=["gsis_id", "grp"])


rows = []
for season in (2025, 2026):
  dep = c.get("depth", season, None, stale=False)
  inj = c.get("injuries", season, None, stale=False)
  out_wk = set(zip(inj[inj.report_status == "Out"].gsis_id, inj[inj.report_status == "Out"].week))
  ros = c.get("rosters", season, None, stale=False)
  ros = ros.assign(team=ros.team.replace({"LAR": "LA"}))
  on_team = set(zip(ros[ros.status == "ACT"].gsis_id, ros[ros.status == "ACT"].team, ros[ros.status == "ACT"].week))
  sn, last_season = snaps(season), snaps(season - 1)
  dts = sorted(pd.to_datetime(dep.dt.unique(), utc=True))
  s = sched[(sched.season == season) & (sched.game_type == "REG")]
  for wk in range(1, 7):
    if wk not in set(sn.week):
      continue
    first = pd.to_datetime(s[s.week == wk].gameday).min().tz_localize("UTC")
    before = [t for t in dts if t < first]
    if not before:
      continue
    snap = before[-1].strftime("%Y-%m-%dT%H:%M:%SZ")
    chart = dep[(dep.dt == snap) & dep.gsis_id.notna()].sort_values("pos_rank").drop_duplicates(["team", "pos_grp", "pos_slot"])
    cur = sn[sn.week == wk]
    for team, ch in chart.groupby("team"):
      t = "LA" if team == "LAR" else team
      game = cur[cur.team == t]
      if game.empty:
        continue
      avail = lambda g: (g, t, wk) in on_team and (g, wk) not in out_wk  # noqa: E731
      mine = sn[(sn.team == t) & (sn.week < wk)]
      if mine.week.nunique() == 0:  # week 1 (or no games yet): last season's final 3 games, any team
        prev = last_season[last_season.week >= last_season.week.max() - 2]
        base = prev[prev.gsis_id.map(avail)]
      else:
        wks = sorted(mine.week.unique())[-3:]
        base = mine[mine.week.isin(wks) & mine.gsis_id.map(avail)]
      for grp in sorted(set(GROUP.values())):
        espn = [g for g in set(ch.gsis_id) if GROUP.get(pos_of.get(g)) == grp]
        n = len(espn)
        truth = set(game[game.grp == grp].nlargest(n, "snaps").gsis_id) if n else set()
        if not n or len(truth) < n:
          continue
        use = base[base.grp == grp].groupby("gsis_id").snaps.sum().nlargest(n).index.tolist()
        rows.append({"season": season, "week": wk, "grp": grp, "n": n, "espn": sum(g in truth for g in espn) / n,
                     "usage": sum(g in truth for g in use) / n})
r = pd.DataFrame(rows)
wavg = lambda x, col: (x[col] * x.n).sum() / x.n.sum()  # noqa: E731
print(r.groupby("week").apply(lambda x: pd.Series({"espn": wavg(x, "espn"), "usage": wavg(x, "usage"), "cells": len(x)})).round(3).to_string())
print("\nweek 1 by position:")
w1 = r[r.week == 1]
print(w1.groupby("grp").apply(lambda x: pd.Series({"espn": wavg(x, "espn"), "usage": wavg(x, "usage")})).round(3).to_string())
