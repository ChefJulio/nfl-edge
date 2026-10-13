"""Do referees move results against the market? Spread and total outcomes by referee, and by referee x team.

Usage: python tools/referees.py        (seconds; schedules only)

Against the spread: residual = (home margin - Vegas spread), covers exclude pushes. Totals: (total points - line).
For each question two tests, each against 2,000 shuffles of referee labels within season (keeps schedule structure):
  spread   is the variation across referees (or referee x team pairs) larger than chance would produce?
  persist  does a referee's (pair's) tendency in its EARLIER games predict its LATER games? (a real tendency must)
"""
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402

pd.set_option("display.width", 200)
RNG = np.random.default_rng(0)
N_PERM = 2000


def dispersion(df: pd.DataFrame, key: list, col: str, min_n: int) -> float:
  """Games-weighted variance of group means of col (groups with >= min_n games): how much groups differ."""
  g = df.groupby(key)[col].agg(["mean", "size"])
  g = g[g["size"] >= min_n]
  return float(((g["mean"] - df[col].mean()) ** 2 * g["size"]).sum() / g["size"].sum())


def persistence(df: pd.DataFrame, key: list, col: str) -> float:
  """Correlation between each group's mean over its first half of games (by date) and its second half."""
  df = df.sort_values("order")
  rank = df.groupby(key).cumcount()
  n = df.groupby(key)[col].transform("size")
  first = df[rank < n // 2].groupby(key)[col].mean()
  second = df[(rank >= n // 2) & (n >= 4)].groupby(key)[col].mean()
  j = pd.concat([first, second], axis=1, keys=["a", "b"]).dropna()
  return float(np.corrcoef(j.a, j.b)[0, 1]) if len(j) > 3 else np.nan


def test(df: pd.DataFrame, key: list, col: str, min_n: int, label: str):
  obs_d, obs_p = dispersion(df, key, col, min_n), persistence(df, key, col)
  null_d, null_p = [], []
  sh = df.copy()
  for _ in range(N_PERM):
    sh["referee"] = df.groupby("season").referee.transform(lambda x: RNG.permutation(x.to_numpy()))
    null_d.append(dispersion(sh, key, col, min_n))
    null_p.append(persistence(sh, key, col))
  null_d, null_p = np.array(null_d), np.array(null_p)
  print(f"  {label:44s} spread: {obs_d / null_d.mean():.2f}x chance (p={np.mean(null_d >= obs_d):.2f})   "
        f"persist: r={obs_p:+.3f} vs chance {np.nanmean(null_p):+.3f} (p={np.nanmean(null_p >= obs_p):.2f})")


if __name__ == "__main__":
  cfg = copy.deepcopy(load_config())
  cfg["data"]["history_seasons"] = 9
  s = D.load_all(cfg).schedules
  s = s[s.home_score.notna() & s.spread_line.notna() & s.referee.notna() & (s.game_type == "REG")].copy()
  s = s.sort_values(["gameday", "gametime"]).reset_index(drop=True)
  s["order"] = np.arange(len(s))
  s["ats"] = s.home_score - s.away_score - s.spread_line
  s["cover"] = np.where(s.ats > 0, 1.0, np.where(s.ats < 0, 0.0, np.nan))
  s["ou"] = s.home_score + s.away_score - s.total_line
  s["over"] = np.where(s.ou > 0, 1.0, np.where(s.ou < 0, 0.0, np.nan))
  print(f"{len(s)} regular-season games {s.season.min()}-{s.season.max()}, {s.referee.nunique()} referees "
        f"(median {s.groupby('referee').size().median():.0f} games each). Home covered {s.cover.mean():.1%}, "
        f"over hit {s.over.mean():.1%}.\n")
  print("Referee alone (refs with 30+ games):")
  test(s, ["referee"], "ats", 30, "home margin vs spread (points)")
  test(s.dropna(subset=["cover"]), ["referee"], "cover", 30, "home cover rate")
  test(s, ["referee"], "ou", 30, "total points vs line")
  test(s.dropna(subset=["over"]), ["referee"], "over", 30, "over rate")
  # team-relative: one row per team per game, residual from that team's side
  t = pd.concat([s.assign(team=s.home_team, res=s.ats), s.assign(team=s.away_team, res=-s.ats)], ignore_index=True)
  t["cov"] = np.where(t.res > 0, 1.0, np.where(t.res < 0, 0.0, np.nan))
  print("\nReferee x team (pairs with 4+ games):")
  test(t, ["referee", "team"], "res", 4, "team margin vs spread with this ref (points)")
  test(t.dropna(subset=["cov"]), ["referee", "team"], "cov", 4, "team cover rate with this ref")
  print("\nMost extreme referees (30+ games), for color only; see the tests above before believing any of it:")
  g = s.groupby("referee").agg(games=("ats", "size"), home_cover=("cover", "mean"), ats_pts=("ats", "mean"),
                               over=("over", "mean"), ou_pts=("ou", "mean"))
  g = g[g.games >= 30].sort_values("home_cover")
  print(pd.concat([g.head(3), g.tail(3)]).round(3).to_string())
