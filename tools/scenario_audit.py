"""Timing stress test for injury handling (owner 2026-10-22: "come up with scenarios for hypothetical players that
would trip up our model ... bye weeks, IR placement, injured in game, combinations of those ... have we covered them
all?").

Each scenario plants one synthetic player into a copy of the live season's data (a real team, its real schedule):
his game history (snaps vs his usual, in-game injury notes and returns), report rows with real dates, reserve-list
codes, ESPN news and game-day rulings, and how far the week has got (which of his team's report days are in). Then
it runs the production code (InjuryModel.availability: chance to play, status, which model spoke; designations: the
tag) and checks what the rules say should happen. A failure is a gap to look at, not automatically a bug: the
"expect" lines are the rules as the owner set them (docs/INSIGHTS.md, the {#tags} audit).

  python tools/scenario_audit.py [--only=S01,S07]
"""
import copy
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import run  # noqa: E402
from nfledge import data as D  # noqa: E402
from nfledge import tuesday as T  # noqa: E402
from nfledge.config import load_config, load_scoring  # noqa: E402

GID = "00-SCN0001"
DAYCODE = {"D": "Did Not Participate In Practice", "L": "Limited Participation in Practice", "F": "Full Participation in Practice"}


@dataclass
class Scenario:
  sid: str
  title: str
  team_rule: str = "sunday"           # which real team: "sunday" (plays Sunday this week, played last week), "bye_last"
                                      # (bye last week), "bye_now" (bye this week), "thursday" (plays Thursday)
  games: dict = field(default_factory=dict)   # team game index from the end (-1 = his team's last game) -> snap share
                                              # (0 = didn't play); unlisted games: played at his usual 0.85
  hurt: dict = field(default_factory=dict)    # game index -> "out" (hurt, not back) / "back" (hurt, returned)
  last_report: tuple | None = None    # his row on the report for his last game: (days, game status, reason)
  week_days: str = ""                 # his entries on this week's report days so far ("D", "L", "F", "-" = not listed)
  team_days: int = 0                  # how many of his team's report days are in (0 = no report yet)
  final: bool = False                 # his team's final report is in
  game_status: str = "None"           # this week's game status on the final report
  why: str = "ankle"
  reserve: str | None = None          # reserve code on the latest roster week (R01 IR, R48 designated to return, ...)
  reserve_prev: str | None = None     # reserve code on every earlier week (then active now: activated this week)
  traded: bool = False                # on another team through last week (his games there); this team only now
  at_hours: float | None = None       # the moment checked, in hours from his team's kickoff (None: the real time)
  extra_day: bool = False             # his team filed an extra report day before its first calendar day (travel week)
  expect_overdue: bool | None = None  # the chronology flags one of his team's report days as overdue
  expect_final: bool | None = None    # the chronology calls his team's final report in
  espn: tuple | None = None           # (status, return date offset in days from his game or None) as ESPN news since his last game
  gameday: str | None = None          # "ACT" / "INA"
  expect_tag: str | None = None       # the tag the rules give
  expect_path: str | None = None      # which part of the code spoke: tuesday / practice / final / espn / gameday / none
  expect_avail: tuple | None = None   # (low, high) for the chance to play
  note: str = ""


