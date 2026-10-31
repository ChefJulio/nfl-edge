"""This week's reserve-list status from ESPN, layered over nflverse's weekly rosters (owner 2026-10-28: "i thought we
moved off using nflverse for current news ... make sure it's removed from all injury news stuff if we can replace
[it with] espn").

The weekly rosters are the only source of who is on injured reserve / PUP / NFI / suspended, and they trail the moves
by a day or more (Dameon Pierce, placed on IR Wednesday night of week 8, still read active; the board tagged him Q).
Every live reader of a player's list (the tags, 0% for reserve players, the return model's designation, the scratch
model, the lineup and starting-CB terms, bye-week lists, the player pages, the search directory) reads a rosters frame,
so the fix is one layer on it: ESPN's injury feed, where it moved a player onto a list (or between them: IR -> IR with
the return window open) after his team's last game, sets his roster row for the week the site shows, in the rosters'
own codes. Rows it writes carry status_src = "espn" for the audit. Activations off a list stay with InjuryModel
({#activated}), which reads them against these rows.

The same holds for club moves (owner 2026-10-31: Buckner traded to SF, still a Colt): team_overlay() puts a player on
the club ESPN's team rosters list him on, applied before the reserve-list layer (team_src = "espn").

Past weeks are never touched: training rows and outcomes stay nflverse's (what happened, not what was known then).
  run.py                 apply_espn_teams(data, rosters, week), then apply_espn_reserve(data, feed, week): data.rosters
  tools (player pages,   overlay(rosters, feed, schedules, season, week, players): the same on a roster frame
  depth / directory)
"""
from __future__ import annotations

import pandas as pd

# ESPN's fantasy status (details.fantasyStatus.abbreviation) -> the rosters' status_description_abbr. "-R": the
# return window is open (IR-R is the rosters' R48, designated to return; PUP / NFI keep their code)
ESPN_RESERVE = {"IR": "R01", "IR-R": "R48", "PUP": "R04", "PUP-R": "R04", "NFI": "R05", "NFI-R": "R05",
                "RESERVE-SUS": "R40", "SUSP": "R40"}
# the feed's status when its fantasy status is missing
ESPN_STATUS_RESERVE = {"Injured Reserve": "R01", "Physically Unable to Perform": "R04", "Suspension": "R40"}


def _code(row) -> str | None:
  fs = str(getattr(row, "fantasy_status", "") or "")
  return ESPN_RESERVE.get(fs) or ESPN_STATUS_RESERVE.get(str(getattr(row, "status", "") or ""))


