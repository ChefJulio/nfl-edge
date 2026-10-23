"""The 4th quarter as possessions ((CL) in docs/INSIGHTS.md; owner 2026-10-23: "if it's 19-20 and then they score a
touchdown/xp the score is then 27-19, that's a one score game with a td and 2 pt conversion ... the time left matters a
lot"). The general win probability model prices points smoothly at any clock, so key numbers (a field goal beats a 1-
or 2-point lead; 8 is one score, 9 two) can't come from it. Here a score margin is valued by playing out the
possessions left, alternating: each ends in a touchdown, a field goal or nothing, and the final score decides.

  fit(pbp)                 - the measured pieces (JSON-ready): the current drive's outcome rates by field position /
                             down / distance, later drives' rates, how many possessions remain by clock and lead
  wp(m, states)            - the win chance of 4th-quarter states (DataFrame, the side of the team with the ball)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

YL = [0, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]   # field position bands (yards to the end zone)
TOGO = [0, 3, 6, 10, 99]                                # distance buckets: 1-3, 4-6, 7-10, 11+
SEC_BIN = 30                                            # possessions-left table: 30-second bins of the 4th quarter
K_MAX = 10
SHRINK = 50                                             # a thin cell leans on its field position band by this many drives
DRIVE_FROM = 2012
OT_WIN = 0.5


def _band(v, edges) -> np.ndarray:
  return np.clip(np.searchsorted(edges, np.asarray(v, float), side="left") - 1, 0, len(edges) - 2)


def _drive_rows(d: pd.DataFrame) -> pd.DataFrame:
  """Every regulation scrimmage snap (2012 on) with its drive's ending: td / fg / none (from the offense's side)."""
  x = d[(d.season_type == "REG") & (d.qtr <= 4) & d.drive.notna() & (d.season >= DRIVE_FROM)]
  key = ["game_id", "drive"]
  td = x[(x.touchdown == 1) & (x.td_team == x.posteam)].groupby(key).size().rename("is_td")
  fg = x[x.field_goal_result == "made"].groupby(key).size().rename("is_fg")
  s = x[x.down.notna() & x.posteam.notna() & x.play_type.isin(["run", "pass", "punt", "field_goal", "qb_kneel", "qb_spike"])]
  s = s.join(td, on=key).join(fg, on=key)
  end = np.where(s.is_td.fillna(0) > 0, "td", np.where(s.is_fg.fillna(0) > 0, "fg", "none"))
  return pd.DataFrame({"game_id": s.game_id.to_numpy(), "drive": s.drive.to_numpy(), "play_id": s.play_id.to_numpy(),
                       "qtr": s.qtr.to_numpy(), "sec": s.game_seconds_remaining.to_numpy(float), "yl": s.yardline_100.to_numpy(float),
                       "down": s.down.to_numpy(float), "togo": s.ydstogo.to_numpy(float), "diff": s.score_differential.fillna(0).to_numpy(float),
                       "posteam": s.posteam.to_numpy(), "end": end})


def fit(d: pd.DataFrame) -> dict:
  r = _drive_rows(d)
  r["yb"], r["tb"] = _band(r.yl, YL), _band(r.togo, TOGO)
  r["td"], r["fg"] = (r.end == "td").astype(float), (r.end == "fg").astype(float)
  # (a) the current drive: by field position band x down x distance, shrunk toward the band
  band = r.groupby("yb")[["td", "fg"]].mean()
  cur = {}
  for (yb, dn, tb), g in r.groupby(["yb", "down", "tb"]):
    n, b = len(g), band.loc[yb]
    cur[f"{int(yb)}:{int(dn)}:{int(tb)}"] = [round(float((g.td.sum() + SHRINK * b.td) / (n + SHRINK)), 4),
                                             round(float((g.fg.sum() + SHRINK * b.fg) / (n + SHRINK)), 4)]
  band_rates = {int(k): [round(float(v.td), 4), round(float(v.fg), 4)] for k, v in band.iterrows()}
  # (b) a later drive: drives' first snaps that follow a kickoff or punt (their usual starting spots), 4th quarter
  firsts = r.sort_values(["game_id", "play_id"]).drop_duplicates(["game_id", "drive"])
  later = firsts[firsts.yl.between(55, 85)]
  per_drive = [round(float(later.td.mean()), 4), round(float(later.fg.mean()), 4)]
  # (c) possessions left after the current one, 4th quarter: drives that start later in regulation
  q4 = r[r.qtr == 4]
  dr = q4.groupby(["game_id", "drive"]).sec.max().reset_index().sort_values(["game_id", "drive"])
  dr["left"] = dr.groupby("game_id").cumcount(ascending=False)  # drives after this one in the 4th quarter
  q4 = q4.merge(dr[["game_id", "drive", "left"]], on=["game_id", "drive"])
  q4["sb"] = np.minimum((q4.sec // SEC_BIN).astype(int), 900 // SEC_BIN - 1)
  q4["lead"] = np.sign(q4["diff"]).astype(int)
  ktab = {}
  for (sb, ld), g in q4.groupby(["sb", "lead"]):
    k = np.clip(g.left.to_numpy(int), 0, K_MAX)
    ktab[f"{int(sb)}:{int(ld)}"] = [round(float(v), 4) for v in np.bincount(k, minlength=K_MAX + 1) / len(k)]
  return {"cur": cur, "band": band_rates, "later": per_drive, "k": ktab, "sec_bin": SEC_BIN, "k_max": K_MAX,
          "yl": YL, "togo": TOGO, "team_total": 22.5, "n_drives": int(r.drop_duplicates(["game_id", "drive"]).shape[0])}


def _scale(rates, team_total, mean_total):
  s = np.clip(team_total / mean_total, 0.6, 1.5)
  td, fg = rates[0] * s, rates[1] * s
  tot = td + fg
  if tot > 0.95:
    td, fg = td * 0.95 / tot, fg * 0.95 / tot
  return td, fg


def wp_one(m: dict, diff: float, sec: float, yl: float, down: int, togo: float, line: float, total: float, xp: float,
           two: float = 0.476) -> float:
  """One 4th-quarter state from the side of the team with the ball (line: its Vegas expected margin, total: over/under)."""
  key = f"{_band(yl, m['yl'])[()]}:{int(down)}:{_band(togo, m['togo'])[()]}"
  cur = m["cur"].get(key) or m["band"][int(_band(yl, m["yl"])[()])]
  tt_us, tt_them = (total + line) / 2, (total - line) / 2
  c_td, c_fg = _scale(cur, tt_us, m["team_total"])
  u_td, u_fg = _scale(m["later"], tt_us, m["team_total"])
  t_td, t_fg = _scale(m["later"], tt_them, m["team_total"])
  sb = min(int(sec // m["sec_bin"]), 900 // m["sec_bin"] - 1)
  kp = np.asarray(m["k"].get(f"{sb}:{int(np.sign(diff))}") or m["k"].get(f"{sb}:0"))
  # f[k][d]: win chance with k possessions left, the other team next; d = our margin, indexes -80..80
  D = np.arange(-80, 81)
  term = np.where(D > 0, 1.0, np.where(D < 0, 0.0, OT_WIN))

  def shift(v, s):  # v indexed by margin D; returns v at margin D + s (edges held)
    out = np.empty_like(v)
    if s >= 0:
      out[:len(v) - s] = v[s:]; out[len(v) - s:] = v[-1]
    else:
      out[-s:] = v[:s]; out[:-s] = v[0]
    return out

  def td_val(v, sign):
    """After a touchdown the scorer takes the better try (owner: down 8 is "one score with a td and 2 pt
    conversion"): the extra point or two, at the measured rates; sign +1 us (maximize), -1 them (minimize ours)."""
    kick = xp * shift(v, sign * 7) + (1 - xp) * shift(v, sign * 6)
    go2 = two * shift(v, sign * 8) + (1 - two) * shift(v, sign * 6)
    return np.maximum(kick, go2) if sign > 0 else np.minimum(kick, go2)

  def step(v, td, fg, sign):  # one possession by a team whose points move our margin by sign * pts
    return td * td_val(v, sign) + fg * shift(v, sign * 3) + (1 - td - fg) * v

  # f_them[k]: k possessions left, the other team has the next one
  f_them = [term]
  f_us = [term]
  for k in range(1, len(kp)):
    f_them.append(step(f_us[k - 1], t_td, t_fg, -1))
    f_us.append(step(f_them[k - 1], u_td, u_fg, +1))
  after = sum(kp[k] * f_them[k] for k in range(len(kp)))  # after the current drive, the other team is next
  i0 = min(max(int(diff) + 80, 0), len(D) - 1)
  return float(c_td * td_val(after, +1)[i0] + c_fg * shift(after, 3)[i0] + (1 - c_td - c_fg) * after[i0])


def wp(m: dict, S: pd.DataFrame, xp: float, two: float = 0.476) -> np.ndarray:
  """States: diff, sec (game seconds left, <= 900), yl, down, togo, line, total."""
  return np.array([wp_one(m, r.diff, r.sec, r.yl, r.down, r.togo, r.line, r.total, xp, two) for r in S.itertuples()])
