"""The end-of-half drive model ((CH) in docs/INSIGHTS.md; owner 2026-10-23: "research what the end of half drives
actually look like ... it's all passes, get out of bounds, you can make a lot happen with 30 seconds ... don't use
these brainless averages"). In a half's last 3:00 a general win probability model smears the two-minute drill (both
ours and nflfastR's missed tied-inside-the-35 by 8-13 points); here the drive itself is modeled: how it ends
(touchdown / field goal good / missed / no score) and how much clock is left when it does, from every snap in that
window; win probability = each ending's chance x the win chance after it.

  rows(pbp)               - one row per scrimmage snap with <= LIMIT seconds left in a half: FEATURES + ending + left
  fit(r)                  - {"cls": multiclass model, "left": {q: quantile regressor}}
  wp(states, ...)         - win probability for states (DataFrame, the offense's side), vectorized, depth-limited
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LIMIT = 180  # seconds left in the half where the drive model speaks
ENDINGS = ["td", "fg", "fg_miss", "none"]
FEATURES = ["half_sec", "yardline_100", "down", "ydstogo", "own_to", "opp_to", "q4", "diff4"]
QS = [0.25, 0.5, 0.75]
HALF_LIFE = 3.0  # seasons: today's kickers and offenses count more
PARAMS = dict(learning_rate=0.05, max_iter=300, max_leaf_nodes=31, min_samples_leaf=100, l2_regularization=1.0,
              early_stopping=False, random_state=0)
OT_WIN = 0.5  # a tie at the end of regulation: overtime, either side


def features(df: pd.DataFrame) -> pd.DataFrame:
  x = pd.DataFrame(index=df.index)
  x["half_sec"] = df.half_sec.astype(float)
  x["yardline_100"] = df.yardline_100.astype(float)
  x["down"] = df.down.astype(float)
  x["ydstogo"] = df.ydstogo.astype(float)
  x["own_to"] = df.own_to.astype(float)
  x["opp_to"] = df.opp_to.astype(float)
  x["q4"] = df.q4.astype(float)
  x["diff4"] = np.where(df.q4 == 1, np.clip(df.score_diff.astype(float), -9, 9), 0.0)
  return x[FEATURES]


def rows(pbp: pd.DataFrame) -> pd.DataFrame:
  """Every scrimmage snap with <= LIMIT s left in the 2nd or 4th quarter, with its drive's ending and the half seconds
  left when the drive ended (the next play's clock in the same half, else 0)."""
  d = pbp[(pbp.season_type == "REG") & pbp.qtr.isin([2, 4]) & pbp.drive.notna()].sort_values(["game_id", "play_id"])
  d = d.reset_index(drop=True)
  key = ["game_id", "drive"]
  td = d[(d.touchdown == 1) & (d.td_team == d.posteam)].groupby(key).size().rename("is_td")
  fgm = d[d.field_goal_result == "made"].groupby(key).size().rename("is_fg")
  fga = d[d.field_goal_attempt == 1].groupby(key).size().rename("is_fga")
  last = d.groupby(key).play_id.max().rename("last_id").reset_index()
  # the clock when the drive ended: the next row after its last play, same game and quarter (else the half ran out)
  nxt = d[["game_id", "play_id", "qtr", "half_seconds_remaining"]].rename(columns={"play_id": "nid", "qtr": "nq", "half_seconds_remaining": "nleft"})
  last = pd.merge_asof(last.sort_values("last_id"), nxt.sort_values("nid"), left_on="last_id", right_on="nid", by="game_id",
                       direction="forward", allow_exact_matches=False)
  lq = d.groupby(key).qtr.max().rename("lq").reset_index()
  last = last.merge(lq, on=key)
  last["left"] = np.where(last.nq == last.lq, last.nleft, 0.0)
  # where the other team's next drive starts (its yards to the end zone), same quarter
  firsts = d[d.down.notna() & d.posteam.notna()].drop_duplicates(key)[key + ["posteam", "yardline_100", "qtr"]]
  firsts = firsts.rename(columns={"drive": "ndrive", "posteam": "npos", "yardline_100": "opp_yl", "qtr": "oq"})
  dpos = d.drop_duplicates(key)[key + ["posteam"]].rename(columns={"posteam": "dpos"})
  last = last.merge(dpos, on=key)
  last = last.sort_values(["game_id", "drive"])
  firsts = firsts.sort_values(["game_id", "ndrive"])
  last = pd.merge_asof(last.sort_values("drive"), firsts.sort_values("ndrive"), left_on="drive", right_on="ndrive", by="game_id",
                       direction="forward", allow_exact_matches=False)
  last["opp_yl"] = np.where((last.npos != last.dpos) & (last.oq == last.lq), last.opp_yl, np.nan)
  s = d[d.down.notna() & d.posteam.notna() & d.play_type.isin(["run", "pass", "punt", "field_goal", "qb_kneel", "qb_spike"])
        & (d.half_seconds_remaining <= LIMIT)]
  s = s.join(td, on=key).join(fgm, on=key).join(fga, on=key).merge(last[key + ["left", "opp_yl"]], on=key, how="left")
  end = np.where(s.is_td.fillna(0) > 0, "td", np.where(s.is_fg.fillna(0) > 0, "fg", np.where(s.is_fga.fillna(0) > 0, "fg_miss", "none")))
  return pd.DataFrame({
    "game_id": s.game_id.to_numpy(), "season": s.season.to_numpy(), "qtr": s.qtr.to_numpy(),
    "half_sec": s.half_seconds_remaining.to_numpy(float), "yardline_100": s.yardline_100.to_numpy(float),
    "down": s.down.to_numpy(float), "ydstogo": s.ydstogo.to_numpy(float),
    "own_to": s.posteam_timeouts_remaining.fillna(3).to_numpy(float), "opp_to": s.defteam_timeouts_remaining.fillna(3).to_numpy(float),
    "q4": (s.qtr == 4).astype(int).to_numpy(), "score_diff": s.score_differential.fillna(0).to_numpy(float),
    "ending": end, "left": np.clip(np.minimum(s.left.fillna(0).to_numpy(float), s.half_seconds_remaining.to_numpy(float)), 0, None),
    "opp_yl": s.opp_yl.to_numpy(float),
  })


YL_BANDS = [0, 20, 40, 60, 80, 100]


def spots(r: pd.DataFrame) -> dict:
  """Where the other team starts after a drive that ends without a score (by the snap's field position band) or with a
  missed field goal: its yards to the end zone, quantiles QS (rows: rows(); only drives it got the ball back from)."""
  out = {"none": [], "fg_miss": []}
  x = r[r.opp_yl.notna()]
  for lo, hi in zip(YL_BANDS[:-1], YL_BANDS[1:]):
    b = x[(x.ending == "none") & (x.yardline_100 > lo) & (x.yardline_100 <= hi)]
    out["none"].append([float(v) for v in np.quantile(b.opp_yl, QS)] if len(b) >= 30 else None)
  m = x[x.ending == "fg_miss"]
  out["fg_miss"] = [float(v) for v in np.quantile(m.opp_yl, QS)]
  return out


def _w(r: pd.DataFrame) -> np.ndarray:
  return (0.5 ** ((r.season.max() - r.season) / HALF_LIFE)).to_numpy(float)


def fit(r: pd.DataFrame) -> dict:
  from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
  X, w = features(r), _w(r)
  cls = HistGradientBoostingClassifier(**PARAMS).fit(X, pd.Categorical(r.ending, categories=ENDINGS).codes, sample_weight=w)
  # seconds left at the end, given the ending (one-hot): quantile regressions
  Xl = _left_X(X, r.ending)
  left = {q: HistGradientBoostingRegressor(loss="quantile", quantile=q, **PARAMS).fit(Xl, r.left, sample_weight=w) for q in QS}
  return {"cls": cls, "left": left}


def _left_X(X: pd.DataFrame, ending) -> pd.DataFrame:
  Xl = X.copy()
  e = np.asarray(ending)
  for k in ENDINGS:
    Xl[f"end_{k}"] = (e == k).astype(float)
  return Xl


def probs(m: dict, states: pd.DataFrame) -> np.ndarray:
  """P(ending) per state, columns in ENDINGS order."""
  p = np.zeros((len(states), len(ENDINGS)))
  pr = m["cls"].predict_proba(features(states))
  for j, c in enumerate(m["cls"].classes_):
    p[:, int(c)] = pr[:, j]
  return p


def lefts(m: dict, states: pd.DataFrame, ending: str) -> np.ndarray:
  """Seconds left in the half when the drive ends this way: (n, len(QS)), never more than the time there was."""
  Xl = _left_X(features(states), [ending] * len(states))
  out = np.column_stack([m["left"][q].predict(Xl) for q in QS])
  return np.clip(np.sort(out, axis=1), 0, states.half_sec.to_numpy(float)[:, None])


class Composer:
  """Win probability in a half's last LIMIT seconds from the drive model; elsewhere (and past `depth` possessions)
  the general model (nfledge/winprob.py). States: DataFrame from the offense's side with score_diff, game_sec,
  half_sec, down, ydstogo, yardline_100, own_to, opp_to, exp_margin, home, receive_2h."""

  def __init__(self, m: dict, gen, spots_: dict, kick_spots: list, xp: float):
    self.m, self.gen, self.sp, self.kick, self.xp = m, gen, spots_, kick_spots, xp

  def general(self, S: pd.DataFrame) -> np.ndarray:
    from . import winprob as W
    if not len(S):
      return np.zeros(0)
    return self.gen.predict_proba(W.features(S))[:, 1]

  @staticmethod
  def _theirs(S: pd.DataFrame, diff, sec_half, yl) -> pd.DataFrame:
    """The other team's 1st & 10 at `yl` (its yards to go), `sec_half` left in the same half."""
    first = (S.game_sec > 1800).to_numpy()
    o = pd.DataFrame({
      "score_diff": -np.asarray(diff, float), "half_sec": np.asarray(sec_half, float),
      "game_sec": np.asarray(sec_half, float) + np.where(first, 1800, 0), "down": 1.0,
      "ydstogo": np.minimum(10.0, np.asarray(yl, float)), "yardline_100": np.asarray(yl, float),
      "own_to": S.opp_to.to_numpy(float), "opp_to": S.own_to.to_numpy(float), "exp_margin": -S.exp_margin.to_numpy(float),
      "home": 1 - S.home.to_numpy(float), "receive_2h": 1 - S.receive_2h.to_numpy(float)})
    return o

  def _halftime(self, S: pd.DataFrame, diff) -> np.ndarray:
    """The 2nd quarter ran out: the general model at the second-half kickoff (whoever receives it)."""
    rec = S.receive_2h.to_numpy(float) == 1
    yl = self.kick[1]
    us = pd.DataFrame({"score_diff": np.asarray(diff, float), "half_sec": 1800.0, "game_sec": 1800.0, "down": 1.0, "ydstogo": 10.0,
                       "yardline_100": yl, "own_to": 3.0, "opp_to": 3.0, "exp_margin": S.exp_margin.to_numpy(float),
                       "home": S.home.to_numpy(float), "receive_2h": 0.0})
    them = us.assign(score_diff=-us.score_diff, exp_margin=-us.exp_margin, home=1 - us.home)
    return np.where(rec, self.general(us), 1 - self.general(them))

  def wp(self, S: pd.DataFrame, depth: int = 2) -> np.ndarray:
    S = S.reset_index(drop=True)
    out = np.zeros(len(S))
    use = (S.half_sec.to_numpy(float) <= LIMIT) & S.down.notna().to_numpy() & (S.down.to_numpy(float) >= 1) & (depth > 0)
    if (~use).any():
      out[~use] = self.general(S[~use])
    if not use.any():
      return out
    E = S[use].reset_index(drop=True)
    E = E.assign(q4=(E.game_sec <= 1800).astype(int))
    P = probs(self.m, E)
    q4 = E.q4.to_numpy() == 1
    val = np.zeros(len(E))
    yl = E.yardline_100.to_numpy(float)
    band = np.clip(np.searchsorted(YL_BANDS, yl, side="left") - 1, 0, len(YL_BANDS) - 2)
    for j, ending in enumerate(ENDINGS):
      L = lefts(self.m, E, ending)  # (n, 3)
      branches = [(7, self.xp), (6, 1 - self.xp)] if ending == "td" else [(3, 1.0)] if ending == "fg" else [(0, 1.0)]
      acc = np.zeros(len(E))
      for pts, wgt in branches:
        diff = E.score_diff.to_numpy(float) + pts
        for k in range(L.shape[1]):
          t = L[:, k]
          v = np.zeros(len(E))
          done = t <= 5
          # time ran out: the 4th quarter's final score (a tie: overtime), or halftime
          if done.any():
            dd = diff[done]
            fin = np.where(dd > 0, 1.0, np.where(dd < 0, 0.0, OT_WIN))
            v[done] = np.where(q4[done], fin, self._halftime(E[done], dd))
          live = ~done
          if live.any():
            idx = np.where(live)[0]
            if ending in ("td", "fg"):
              spots_ = [self.kick] * len(idx)
              left = t[idx] - 5  # the kickoff
            elif ending == "fg_miss":
              spots_ = [self.sp["fg_miss"]] * len(idx)
              left = t[idx]
            else:
              spots_ = [self.sp["none"][b] or self.sp["fg_miss"] for b in band[idx]]
              left = t[idx]
            vals = np.zeros(len(idx))
            for c in range(3):
              ylo = np.array([s_[c] for s_ in spots_], float)
              O = self._theirs(E.iloc[idx].reset_index(drop=True), diff[idx], np.maximum(left, 1), ylo)
              vals += 1 - self.wp(O, depth - 1)
            v[idx] = vals / 3
          acc += wgt * v / L.shape[1]
      val += P[:, j] * acc
    out[use] = val
    return out