S = [
  Scenario("S01", "Healthy, no report yet", expect_tag="", expect_avail=(0.9, 1.0)),
  Scenario("S02", "Hurt last game, not back; Tuesday", games={-1: 0.35}, hurt={-1: "out"},
           expect_tag="Q", expect_path="tuesday", expect_avail=(0.1, 0.6)),
  Scenario("S03", "Hurt last game, returned; Tuesday", games={-1: 0.70}, hurt={-1: "back"},
           expect_tag="", expect_path="tuesday", expect_avail=(0.75, 1.0)),
  Scenario("S04", "Hurt last game, not back; team filed Wednesday, he isn't on it", games={-1: 0.35}, hurt={-1: "out"},
           team_days=1, week_days="-", expect_tag="", expect_avail=(0.85, 1.0),
           note="not listed on a filed day = practiced fully"),
  Scenario("S05", "Hurt last game, not back; DNP Wednesday", games={-1: 0.35}, hurt={-1: "out"}, team_days=1,
           week_days="D", expect_tag="Q", expect_path="practice", expect_avail=(0.05, 0.65)),
  Scenario("S06", "Hurt in his last game, then a bye; Tuesday of the week he plays again", team_rule="bye_last",
           games={-1: 0.30}, hurt={-1: "out"}, expect_tag="Q", expect_path="tuesday", expect_avail=(0.3, 0.9),
           note="Q holds through the bye; the extra rest week should lift his chance vs S02"),
  Scenario("S07", "Missed last game, Out on its report (hamstring); Tuesday", games={-1: 0.0},
           last_report=("DDD", "Out", "hamstring"), expect_tag="Q", expect_path="tuesday", expect_avail=(0.2, 0.7)),
  Scenario("S08", "Missed last game, listed for rest; Tuesday", games={-1: 0.0}, last_report=("DDF", "Out", "rest"),
           why="rest", expect_tag="", note="rest / personal absences don't carry a Q"),
  Scenario("S09", "Final report: Out", team_days=3, week_days="DDD", final=True, game_status="Out",
           last_report=("DDD", "Out", "knee"), games={-1: 0.0}, expect_tag="O", expect_avail=(0.0, 0.0)),
  Scenario("S10", "Final report: Doubtful", team_days=3, week_days="DDD", final=True, game_status="Doubtful",
           expect_tag="D", expect_avail=(0.0, 0.15)),
  Scenario("S11", "Final report: Questionable, no practice all week", team_days=3, week_days="DDD", final=True,
           game_status="Questionable", expect_tag="Q", expect_avail=(0.1, 0.5)),
  Scenario("S12", "Questionable, then inactive on game day", team_days=3, week_days="LLL", final=True,
           game_status="Questionable", gameday="INA", expect_tag="O", expect_avail=(0.0, 0.0)),
  Scenario("S13", "Questionable, then active on game day", team_days=3, week_days="LLF", final=True,
           game_status="Questionable", gameday="ACT", expect_tag="", expect_avail=(0.95, 1.0)),
  Scenario("S14", "Placed on IR (latest roster week)", reserve="R01", expect_tag="IR"),
  Scenario("S15", "ESPN Out with a return date after this game; Tuesday", games={-1: 0.0},
           last_report=("DDD", "Out", "knee"), espn=("Out", 10), expect_tag="O", expect_avail=(0.0, 0.1)),
  Scenario("S16", "ESPN Out, no return date; Tuesday", games={-1: 0.4}, hurt={-1: "out"}, espn=("Out", None),
           expect_tag="Q", expect_path="espn", expect_avail=(0.1, 0.6), note="plain ESPN Out isn't an O"),
  Scenario("S17", "Report on NFL.com, nflverse behind (the Shough case)", team_days=1, week_days="F",
           last_report=("FFF", "None", "ankle"), expect_tag="", expect_path="practice", expect_avail=(0.9, 1.0)),
  Scenario("S18", "Late addition: not listed Wednesday, DNP Thursday", team_days=2, week_days="-D",
           expect_tag="", expect_path="practice", expect_avail=(0.2, 0.85),
           note="no Q from the Tuesday rule (wasn't hurt last game); the tag only comes with the final report"),
  Scenario("S19", "Dropped off the report: DNP Wednesday, not listed Thursday", team_days=2, week_days="D-",
           expect_tag="", expect_avail=(0.3, 0.95)),
  Scenario("S20", "Bye this week, hurt and not back in his last game", team_rule="bye_now", games={-1: 0.3},
           hurt={-1: "out"}, expect_tag="Q", note="tag_map: a bye team's player keeps his Tuesday Q through the bye"),
  Scenario("S21", "Thursday game, short week: hurt last game, not back; final report Questionable, DNP-LP-LP",
           team_rule="thursday", games={-1: 0.4}, hurt={-1: "out"}, team_days=3, week_days="DLL", final=True,
           game_status="Questionable", expect_tag="Q", expect_path="final", expect_avail=(0.3, 0.9),
           note="the final-report rule follows the real clock, so a short week is checked at its final report"),
  Scenario("S22", "Missed two games on IR-type absence then back at practice: LLF final, no status", games={-1: 0.0, -2: 0.0},
           last_report=("DDD", "Out", "hamstring"), team_days=3, week_days="LLF", final=True,
           expect_tag="", expect_avail=(0.75, 1.0)),
  Scenario("S23", "Healthy scratch last game (not on report, no snaps)", games={-1: 0.0}, expect_tag="",
           note="no Q: not hurt, not on the report"),
  Scenario("S24", "ESPN midweek Out while NFL.com has him Limited Wednesday", games={-1: 0.5}, hurt={-1: "out"},
           team_days=1, week_days="L", espn=("Out", None), expect_tag="Q",
           note="which wins mid-week: the official practice line or ESPN's ruling?"),
  Scenario("S26", "Traded this week: played every game for his old team, healthy", traded=True, expect_tag="",
           expect_avail=(0.8, 1.0), note="judged by his own last game, not his new team's (which he didn't play in)"),
  Scenario("S27", "Activated from IR this week: full final report, no status", reserve_prev="R48",
           games={-1: 0.0, -2: 0.0, -3: 0.0, -4: 0.0}, team_days=3, week_days="LLF", final=True, expect_tag="",
           expect_path="final", expect_avail=(0.7, 1.0)),
  Scenario("S28", "Monday-night team, Sunday 9 p.m.: Thursday and Friday in, Saturday's final report missing",
           team_rule="monday", at_hours=-23.25, team_days=2, week_days="DL", expect_tag="", expect_path="practice",
           expect_overdue=True, expect_final=False, note="the missing final report is flagged, not read as 'no status'"),
  Scenario("S29", "Sunday team, Saturday 10 a.m.: Wednesday and Thursday in (DNP, DNP), Friday's final report missing",
           at_hours=-27.0, team_days=2, week_days="DD", expect_tag="", expect_path="practice", expect_overdue=True,
           expect_final=False, expect_avail=(0.05, 0.7)),
  Scenario("S30", "Travel week: an extra report day filed, then all three calendar days (final)", extra_day=True,
           at_hours=-40.0, team_days=3, week_days="LLLF", final=True, game_status="Questionable", expect_tag="Q",
           expect_path="final", expect_overdue=False, expect_final=True),
  Scenario("S25", "Designated to return from IR, practicing (window open)", reserve="R48", team_days=2, week_days="LL",
           games={-1: 0.0, -2: 0.0, -3: 0.0}, expect_tag="IR", expect_path="practice", expect_avail=(0.3, 0.95),
           note="reserve-list rows: the week model with the reserve inputs"),
]


