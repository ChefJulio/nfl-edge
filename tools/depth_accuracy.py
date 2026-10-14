"""How often a depth chart's starters actually start: ESPN's chart (nflverse daily snapshots, last one before the
game) vs "last game's snap leaders", scored against the game's snap counts (2025 + 2026 so far, weeks 2+).
Per team-game and position group: N = ESPN's depth-1 players in that group; truth = that game's top-N by snaps in
the group (group by the player's own position); score = share of predicted starters inside the truth set."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # run: python tools/depth_accuracy.py
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402

GROUP = {**{p: "QB" for p in ["QB"]}, **{p: "RB" for p in ["RB", "FB", "HB"]}, **{p: "WR" for p in ["WR"]}, "TE": "TE",
         **{p: "OL" for p in "T OT G OG C OL".split()}, **{p: "DL" for p in "DE DT NT DL".split()},
         **{p: "LB" for p in "LB ILB OLB MLB".split()}, "CB": "CB", **{p: "S" for p in "S SS FS SAF DB".split()}}
c = D.Cache(ROOT / "cache")
players = c.get("players", "all", None, stale=False)
pfr = players.dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates("pfr_id").set_index("pfr_id").gsis_id
pos_of = players.dropna(subset=["gsis_id"]).drop_duplicates("gsis_id").set_index("gsis_id").position
sched = c.get("schedules", "since1999", None, stale=False)
rows = []
for season in (2025, 2026):
  dep = c.get("depth", season, None, stale=False)
  inj = c.get("injuries", season, None, stale=False)
  out_wk = set(zip(inj[inj.report_status == "Out"].gsis_id, inj[inj.report_status == "Out"].week))
  ros = c.get("rosters", season, None, stale=False)
  reserve = set(zip(ros[ros.status.isin(["RES", "CUT", "INA", "DEV"])].gsis_id, ros[ros.status.isin(["RES", "CUT", "INA", "DEV"])].week))
  sn = c.get("snaps", season, None, stale=False)
  sn = sn[sn.game_type == "REG"].copy()
  sn["gsis_id"] = sn.pfr_player_id.map(pfr)
  sn["snaps"] = sn[["offense_snaps", "defense_snaps"]].max(axis=1)
  sn["grp"] = sn.position.map(GROUP)
  sn = sn.dropna(subset=["gsis_id", "grp"])
  dts = sorted(pd.to_datetime(dep.dt.unique(), utc=True))
  s = sched[(sched.season == season) & (sched.game_type == "REG")]
  for wk in sorted(sn.week.unique()):
    if wk < 2:
      continue
    first = pd.to_datetime(s[s.week == wk].gameday).min().tz_localize("UTC")
    before = [t for t in dts if t < first]  # strictly before the week's first game day
    if not before:
      continue
    snap = before[-1].strftime("%Y-%m-%dT%H:%M:%SZ")
    chart = dep[(dep.dt == snap) & dep.gsis_id.notna()]
    chart = chart.sort_values("pos_rank").drop_duplicates(["team", "pos_grp", "pos_slot"])  # first player in each slot
    cur, prev = sn[sn.week == wk], sn[sn.week < wk]
    for team, ch in chart.groupby("team"):
      t = D.team_name_fix(pd.Series([team])).iloc[0]
      game = cur[cur.team == t]
      if game.empty:
        continue
      last_wk = prev[prev.team == t].week.max()
      last = prev[(prev.team == t) & (prev.week == last_wk)]
      starters = set(ch.gsis_id)
      for grp in sorted(set(GROUP.values())):
        espn = [g for g in starters if GROUP.get(pos_of.get(g)) == grp]
        n = len(espn)
        if not n:
          continue
        truth = set(game[game.grp == grp].nlargest(n, "snaps").gsis_id)
        if len(truth) < n:
          continue
        roster_now = set(game.gsis_id) | set(last.gsis_id)
        base = list(last[last.grp == grp].nlargest(n, "snaps").gsis_id)
        avail = lambda g: (g, wk) not in out_wk and (g, wk) not in reserve  # noqa: E731
        lastx = list(last[(last.grp == grp) & last.gsis_id.map(avail)].nlargest(n, "snaps").gsis_id)
        w3 = prev[(prev.team == t) & (prev.grp == grp) & (prev.week >= last_wk - 2)]
        w3 = w3[w3.gsis_id.map(avail)].groupby("gsis_id").snaps.sum().nlargest(n).index.tolist()
        hasrep = any((g, wk) in out_wk for g in base)
        rows.append({"season": season, "week": wk, "team": t, "grp": grp, "n": n,
                     "espn": sum(g in truth for g in espn) / n,
                     "last_game": sum(g in truth for g in base) / n if len(base) == n else None,
                     "last_avail": sum(g in truth for g in lastx) / n if len(lastx) == n else None,
                     "last3_avail": sum(g in truth for g in w3) / n if len(w3) == n else None, "rep": hasrep})
r = pd.DataFrame(rows)
print(f"{len(r)} team-game-group cells, {r.season.min()}-{r.season.max()}")
out = r.groupby("grp")[["espn", "last_game", "last_avail", "last3_avail"]].mean().round(3)
out["n_cells"] = r.groupby("grp").size()
print(out.loc[["QB", "RB", "WR", "TE", "OL", "DL", "LB", "CB", "S"]].to_string())
w = r.groupby("grp").n.sum()
print("overall (per starter):", round((r.espn * r.n).sum() / r.n.sum(), 3), "vs last game",
      round((r.last_game.fillna(0) * r.n).sum() / r[r.last_game.notna()].n.sum(), 3))
for c_ in ("espn", "last_game", "last_avail", "last3_avail"):
  ok = r[c_].notna()
  print(c_, round((r[c_][ok] * r.n[ok]).sum() / r.n[ok].sum(), 3))
print("cells where last game's starter was ruled Out:", int(r.rep.sum()))
