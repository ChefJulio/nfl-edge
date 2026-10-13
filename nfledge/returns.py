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


def _injury_code(s: pd.Series) -> pd.Series:
  m = {k: i for i, k in enumerate(INJURY_GROUPS)}
  return s.map(lambda x: next((m[k] for k in INJURY_GROUPS if isinstance(x, str) and k.lower() in x.lower()),
                              len(INJURY_GROUPS))).astype(float)


class ReturnModel:
  def __init__(self, data, played: set):
    """played: set of (season, week, gsis_id) for every player-game played (any snaps)."""
    self.data, self.played = data, played

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
    nxt = {}  # (season, team, week) -> team's next game week
    for (season, team), g in team_weeks.groupby(["season", "team"]):
      ws = sorted(g.week)
      for a, b in zip(ws, ws[1:]):
        nxt[(season, team, a)] = b
    self._nxt = nxt
    rows = []
    for (season, gid), g in r.sort_values("week").groupby(["season", "gsis_id"]):
      ever_played, missed = False, 0
      for x in g.itertuples(index=False):
        if (season, x.team, x.week) not in team_set:  # bye / no game
          continue
        played = (season, x.week, gid) in self.played
        rep_status, body = inj.get((season, x.week, gid), (None, None))
        injured = (x.status == "RES") or (isinstance(rep_status, str) and rep_status in REPORT)
        if played:
          ever_played, missed = True, 0
          continue
        if not (ever_played and injured):
          missed = 0 if not injured else missed
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
                     "back": (season, nw, gid) in self.played})
    d = pd.DataFrame(rows)
    return self._encode(d) if len(d) else d

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
      categorical_features=[FEATURES.index("inj_code"), FEATURES.index("pos_code")])
    self.model = make().fit(d[FEATURES], d.back)
    # (An isotonic calibration on leave-one-season-out predictions was tested and made the walk-forward Brier
    # worse, 0.132 -> 0.136: older seasons' miscalibration doesn't carry forward. Raw model kept.)
    return self

  def hazard(self, d: pd.DataFrame) -> np.ndarray:
    return self.model.predict_proba(d[FEATURES])[:, 1]

  def p_active(self, state: pd.DataFrame, horizon: int) -> np.ndarray:
    """P(active in each of the next `horizon` games), shape (len(state), horizon), for players out now. Each step
    adds one missed game; the designation stays until he returns (IR / PUP players stay designated)."""
    s = state.copy()
    out = np.zeros((len(s), horizon))
    still_out = np.ones(len(s))
    for h in range(horizon):
      p = self.hazard(s)
      back_now = still_out * p
      # back this game, or back earlier and still active (measured stay-active rate)
      out[:, h] = (1 - still_out) * getattr(self, "stay_active", 1.0) + back_now
      still_out = still_out * (1 - p)
      s["missed"] = s.missed + 1
      s["week"] = s.week + 1
      s["missed_x_ir"] = s.missed * (s.desig_ir + s.desig_pup)
      s["report"] = np.where(s.report > 0, 3, 0)  # a player still out next week is listed Out (or on IR)
    return out
