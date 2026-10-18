"""Injury return timing: for a player currently out with an injury, the chance he is active k weeks from now.

Practice participation (injuries.py) tells us about THIS week. Further out it says little, and players already
ruled out for weeks (injured reserve, PUP) are not on injury reports at all. This model learns, from every
injury absence since 2018, the chance an injured player is back for his team's NEXT game given:
  games already missed, current roster designation (IR, IR designated to return, PUP, other reserve, active /
  inactive), the latest injury-report status, the injury itself (body part), position, and week of the season.
Chaining those one-game chances (each step one more game missed, designation carried until he returns) gives
P(active) 1, 2, 3 ... games ahead. Minimum stays on IR / PUP and season-ending injuries are learned from the data,
not hard-coded. Trained only on seasons before the one projected (walk-forward), like everything else.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

POS_GROUP = {"QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE", "T": "OL", "G": "OL", "C": "OL", "OL": "OL",
             "DE": "DL", "DT": "DL", "NT": "DL", "DL": "DL", "LB": "LB", "ILB": "LB", "OLB": "LB", "MLB": "LB",
             "CB": "DB", "S": "DB", "FS": "DB", "SS": "DB", "DB": "DB", "K": "ST", "P": "ST", "LS": "ST"}
INJURY_GROUPS = ["Knee", "Ankle", "Hamstring", "Shoulder", "Concussion", "Groin", "Calf", "Illness", "Foot", "Back",
                 "Hip", "Neck", "Quadricep", "Toe", "Elbow", "Achilles", "Hand", "Wrist", "Chest", "Ribs"]
DESIG = {"R01": "ir", "R48": "ir_return", "R04": "pup", "A01": "active", "I01": "inactive"}
REPORT = {"Out": 3, "Doubtful": 2, "Questionable": 1}
FEATURES = ["missed", "desig_ir", "desig_ir_return", "desig_pup", "desig_reserve_other", "desig_active",
            "report", "inj_code", "pos_code", "week", "missed_x_ir"]
# The chain's hazard also reads the calendar (INSIGHTS {#return-calendar} (AD), owner 2026-10-17: byes, Thursday
# games, time since he got hurt): gap = days from the game he just missed to his team's next one; days_out = days
# from the last game before this absence to that next game. return_timing.py (IR) keeps FEATURES: no gain there.
CHAIN_FEATURES = FEATURES + ["gap", "days_out"]
# (AX, injuries.opened_out) players who open the season on a reserve list: opened_out = 1 in those episodes (before
# his first game of the season); prior_g = games he played the season before (every episode). Read by both the chain
# and the direct IR model when the flag is on.
OPENED_FEATURES = ["opened_out", "prior_g"]


def _gamedays(data) -> dict:
  """(season, week, team) -> game date, regular season."""
  s = data.schedules[data.schedules.game_type == "REG"]
  out = {}
  for x in s.itertuples():
    out[(x.season, x.week, x.home_team)] = out[(x.season, x.week, x.away_team)] = pd.Timestamp(x.gameday)
  return out


def played_set(data) -> set:
  """(season, week, gsis_id) for every player-game with any snap (offense, defense or special teams)."""
  sn = data.snaps.dropna(subset=["gsis_id"])
  any_snap = (sn.offense_snaps.fillna(0) + sn.defense_snaps.fillna(0) + sn.st_snaps.fillna(0)) > 0
  played = set(map(tuple, sn.loc[any_snap, ["season", "week", "gsis_id"]].itertuples(index=False)))
  # Snap counts post a day or two after games; weekly player stats (from play-by-play) land sooner.
  st = data.stats
  idc = "player_id" if "player_id" in st else "gsis_id"
  played |= set(zip(st.season, st.week, st[idc]))
  return played


def availability_plan(data, proj: pd.DataFrame, week: int, espn_feed: pd.DataFrame | None, cache_dir, gb: dict) -> dict:
  """(AM, owner 2026-10-17: one source of truth) the live build's availability plan, computed once as of the current
  week and passed to every page's projections and to Power: {"avail": week -> {gsis: P(plays)}, "status": week ->
  {gsis: text}, "extra": week -> IR players expected back}, for this week (the injury model's chance, players it
  marks injured) and every later regular-season week (lookahead_availability). The chain starts from this week's
  chance for every player the injury model lists, whatever the source (practice report, ESPN bridge, Tuesday model,
  carried status), not only practice-report players."""
  season = data.current_season
  s = data.schedules
  last = int(s[(s.season == season) & (s.game_type == "REG")].week.max())
  hurt = proj[(proj.status.fillna("") != "") & (proj.avail < 1)]
  now_report = dict(zip(hurt.gsis_id, hurt.avail.astype(float)))
  # players ESPN lists on IR who are off this week's board (IR players aren't projected: Jalen Hurts, placed on IR
  # before missing a game, was absent from the plan and Power read "absent" as healthy, 2026-10-18): out this week, then
  # the newly-injured chain with the IR floor
  ir = espn_ir(data, espn_feed)
  for g in ir:
    now_report.setdefault(g, 0.0)
  # nflverse's reserve lists too (IR, PUP, NFI, suspension: roster status RES), for players ESPN's IR list misses (PUP /
  # NFI, ESPN lag, an unmatched ESPN id; IR audit 2026-10-18): newly placed ones start the chain; everyone on a list is
  # out this week (set after the lookahead, so long-term reserve players keep their IR-model inputs untouched)
  for g in reserve_now(data, new_only=True):
    now_report.setdefault(g, 0.0)
  later = list(range(week + 1, last + 1))
  avail, status, extra = lookahead_availability(data, week, later, now_report, espn_feed=espn_feed, cache_dir=cache_dir, gb=gb)
  avail[week] = dict(now_report)
  for g in reserve_now(data):
    avail[week][g] = 0.0
  return {"avail": avail, "status": status, "extra": extra}


def lookahead_availability(data, current_week: int, weeks: list[int], now_report: dict | None = None,
                           espn_feed: pd.DataFrame | None = None, cache_dir=None, gb: dict | None = None) -> tuple[dict, dict, dict]:
  """For each lookahead week: {gsis_id: P(active)} and {gsis_id: status text} for players out injured now, plus
  the injured-reserve players expected back that week (to add to the roster). Fit on every injury episode whose
  outcome is known (walk-forward: nothing from the future). now_report: {gsis_id: P(plays this week)} for players
  on this week's practice report (InjuryModel.availability): the chain starts from it instead of the hazard.
  Players on IR use return_timing.py's direct model instead of the chain (pre-registered hybrid, owner-approved
  2026-10-15), fed this week's practice and ESPN's live status / return date (espn_feed); cache_dir and gb are
  needed for it (without them every player stays on the chain)."""
  season = data.current_season
  m = ReturnModel(data, played_set(data))
  st = m.states(sorted(data.seasons))
  if st.empty:
    return {}, {}, {}
  known = (st.season < season) | (st.next_week < current_week)
  m.fit_frame(st[known])
  # Each injured player's latest state, including this week's finished games; anyone who has played since that
  # state is back and drops out.
  cur = st[(st.season == season) & (st.week <= current_week)].sort_values("week").groupby("gsis_id").tail(1)
  cur = cur[[not any((season, w, g) in m.played for w in range(int(wk) + 1, current_week + 1))
             for g, wk in zip(cur.gsis_id, cur.week)]]
  cur = cur[cur.next_week >= current_week - 1]  # still out as of his team's most recent game
  horizon = 18
  now_report = now_report or {}
  ir_now = espn_ir(data, espn_feed)
  for g in reserve_now(data, new_only=True):
    ir_now.setdefault(g, None)  # (IR audit) newly on a reserve list: the league minimum; ESPN's date when it has one
  new = _newly_injured(data, m, season, current_week, now_report, set(cur.gsis_id), ir=ir_now)
  if cur.empty and new.empty:
    return {w: {} for w in weeks}, {w: {} for w in weeks}, {w: pd.DataFrame() for w in weeks}
  first = np.array([float(now_report[g]) if (g in now_report and int(nw) == current_week) else np.nan
                    for g, nw in zip(cur.gsis_id, cur.next_week)])
  pa = m.p_active(cur, horizon, first=first, stay=1.0) if len(cur) else np.zeros((0, horizon))  # once back: 1.0
  ir_rows = np.where(cur.desig.to_numpy() == "ir")[0]
  if len(ir_rows) and cache_dir is not None and gb is not None:
    from . import return_timing as RT
    seasons = [s_ for s_ in range(RT.FIRST_SEASON, season) if s_ in set(data.seasons)]
    rt = RT.fit(RT.training_rows(data, m, gb, seasons, cache_dir), opened_out=m.opened_out)
    prac = pd.concat([data.avail_hist[["season", "week", "gsis_id", "days", "game_status"]],
                      data.practice[data.practice.season == season][["season", "week", "gsis_id", "days", "game_status"]]
                      if data.practice is not None else None], ignore_index=True)
    esp = pd.read_parquet(RT.CAPTURES) if RT.CAPTURES.exists() else pd.DataFrame(columns=["captured", "espn_id", "status", "ret"])
    if espn_feed is not None and len(espn_feed):  # live: as captured now
      ret = pd.to_datetime(espn_feed.get("return_date"), errors="coerce", utc=True).dt.tz_convert(None)
      live = pd.DataFrame({"captured": pd.Timestamp.now().normalize(), "espn_id": espn_feed.espn_id.astype(str),
                           "status": espn_feed.status, "ret": ret})
      esp = pd.concat([esp, live], ignore_index=True)
    # features need his whole season of states (games on IR so far, window opened earlier), then his latest row
    ids = set(cur.gsis_id.iloc[ir_rows])
    full = RT.enrich(data, st[(st.season == season) & st.gsis_id.isin(ids)], prac, esp).set_index(["gsis_id", "week"])
    sub = full.loc[list(zip(cur.gsis_id.iloc[ir_rows], cur.week.iloc[ir_rows]))].reset_index()
    sub["p_now"] = first[ir_rows]
    pa[ir_rows, :] = RT.predict(rt, sub, horizon)
  if len(new):  # newly injured: this week's chance p, else the chain from missing this week's game; back = 1.0
    p0 = new.p_now.to_numpy()[:, None]
    cur = pd.concat([cur, new], ignore_index=True)
    pa = np.vstack([pa, p0 + (1 - p0) * m.p_active(new, horizon, stay=1.0)])
  s = data.schedules
  reg = s[(s.season == season) & (s.game_type == "REG")]
  team_weeks = {t: sorted(set(reg[reg.home_team == t].week) | set(reg[reg.away_team == t].week))
                for t in set(reg.home_team) | set(reg.away_team)}
  r = data.rosters
  last = r[(r.season == season) & r.gsis_id.isin(cur.gsis_id)].sort_values("week").groupby("gsis_id").tail(1)
  info = last.set_index("gsis_id")
  # (AM, owner chose A 2026-10-17) the IR floor for players ESPN lists on IR whom nflverse hasn't designated yet
  # (designated ones are on the direct model, which knows the minimum and ESPN's date): no game for the league minimum
  # from his team's next unplayed game, nor before ESPN's estimated return date (only 3.6% of 922 IR stints 2022-25
  # played before it); newly injured and already out alike (Hurts, out week 6 then IR, sat on the chain at 56%)
  zero = {x.gsis_id: ir_zero_weeks(data, season, x.team, current_week, ir_now[x.gsis_id])
          for x in cur.itertuples() if x.gsis_id in ir_now and x.desig != "ir"}
  avail, status, extra = {}, {}, {}
  for w in weeks:
    a, t_, rows = {}, {}, []
    for i, x in enumerate(cur.itertuples()):
      tw = team_weeks.get(x.team, [])
      if w not in tw:
        continue
      k = sum(1 for g in tw if x.week < g <= w)  # his team's games from his last state through week w
      if k == 0 and w == x.week and getattr(x, "bye_start", False) is True:
        p = 0.0 if w in zero.get(x.gsis_id, ()) else float(x.p_now)  # (IR audit) placed in his bye week: his next game
        a[x.gsis_id], t_[x.gsis_id] = p, f"{p:.0%} to play"
        continue
      if k < 1 or k > horizon:
        continue
      p = 0.0 if w in zero.get(x.gsis_id, ()) else float(pa[i, k - 1])
      a[x.gsis_id] = p
      t_[x.gsis_id] = f"{p:.0%} to play"
      # a reserve-list player joins that week's roster with his chance to play, like an injured active player: under
      # 50% he's projected to sit (teammates keep the volume) but his if-active line and chance still count toward
      # rest-of-season totals (the >= 0.5 cut used before left IR players at 0 ROS points: Achane 2026 wk 6)
      if x.gsis_id in info.index and info.at[x.gsis_id, "status"] == "RES" and p >= 0.05:
        pos = POS_GROUP.get(str(info.at[x.gsis_id, "position"]), "")
        if pos in ("QB", "RB", "WR", "TE"):
          rows.append({"gsis_id": x.gsis_id, "team": x.team, "pos": pos,
                       "full_name": info.at[x.gsis_id, "full_name"], "depth_rank": np.nan})
    avail[w], status[w], extra[w] = a, t_, pd.DataFrame(rows)
  return avail, status, extra


def reserve_now(data, new_only: bool = False) -> set:
  """QB / RB / WR / TE on a reserve list (nflverse roster status RES) in the current season's latest roster week;
  new_only: placed there since the week before (players already on it have return states and the IR model)."""
  r = data.rosters[(data.rosters.season == data.current_season) & data.rosters.gsis_id.notna()]
  if not len(r):
    return set()
  last = int(r.week.max())
  cur = r[(r.week == last) & (r.status == "RES") & r.position.isin(["QB", "RB", "WR", "TE", "FB"])]
  out = set(cur.gsis_id)
  if new_only:
    before = set(r[(r.week == last - 1) & (r.status == "RES")].gsis_id)
    out -= before
  return out


def espn_ir(data, feed: pd.DataFrame | None) -> dict:
  """gsis -> ESPN's estimated return date (or None) for players ESPN lists on injured reserve right now (owner
  2026-10-17: Jalen Hurts placed on IR on a Saturday, before nflverse's rosters show it): matched through the rosters'
  ESPN ids."""
  if feed is None or not len(feed) or "status" not in feed:
    return {}
  f = feed[feed.status == "Injured Reserve"].dropna(subset=["espn_id"])
  r = data.rosters[data.rosters.espn_id.notna()]
  m = dict(zip(r.espn_id.astype(str).str.replace(r"\.0$", "", regex=True), r.gsis_id))
  ret = pd.to_datetime(f.get("return_date"), errors="coerce", utc=True).dt.tz_convert(None) if "return_date" in f else pd.Series(pd.NaT, index=f.index)
  return {m[i]: (None if pd.isna(d) else d) for i, d in zip(f.espn_id.astype(str), ret) if i in m and isinstance(m[i], str)}


def ir_zero_weeks(data, season: int, team: str, week: int, ret) -> set:
  """Weeks an injured-reserve player can't play (owner 2026-10-17, (AM)): his team's first league-minimum games not
  yet played from `week` on (placement counts from the next game), and every game before ESPN's estimated return date."""
  from .return_timing import ir_min
  s = data.schedules
  g = s[(s.season == season) & (s.game_type == "REG") & ((s.home_team == team) | (s.away_team == team))
        & (s.week >= week) & s.home_score.isna()].sort_values("week")
  out = set(int(w) for w in g.week.head(ir_min(season)))
  if ret is not None:
    out |= set(int(w) for w in g[pd.to_datetime(g.gameday) < ret].week)
  return out