class World:
  def __init__(self):
    self.cfg, self.scoring = load_config(), load_scoring()
    self.data = D.load_all(self.cfg)
    self.season = self.data.current_season
    self.week = run.display_week(self.data)
    eng = run.trained_engine(self.data, self.cfg, self.scoring, self.season)
    self.im = eng.injury_model
    self.cache = D.Cache(ROOT / self.cfg["data"]["cache_dir"])
    self.rep0, self.hurt0 = T.report_rows(self.data), T.hurt_notes(self.data, self.cache)
    self.nb0 = T.hurt_not_back(self.data, self.cache, self.season)
    sch = self.data.schedules
    self.sch = sch[(sch.season == self.season) & (sch.game_type == "REG")]
    # the week models (trained on earlier seasons) once, as InjuryModel.week_prob builds them
    im = self.im
    rep_rows, hurt = im._tues_inputs()
    im._week_res = bool(self.cfg.get("injuries", {}).get("reserve_rows"))
    wr = T.week_rows(self.data, rep_rows, hurt, reserve=im._week_res).dropna(subset=["y"])
    im._week_all, im._week_models = wr[~((wr.stage == 3) & (wr.gs_now == "Out"))], {}
    ro = self.data.rosters
    self.tpl_ro = ro[(ro.season == self.season) & (ro.position == "WR") & (ro.status == "ACT")].iloc[0]
    sn = self.data.snaps
    self.tpl_sn = sn[(sn.season == self.season) & (sn.position == "WR")].iloc[0]
    inj = self.data.injuries
    self.tpl_inj = inj[(inj.season == self.season)].iloc[0]

  def team_for(self, rule: str) -> str:
    wk, prev = self.sch[self.sch.week == self.week], self.sch[self.sch.week == self.week - 1]
    plays_now = set(wk.home_team) | set(wk.away_team)
    played_prev = set(prev.home_team) | set(prev.away_team)
    day = {t: pd.Timestamp(g).day_name() for t, g in [*zip(wk.home_team, wk.gameday), *zip(wk.away_team, wk.gameday)]}
    if rule == "monday":
      c = sorted(t for t in plays_now & played_prev if day[t] == "Monday")
    elif rule == "bye_now":
      c = sorted(set(self.sch.home_team) - plays_now)
    elif rule == "bye_last":
      c = sorted(t for t in plays_now - played_prev if day[t] == "Sunday")
    elif rule == "thursday":
      c = sorted(t for t in plays_now & played_prev if day[t] == "Thursday")
    else:
      c = sorted(t for t in plays_now & played_prev if day[t] == "Sunday")
    if not c:
      raise LookupError(f"no team this week fits '{rule}'")
    return c[0]

  def team_games(self, team: str) -> list[int]:
    s = self.sch[((self.sch.home_team == team) | (self.sch.away_team == team)) & (self.sch.week < self.week)]
    return sorted(s.week)

  def report_dates(self, team: str, n: int) -> list[str]:
    from nfledge.practice_calendar import team_report_days
    cal = team_report_days(self.data.schedules, self.season, self.week, {})
    days = cal.get(team) or []
    return list(days)[:n]

  def build(self, sc: Scenario):
    d, s, w = copy.copy(self.data), self.season, self.week
    team = self.team_for(sc.team_rule)
    games = self.team_games(team)
    old = None
    if sc.traded:  # another Sunday team that also played last week: his games so far were there
      wk, prev = self.sch[self.sch.week == w], self.sch[self.sch.week == w - 1]
      both = sorted((set(wk.home_team) | set(wk.away_team)) & (set(prev.home_team) | set(prev.away_team)) - {team})
      old = both[-1]
      games = self.team_games(old)
    # roster: weeks 1..now on this team (reserve code on the latest week if any)
    ro = []
    for wk in range(1, w + 1):
      r = self.tpl_ro.copy()
      r["gsis_id"], r["team"], r["season"], r["week"], r["full_name"] = GID, team, s, wk, "Scenario Player"
      r["espn_id"], r["status"], r["status_description_abbr"] = "999999901", "ACT", "A01"
      if old and wk < w:
        r["team"] = old
      if wk == w and sc.reserve:
        r["status"], r["status_description_abbr"] = "RES", sc.reserve
      if wk < w and sc.reserve_prev:
        r["status"], r["status_description_abbr"] = "RES", sc.reserve_prev
      ro.append(r)
    d.rosters = pd.concat([self.data.rosters, pd.DataFrame(ro)], ignore_index=True)
    # snaps: his team's games, usual 0.85, overrides by index from the end
    sn = []
    for i, gw in enumerate(games):
      share = sc.games.get(i - len(games), 0.85)
      if share <= 0:
        continue
      r = self.tpl_sn.copy()
      r["gsis_id"], r["team"], r["season"], r["week"], r["game_type"] = GID, old or team, s, gw, "REG"
      r["offense_pct"], r["defense_pct"], r["offense_snaps"], r["defense_snaps"], r["st_snaps"] = share, 0.0, round(65 * share), 0, 0
      sn.append(r)
    d.snaps = pd.concat([self.data.snaps, pd.DataFrame(sn)], ignore_index=True) if sn else self.data.snaps
    # report rows, as NFL.com files them (production builds the current season's injury table from these:
    # data.injuries_from_nflcom); his last game's and this week's so far
    full = {a: n for n, a in D.team_names(self.data.teams).items()}
    pr = []

    def row(wk, tm, days_, dates_, gs_, why_):
      return {"season": s, "week": wk, "gsis_id": GID, "position": "WR", "game_status": gs_, "days": days_,
              "dates": dates_, "team_name": full.get(tm, tm), "full_name": "Scenario Player",
              "report_injuries": why_ if gs_ != "None" else "", "practice_injuries": why_}
    last = games[-1] if games else None
    if sc.last_report and last is not None:
      days_, gs_, why_ = sc.last_report
      gd0 = self.sch[((self.sch.home_team == (old or team)) | (self.sch.away_team == (old or team))) & (self.sch.week == last)].gameday
      d_ = pd.Timestamp(gd0.iloc[0]) if len(gd0) else None
      dl = ",".join(str((d_ - pd.Timedelta(days=4 - k)).date()) for k in range(len(days_))) if d_ is not None else ""
      pr.append(row(last, old or team, days_, dl, gs_.upper() if gs_ != "None" else "None", why_.title()))
    dates = self.report_dates(team, sc.team_days)
    if sc.extra_day and dates:
      dates = [str((pd.Timestamp(dates[0]) - pd.Timedelta(days=1)).date())] + dates
    if dates:
      mine = [(dt, c) for dt, c in zip(dates, sc.week_days) if c != "-"]
      if mine:
        pr.append(row(w, team, "".join(c for _, c in mine), ",".join(dt for dt, _ in mine),
                      sc.game_status.upper() if sc.final and sc.game_status != "None" else "None", sc.why.title()))
      # the rest of his team's report: a teammate listed every filed day, so the team's days count as filed
      ro_t = self.data.rosters[(self.data.rosters.season == s) & (self.data.rosters.team == team) & (self.data.rosters.status == "ACT")]
      mate = ro_t[ro_t.position == "OL"].gsis_id.iloc[0] if (ro_t.position == "OL").any() else ro_t.gsis_id.iloc[0]
      pr.append({**row(w, team, "F" * len(dates), ",".join(dates), "None", "Knee"), "gsis_id": mate, "position": "OL"})
    mine_team = set(self.data.rosters[(self.data.rosters.season == s) & (self.data.rosters.team == team)].gsis_id)
    base_pr = self.data.practice
    base_pr = base_pr[~((base_pr.season == s) & (base_pr.week == w) & base_pr.gsis_id.isin(mine_team))]
    new_pr = pd.DataFrame(pr)
    d.practice = pd.concat([base_pr, new_pr], ignore_index=True) if len(new_pr) else base_pr
    base_inj = self.data.injuries
    base_inj = base_inj[~((base_inj.season == s) & (base_inj.week == w) & (base_inj.team == team))]  # this week: our script decides
    add = D.injuries_from_nflcom(new_pr, self.data.teams, self.data.schedules) if len(new_pr) else None
    d.injuries = pd.concat([base_inj, add], ignore_index=True) if add is not None and len(add) else base_inj
    # in-game notes
    hurt = T.HurtSet(self.hurt0)
    hurt.back, hurt.ret_seasons = set(self.hurt0.back), set(self.hurt0.ret_seasons)
    nb = set(self.nb0)
    for i, kind in sc.hurt.items():
      gw = games[i]
      hurt.add((GID, s, gw))
      if kind == "back":
        hurt.back.add((GID, s, gw))
      else:
        nb.add((GID, s, gw))
    return d, team, hurt, nb

  def run(self, sc: Scenario) -> dict:
    d, team, hurt, nb = self.build(sc)
    im = self.im
    for a in ("_tues_rows", "_scratch_cache"):
      if hasattr(im, a):
        delattr(im, a) if a != "_scratch_cache" else im._scratch_cache.clear()
    run.attach_data(type("E", (), {})(), None) if False else None
    im.data = d
    im._tues_in = (T.report_rows(d), hurt)
    im._week_ctx = T._Ctx(d, *im._tues_in)
    T.hurt_not_back, real_nb = (lambda *_a, **_k: nb), T.hurt_not_back
    games_now = self.sch[self.sch.week == self.week]
    gday = games_now[(games_now.home_team == team) | (games_now.away_team == team)].gameday
    im.espn_bridge, im.espn_midweek, im.espn_gameday, im.espn_questionable = {}, {}, {}, set()
    if sc.espn:
      st, ret = sc.espn
      b = "Out+ret" if st == "Out" and ret is not None and ret > 0 else st
      if sc.team_days:
        im.espn_midweek = {GID: b} if b in ("Out", "Out+ret", "IR") else {}
      else:
        im.espn_bridge = {GID: b}
    if sc.gameday:
      im.espn_gameday = {GID: (sc.gameday, "")}
    from nfledge.week_clock import kickoff
    g0 = games_now[(games_now.home_team == team) | (games_now.away_team == team)]
    kick = kickoff(g0.gameday.iloc[0], g0.gametime.iloc[0]) if len(g0) else None
    im.now = kick + pd.Timedelta(hours=sc.at_hours) if (sc.at_hours is not None and kick is not None) else None
    try:
      p = pd.DataFrame([{"gsis_id": GID, "team": team, "pos": "WR", "full_name": "Scenario Player"}])
      out = {"team": team}
      if sc.team_rule == "bye_now":
        tags = im.tag_map(self.season, self.week)
        out.update(tag=tags.get(GID, ""), avail=np.nan, status="(bye)", why="", path="none")
      else:
        a = im.availability(p, self.season, self.week)
        r = a.iloc[0]
        tag = r.get("tag", "")
        if sc.reserve and not tag:
          tag = im.tag_map(self.season, self.week).get(GID, "")
        st_ = str(r.status)
        path = ("gameday" if st_.startswith(("Inactive", "Active")) else "espn" if "ESPN" in st_ else
                "tuesday" if str(r.get("tuesday", "") or "") else "practice" if bool(r.get("partial_week")) and bool(r.get("on_report"))
                else "final" if bool(r.get("on_report")) else "none")
        out.update(tag=tag or "", avail=float(r.avail), status=st_, why=str(r.get("tuesday", "") or ""), path=path)
      from nfledge.injuries import chrono
      c = chrono(d, self.season, self.week, im.now)
      tc = c.team(team) if c is not None else None
      out["overdue"] = bool(tc and tc.overdue)
      out["final"] = bool(tc and tc.final)
      out["stage"] = tc.stage if tc else None
      return out
    finally:
      T.hurt_not_back = real_nb
      im.now = None


