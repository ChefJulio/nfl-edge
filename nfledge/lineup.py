"""Lineup value: who is missing (or back) beyond the QB, valued by on-field play (INSIGHTS (BO), (BP), (BP2)).

The team ratings learn from recent games (recency half-life ~3 games). For each team-game and each non-QB player
who has played for this team in its previous 8 games (weights 0.5^(games ago / 3)):
  recent = weighted mean snap share (0 in games he missed), role = weighted mean share in the games he played;
  kept if role >= 0.3; delta = (role if available else 0) - recent.
A new absence costs his role, a return adds back what the ratings missed, a player gone for weeks counts ~0 (the
ratings already learned without him). Each delta is weighted by the player's on-field value (EPA per play with him
on the field, ridge plus-minus over 2016-25 plays: tools/rapm_build.py -> data/history/rapm_values.parquet; players
without one get their position group's value at zero plays) and summed over offense (no QB: the win formula has
him) and defense. Shared by the backtest (tools/lineup_build.py) and the live Matchups win chance.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

VALUES = Path(__file__).resolve().parent.parent / "data" / "history" / "rapm_values.parquet"
GROUP = {"QB": "QB", "T": "OL", "G": "OL", "C": "OL", "OL": "OL", "OT": "OL", "OG": "OL", "WR": "WR", "TE": "TE",
         "RB": "RB", "HB": "RB", "FB": "RB", "DE": "DL", "DT": "DL", "NT": "DL", "DL": "DL",
         "LB": "LB", "ILB": "LB", "OLB": "LB", "MLB": "LB", "CB": "CB", "S": "S", "FS": "S", "SS": "S", "DB": "S"}
OFF, DEF = ["OL", "WR", "TE", "RB"], ["DL", "LB", "CB", "S"]
N_BACK, HALF, MIN_ROLE = 8, 3.0, 0.3


def shares(snaps: pd.DataFrame) -> pd.DataFrame:
  """Regular-season snap rows with a gsis id, each with its position group and the share for its side."""
  sn = snaps[(snaps.game_type == "REG") & snaps.position.isin(GROUP)].dropna(subset=["gsis_id"]).copy()
  sn["grp"] = sn.position.map(GROUP)
  sn["share"] = np.where(sn.grp.isin(OFF + ["QB"]), sn.offense_pct.fillna(0), sn.defense_pct.fillna(0))
  return sn[["season", "week", "game_id", "team", "gsis_id", "grp", "share"]]


class Lineups:
  """Each team's regulars going into a game, from the snap shares of its previous games."""

  def __init__(self, sh: pd.DataFrame):
    self.by_team = {}
    for team, g in sh.groupby("team"):
      games = g[["season", "week", "game_id"]].drop_duplicates().sort_values(["season", "week"]).reset_index(drop=True)
      per = {gid: (dict(zip(x.gsis_id, x.share)), dict(zip(x.gsis_id, x.grp))) for gid, x in g.groupby("game_id")}
      self.by_team[team] = (games, per)
    # (BR) each player's own games (any team), for arrivals: [(season, week, team, share, grp)] in order
    self.by_player = {}
    for p, g in sh[sh.share > 0].sort_values(["season", "week"]).groupby("gsis_id"):
      self.by_player[p] = list(zip(g.season, g.week, g.team, g.share, g.grp))

  def regulars(self, team: str, season: int, week: int) -> list[tuple[str, str, float, float]]:
    """[(gsis_id, group, role, recent)] for the team's game in (season, week), from games strictly before it."""
    if team not in self.by_team:
      return []
    games, per = self.by_team[team]
    before = games[(games.season < season) | ((games.season == season) & (games.week < week))].tail(N_BACK)
    if not len(before):
      return []
    gids = list(before.game_id)
    wts = 0.5 ** (np.arange(len(gids) - 1, -1, -1) / HALF)
    ppl = {}
    for gid in gids:
      for p in per[gid][0]:
        ppl.setdefault(p, None)
    out = []
    for p in ppl:
      sh = np.array([per[gid][0].get(p, 0.0) for gid in gids])
      on = np.array([per[gid][0].get(p, 0.0) > 0 for gid in gids])
      recent = float((wts * sh).sum() / wts.sum())
      role = float((wts * sh * on).sum() / (wts * on).sum()) if on.any() else 0.0
      if role < MIN_ROLE:
        continue
      last = gids[int(np.where(on)[0][-1])]
      out.append((p, per[last][1][p], role, recent))
    return out


  def arrivals(self, team: str, season: int, week: int, roster: set, regulars: set) -> list[tuple[str, str, float, float]]:
    """(BR) players on the team's roster this week who aren't its regulars but were regulars elsewhere (role >= 0.3 in
    their own last 8 games, the latest of them for another team): [(gsis_id, group, role, recent=0)]; the team's
    ratings never saw them, so an available arrival adds his whole role."""
    out = []
    for p in roster - regulars:
      h = [x for x in self.by_player.get(p, []) if (x[0], x[1]) < (season, week)][-N_BACK:]
      if not h or h[-1][2] == team:
        continue
      sh = np.array([x[3] for x in h])
      wts = 0.5 ** (np.arange(len(h) - 1, -1, -1) / HALF)
      role = float((wts * sh).sum() / wts.sum())
      if role >= MIN_ROLE:
        out.append((p, h[-1][4], role, 0.0))
    return out


