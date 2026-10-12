"""Defensive personnel adjustments: tested, and OFF by default (config team_model.cb_adjust = false).

Walk-forward tests (train on earlier seasons, test 2025 and 2026) of whether this week's defensive absences
should move a team's rating:
- Stat-weighted defender values (pressures, sacks, coverage yards/TDs, INTs, tackles from PFR) learned from
  game-level residuals: overfit, unstable signs, worse out of sample.
- Regular starters missing beyond the team's usual, pooled or by DL / LB / CB / S; offensive-line starters
  missing: no reliable out-of-sample gain.
- Cornerbacks looked promising when counting every missed snap (+2-3 pts per 100 dropbacks per missing
  starter), but that signal came from in-game events (injuries during the game, benchings) that cannot be
  known beforehand. Counting only full absences - what an injury report can predict - the effect flips sign
  between training sets and worsens out-of-sample error (2025 -0.7%, 2026 -0.6%).
Conclusion: with free data, pre-game defensive absences carry no reliable signal beyond the team rating at the
game level. Kept (switchable) so it can be re-tested as more seasons accumulate.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .team_model import asof_weights

CB_POS = {"CB"}
REGULAR_SHARE = 0.5


class Personnel:
  def __init__(self, data, cfg):
    self.data, self.cfg = data, cfg
    sn = data.snaps
    sn = sn[(sn.defense_snaps > 0) & sn.position.isin(CB_POS)].copy()
    sn["team"] = sn.team.replace({"LAR": "LA"})
    self.cb = sn[["season", "week", "game_id", "team", "pfr_player_id", "gsis_id", "player", "defense_pct"]]
    self.coef = 0.0
    self._typ: dict = {}

  # -- regular corners and how many are missing ------------------------------------------------------------------
  def regulars(self, season: int, week: int) -> pd.DataFrame:
    """Each team's regular CBs entering (season, week): recency-weighted snap share >= 50%."""
    h = self.cb[((self.cb.season == season) & (self.cb.week < week)) | (self.cb.season == season - 1)]
    w = asof_weights(h.season, h.week, season, week, self.cfg)
    h = h.assign(w=w)[w > 0]
    if h.empty:
      return pd.DataFrame(columns=["team", "pfr_player_id", "gsis_id", "player", "share"])
    last_team = h.sort_values(["season", "week"]).groupby("pfr_player_id").tail(1).set_index("pfr_player_id")
    g = h[h.team == h.pfr_player_id.map(last_team.team)]
    share = (g.defense_pct * g.w).groupby([g.team, g.pfr_player_id]).sum() / g.w.groupby(
      [g.team, g.pfr_player_id]).sum()
    reg = share[share >= REGULAR_SHARE].rename("share").reset_index()
    reg["gsis_id"] = reg.pfr_player_id.map(last_team.gsis_id)
    reg["player"] = reg.pfr_player_id.map(last_team.player)
    return reg

  def missing_history(self, seasons: list[int]) -> pd.DataFrame:
    """Per team-game: regular-CB snap share missing, and the team's own as-of typical value."""
    rows = []
    for s in sorted(set(seasons) | {min(seasons) - 1}):
      for wk in sorted(self.cb[self.cb.season == s].week.unique()):
        reg = self.regulars(s, wk)
        cur = self.cb[(self.cb.season == s) & (self.cb.week == wk)]
        for team, lu in cur.groupby("team"):
          r = reg[reg.team == team]
          # Full absences only (did not play), matching what availability can predict before the game;
          # in-game rotation and injuries are part of the typical lineup the rating already reflects.
          played = set(lu.pfr_player_id)
          miss = r.share[~r.pfr_player_id.isin(played)].sum()
          rows.append({"season": s, "week": wk, "game_id": lu.game_id.iat[0], "team": team, "miss": float(miss)})
    x = pd.DataFrame(rows).sort_values(["team", "season", "week"])
    x["typical"] = x.groupby("team").miss.transform(lambda v: v.shift(1).expanding().mean())
    x["typical"] = x.typical.fillna(x.miss.mean())
    return x

  # -- fit -------------------------------------------------------------------------------------------------------
  def fit(self, seasons: list[int], tm, team_ledger) -> "Personnel":
    """Slope of 'pass EPA allowed vs as-of rating' on extra CB share missing (weighted by dropbacks)."""
    x = self.missing_history(seasons)
    x = x[x.season.isin(seasons)]
    tl = team_ledger.set_index(["game_id", "opp"])  # defense team = opp of the offense row
    p = tm.plays["pass"]
    y, d, w = [], [], []
    for (s, wk), g in x.groupby(["season", "week"]):
      r = tm.fit(s, wk)
      pw = p[(p.season == s) & (p.week == wk)]
      means = pw.groupby(["game_id", "defteam"]).epa.agg(["mean", "size"])
      for _, row in g.iterrows():
        key = (row.game_id, row.team)
        if key not in means.index or key not in tl.index:
          continue
        off = tl.loc[key]
        off = off.iloc[0] if isinstance(off, pd.DataFrame) else off
        exp = r.expected_epa(off.team, row.team, "pass", off.home, 0, off.qb)
        y.append(means.loc[key, "mean"] - exp)
        w.append(means.loc[key, "size"])
        d.append(row.miss - row.typical)
    y, d, w = map(np.asarray, (y, d, w))
    self.pairs = (y, d, w)
    dc = d - np.average(d, weights=w)
    self.coef = float(np.sum(w * dc * (y - np.average(y, weights=w))) / np.sum(w * dc * dc))
    self.n_games = len(y)
    return self

  # -- this week -------------------------------------------------------------------------------------------------
  def week_adjustments(self, season: int, week: int, avail: pd.Series) -> pd.DataFrame:
    """Per team: expected extra regular-CB share missing (from P(active)) -> EPA/play added to the pass
    defense coefficient (positive = more passing allowed). avail: gsis_id -> P(active)."""
    reg = self.regulars(season, week)
    if reg.empty:
      return pd.DataFrame(columns=["adj_pass", "cb_out"])
    hist = self._typical(season, week)
    ros = self.data.rosters
    ros = ros[(ros.season == season) & (ros.week <= week)]
    ros = ros[ros.week == ros.groupby("team").week.transform("max")]
    on_roster = set(ros[ros.status.isin(["ACT", "INA"])].gsis_id.dropna())
    reg["p"] = reg.gsis_id.map(avail).fillna(1.0)
    reg.loc[~reg.gsis_id.isin(on_roster), "p"] = 0.0  # IR / released
    out = {}
    for team, r in reg.groupby("team"):
      exp_miss = float((r.share * (1 - r.p)).sum())
      extra = exp_miss - hist.get(team, exp_miss)
      outs = r[r.p < 0.5].player.tolist()
      out[team] = {"adj_pass": self.coef * extra, "cb_out": ", ".join(outs)}
    return pd.DataFrame(out).T

  def _typical(self, season: int, week: int) -> pd.Series:
    key = (season, week)
    if key not in self._typ:
      x = self.missing_history([season])
      x = x[((x.season == season) & (x.week < week)) | (x.season == season - 1)]
      self._typ[key] = x.groupby("team").miss.mean()
    return self._typ[key]
