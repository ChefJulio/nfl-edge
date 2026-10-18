"""The week clock (owner 2026-10-18: "our site should be generally aware of the date ... make every day of the week a
day where we expect things"). One place that knows, for any moment, where the NFL week stands: which week the site
shows, each team's kickoff and game state, its three practice-report days with their 4 p.m. ET deadlines, the
fantasy waiver run, and when each week rolls over. Everything else reads it instead of inferring the day from which
data happens to exist.

Times are America/New_York throughout (zoneinfo: daylight saving handled by the time-zone database). The schedule
comes from nflverse (gameday + gametime are Eastern). The practice-report days come from practice_calendar (league
policy by game weekday). The week JSON carries `clock` (to_json) so the browser applies the current time between
builds (shell.js NFLE.clock).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import data as D
from .practice_calendar import report_dates

ET = "America/New_York"
ROLLOVER_HOUR_ET = 6      # the site moves to the next week at 06:00 ET on the Tuesday after a week's last game
REPORT_DUE_HOUR_ET = 16   # practice reports are due 4 p.m. ET (league policy)
GAME_HOURS = 4            # a game is treated as live up to this long after kickoff when no final score is in yet
INACTIVES_MIN = 90       # game-day inactives are posted 90 minutes before kickoff
WAIVER_RUN = ("Wed", 3)   # Sleeper / ESPN default waiver processing, Wednesday ~03:00 ET (~2 a.m. CT)


def now_et() -> pd.Timestamp:
  return pd.Timestamp.now(tz=ET)


def kickoff(gameday, gametime) -> pd.Timestamp | None:
  """A game's kickoff as an aware Eastern timestamp (None without a date)."""
  if gameday is None or pd.isna(gameday):
    return None
  t = str(gametime) if gametime is not None and not pd.isna(gametime) and str(gametime) else "13:00"
  return pd.Timestamp(f"{pd.Timestamp(gameday).date()} {t}").tz_localize(ET)


@dataclass
class TeamWeek:
  team: str
  opp: str
  home: bool
  kick: pd.Timestamp
  final: bool
  reports: list  # [(date 'YYYY-MM-DD', due Timestamp)]

  def state(self, now: pd.Timestamp) -> str:
    """'final' | 'live' | 'upcoming'."""
    if self.final:
      return "final"
    return "live" if now >= self.kick else "upcoming"

  def reports_in(self, now: pd.Timestamp) -> int:
    """How many of this week's report deadlines have passed (0-3)."""
    return sum(1 for _, due in self.reports if now >= due)

  def inactives_in(self, now: pd.Timestamp) -> bool:
    """Game-day actives / inactives are posted (kickoff - 90 minutes)."""
    return now >= self.kick - pd.Timedelta(minutes=INACTIVES_MIN)

  def final_report_in(self, now: pd.Timestamp) -> bool:
    return bool(self.reports) and now >= self.reports[-1][1]


class Clock:
  def __init__(self, schedules: pd.DataFrame, now: pd.Timestamp | None = None):
    self.s = schedules[schedules.game_type == "REG"]
    self.now = (now.tz_convert(ET) if now is not None and now.tzinfo else (now.tz_localize(ET) if now is not None else now_et()))

  # ---- weeks
  def _week_games(self, season: int, week: int) -> pd.DataFrame:
    return self.s[(self.s.season == season) & (self.s.week == week)]

  def rollover(self, season: int, week: int) -> pd.Timestamp | None:
    """06:00 ET on the Tuesday after the week's last kickoff."""
    g = self._week_games(season, week)
    ks = [kickoff(a, b) for a, b in zip(g.gameday, g.gametime)]
    ks = [k for k in ks if k is not None]
    if not ks:
      return None
    last = max(ks).normalize()
    days = (1 - last.weekday()) % 7 or 7
    return last + pd.Timedelta(days=days, hours=ROLLOVER_HOUR_ET)

  def current_week(self, season: int) -> int:
    """The week the site shows: the first week whose rollover hasn't passed. A week with a game not final (postponed,
    or scores not in yet) is held past its rollover until it is."""
    weeks = sorted(int(w) for w in self.s[self.s.season == season].week.unique())
    for w in weeks:
      r = self.rollover(season, w)
      g = self._week_games(season, w)
      started = any((k := kickoff(a, b)) is not None and k <= self.now for a, b in zip(g.gameday, g.gametime))
      if r is None or self.now < r or (started and g.home_score.isna().any()):
        return w
    return weeks[-1] if weeks else 1

  # ---- teams
  def team_week(self, season: int, week: int, team: str) -> TeamWeek | None:
    for g in self._week_games(season, week).itertuples():
      h, a = D.RELOCATED.get(g.home_team, g.home_team), D.RELOCATED.get(g.away_team, g.away_team)
      if team not in (h, a):
        continue
      k = kickoff(g.gameday, g.gametime)
      if k is None:
        return None
      reps = [(d, pd.Timestamp(d).tz_localize(ET) + pd.Timedelta(hours=REPORT_DUE_HOUR_ET)) for d in report_dates(g.gameday)]
      return TeamWeek(team, a if team == h else h, team == h, k, bool(pd.notna(g.home_score)), reps)
    return None

  def teams(self, season: int, week: int) -> dict:
    out = {}
    for g in self._week_games(season, week).itertuples():
      for t in (g.home_team, g.away_team):
        t = D.RELOCATED.get(t, t)
        tw = self.team_week(season, week, t)
        if tw:
          out[t] = tw
    return out

  def final_report_teams(self, season: int, week: int) -> set:
    return {t for t, tw in self.teams(season, week).items() if tw.final_report_in(self.now)}

  def waiver_run(self, season: int, week: int) -> pd.Timestamp | None:
    """The waiver run after this week's rollover (Wednesday ~03:00 ET)."""
    r = self.rollover(season, week)
    return None if r is None else r.normalize() + pd.Timedelta(days=1, hours=WAIVER_RUN[1])

  def phase(self, season: int, week: int) -> str:
    """'reports' (before the week's first kickoff) | 'games' (a game kicked off, not all final) | 'done'."""
    ts = self.teams(season, week).values()
    if not ts:
      return "bye"
    if all(t.final for t in ts):
      return "done"
    return "games" if any(self.now >= t.kick for t in ts) else "reports"

  # ---- the browser's copy
  def to_json(self, season: int, week: int) -> dict:
    """What a week page needs to apply the current time itself: ISO times (with offsets) for every team's kickoff and
    report deadlines, the rollover and the waiver run, and when this was built."""
    iso = lambda t: None if t is None else t.isoformat()
    return {"tz": ET, "built": iso(self.now), "week": week, "rollover": iso(self.rollover(season, week)),
            "waivers": iso(self.waiver_run(season, week)), "due_hour": REPORT_DUE_HOUR_ET,
            "teams": {t: {"kick": iso(tw.kick), "opp": tw.opp, "home": tw.home, "final": tw.final,
                          "inactives": iso(tw.kick - pd.Timedelta(minutes=INACTIVES_MIN)),
                          "reports": [{"date": d, "due": iso(due)} for d, due in tw.reports]}
                      for t, tw in sorted(self.teams(season, week).items())}}