def roster_ids(rosters: pd.DataFrame, season: int, week: int, team: str) -> set:
  """The team's players that week who could play: active or game-day inactive."""
  ro = rosters[(rosters.season == season) & (rosters.week == week) & (rosters.team == team) & rosters.status.isin(["ACT", "INA"])]
  return set(ro.gsis_id.dropna())


class Values:
  """On-field value per (season, player, side), EPA per play, + = good; group prior for players without one."""

  def __init__(self, path: Path = VALUES):
    v = pd.read_parquet(path)
    pri = v.gsis_id.str.startswith("__prior_")
    self.v = {(t, g, s): x for t, g, s, x in zip(v.target[~pri], v.gsis_id[~pri], v.side[~pri], v.value[~pri])}
    self.prior = {(t, s, g[len("__prior_"):]): x for t, g, s, x in zip(v.target[pri], v.gsis_id[pri], v.side[pri], v.value[pri])}
    self.latest = int(v.target.max())

  def __call__(self, season: int, gsis_id: str, grp: str) -> float:
    t = min(season, self.latest)
    side = "def" if grp in DEF else "off"
    return self.v.get((t, gsis_id, side), self.prior.get((t, side, grp), 0.0))


def team_term(regs: list, available, value) -> dict:
  """Sums of delta x value over offense (no QB) and defense, plus the per-player parts (largest first).
  available(gsis_id) -> bool; value(gsis_id, grp) -> EPA per play."""
  off = dfn = 0.0
  parts = []
  for p, grp, role, recent in regs:
    if grp == "QB":
      continue
    d = (role if available(p) else 0.0) - recent
    if abs(d) < 1e-9:
      continue
    c = d * value(p, grp)
    if grp in DEF:
      dfn += c
    else:
      off += c
    parts.append((p, grp, d, c))
  parts.sort(key=lambda x: -abs(x[3]))
  return {"off": off, "def": dfn, "parts": parts}


def report_available(rosters: pd.DataFrame, injuries: pd.DataFrame, season: int, week: int, team: str):
  """(BP) availability as of the injury report: on the team's roster that week (active or game-day inactive) and not
  Out / Doubtful on its report for the week. Before the team's report for the week is out (it comes Wednesday to
  Friday), its latest earlier report this season stands in, so a player out last week isn't counted as back on
  Tuesday (the backtest only ever saw final reports). Before the week's roster exists, the roster check is skipped."""
  ro = rosters[(rosters.season == season) & (rosters.week == week) & (rosters.team == team)]
  st = dict(zip(ro.gsis_id, ro.status))
  rep = injuries[(injuries.season == season) & (injuries.team == team) & (injuries.week <= week)]
  if len(rep):
    rep = rep[rep.week == rep.week.max()]
  out = set(rep[rep.report_status.isin(["Out", "Doubtful"])].gsis_id)
  if not st:
    return lambda p: p not in out
  return lambda p: st.get(p) in ("ACT", "INA") and p not in out


SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"}


def last_name(full: str) -> str:
  """'Michael Pittman Jr.' -> 'Pittman'."""
  w = [x for x in str(full).split() if x.lower() not in SUFFIXES]
  return w[-1] if w else str(full)