def overlay(rosters: pd.DataFrame, feed: pd.DataFrame | None, schedules: pd.DataFrame, season: int, week: int,
            players: pd.DataFrame | None = None) -> tuple[pd.DataFrame, list[dict]]:
  """(rosters with ESPN's moves for `week`, the changes [{gsis, name, team, week, from, to, updated}]). A list ESPN
  shows from before his team's last game is what the rosters already reflect (or an entry ESPN never cleared): left
  alone, so a stale ESPN IR can't undo an activation the rosters have."""
  if feed is None or not len(feed) or "status" not in feed or rosters is None or not len(rosters):
    return rosters, []
  from .codes import RESERVE, team as team_code
  from .data import espn_gsis
  from .week_clock import kickoff
  ro = rosters.copy()
  cur = ro[(ro.season == season) & ro.gsis_id.notna() & (ro.week <= week)].sort_values("week")
  latest = cur.drop_duplicates("gsis_id", keep="last").set_index("gsis_id")
  gs = espn_gsis(ro) if "espn_id" in ro else {}
  if players is not None and "espn_id" in players:  # a player the rosters lack an ESPN id for (new signings)
    for e, g in zip(players.espn_id, players.gsis_id):
      if pd.notna(e) and isinstance(g, str):
        gs.setdefault(str(e).replace(".0", ""), g)
  fin = schedules[(schedules.season == season) & (schedules.week < week) & schedules.home_score.notna()]
  last_kick = {}  # each team's last game played before `week`: its kickoff
  for x in fin.itertuples():
    k = kickoff(x.gameday, getattr(x, "gametime", None))
    if k is None:
      continue
    for t in (team_code(x.home_team), team_code(x.away_team)):
      last_kick[t] = max(last_kick.get(t, k), k)
  changes = []
  for x in feed.dropna(subset=["espn_id"]).itertuples():
    code = _code(x)
    g = gs.get(str(x.espn_id))
    if not code or not isinstance(g, str) or g not in latest.index:
      continue
    row = latest.loc[g]
    team = team_code(row.team)
    up = pd.to_datetime(x.updated, errors="coerce", utc=True)
    lk = last_kick.get(team)
    if pd.isna(up) or lk is None or up <= lk:
      continue  # before his team's last game: not news the rosters could have missed
    on = str(row.status_description_abbr) if row.status == "RES" else None
    if on and RESERVE.get(on) == RESERVE.get(code) and not (code == "R48" and on != "R48"):
      continue  # already on that list (IR -> IR with the window open is still news: R48)
    changes.append({"gsis": g, "name": getattr(x, "name", ""), "team": team, "week": int(week), "from": on or str(row.status),
                    "to": code, "updated": up.isoformat(), "_row": row.team})
  if not changes:
    return rosters, []
  ro = _carry(ro, season, week, {c["_row"] for c in changes})
  for c in changes:
    g, code, row_team = c["gsis"], c["to"], c.pop("_row")
    m = (ro.season == season) & (ro.week == week) & (ro.gsis_id == g)
    if not m.any():  # his latest row is older than his team's latest week: his row for this week
      r_ = latest.loc[g].to_dict()
      r_.update(gsis_id=g, season=season, week=int(week), team=row_team)
      ro = pd.concat([ro, pd.DataFrame([r_])], ignore_index=True)
      m = (ro.season == season) & (ro.week == week) & (ro.gsis_id == g)
    ro.loc[m, "status"], ro.loc[m, "status_description_abbr"], ro.loc[m, "status_src"] = "RES", code, "espn"
  return ro, changes


def _carry(ro: pd.DataFrame, season: int, week: int, teams) -> pd.DataFrame:
  """A team whose roster for `week` isn't posted yet: its latest roster carried to `week` first (status_src "carried"),
  so readers that take each team's latest roster week (engine.candidates, tag_map, returns.window_open, personnel,
  report.bye_rows ...) still see the whole team, exactly as when nflverse posts the week."""
  s_ = ro[(ro.season == season) & ro.gsis_id.notna()]
  add = []
  for t_raw in teams:
    tw = s_[s_.team == t_raw]
    mx = int(tw.week.max()) if len(tw) else week
    if mx < week:
      add.append(tw[tw.week == mx].assign(week=int(week), status_src="carried"))
  return pd.concat([ro] + add, ignore_index=True) if add else ro


# More moves than this in one build means a mapping problem (club codes, ids), not a busy week: the overlay stands down
TEAM_MOVES_MAX = 40


