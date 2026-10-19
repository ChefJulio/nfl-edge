"""Elo ratings from final scores: every team starts at 1505, moves by K x margin multiplier x (result - expected)
after each game (playoffs included), and is pulled a share `revert` back toward 1505 every offseason. Settings are
fit on our data by tools/elo_eval.py (config.toml [report.win_model])."""
import numpy as np
import pandas as pd

MEAN = 1505.0


def run(g: pd.DataFrame, k: float, hfa: float, revert: float, margin: bool, pre: list | None = None
        ) -> tuple[np.ndarray, dict, int | None]:
  """Walk the finished games in g (sorted by date). Returns each game's pre-game home-minus-away rating difference,
  the ratings after the last game, and the season of the last game. If `pre` is a list, each game's pre-game
  (home, away) ratings are appended to it."""
  r, season, out = {}, None, np.empty(len(g))
  for i, (s, h, a, hs, as_, neutral) in enumerate(zip(g.season, g.home_team, g.away_team, g.home_score,
                                                      g.away_score, g.location == "Neutral")):
    if s != season:
      r = {t: MEAN + (v - MEAN) * (1 - revert) for t, v in r.items()}
      season = s
    rh, ra = r.get(h, MEAN), r.get(a, MEAN)
    out[i] = rh - ra
    if pre is not None:
      pre.append((rh, ra))
    edge = rh - ra + (0 if neutral else hfa)
    p = 1 / (1 + 10 ** (-edge / 400))
    m = hs - as_
    res = 1.0 if m > 0 else 0.0 if m < 0 else 0.5
    mult = np.log(abs(m) + 1) * 2.2 / ((edge if m > 0 else -edge) * 0.001 + 2.2) if margin and m else 1.0
    r[h], r[a] = rh + k * mult * (res - p), ra - k * mult * (res - p)
  return out, r, season


def finished(schedules: pd.DataFrame) -> pd.DataFrame:
  return schedules[schedules.home_score.notna()].sort_values(["season", "gameday", "gametime"]).reset_index(drop=True)


def ratings_before(schedules: pd.DataFrame, season: int, week: int, w: dict, also: frozenset = frozenset()) -> dict:
  """Every team's Elo going into (season, week), from games finished before it only; also: game_ids of `week`
  itself to count (the current week's games through Sunday once the ratings take them in: TeamModel.set_live)."""
  g = finished(schedules)
  g = g[(g.season < season) | ((g.season == season) & ((g.week < week) | g.game_id.isin(also)))]
  _, r, last = run(g, w["elo_k"], w["elo_hfa"], w["elo_revert"], w["elo_margin"])
  if last is not None and last < season:  # the offseason pull before the first game of a new season
    r = {t: MEAN + (v - MEAN) * (1 - w["elo_revert"]) for t, v in r.items()}
  return r
