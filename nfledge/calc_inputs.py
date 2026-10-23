"""The decision calculator's inputs ((CG) in docs/INSIGHTS.md): what each choice's outcomes are and how likely, measured
from nflverse play-by-play (cache/pbp_calc_<season>, nfledge/winprob.PBP_COLS). The win probability of each outcome
comes from nfledge/winprob.py; static/calc_engine.js weighs them.

  conversion(d)   - P(a 4th-down run or pass gains the distance): logistic on log(yards to go), field position, goal to
                    go (the last CONV_SEASONS seasons)
  gains(d)        - yards gained given success / failure, as quantiles by distance bucket
  fg(d)           - P(field goal good) by kick distance, 18-70 yards (isotonic, the last FG_SEASONS seasons); kick
                    distance = field position + 18
  punts(d)        - the receiving team's field position after a punt, as quantiles by the punt's field position
                    (2021 on; blocks and return touchdowns left out, as nfl4th does)
  kickoff(d)      - the receiving team's start after a normal kickoff (the latest season: the 2025 kickoff rules)
  onside(d)       - recovery rate (2024 on, shrunk toward 2018-23) and where each side gets the ball
  tries(d)        - extra point and two-point success rates (2021 on)
  clock(d)        - seconds a running clock takes between snaps beyond the play itself (what a timeout saves), and a
                    play's own length
Every fitter takes the play-by-play and returns plain numbers / lists (JSON-ready).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

QS = [0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95]  # outcome quantiles: 10 equally likely outcomes
DIST_BUCKETS = [(1, 1), (2, 2), (3, 3), (4, 5), (6, 10), (11, 99)]
# (CG, owner's call 2026-10-23, "up to you"): fourth-down conversion and long field goals have climbed (2024-25: 50-59
# yd made 71% vs 62% from a 2018-23 fit; 4th & 4-5 converted 55% vs 42%), so both come from recent seasons only: field
# goals the last 2 (2022-23 predicted 2024-25 within 1.3 points in every 10-yard band), fourth downs the last 3
# seasons' fourth-down tries. A flat window and a 1-season half-life both failed the pre-registered check. The page
# shows both rates and lets you change them (your kicker, your offense).
FG_SEASONS, CONV_SEASONS = 2, 3
FG_OFFSET = 18  # kick distance = yards to the end zone + 18 (snap 7-8 + the end zone's 10; median 2018-25)


def _reg(d: pd.DataFrame) -> pd.DataFrame:
  return d[(d.season_type == "REG") & (d.qtr <= 4)]


def _snaps34(d: pd.DataFrame) -> pd.DataFrame:
  x = _reg(d)
  return x[x.down.isin([3, 4]) & x.play_type.isin(["run", "pass"]) & (x.qb_kneel != 1) & (x.qb_spike != 1)
           & x.ydstogo.notna() & x.yardline_100.notna() & x.yards_gained.notna()]


def _conv_y(x: pd.DataFrame) -> np.ndarray:
  return ((x.yards_gained >= x.ydstogo) | (x.touchdown == 1)).astype(float).to_numpy() * (x.fumble_lost != 1) * (x.interception != 1)


def _conv_X(ydstogo, yardline_100, down=None) -> np.ndarray:
  y = np.asarray(ydstogo, float)
  yl = np.asarray(yardline_100, float)
  return np.column_stack([np.log(y), yl / 100, (y >= yl).astype(float)])


def conversion(d: pd.DataFrame) -> dict:
  from sklearn.linear_model import LogisticRegression
  last = int(d.season.max())
  x = _snaps34(d[d.season > last - CONV_SEASONS])
  x = x[x.down == 4]
  m = LogisticRegression(C=10.0, max_iter=2000).fit(_conv_X(x.ydstogo, x.yardline_100), _conv_y(x))
  return {"coef": [float(c) for c in m.coef_[0]], "intercept": float(m.intercept_[0]),
          "terms": ["log ydstogo", "yardline_100 / 100", "goal to go"], "seasons": [last - CONV_SEASONS + 1, last], "n": int(len(x))}


def conv_prob(c: dict, ydstogo, yardline_100, down=4) -> np.ndarray:
  z = c["intercept"] + _conv_X(np.atleast_1d(ydstogo), np.atleast_1d(yardline_100)) @ np.array(c["coef"])
  return 1 / (1 + np.exp(-z))


def gains(d: pd.DataFrame) -> dict:
  """Yards gained: on success (at least the distance; capped at the end zone by the engine) and on failure, ten
  equally likely values per distance bucket (2014 on)."""
  x = _snaps34(d[d.season >= 2014])
  ok = _conv_y(x) == 1
  out = []
  for lo, hi in DIST_BUCKETS:
    b = (x.ydstogo >= lo) & (x.ydstogo <= hi)
    s, f = x[b & ok], x[b & ~ok & (x.fumble_lost != 1) & (x.interception != 1)]
    out.append({"lo": lo, "hi": hi, "succ_over": [float(v) for v in np.quantile(s.yards_gained - s.ydstogo, QS)],
                "fail": [float(v) for v in np.quantile(f.yards_gained, QS)], "n": int(b.sum())})
  return {"buckets": out}


def fg(d: pd.DataFrame) -> dict:
  """Make rate by kick distance, 18-70 yards: isotonic (never easier from farther) on the last FG_SEASONS seasons. A
  logistic curve's shape was off for today's kickers (2022-23 fit: 40-49 yd 2.6 points high, 50-59 yd 5.4 low on
  2024-25) where the plain recent rates were within 1.3 points."""
  from sklearn.isotonic import IsotonicRegression
  last = int(d.season.max())
  # three seasons before them at a quarter weight: the long tail (60+ yd) has ~20 tries in two seasons
  x = _reg(d[d.season > last - FG_SEASONS - 3])
  x = x[(x.field_goal_attempt == 1) & x.kick_distance.notna()]
  w = np.where(x.season > last - FG_SEASONS, 1.0, 0.25)
  iso = IsotonicRegression(increasing=False, y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(
    x.kick_distance.to_numpy(float), (x.field_goal_result == "made").astype(float).to_numpy(), sample_weight=w)
  dist = np.arange(18, 71)
  return {"from": 18, "rate": [round(float(v), 4) for v in iso.predict(dist)], "offset": FG_OFFSET,
          "seasons": [last - FG_SEASONS + 1, last], "n": int(len(x))}


def fg_prob(c: dict, dist) -> np.ndarray:
  dist = np.clip(np.round(np.atleast_1d(np.asarray(dist, float))).astype(int), c["from"], c["from"] + len(c["rate"]) - 1)
  return np.asarray(c["rate"])[dist - c["from"]]


def punts(d: pd.DataFrame) -> dict:
  """The receiving team's yards to the end zone after the punt (return included, touchback = 80), ten equally likely
  values for each 5-yard band of the punt's field position (2021 on)."""
  x = _reg(d[d.season >= 2021])
  x = x[(x.punt_attempt == 1) & (x.punt_blocked != 1) & x.kick_distance.notna() & (x.touchdown != 1) & (x.fumble_lost != 1)]
  rec = np.where(x.touchback == 1, 80.0, 100 - (x.yardline_100 - x.kick_distance) - x.return_yards.fillna(0))
  x = x.assign(rec=np.clip(rec, 1, 99))
  out = []
  for lo in range(30, 100, 5):
    b = x[(x.yardline_100 >= lo) & (x.yardline_100 < lo + 5)]
    if len(b) >= 30:
      out.append({"lo": lo, "hi": lo + 4, "rec": [float(v) for v in np.quantile(b.rec, QS)], "n": int(len(b))})
  return {"bands": out}