def ir_newly(data, pa: np.ndarray, season: int, team: str, week: int, ret) -> np.ndarray:
  """A player newly placed on IR (owner 2026-10-17): this week's game is the first of the league minimum, so he sits
  his next (minimum - 1) games, or every game before ESPN's estimated return date if that is later; after that the
  newly-injured chain (pa: one row of P(active) for his games after this week). The chain itself stays on the
  active-player state: its IR state is learned mostly from season-ending stays (Hurts, back Nov 22 per ESPN, came
  out at 7% for the rest of the season under it)."""
  from .return_timing import ir_min
  s = data.schedules
  g = s[(s.season == season) & (s.game_type == "REG") & ((s.home_team == team) | (s.away_team == team)) & (s.week > week)].sort_values("week")
  n_min = max(ir_min(season) - 1, 0)
  n_ret = int((pd.to_datetime(g.gameday) < ret).sum()) if ret is not None else 0
  pa = pa.copy()
  pa[:, :max(n_min, n_ret)] = 0.0
  return pa


def _newly_injured(data, m, season: int, week: int, now_report: dict, known: set, ir: set = frozenset()) -> pd.DataFrame:
  """(AH, INSIGHTS {#newinj-chain}, owner 2026-10-17: Jalen Hurts ruled out, then 99% for the next week) players on
  this week's report who played their team's previous game and have no return state: the state after missing this
  week's game (missed 1, active, report status, injury, calendar), with p_now = this week's chance to play. The
  lookahead counted them fully available from next week on. ir: players already placed on injured reserve (espn_ir):
  p_now 0 (their minimum stay and ESPN's return date: ir_newly)."""
  inj = data.injuries
  inj = inj[(inj.season == season) & (inj.week == week) & (inj.game_type == "REG") & inj.gsis_id.notna()]
  inj = inj.drop_duplicates("gsis_id", keep="last").set_index("gsis_id")
  r = data.rosters
  r = r[(r.season == season) & r.gsis_id.notna()].sort_values("week").drop_duplicates("gsis_id", keep="last").set_index("gsis_id")
  rows = []
  for g, p_now in now_report.items():
    if g in known or g not in r.index or (season, week, g) in m.played:
      continue
    team = r.at[g, "team"]
    ws = m._tw.get((season, team), [])
    prev = next((w for w in reversed(ws) if w < week), None)
    # his team's bye this week (IR audit 2026-10-18: an IR placement in a bye week was skipped): the state is the one
    # after missing his next game, and that game gets p_now (lookahead_availability: "bye_start")
    gw = week if week in ws else next((w for w in ws if w > week), None)
    nxt = next((w for w in ws if gw is not None and w > gw), None)
    if gw is None or prev is None or nxt is None or (season, prev, g) not in m.played:
      continue
    status = inj.at[g, "report_status"] if g in inj.index else None
    rows.append({"season": season, "week": gw, "bye_start": gw != week, "gsis_id": g, "team": team, "missed": 1, "desig": "active",
                 "report": REPORT.get(status, 0) if isinstance(status, str) else 0,
                 "injury": inj.at[g, "report_primary_injury"] if g in inj.index else None,
                 "position": r.at[g, "position"], "next_week": nxt, "back": False, "p_now": 0.0 if g in ir else float(np.clip(p_now, 0, 1)),
                 "opened_out": 0.0, "prior_g": m.prior_g(season, g)})
  if not rows:
    return pd.DataFrame()
  return m._calendar(ReturnModel._encode(pd.DataFrame(rows)))


