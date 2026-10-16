"""Power rank C: rest-of-season strength, injury-aware (owner 2026-10-16; INSIGHTS (M), tools/power_c.py).

A team's C rating at week w = the mean over its remaining regular-season games of
  P(usual starting QB back for that game) x rating with him + (1 - P) x rating with his backup.
Ratings are linear in the QB, so the mean equals pbar x units with the usual starter + (1 - pbar) x units with the
backup, pbar = his average chance over the remaining games: every unit blends the same way and Offense + Defense + ST
still add up to Net. Gate passed 2021-25: rank correlation with rest-of-season point differential 0.445 vs 0.436 for
this week's lineup (season-weeks with a starter out: +0.010 [+0.002, +0.019]); better 4 of 5 seasons.

  usual    most starts this season before w (tie: the incumbent)
  backup   this week's starter if not the usual one, else the depth chart's QB2
  P        the return-timing chain (nfledge/returns.py) fit only on outcomes known before w; this week's game uses
           this week's chance to play when one is given (now)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HORIZON = 18


def _states(eng):
  """Return-model states for every loaded season, built once per engine."""
  from .returns import ReturnModel, played_set
  c = eng.__dict__.setdefault("_powerc", {})
  if "m" not in c:
    c["m"] = ReturnModel(eng.data, played_set(eng.data))
    c["st"] = c["m"].states(sorted(eng.data.seasons))
  return c["m"], c["st"]


def usual_starters(eng, season: int, week: int) -> dict:
  """team -> the QB with the most starts this season before `week` (tie: the one who started first)."""
  tl = eng.team_ledger
  cur = tl[(tl.season == season) & (tl.week < week) & tl.qb.notna()].sort_values("week")
  out = {}
  for t, g in cur.groupby("team"):
    seq = list(g.qb)
    cnt = pd.Series(seq).value_counts()
    out[t] = min(cnt[cnt == cnt.max()].index, key=seq.index)
  return out


def inputs(eng, season: int, week: int, recent: dict, now: dict | None = None, by_week: dict | None = None) -> tuple[dict, dict, dict]:
  """(usual, backup, pbar): team -> usual starter, backup, and the usual starter's mean chance to play over the
  team's remaining games from `week` on. recent: team -> this week's (or most recent) starter. now: gsis -> this
  week's chance to play (replaces the chain's first step). by_week: if a dict is given, it is filled with team ->
  {week: P(usual starter plays)} for every remaining game (the playoff odds use them game by game)."""
  from . import data as D
  d = eng.data
  usual = usual_starters(eng, season, week)
  m, st = _states(eng)
  known = (st.season < season) | ((st.season == season) & (st.next_week < week))
  m.fit_frame(st[known])
  cur = st[(st.season == season) & (st.week < week)].sort_values("week").groupby("gsis_id").tail(1)
  cur = cur[np.array([not any((season, x, g) in m.played for x in range(int(wk) + 1, week))
                      for g, wk in zip(cur.gsis_id, cur.week)], dtype=bool)]
  cur = cur[cur.next_week >= week]
  cur = cur[cur.gsis_id.isin(set(usual.values()))]
  now = now or {}
  first = np.array([float(now[g]) if g in now else np.nan for g in cur.gsis_id])
  pa = m.p_active(cur, HORIZON, first=first, stay=1.0) if len(cur) else np.zeros((0, HORIZON))
  row = {g: (i, int(wk)) for i, (g, wk) in enumerate(zip(cur.gsis_id, cur.week))}
  sch = d.schedules[(d.schedules.season == season) & (d.schedules.game_type == "REG")]
  weeks = {}
  for g in sch.itertuples():
    for t in (g.home_team, g.away_team):
      weeks.setdefault(D.RELOCATED.get(t, t), []).append(int(g.week))
  dc = D.depth_for_week(d, season, week)
  q2 = dc[(dc.pos == "QB") & (dc["rank"] == 2)]
  qb2 = {D.RELOCATED.get(t, t): g for t, g in zip(q2.team, q2.gsis_id)}
  backup, pbar = {}, {}
  for t, q in usual.items():
    backup[t] = recent.get(t) if recent.get(t) not in (None, q) else qb2.get(t)
    rem = sorted(x for x in weeks.get(t, []) if x >= week)
    if not rem:
      continue
    if q in row:
      i, last = row[q]
      ks = [sum(1 for x in weeks[t] if last < x <= r) for r in rem]
      ps = [float(pa[i, min(max(k, 1), HORIZON) - 1]) for k in ks]
    elif q in now:  # on this week's report but not out as of last game: this week's chance, then healthy
      ps = [float(now[q])] + [1.0] * (len(rem) - 1)
    else:
      ps = [1.0] * len(rem)
    pbar[t] = float(np.mean(ps))
    if by_week is not None:
      by_week[t] = dict(zip(rem, ps))
  return usual, backup, pbar


def blend(u_usual: pd.DataFrame, u_backup: pd.DataFrame, pbar: dict) -> pd.DataFrame:
  """Unit ratings (report.unit_points frames) blended per team by pbar (teams without one: the usual-starter row)."""
  p = pd.Series({t: pbar.get(t, 1.0) for t in u_usual.index})
  return u_usual.mul(p, axis=0) + u_backup.reindex(u_usual.index).fillna(u_usual).mul(1 - p, axis=0)