def check(sc: Scenario, o: dict) -> list[str]:
  bad = []
  if sc.expect_tag is not None and o["tag"] != sc.expect_tag:
    bad.append(f"tag {o['tag'] or '-'} (expected {sc.expect_tag or '-'})")
  if sc.expect_path and o.get("path") != sc.expect_path:
    bad.append(f"model {o.get('path')} (expected {sc.expect_path})")
  if sc.expect_overdue is not None and o.get("overdue") != sc.expect_overdue:
    bad.append(f"overdue {o.get('overdue')} (expected {sc.expect_overdue})")
  if sc.expect_final is not None and o.get("final") != sc.expect_final:
    bad.append(f"final report {o.get('final')} (expected {sc.expect_final})")
  if sc.expect_avail and o["avail"] == o["avail"] and not (sc.expect_avail[0] - 1e-9 <= o["avail"] <= sc.expect_avail[1] + 1e-9):
    bad.append(f"chance {o['avail']:.0%} (expected {sc.expect_avail[0]:.0%}-{sc.expect_avail[1]:.0%})")
  return bad


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  only = set(opt["only"].split(",")) if "only" in opt else None
  wd = World()
  print(f"world: {wd.season} week {wd.week}\n")
  fails = 0
  for sc in S:
    if only and sc.sid not in only:
      continue
    try:
      o = wd.run(sc)
      bad = check(sc, o)
    except Exception as e:  # a crash is a finding too
      o, bad = {"team": "?", "tag": "?", "avail": np.nan, "status": "", "why": ""}, [f"ERROR {type(e).__name__}: {str(e)[:140]}"]
    fails += bool(bad)
    av = f"{o['avail']:.0%}" if o["avail"] == o["avail"] else "-"
    print(f"{'FAIL' if bad else 'ok  '} {sc.sid} {sc.title} [{o['team']}]")
    print(f"       tag {o['tag'] or '-'} | chance {av} | {o.get('path', '?')} | stage {o.get('stage')} final {o.get('final')} overdue {o.get('overdue')} | {o['status'] or '-'}" + (f" | {o['why'][:110]}" if o["why"] else ""))
    for b in bad:
      print(f"       -> {b}")
    if sc.note:
      print(f"       note: {sc.note}")
  print(f"\n{fails} of {len([s for s in S if not only or s.sid in only])} scenarios need a look")


if __name__ == "__main__":
  main()