def _injury_code(s: pd.Series) -> pd.Series:
  m = {k: i for i, k in enumerate(INJURY_GROUPS)}
  return s.map(lambda x: next((m[k] for k in INJURY_GROUPS if isinstance(x, str) and k.lower() in x.lower()),
                              len(INJURY_GROUPS))).astype(float)


class ReturnModel:
  def __init__(self, data, played: set, opened_out: bool | None = None):
    """played: set of (season, week, gsis_id) for every player-game played (any snaps). opened_out: (AX) episodes for
    players who open the season on a reserve list, and the features that mark them (default: config
    injuries.opened_out)."""
    self.data, self.played = data, played
    if opened_out is None:
      from .config import load_config
      opened_out = load_config().get("injuries", {}).get("opened_out") is True
    self.opened_out = bool(opened_out)
    self.feats = CHAIN_FEATURES + (OPENED_FEATURES if self.opened_out else [])
    games = {}
    for s_, _, g in played:
      games[(s_, g)] = games.get((s_, g), 0) + 1
    self._games = games

  def prior_g(self, season: int, gsis_id: str) -> float:
    """Games he played the season before."""
    return float(self._games.get((season - 1, gsis_id), 0))

  # -- episodes ----------------------------------------------------------------------------------------------------
  def states(self, seasons: list[int]) -> pd.DataFrame:
    """One row per (player, week) where a previously active player is out injured: his state after that week,
    and whether he played his team's next game (the label)."""
    r = self.data.rosters
    r = r[r.season.isin(seasons) & r.gsis_id.notna()][["season", "week", "gsis_id", "team", "position", "status",
                                                        "status_description_abbr"]].drop_duplicates(
      ["season", "week", "gsis_id"], keep="last")
    inj = self.data.injuries
    inj = inj[inj.season.isin(seasons) & inj.gsis_id.notna() & (inj.game_type == "REG")]
    inj = inj.drop_duplicates(["season", "week", "gsis_id"], keep="last")
    inj = {(a, b, c): (st, body) for a, b, c, st, body in
           zip(inj.season, inj.week, inj.gsis_id, inj.report_status, inj.report_primary_injury)}
    s = self.data.schedules
    reg = s[s.season.isin(seasons) & (s.game_type == "REG")]
    team_weeks = pd.concat([reg[["season", "week", "home_team"]].rename(columns={"home_team": "team"}),
                            reg[["season", "week", "away_team"]].rename(columns={"away_team": "team"})])
    team_set = set(zip(team_weeks.season, team_weeks.team, team_weeks.week))  # (season, team, week)
    # only games already played can be missed (owner 2026-10-18: "only 1 game has been played, it's Sunday early AM"):
    # nflverse's weekly rosters list the current week from its first game on, so between Thursday and Monday night every
    # injured player got a missed game his team hadn't played yet (Hurts read as already out, Caleb Williams 4 straight)
    fin = reg[reg.home_score.notna()]
    final_set = set(zip(fin.season, fin.home_team, fin.week)) | set(zip(fin.season, fin.away_team, fin.week))
    nxt = {}  # (season, team, week) -> team's next game week
    for (season, team), g in team_weeks.groupby(["season", "team"]):
      ws = sorted(g.week)
      for a, b in zip(ws, ws[1:]):
        nxt[(season, team, a)] = b
    self._nxt = nxt
    first_wk = team_weeks.groupby(["season", "team"]).week.min().to_dict()  # each team's first game
    rows = []
    for (season, gid), g in r.sort_values("week").groupby(["season", "gsis_id"]):
      ever_played, missed, opened = False, 0, False
      for x in g.itertuples(index=False):
        if (season, x.team, x.week) not in team_set:  # bye / no game
          continue
        if (season, x.team, x.week) not in final_set:  # his team hasn't played that week yet
          continue
        played = (season, x.week, gid) in self.played
        rep_status, body = inj.get((season, x.week, gid), (None, None))
        injured = (x.status == "RES") or (isinstance(rep_status, str) and rep_status in REPORT)
        if played:
          ever_played, missed, opened = True, 0, False
          continue
        # (AX) on a reserve list at his team's first game, before playing that season: an episode from there
        if self.opened_out and not ever_played and x.status == "RES" and x.week == first_wk.get((season, x.team)):
          opened = True
        if not ((ever_played or opened) and injured):
          missed = 0 if not injured else missed
          opened = opened and injured
          continue
        missed += 1
        nw = nxt.get((season, x.team, x.week))
        if nw is None:  # season over: no label
          continue
        rows.append({"season": season, "week": x.week, "gsis_id": gid, "team": x.team, "missed": missed,
                     "desig": DESIG.get(x.status_description_abbr, "reserve_other" if x.status == "RES" else "active"),
                     "report": REPORT.get(rep_status, 0) if isinstance(rep_status, str) else 0,
                     "injury": body,
                     "position": x.position, "next_week": nw,
                     "back": (season, nw, gid) in self.played,
                     "opened_out": float(opened and not ever_played), "prior_g": self.prior_g(season, gid)})
    d = pd.DataFrame(rows)
    if not len(d):
      return d
    self._tw = {k: sorted(g.week.astype(int)) for k, g in team_weeks.groupby(["season", "team"])}
    self._gd = _gamedays(self.data)
    return self._calendar(self._encode(d))

  def _day(self, season, week, team):
    return self._gd.get((season, int(week), team), pd.NaT) if week is not None and week == week else pd.NaT

  def _calendar(self, d: pd.DataFrame) -> pd.DataFrame:
    """gap / days_out (CHAIN_FEATURES); last_played = his team's game before this run of missed games."""
    gap, out, last = [], [], []
    for x in d.itertuples():
      ws = self._tw.get((x.season, x.team), [])
      i = ws.index(int(x.week)) if int(x.week) in ws else None
      lp = ws[i - int(x.missed)] if i is not None and i - int(x.missed) >= 0 else None
      d1 = self._day(x.season, x.next_week, x.team)
      gap.append((d1 - self._day(x.season, x.week, x.team)).days if pd.notna(d1) else np.nan)
      out.append((d1 - self._day(x.season, lp, x.team)).days if lp is not None and pd.notna(d1) else np.nan)
      last.append(lp)
    return d.assign(gap=gap, days_out=out, last_played=last)

  @staticmethod
  def _encode(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    for k in ("ir", "ir_return", "pup", "reserve_other", "active"):
      d[f"desig_{k}"] = (d.desig == k).astype(float)
    d["inj_code"] = _injury_code(d.injury)
    groups = sorted(set(POS_GROUP.values()))
    d["pos_code"] = d.position.map(POS_GROUP).map({g: i for i, g in enumerate(groups)}).fillna(len(groups))
    d["missed_x_ir"] = d.missed * (d.desig_ir + d.desig_pup)
    return d

  # -- fit / predict -------------------------------------------------------------------------------------------------
  def active_after(self, season: int, gsis_id: str, team: str, week: int, h: int):
    """Did he play his team's h-th game after `week`? None if the season ended first."""
    w = week
    for _ in range(h):
      w = self._nxt.get((season, team, w))
      if w is None:
        return None
    return (season, w, gsis_id) in self.played

  def fit(self, seasons: list[int]):
    return self.fit_frame(self.states(seasons))

  def fit_frame(self, d: pd.DataFrame):
    from sklearn.ensemble import HistGradientBoostingClassifier
    self.n_train = len(d)
    # After a player returns he is not certain to stay active (re-injury, scratches): measured, not assumed.
    back = d[d.back]
    stay = [self.active_after(r.season, r.gsis_id, r.team, int(r.next_week), 1) for r in back.itertuples()]
    stay = [x for x in stay if x is not None]
    self.stay_active = float(np.mean(stay)) if stay else 1.0
    make = lambda: HistGradientBoostingClassifier(  # noqa: E731
      max_iter=200, learning_rate=0.05, max_depth=3, random_state=0,
      categorical_features=[self.feats.index("inj_code"), self.feats.index("pos_code")])
    self.model = make().fit(d[self.feats], d.back)
    # (An isotonic calibration on leave-one-season-out predictions was tested and made the walk-forward Brier
    # worse, 0.132 -> 0.136: older seasons' miscalibration doesn't carry forward. Raw model kept.)
    return self

  def hazard(self, d: pd.DataFrame) -> np.ndarray:
    return self.model.predict_proba(d[self.feats])[:, 1]

  def p_active(self, state: pd.DataFrame, horizon: int, first: np.ndarray | None = None,
               stay: float | None = None) -> np.ndarray:
    """P(active in each of the next `horizon` games), shape (len(state), horizon), for players out now. Each step
    adds one missed game; the designation stays until he returns (IR / PUP players stay designated).
    first: per-row P(plays) for the first game where this week's report knows better (NaN = the hazard). Owner-
    approved test 2026-10-15 (tools/lookahead_chain_eval.py, A): walk-forward 2022-25 Brier over his next 2-6 games
    0.228 -> 0.194, 4/4 seasons.
    stay: P(active) in each game after he's back (default: the measured stay_active, 0.89). Lookahead passes 1.0:
    owner 2026-10-15 ("once a player returns ... odds of being fully past that injury are very high"), and the
    data agrees: skill starters back from injury play their next 1-5 games at 95.9 / 88.3 / 86.8 / 85.6 / 84.6% vs
    95.2 / 89.6 / 88.2 / 86.7 / 84.9% for healthy starters in the same role (2022-25), i.e. like a healthy player,
    whom the lookahead counts at 1.0; the 0.89 left every returned player 11 points below healthy ones there."""
    stay = getattr(self, "stay_active", 1.0) if stay is None else stay
    s = state.copy()
    out = np.zeros((len(s), horizon))
    still_out = np.ones(len(s))
    for h in range(horizon):
      p = self.hazard(s)
      if h == 0 and first is not None:
        p = np.where(np.isnan(first), p, first)
      back_now = still_out * p
      # back this game, or back earlier and still active
      out[:, h] = (1 - still_out) * stay + back_now
      still_out = still_out * (1 - p)
      # he missed next_week: the state moves to it, and the calendar to his team's following game (byes, short weeks)
      nw, gap, dout = [], [], []
      for x in s.itertuples():
        ws = self._tw.get((x.season, x.team), [])
        cur = int(x.next_week)
        nxt = next((w for w in ws if w > cur), None)
        d1 = self._day(x.season, nxt, x.team) if nxt is not None else pd.NaT
        nw.append(nxt if nxt is not None else cur + 1)
        gap.append((d1 - self._day(x.season, cur, x.team)).days if pd.notna(d1) else np.nan)
        lp = x.last_played
        dout.append((d1 - self._day(x.season, lp, x.team)).days if pd.notna(d1) and lp is not None and lp == lp else np.nan)
      s["week"], s["next_week"], s["gap"], s["days_out"] = s.next_week, nw, gap, dout
      s["missed"] = s.missed + 1
      s["missed_x_ir"] = s.missed * (s.desig_ir + s.desig_pup)
      s["report"] = np.where(s.report > 0, 3, 0)  # a player still out next week is listed Out (or on IR)
    return out