def _next_snap(d: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
  """For each row, the next scrimmage snap in the same game: its possession team and yards to the end zone."""
  s = d[d.down.notna() & d.posteam.notna()].sort_values(["game_id", "play_id"])[["game_id", "play_id", "posteam", "yardline_100"]]
  r = rows.sort_values(["game_id", "play_id"])[["game_id", "play_id", "posteam"]].rename(columns={"posteam": "rec_team"})
  m = pd.merge_asof(r.sort_values("play_id"), s.sort_values("play_id").rename(columns={"play_id": "next_id"}),
                    left_on="play_id", right_on="next_id", by="game_id", direction="forward", allow_exact_matches=False)
  return m


def kickoff(d: pd.DataFrame) -> dict:
  """The receiving team's first snap after a normal kickoff, latest season (the kickoff rules changed in 2024 and 2025)."""
  last = int(d.season.max())
  x = _reg(d[d.season == last])
  k = x[(x.kickoff_attempt == 1) & ~x.desc.str.contains("onside", case=False, na=False) & (x.touchdown != 1)]
  m = _next_snap(x, k)
  m = m[m.posteam == m.rec_team]
  return {"season": last, "rec": [float(v) for v in np.quantile(m.yardline_100, QS)], "n": int(len(m))}


def onside(d: pd.DataFrame) -> dict:
  """Recovery rate: 2024 on (the new kickoff rules), shrunk toward 2018-23's rate with the weight of 50 kicks; where the
  next snap was when the kicking team recovered and when it didn't (2018 on)."""
  x = _reg(d[d.season >= 2018])
  k = x[(x.kickoff_attempt == 1) & x.desc.str.contains("onside", case=False, na=False)]
  new, old = k[k.season >= 2024], k[k.season < 2024]
  p_old = float(old.own_kickoff_recovery.mean())
  p = float((new.own_kickoff_recovery.sum() + 50 * p_old) / (len(new) + 50))
  m = _next_snap(x, k)
  m = m.merge(k[["game_id", "play_id", "own_kickoff_recovery"]], on=["game_id", "play_id"])
  kept = m[(m.own_kickoff_recovery == 1) & (m.posteam != m.rec_team)]  # the kicking team (not the listed receiver) snaps next
  lost = m[(m.own_kickoff_recovery != 1) & (m.posteam == m.rec_team)]
  return {"p": p, "p_new": float(new.own_kickoff_recovery.mean()) if len(new) else None, "n_new": int(len(new)), "p_old": p_old, "n_old": int(len(old)),
          "kept_yl": float(kept.yardline_100.median()), "lost_yl": float(lost.yardline_100.median())}


def tries(d: pd.DataFrame) -> dict:
  x = _reg(d[d.season >= 2021])
  xp = x[x.extra_point_result.notna()]
  tp = x[x.two_point_attempt == 1]
  return {"xp": float((xp.extra_point_result == "good").mean()), "n_xp": int(len(xp)),
          "two": float((tp.two_point_conv_result == "success").mean()), "n_two": int(len(tp))}


def clock(d: pd.DataFrame) -> dict:
  """What a timeout saves: the seconds between snaps when the clock keeps running (after an in-bounds run or completed
  pass; no penalty, score, spike or timeout; not across the two-minute warning) minus a play's own length (the gap
  after an incomplete pass, when the clock stops at the whistle). The pace depends on the offense's situation
  (2026-10-23: 39 s between snaps normally, 21-24 in a half's last two minutes, 43 for a 4th-quarter leader between 5:00
  and 2:00): medians by half (2 / 4), time left in it (two = 2:00 or less, five = 2:01-5:00, else normal) and whether
  the offense leads. 2018 on."""
  x = _reg(d[d.season >= 2018])
  x = x[x.down.notna() | (x.timeout == 1)].sort_values(["game_id", "play_id"]).reset_index(drop=True)
  nxt = x.groupby("game_id").shift(-1)
  inc = x.desc.str.contains("incomplete", case=False, na=False)
  base = (nxt.qtr == x.qtr) & (nxt.posteam == x.posteam) & (x.penalty != 1) & (x.touchdown != 1) & (nxt.timeout != 1)          & nxt.down.notna() & (x.qb_spike != 1) & (x.timeout != 1)
  gap = x.game_seconds_remaining - nxt.game_seconds_remaining
  cross = (x.half_seconds_remaining > 120) & (nxt.half_seconds_remaining <= 120)
  runs = base & x.play_type.isin(["run", "pass"]) & (x.out_of_bounds != 1) & ~inc & ~cross & (gap > 0) & (gap < 60)
  stops = base & (x.play_type == "pass") & inc & (gap > 0) & (gap < 20)
  play_len = float(gap[stops].median())
  half = np.where(x.qtr <= 2, 2, 4)
  band = np.where(x.half_seconds_remaining <= 120, "two", np.where(x.half_seconds_remaining <= 300, "five", "normal"))
  lead = np.where(x.score_differential > 0, "lead", "trail")
  key = pd.Series([f"{h}:{b}:{l}" for h, b, l in zip(half, band, lead)], index=x.index)
  g = gap[runs].groupby(key[runs]).agg(["median", "size"])
  pace = {k: float(v["median"]) for k, v in g.iterrows() if v["size"] >= 200}
  return {"play_len": play_len, "pace": pace, "normal": float(gap[runs & (band == "normal")].median()),
          "saved": float(gap[runs & (band == "normal")].median() - play_len), "n_run": int(runs.sum()), "n_stop": int(stops.sum())}


def build(d: pd.DataFrame) -> dict:
  """Everything the browser engine reads except the conversion trees (tools/calc_build.py exports conversion_gb)."""
  return {"gains": gains_by_field(d), "fg": fg_v3(d), "punts": punts_v2(d), "kickoff": kickoff(d),
          "onside": onside(d), "tries": tries(d), "clock": clock(d), "conv_features": CONV_FEATURES}


# ------------------------------------------------------------------------------------------------------------------
# (CI, 2026-10-23) the inputs upgraded with what nfl4th and the NYT 4th Down Bot account for (docs/INSIGHTS.md)
CONV_FEATURES = ["down", "ydstogo", "yardline_100", "spread", "total", "team_total", "outdoors", "dome", "retractable"]
CONV_PARAMS = dict(learning_rate=0.05, max_iter=150, max_leaf_nodes=15, min_samples_leaf=200, l2_regularization=1.0,
                   early_stopping=False, random_state=0)
CI_HALF_LIFE = 3.0
YL_BANDS = [0, 10, 20, 40, 60, 80, 100]


def _roof(r: pd.Series) -> pd.DataFrame:
  r = r.fillna("outdoors").astype(str).str.lower()
  return pd.DataFrame({"outdoors": r.isin(["outdoors", "open"]).astype(float), "dome": (r == "dome").astype(float),
                       "retractable": (r == "closed").astype(float)}, index=r.index)


def conv_features(df: pd.DataFrame) -> pd.DataFrame:
  """down, ydstogo, yardline_100, spread (the offense's expected margin), total, roof (string) -> model inputs."""
  x = pd.DataFrame(index=df.index)
  x["down"] = df.down.astype(float)
  x["ydstogo"] = df.ydstogo.astype(float)
  x["yardline_100"] = df.yardline_100.astype(float)
  x["spread"] = df.spread.astype(float)
  x["total"] = df.total.astype(float)
  x["team_total"] = (x.total + x.spread) / 2
  x = x.join(_roof(df.roof))
  return x[CONV_FEATURES]


def _gain_rows(d: pd.DataFrame) -> pd.DataFrame:
  """3rd / 4th-down runs, passes and sacks, plus defensive penalties that gave a first down (nfl4th codes the gain as
  the distance, or the penalty yards if more). A turnover is a failure at the spot."""
  x = _reg(d[d.season >= 2014])
  x = x[x.down.isin([3, 4]) & x.ydstogo.notna() & x.yardline_100.notna() & (x.qb_kneel != 1) & (x.qb_spike != 1)]
  x = x[x.play_type_nfl.isin(["RUSH", "PASS", "SACK"]) | (x.first_down_penalty == 1)]
  pen = x.first_down_penalty == 1
  gain = np.where(pen & (x.penalty_yards.fillna(0) < x.ydstogo), x.ydstogo, np.where(pen, x.penalty_yards, x.yards_gained))
  gain = pd.Series(gain, index=x.index).fillna(0).astype(float)
  to = (x.interception == 1) | (x.fumble_lost == 1)
  gain = np.where(to, np.minimum(gain, x.ydstogo - 1), gain)
  spread = np.where(x.posteam == x.home_team, x.spread_line, -x.spread_line)
  out = pd.DataFrame({"season": x.season, "down": x.down, "ydstogo": x.ydstogo, "yardline_100": x.yardline_100,
                      "spread": spread, "total": x.total_line, "roof": x.roof, "gain": gain}, index=x.index)
  out["y"] = ((out.gain >= out.ydstogo) | (out.gain >= out.yardline_100)).astype(int)
  return out.dropna(subset=["spread", "total"])


def conversion_gb(d: pd.DataFrame):
  from sklearn.ensemble import HistGradientBoostingClassifier
  g = _gain_rows(d)
  w = (0.5 ** ((g.season.max() - g.season) / CI_HALF_LIFE)).to_numpy(float)
  return HistGradientBoostingClassifier(**CONV_PARAMS).fit(conv_features(g), g.y, sample_weight=w)


def gains_by_field(d: pd.DataFrame) -> dict:
  """Yards gained after success (beyond the distance) and after failure, ten equally likely values per distance bucket x
  field-position band (fewer than 40 plays: the distance bucket's all-field values)."""
  g = _gain_rows(d)
  out = []
  for lo, hi in DIST_BUCKETS:
    b = g[(g.ydstogo >= lo) & (g.ydstogo <= hi)]
    whole = {"succ_over": np.quantile(b[b.y == 1].gain - b[b.y == 1].ydstogo, QS), "fail": np.quantile(b[b.y == 0].gain, QS)}
    bands = []
    for a, z in zip(YL_BANDS[:-1], YL_BANDS[1:]):
      c = b[(b.yardline_100 > a) & (b.yardline_100 <= z)]
      s, f = c[c.y == 1], c[c.y == 0]
      bands.append({"lo": a, "hi": z,
                    "succ_over": [float(v) for v in (np.quantile(s.gain - s.ydstogo, QS) if len(s) >= 40 else whole["succ_over"])],
                    "fail": [float(v) for v in (np.quantile(f.gain, QS) if len(f) >= 40 else whole["fail"])]})
    out.append({"lo": lo, "hi": hi, "bands": bands})
  return {"buckets": out, "yl_bands": YL_BANDS}


def _fg_X(dist, outdoors, wind) -> np.ndarray:
  dist = np.asarray(dist, float)
  o = np.asarray(outdoors, float)
  w = np.nan_to_num(np.asarray(wind, float), nan=8.0)  # outdoors, wind not recorded: a typical 8 mph
  return np.column_stack([dist, dist ** 2 / 100, o, o * w])


def fg_v2(d: pd.DataFrame) -> dict:
  """Make rate by distance, roof and wind (outdoors), seasons 2010 on weighted by CI_HALF_LIFE, with the long-range
  selection correction (as nfl4th does it): where the 4th-down field goal attempt rate falls below 80% of its plateau,
  the log-odds blend toward a curve fitted only where everyone kicks (it may only lower the rate); tapered to 0 at
  70 yd."""
  from sklearn.linear_model import LogisticRegression
  x = _reg(d[d.season >= 2010])
  last = int(x.season.max())
  fgx = x[(x.field_goal_attempt == 1) & x.kick_distance.notna()]
  o = _roof(fgx.roof).outdoors
  w = (0.5 ** ((last - fgx.season) / CI_HALF_LIFE)).to_numpy(float)
  yv = (fgx.field_goal_result == "made").astype(int)
  full = LogisticRegression(C=10.0, max_iter=4000).fit(_fg_X(fgx.kick_distance, o, fgx.wind), yv, sample_weight=w)
  # attempt rate on 4th down by distance (the selection), the last 3 seasons: who tries a 52-yarder today, not in 2012
  # (v2, 2026-10-23: a 2010-23 rate over-corrected 50-59 yd, 64.6% vs 71.4% made in 2024-25)
  f4 = x[(x.down == 4) & x.yardline_100.notna() & (x.season > last - 3)]
  dist4 = (f4.yardline_100 + FG_OFFSET).round()
  rate = (f4.field_goal_attempt == 1).groupby(dist4).mean()
  rate = rate.reindex(range(18, 71)).interpolate().bfill().ffill().rolling(3, center=True, min_periods=1).mean()
  plateau = float(rate.loc[18:45].max())
  wt = np.clip(rate / plateau, 0, 1)
  ok_d = [int(dd) for dd, v in wt.items() if v >= 0.8]
  sel = fgx[fgx.kick_distance.round().isin(ok_d)]
  so = _roof(sel.roof).outdoors
  ws = (0.5 ** ((last - sel.season) / CI_HALF_LIFE)).to_numpy(float)
  base = LogisticRegression(C=10.0, max_iter=4000).fit(_fg_X(sel.kick_distance, so, sel.wind), (sel.field_goal_result == "made").astype(int), sample_weight=ws)
  return {"full": {"coef": [float(c) for c in full.coef_[0]], "intercept": float(full.intercept_[0])},
          "base": {"coef": [float(c) for c in base.coef_[0]], "intercept": float(base.intercept_[0])},
          "weight": {"from": 18, "w": [round(float(v), 4) for v in wt.to_numpy()]}, "offset": FG_OFFSET, "taper": [64, 70],
          "n": int(len(fgx)), "seasons": [2010, last], "half_life": CI_HALF_LIFE}


def fg_v2_prob(c: dict, dist, outdoors=1.0, wind=np.nan) -> np.ndarray:
  dist = np.atleast_1d(np.asarray(dist, float))
  X = _fg_X(dist, np.broadcast_to(outdoors, dist.shape), np.broadcast_to(wind, dist.shape))
  zf = c["full"]["intercept"] + X @ np.array(c["full"]["coef"])
  zb = c["base"]["intercept"] + X @ np.array(c["base"]["coef"])
  wv = np.asarray(c["weight"]["w"])
  i = np.clip(np.round(dist).astype(int) - c["weight"]["from"], 0, len(wv) - 1)
  wd = wv[i]
  z = np.minimum(zf, wd * zf + (1 - wd) * zb)  # the correction may only lower it
  p = 1 / (1 + np.exp(-z))
  t0, t1 = c["taper"]
  return p * np.clip((t1 - dist) / (t1 - t0), 0, 1)


def punts_v2(d: pd.DataFrame) -> dict:
  """Every punt by 5-yard band of the punt's spot (2018 on): blocked, muffed and lost (the kicking team recovers),
  returned for a touchdown, else where the receiving team starts (ten equally likely values)."""
  x = _reg(d[d.season >= 2018])
  x = x[(x.punt_attempt == 1) & x.yardline_100.notna()]
  blocked = x.punt_blocked == 1
  ret_td = (x.touchdown == 1) & (x.td_team != x.posteam)
  muff = (x.fumble_lost == 1) & (x.fumble_recovery_1_team == x.posteam) & ~blocked
  rec = np.where(x.touchback == 1, 80.0, 100 - (x.yardline_100 - x.kick_distance.fillna(0)) - x.return_yards.fillna(0))
  x = x.assign(rec=np.clip(rec, 1, 99), blocked=blocked, ret_td=ret_td, muff=muff)
  out = []
  for lo in range(30, 100, 5):
    b = x[(x.yardline_100 >= lo) & (x.yardline_100 < lo + 5)]
    if len(b) < 30:
      continue
    clean = b[~b.blocked & ~b.ret_td & ~b.muff]
    out.append({"lo": lo, "hi": lo + 4, "p_block": float(b.blocked.mean()), "p_ret_td": float(b.ret_td.mean()),
                "p_muff": float(b.muff.mean()), "rec": [float(v) for v in np.quantile(clean.rec, QS)], "n": int(len(b))})
  return {"bands": out}


def fg_v3(d: pd.DataFrame) -> dict:
  """(CI v3, 2026-10-23) the recent-season make-rate table (fg(): isotonic, passed 20-59 yd) shifted in log-odds for
  roof and wind by fg_v2's logistic effects, centered on the average attempt (a logistic's distance shape ran 5-7
  points low at 50-59 yd for today's kickers)."""
  t = fg(d)
  v2 = fg_v2(d)
  x = _reg(d[d.season > int(d.season.max()) - 3])
  x = x[(x.field_goal_attempt == 1) & x.kick_distance.notna()]
  o = _roof(x.roof).outdoors.to_numpy(float)
  ow = o * np.nan_to_num(x.wind.to_numpy(float), nan=8.0)
  c = v2["full"]["coef"]
  return {**t, "roof_wind": {"outdoors": c[2], "wind_out": c[3], "mean_out": float(o.mean()), "mean_ow": float(ow.mean())}}


def fg_v3_prob(c: dict, dist, outdoors=None, wind=None) -> np.ndarray:
  p = np.clip(fg_prob(c, dist), 1e-4, 1 - 1e-4)
  taper = np.clip((70 - np.round(np.atleast_1d(np.asarray(dist, float)))) / 6, 0, 1)  # past 64 yd: only strong kickers try
  if outdoors is None:
    return p * taper
  rw = c["roof_wind"]
  o = np.asarray(outdoors, float)
  ow = o * np.nan_to_num(np.asarray(wind, float) if wind is not None else np.full_like(o, np.nan), nan=8.0)
  z = np.log(p / (1 - p)) + rw["outdoors"] * (o - rw["mean_out"]) + rw["wind_out"] * (ow - rw["mean_ow"])
  return taper / (1 + np.exp(-z))
