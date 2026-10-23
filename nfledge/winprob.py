"""In-game win probability (owner 2026-10-23: "a calculator where you input down, distance, score, team timeouts left
and game clock ... to make decisions"; (CG) in docs/INSIGHTS.md): P(the team with the ball wins) from the game state,
the base of Games > Calc and the gamecast's "what should they do?". Ours, tested walk-forward against nflfastR's
vegas_wp (tools/wp_eval.py); exported as trees the browser evaluates (static/calc_engine.js).

  rows(pbp)         - one row per regulation play: features (FEATURES) + y (did the team with the ball win)
  features(df)      - the model inputs from state columns (shared by training and the export's checks)
  fit(rows)         - the model (fixed settings, PARAMS)
  export(model)     - {features, baseline, trees: [[feature, threshold, left, right, value, missing_left], ...]}

Regulation only: overtime's rules changed in 2022 (playoffs) and 2025 (regular season), too few plays under each.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# the play-by-play columns the calculator's models read (tools/calc_build.py caches them as pbp_calc_<season>)
PBP_COLS = ["game_id", "play_id", "season", "week", "season_type", "home_team", "away_team", "posteam", "defteam", "qtr",
            "down", "ydstogo", "yardline_100", "game_seconds_remaining", "half_seconds_remaining",
            "quarter_seconds_remaining", "score_differential", "posteam_timeouts_remaining",
            "defteam_timeouts_remaining", "spread_line", "result", "vegas_wp", "wp", "play_type", "desc",
            "kickoff_attempt", "punt_attempt", "field_goal_attempt", "field_goal_result", "kick_distance",
            "extra_point_result", "two_point_attempt", "two_point_conv_result", "fourth_down_converted",
            "fourth_down_failed", "third_down_converted", "third_down_failed", "yards_gained", "first_down",
            "return_yards", "own_kickoff_recovery", "touchback", "punt_blocked", "timeout", "timeout_team", "penalty",
            "penalty_yards", "penalty_team", "roof", "drive", "posteam_score", "defteam_score", "qb_kneel", "qb_spike",
            "out_of_bounds", "fumble_lost", "interception", "safety", "touchdown", "td_team", "time",
            # (CI) the calculator's inputs: team strength, weather, penalty first downs, punt outcomes
            "total_line", "wind", "temp", "first_down_penalty", "play_type_nfl", "punt_fair_catch", "return_team",
            "fumble_recovery_1_team"]

FEATURES = ["score_diff", "game_sec", "half_sec", "second_half", "down", "ydstogo", "yardline_100", "own_to", "opp_to",
            "exp_margin", "spread_time", "home", "receive_2h", "diff_time"]
# +1 / -1 / 0 per FEATURES: more points, own timeouts, a better expected margin never lower the chance. The clock stays
# free: a v2 that made time monotone by the score (more time never helps the leader) smoothed it but underfit the
# last seconds (down 1-3 inside the opponent's 35 with 0:15 or less: 29% vs 43% actual; v1 41%), so the engine
# averages over nearby clocks instead (static/calc_engine.js)
MONOTONIC = {"score_diff": 1, "own_to": 1, "opp_to": -1, "exp_margin": 1, "yardline_100": -1, "ydstogo": -1,
             "diff_time": 1}
PARAMS = dict(learning_rate=0.05, max_iter=400, max_leaf_nodes=31, min_samples_leaf=200, l2_regularization=1.0,
              early_stopping=False, random_state=0)


def features(df: pd.DataFrame) -> pd.DataFrame:
  """Model inputs from state columns: score_diff, game_sec, half_sec, down (0 = a kickoff), ydstogo, yardline_100,
  own_to, opp_to, exp_margin (the team with the ball's Vegas expected margin), home (0 / 1), receive_2h (0 / 1)."""
  x = pd.DataFrame(index=df.index)
  x["score_diff"] = df.score_diff.astype(float)
  sec = df.game_sec.astype(float)
  x["game_sec"] = sec
  x["half_sec"] = df.half_sec.astype(float)
  x["second_half"] = (sec <= 1800).astype(float)
  x["down"] = df.down.fillna(0).astype(float)
  x["ydstogo"] = df.ydstogo.astype(float)
  x["yardline_100"] = df.yardline_100.astype(float)
  x["own_to"] = df.own_to.astype(float)
  x["opp_to"] = df.opp_to.astype(float)
  x["exp_margin"] = df.exp_margin.astype(float)
  share = (df.game_sec.astype(float) / 3600).clip(0, 1)
  x["spread_time"] = x.exp_margin * np.exp(-4 * (1 - share))  # the line's weight fades as the game is played (nflfastR's form)
  x["home"] = df.home.astype(float)
  # only matters in the first half (who gets the ball after halftime)
  x["receive_2h"] = np.where(df.game_sec > 1800, df.receive_2h.astype(float), 0.0)
  x["diff_time"] = x.score_diff / np.sqrt(sec + 1)  # a lead is worth more the less time is left
  return x[FEATURES]


def rows(pbp: pd.DataFrame) -> pd.DataFrame:
  """State at each regulation snap or kickoff, from the team with the ball's side, with y = it won the game."""
  p = pbp[(pbp.qtr <= 4) & pbp.posteam.notna() & pbp.result.notna() & pbp.game_seconds_remaining.notna()
          & pbp.yardline_100.notna() & (pbp.down.notna() | (pbp.kickoff_attempt == 1))].copy()
  p = p[p.play_type.isin(["run", "pass", "punt", "field_goal", "kickoff", "qb_kneel", "qb_spike", "no_play", "extra_point"])
        | (p.kickoff_attempt == 1)]
  p = p[(p.play_type != "extra_point")]
  home = (p.posteam == p.home_team)
  # receives the second-half kickoff: the team that kicked off to start the game (posteam on a kickoff = the receiver)
  ko = pbp[(pbp.kickoff_attempt == 1) & (pbp.qtr == 1) & pbp.posteam.notna()].sort_values(["game_id", "play_id"])
  first_rec = ko.drop_duplicates("game_id").set_index("game_id").posteam
  out = pd.DataFrame({
    "game_id": p.game_id, "season": p.season, "week": p.week, "qtr": p.qtr,
    "score_diff": p.score_differential.fillna(0), "game_sec": p.game_seconds_remaining,
    "half_sec": p.half_seconds_remaining, "down": p.down.where(p.kickoff_attempt != 1),
    "ydstogo": p.ydstogo.fillna(10).where(p.kickoff_attempt != 1, 10),
    "yardline_100": p.yardline_100, "own_to": p.posteam_timeouts_remaining.fillna(3),
    "opp_to": p.defteam_timeouts_remaining.fillna(3),
    "exp_margin": np.where(home, p.spread_line, -p.spread_line),
    "home": home.astype(int), "receive_2h": (p.game_id.map(first_rec) != p.posteam).astype(int),
    "vegas_wp": p.vegas_wp, "wp_nflfastr": p.wp,
  }, index=p.index)
  won = np.where(home, p.result > 0, p.result < 0)
  out["y"] = np.where(p.result == 0, np.nan, won.astype(float))
  out["exp_margin"] = out.exp_margin.fillna(0.0)
  return out.dropna(subset=["y"])


def fit(r: pd.DataFrame):
  from sklearn.ensemble import HistGradientBoostingClassifier
  cst = [MONOTONIC.get(f, 0) for f in FEATURES]
  return HistGradientBoostingClassifier(monotonic_cst=cst, **PARAMS).fit(features(r), r.y.astype(int))


def export(model, features: list | None = None) -> dict:
  """The fitted trees for the browser: P = sigmoid(baseline + sum of each tree's leaf value). A node is
  [feature index, threshold, left, right, leaf value, missing goes left]; a leaf has feature -1. Go left when
  x <= threshold (sklearn's rule)."""
  trees = []
  for (pred,) in model._predictors:
    nd = pred.nodes
    t = []
    for n in nd:
      if n["is_leaf"]:
        t.append([-1, 0, 0, 0, round(float(n["value"]), 8), 0])
      else:
        t.append([int(n["feature_idx"]), float(n["num_threshold"]), int(n["left"]), int(n["right"]), 0,
                  int(n["missing_go_to_left"])])
    trees.append(t)
  return {"features": features or FEATURES, "baseline": float(np.ravel(model._baseline_prediction)[0]), "trees": trees}


def predict_exported(m: dict, x: pd.DataFrame) -> np.ndarray:
  """The export evaluated as the browser does (a check that it matches the model)."""
  X = x[m["features"]].to_numpy(float)
  raw = np.full(len(X), m["baseline"])
  for t in m["trees"]:
    for i, row in enumerate(X):
      j = 0
      while t[j][0] >= 0:
        f, thr, left, right, _, mleft = t[j]
        v = row[f]
        j = (left if mleft else right) if np.isnan(v) else (left if v <= thr else right)
      raw[i] += t[j][4]
  return 1 / (1 + np.exp(-raw))
