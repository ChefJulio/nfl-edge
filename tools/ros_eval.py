"""Thread 7 (INSIGHTS 2026-10-16): rest-of-season accuracy, descriptive.

Usage: python tools/ros_eval.py
No archive of the live rest-of-season numbers exists (lookahead pages are rebuilt every run), so this scores the
closest walk-forward stand-in: at week W, a player's projection if active (proj_no_inj when present, else proj) x his
team's remaining regular-season games, against what he actually scored from W to the end (missed games count 0).
Baseline: his fantasy points per game so far x the same games. Players with a projection >= 5 at W and 3+ games
played before W. Spearman by position and W, and the bias of assuming every remaining game is played.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import fantasy_value_eval as F  # noqa: E402


def main():
  from nfledge import data as D
  from nfledge.config import load_config
  res = F.latest("baseline")
  res = res[res.pos.isin(["QB", "RB", "WR", "TE"]) & (res.season <= 2025)]
  d = D.load_all(load_config())
  sch = d.schedules[(d.schedules.game_type == "REG") & (d.schedules.season.between(2021, 2025))]
  games = {}
  for g in sch.itertuples():
    for t in (g.home_team, g.away_team):
      games.setdefault((int(g.season), D.RELOCATED.get(t, t)), []).append(int(g.week))
  pts = res.groupby(["season", "gsis_id", "week"]).actual.sum()
  rows = []
  for (s, w), g in res.groupby(["season", "week"]):
    if w not in (4, 8, 12):
      continue
    last = max(games.get((s, "KC"), [18]))
    future = res[(res.season == s) & (res.week >= w)].groupby("gsis_id").actual.sum()
    for x in g.itertuples():
      if (x.raw_games or 0) < 3:
        continue
      p = getattr(x, "proj_no_inj", np.nan)
      p = x.proj if pd.isna(p) else p
      if p < 5:
        continue
      rem = sum(1 for k in games.get((s, D.RELOCATED.get(x.team, x.team)), []) if k >= w)
      rows.append({"season": s, "W": w, "pos": x.pos, "ours": p * rem, "base": x.raw_fpg * rem,
                   "actual": float(future.get(x.gsis_id, 0.0)), "rem": rem})
  r = pd.DataFrame(rows)
  print(f"{len(r):,} player-seasons x W (2021-25), W in 4 / 8 / 12")
  print(f"{'pos':4s} {'W':>3s} {'n':>5s}  Spearman ours  base   bias ours (actual - proj, pts)  base")
  for (pos, w), g in r.groupby(["pos", "W"]):
    sp = lambda c: g[c].corr(g.actual, method="spearman")  # noqa: E731
    print(f"{pos:4s} {w:3d} {len(g):5d}       {sp('ours'):.3f}  {sp('base'):.3f}   {(g.actual - g.ours).mean():+8.1f}  {(g.actual - g.base).mean():+8.1f}")
  by = r.groupby("season").apply(lambda g: pd.Series({"ours": g.ours.corr(g.actual, method="spearman"),
                                                      "base": g.base.corr(g.actual, method="spearman")}), include_groups=False)
  print("\nall positions by season:\n" + by.round(3).to_string())
  print(f"\nbias as a share of the projection: ours {(r.actual.sum() / r.ours.sum() - 1):+.1%}, base {(r.actual.sum() / r.base.sum() - 1):+.1%}")


if __name__ == "__main__":
  main()
