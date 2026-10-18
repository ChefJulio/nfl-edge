"""The practice-report calendar (owner 2026-10-18: "practice days are uniform ... can be back tracked from the game
date"; "use it as a way to expect reports ... a foundation"). League policy fixes each team's three injury-report
days by its game day: Sunday game Wed / Thu / Fri; Monday Thu / Fri / Sat; Thursday Mon / Tue / Wed; Friday and
Saturday Tue / Wed / Thu; Wednesday Sun / Mon / Tue. Reports are due 4 p.m. ET; the final one carries game statuses.
2026 check: 181 of 186 team-weeks' dated reports fall on these days (the rest: Melbourne week 1, extra report days in
travel weeks), so a team's actual report dates are added when it files more.

A fact about the schedule, not a fitted value: every page can expect a team's reports, and a player not listed on a
report day practiced fully (the league's rule). Whether the availability model should switch stage on it is a
separate, tested question ((AP) in docs/INSIGHTS.md).
"""
from __future__ import annotations

import pandas as pd

from . import data as D

# game weekday (Mon = 0) -> days before the game of the three reports
LAG = {6: (4, 3, 2), 0: (4, 3, 2), 3: (3, 2, 1), 4: (3, 2, 1), 5: (4, 3, 2), 2: (3, 2, 1)}


def report_dates(gameday) -> list[str]:
  """The three report dates (YYYY-MM-DD) for a game on `gameday`."""
  gd = pd.Timestamp(gameday)
  return [(gd - pd.Timedelta(days=x)).strftime("%Y-%m-%d") for x in LAG.get(gd.weekday(), (4, 3, 2))]


def team_report_days(schedules: pd.DataFrame, season: int, week: int, filed: dict | None = None) -> dict:
  """team -> sorted report dates this week (the calendar's three plus any extra dates the team filed; filed: team ->
  iterable of dates seen on its reports). Teams on bye are absent."""
  s = schedules[(schedules.season == season) & (schedules.week == week) & (schedules.game_type == "REG")]
  out = {}
  for g in s.itertuples():
    if pd.isna(g.gameday):
      continue
    for t in (g.home_team, g.away_team):
      t = D.RELOCATED.get(t, t)
      out[t] = sorted(set(report_dates(g.gameday)) | set((filed or {}).get(t, ())))
  return out