def team_overlay(rosters: pd.DataFrame, espn_ros: pd.DataFrame | None, season: int, week: int,
                 players: pd.DataFrame | None = None) -> tuple[pd.DataFrame, list[dict]]:
  """(rosters with ESPN's club moves for `week`, the changes [{gsis, name, week, from, to, group}]) (owner 2026-10-31:
  DeForest Buckner, traded to SF on Oct 27, still read as a Colt everywhere). The weekly rosters trail trades, claims
  and signings by up to a week; ESPN's team rosters (fetch_team_rosters, practice squad and reserve lists included)
  carry them within hours. A player ESPN lists on club U whose latest row this season says another club gets a row
  for `week` on U (team_src "espn"): status ACT, DEV on U's practice squad, else his latest status. Being missing from
  ESPN's rosters (a release) is left alone: the rosters catch up. Past weeks are never touched."""
  if espn_ros is None or not len(espn_ros) or rosters is None or not len(rosters):
    return rosters, []
  from .codes import team as team_code
  from .data import espn_gsis
  ro = rosters.copy()
  cur = ro[(ro.season == season) & ro.gsis_id.notna() & (ro.week <= week)].sort_values("week")
  latest = cur.drop_duplicates("gsis_id", keep="last").set_index("gsis_id")
  gs = espn_gsis(ro) if "espn_id" in ro else {}
  if players is not None and "espn_id" in players:
    for e, g in zip(players.espn_id, players.gsis_id):
      if pd.notna(e) and isinstance(g, str):
        gs.setdefault(str(e).replace(".0", ""), g)
  changes = []
  for x in espn_ros.itertuples():
    g = gs.get(str(x.espn_id))
    if not isinstance(g, str) or g not in latest.index:
      continue
    row = latest.loc[g]
    if team_code(row.team) == x.team:
      continue
    changes.append({"gsis": g, "name": x.name, "week": int(week), "from": team_code(row.team), "to": x.team,
                    "group": x.group, "_row": row.team})
  if not changes:
    return rosters, []
  if len(changes) > TEAM_MOVES_MAX:
    eg = ", ".join("%s %s->%s" % (c["name"], c["from"], c["to"]) for c in changes[:5])
    print(f"[status] ESPN team moves skipped: {len(changes)} differences (over {TEAM_MOVES_MAX}: a mapping problem, e.g. {eg})",
          flush=True)
    return rosters, []
  # the new club's codes as the rosters write them (a relocated franchise's old code in an old season stays theirs)
  raw = {team_code(t): t for t in ro.loc[ro.season == season, "team"].dropna().unique()}
  ro = _carry(ro, season, week, {c["_row"] for c in changes} | {raw.get(c["to"], c["to"]) for c in changes})
  for c in changes:
    g, old = c["gsis"], c.pop("_row")
    m = (ro.season == season) & (ro.week == week) & (ro.gsis_id == g)
    if not m.any():  # no row this week (his old club's week is posted without him, or he had no carried row)
      r_ = latest.loc[g].to_dict()
      r_.update(gsis_id=g, season=season, week=int(week), team=old)
      ro = pd.concat([ro, pd.DataFrame([r_])], ignore_index=True)
      m = (ro.season == season) & (ro.week == week) & (ro.gsis_id == g)
    ro.loc[m, "team"] = raw.get(c["to"], c["to"])
    if c["group"] == "practiceSquad":
      ro.loc[m, "status"] = "DEV"
    elif c["group"] in ("offense", "defense", "specialTeam"):
      ro.loc[m, "status"] = "ACT"
    ro.loc[m, "team_src"] = "espn"
  return ro, changes


def apply_espn_teams(data, rosters_feed: pd.DataFrame | None, week: int) -> list[dict]:
  """team_overlay() on data.rosters for this season's `week`, in place; the changes also on data.team_overlay (run.py's
  model cache key)."""
  data.rosters, changes = team_overlay(data.rosters, rosters_feed, data.current_season, week,
                                       getattr(data, "players_table", None))
  data.team_overlay = changes
  return changes


def apply_espn_reserve(data, feed: pd.DataFrame | None, week: int) -> list[dict]:
  """overlay() on data.rosters for this season's `week`, in place; the changes also on data.status_overlay (run.py's
  model cache key)."""
  data.rosters, changes = overlay(data.rosters, feed, data.schedules, data.current_season, week,
                                  getattr(data, "players_table", None))
  data.status_overlay = changes
  return changes


def live_overlay(rosters: pd.DataFrame, schedules: pd.DataFrame, season: int, players: pd.DataFrame | None = None,
                 feed: pd.DataFrame | None = None) -> pd.DataFrame:
  """For the tools: fetch ESPN's feed (unless given) and overlay the week the site shows (week_clock). Never raises:
  without the feed, the rosters as they are."""
  try:
    from .week_clock import Clock
    if feed is None:
      from .espn import fetch_injuries
      feed = fetch_injuries()
    week = Clock(schedules).current_week(season)
    # club moves first (trades, claims, signings), so a reserve-list move lands on his new club's row
    from .espn import fetch_team_rosters
    rosters, tm = team_overlay(rosters, fetch_team_rosters(), season, week, players)
    if tm:
      print(f"[status] ESPN club moves over the rosters (week {week}): "
            + ", ".join(f"{c['name']} {c['from']} -> {c['to']}" for c in tm), flush=True)
    ro, ch = overlay(rosters, feed, schedules, season, week, players)
    if ch:
      print(f"[status] ESPN reserve-list moves over the rosters (week {week}): "
            + ", ".join(f"{c['name']} {c['from']} -> {c['to']}" for c in ch), flush=True)
    return ro
  except Exception as e:
    print(f"[status] ESPN overlay skipped: {type(e).__name__}: {e}", flush=True)
    return rosters
