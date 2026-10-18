"""The week clock against hand-checked calendar cases: every game day's report days, daylight saving, rollover,
international games, holiday slates."""
import pandas as pd
import pytest

from nfledge.week_clock import Clock, kickoff
from nfledge.practice_calendar import report_dates


def sched(rows):
  return pd.DataFrame([{"season": 2026, "week": w, "game_type": "REG", "game_id": f"g{i}", "gameday": d, "gametime": t,
                        "home_team": h, "away_team": a, "home_score": hs} for i, (w, d, t, h, a, hs) in enumerate(rows)])


@pytest.mark.parametrize("day,exp", [
  ("2026-10-18", ["2026-10-14", "2026-10-15", "2026-10-16"]),   # Sunday: Wed-Fri
  ("2026-10-19", ["2026-10-15", "2026-10-16", "2026-10-17"]),   # Monday: Thu-Sat
  ("2026-10-15", ["2026-10-12", "2026-10-13", "2026-10-14"]),   # Thursday: Mon-Wed
  ("2026-12-26", ["2026-12-22", "2026-12-23", "2026-12-24"]),   # Saturday: Tue-Thu
  ("2026-11-27", ["2026-11-24", "2026-11-25", "2026-11-26"]),   # Friday (Black Friday): Tue-Thu
  ("2026-12-23", ["2026-12-20", "2026-12-21", "2026-12-22"]),   # Wednesday (Christmas-week slate): Sun-Tue
])
def test_report_days(day, exp):
  assert report_dates(day) == exp


def test_kickoff_dst():
  assert kickoff("2026-10-18", "13:00").utcoffset() == pd.Timedelta(hours=-4)   # EDT
  assert kickoff("2026-11-01", "13:00").utcoffset() == pd.Timedelta(hours=-5)   # EST from Nov 1 2026
  assert kickoff("2026-11-02", "20:15").tz_convert("UTC").hour == 1             # MNF 8:15 pm EST = 01:15 UTC


def test_week_rollover_and_states():
  s = sched([(6, "2026-10-15", "20:15", "DEN", "SEA", 17), (6, "2026-10-18", "13:00", "JAX", "HOU", None),
             (6, "2026-10-19", "20:15", "SF", "WAS", None), (7, "2026-10-22", "20:15", "KC", "BUF", None)])
  sun = pd.Timestamp("2026-10-18 09:00")
  c = Clock(s, sun)
  assert c.current_week(2026) == 6
  assert c.rollover(2026, 6) == pd.Timestamp("2026-10-20 06:00", tz="America/New_York")
  t = c.teams(2026, 6)
  assert t["DEN"].state(c.now) == "final" and t["JAX"].state(c.now) == "upcoming"
  assert {"JAX", "HOU", "SF", "WAS", "DEN", "SEA"} <= c.final_report_teams(2026, 6)
  # Monday team's final report (Saturday 4 pm) is in by Sunday morning; Thursday-week teams long done
  assert t["SF"].final_report_in(c.now) and t["JAX"].final_report_in(c.now)
  # Wednesday 3 pm: Sunday teams' first report not due yet
  wed = Clock(s, pd.Timestamp("2026-10-14 15:00"))
  assert wed.teams(2026, 6)["JAX"].reports_in(wed.now) == 0 and wed.teams(2026, 6)["DEN"].reports_in(wed.now) == 2  # its Wednesday report is due at 4 pm
  # after Tuesday 06:00 with every game final the site shows week 7
  s2 = s.assign(home_score=[17, 20, 24, None])
  assert Clock(s2, pd.Timestamp("2026-10-20 07:00")).current_week(2026) == 7
  # a week 6 game not final (postponed / scores not in) holds week 6
  assert Clock(s, pd.Timestamp("2026-10-20 07:00")).current_week(2026) == 6


def test_international_week1():
  s = sched([(1, "2026-09-10", "05:35", "LA", "SF", None)])   # Melbourne: early-morning ET kickoff, Thursday
  c = Clock(s, pd.Timestamp("2026-09-09 12:00"))
  assert [d for d, _ in c.teams(2026, 1)["LA"].reports] == ["2026-09-07", "2026-09-08", "2026-09-09"]


def test_to_json_shape():
  s = sched([(6, "2026-10-18", "13:00", "JAX", "HOU", None)])
  j = Clock(s, pd.Timestamp("2026-10-17 12:00")).to_json(2026, 6)
  assert j["teams"]["JAX"]["kick"].startswith("2026-10-18T13:00:00-04:00")
  assert [r["date"] for r in j["teams"]["HOU"]["reports"]] == ["2026-10-14", "2026-10-15", "2026-10-16"]
  assert j["teams"]["HOU"]["reports"][0]["due"].startswith("2026-10-14T16:00:00-04:00")
