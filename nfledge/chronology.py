"""The injury chronology (owner 2026-10-22: "if we use a calendar date timeline we can be precise about timing at every
point ... we know exactly what reports we're expecting to have seen up to 'now' so that if anything is missing it's
not silent, it's 'we're missing this team's practice report even though it's due by now'").

For each team's game in a week, at a moment `now` (America/New_York; default the real time): its report days (league
policy by game day, practice_calendar; plus any extra day it filed, e.g. travel weeks), each one's 4 p.m. ET deadline
and its state:
  upcoming - the deadline hasn't come
  due      - the deadline passed less than GRACE_MIN ago and the report isn't in yet (normal lag)
  overdue  - past the deadline + GRACE_MIN and not in: missing, shown and logged, never read as "practiced fully"
  filed    - his team's report for that date is in (NFL.com's report, dated: anyone listed that day)
Then the team's stage: how many report days are filed (a day that never arrived is skipped and flagged, the later
days still count); final = every report day filed, or a game status posted, or the game kicked off; and the game:
inactives posted (kickoff - 90 min), live, final.

Everything in the injury code that asks "where is this team's week?" reads this (InjuryModel.chrono), instead of
inferring the day from which data happens to exist (the Tyler Warren, Tyler Shough and late-addition bugs of
2026-10-21/22 were all silent inferences).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .week_clock import ET, Clock

GRACE_MIN = 75  # NFL.com's copy usually lands within the hour after the 4 p.m. deadline (news_watch checks at +45)


@dataclass
class ReportDay:
  date: str
  due: pd.Timestamp
  state: str  # upcoming / due / overdue / filed


@dataclass
class TeamChrono:
  team: str
  kick: pd.Timestamp
  game_final: bool
  days: list = field(default_factory=list)  # [ReportDay], calendar order
  has_status: bool = False                  # someone on this week's report has a game status (the final report)
  now: pd.Timestamp | None = None

  @property
  def filed_days(self) -> list[str]:
    """Filed report dates in calendar order. A day that never arrived is skipped (and flagged overdue), not a stop:
    a later day's report is still real information."""
    return [d.date for d in self.days if d.state == "filed"]

  @property
  def stage(self) -> int:
    """0 = no report in yet (Tuesday), then 1, 2 ... days in; 3 once the final report is in."""
    return 3 if self.final else min(len(self.filed_days), 2)

  @property
  def kicked_off(self) -> bool:
    return self.game_final or (self.now is not None and self.now >= self.kick)

  @property
  def final(self) -> bool:
    """The final report is in: every report day filed, or a game status posted, or the game has kicked off (its
    reports are what they are)."""
    return bool(self.days) and (len(self.filed_days) == len(self.days) or self.has_status or self.kicked_off)

  @property
  def published(self) -> bool:
    return bool(self.filed_days) or self.has_status

  @property
  def overdue(self) -> list[str]:
    return [d.date for d in self.days if d.state == "overdue"]

  @property
  def inactives_in(self) -> bool:
    return self.now is not None and self.now >= self.kick - pd.Timedelta(minutes=90)


class Chronology:
  def __init__(self, data, season: int, week: int, now: pd.Timestamp | None = None):
    self.clock = Clock(data.schedules, now)
    self.now = self.clock.now
    self.season, self.week = season, week
    filed, status = {}, set()
    pr = data.practice
    if pr is not None and "dates" in pr:
      x = pr[(pr.season == season) & (pr.week == week)]
      ro = data.rosters
      ro = ro[(ro.season == season) & (ro.week <= week) & ro.gsis_id.notna()].sort_values("week").drop_duplicates("gsis_id", keep="last")
      team_of = dict(zip(ro.gsis_id, ro.team.replace({"LAR": "LA"})))
      if "team_name" in x:  # NFL.com's own team for the row (the roster can lag a trade)
        from .data import team_names
        names = team_names(getattr(data, "teams", None))
        team_of_row = x.team_name.map(names)
      else:
        team_of_row = pd.Series([None] * len(x), index=x.index)
      for g, ds, gs, t_row in zip(x.gsis_id, x.dates, x.game_status, team_of_row):
        t = t_row if isinstance(t_row, str) else team_of.get(g)
        if not t:
          continue
        for d in str(ds or "").split(","):
          if d:
            filed.setdefault(t, set()).add(d)
        if str(gs).upper() in ("OUT", "DOUBTFUL", "QUESTIONABLE"):
          status.add(t)
    self.filed = filed
    self.teams: dict[str, TeamChrono] = {}
    for t, tw in self.clock.teams(season, week).items():
      days = {d: due for d, due in tw.reports}
      for d in filed.get(t, ()):  # an extra day the team filed (travel weeks): due at its own 4 p.m.
        days.setdefault(d, pd.Timestamp(d).tz_localize(ET) + pd.Timedelta(hours=16))
      rds = []
      for d, due in sorted(days.items()):
        if d in filed.get(t, ()):
          st = "filed"
        elif self.now < due:
          st = "upcoming"
        elif self.now < due + pd.Timedelta(minutes=GRACE_MIN):
          st = "due"
        else:
          st = "overdue"
        rds.append(ReportDay(d, due, st))
      # a game final or kicked off: its report days are history, never "overdue"
      if tw.final or self.now >= tw.kick:
        rds = [ReportDay(r.date, r.due, "filed" if r.state == "filed" else "upcoming" if r.state == "upcoming" else "unfiled") for r in rds]
      self.teams[t] = TeamChrono(t, tw.kick, tw.final, rds, t in status, self.now)

  def team(self, t: str) -> TeamChrono | None:
    return self.teams.get({"LAR": "LA"}.get(t, t))

  def published_teams(self) -> set:
    return {t for t, c in self.teams.items() if c.published}

  def final_teams(self) -> set:
    return {t for t, c in self.teams.items() if c.final}

  def overdue(self) -> dict:
    """team -> [overdue report dates] (for the build log, the page and the news watcher)."""
    return {t: c.overdue for t, c in self.teams.items() if c.overdue}

  def to_json(self) -> dict:
    return {t: {"stage": c.stage, "final": c.final, "filed": c.filed_days,
                "days": [{"date": d.date, "due": d.due.isoformat(), "state": d.state} for d in c.days]}
            for t, c in sorted(self.teams.items())}
