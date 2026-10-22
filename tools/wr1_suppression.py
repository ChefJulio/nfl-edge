"""Does a defense erase opposing WR1s as a lasting trait? (owner's friend 2026-10-21: "Pat Surtain's OPRK for WR1 is #1
hardest ... shadow CB can nuke WRs".) Descriptive, before any model change.

Each offense's WR1 / WR2 in a game = its top two WRs by targets that season before the game (3+ games in). His
result = his half-PPR points that game minus his own average over his other games that season (so the receiver's
level is removed). A defense's WR1 suppression = the mean result of the WR1s it faced. Persistence: odd vs even weeks
of a season (split-half) and season to season, for WR1, WR2 and WR1 minus WR2 (a shadow corner should hit the WR1 and
not the WR2). Play-by-play 2016-2025, regular season.

  python tools/wr1_suppression.py
"""
import nflreadpy as nfl
import numpy as np
import pandas as pd


def main():
  yrs = list(range(2016, 2026))
  p = nfl.load_pbp(yrs).select(["season", "week", "season_type", "posteam", "defteam", "receiver_player_id", "pass_attempt",
                                "complete_pass", "receiving_yards", "pass_touchdown", "sack"]).to_pandas()
  p = p[(p.season_type == "REG") & (p.pass_attempt == 1) & (p.sack != 1) & p.receiver_player_id.notna()]
  pos = nfl.load_players().to_pandas().set_index("gsis_id").position
  p = p[p.receiver_player_id.map(pos) == "WR"]
  g = p.groupby(["season", "week", "posteam", "defteam", "receiver_player_id"]).agg(
    tgt=("pass_attempt", "size"), rec=("complete_pass", "sum"), yd=("receiving_yards", "sum"), td=("pass_touchdown", "sum")).reset_index()
  g["pts"] = g.yd.fillna(0) / 10 + 0.5 * g.rec + 6 * g.td
  g = g.sort_values(["season", "receiver_player_id", "week"])
  # his average over his OTHER games that season (his level), and his targets before this game (the WR1 / WR2 pick)
  s_ = g.groupby(["season", "receiver_player_id"])
  g["n"], g["sum_pts"] = s_.pts.transform("size"), s_.pts.transform("sum")
  g["avg_other"] = (g.sum_pts - g.pts) / (g.n - 1).replace(0, np.nan)
  g["res"] = g.pts - g.avg_other
  g["tgt_before"] = g.groupby(["season", "posteam", "receiver_player_id"]).tgt.transform(lambda x: x.shift().fillna(0).cumsum())
  g["games_before"] = g.groupby(["season", "posteam", "receiver_player_id"]).cumcount()
  g = g[(g.games_before >= 3) & (g.n >= 6)]
  g["rank"] = g.groupby(["season", "week", "posteam"]).tgt_before.rank(ascending=False, method="first")
  w = g[g["rank"] <= 2].pivot_table(index=["season", "week", "posteam", "defteam"], columns="rank", values="res").dropna()
  w.columns = ["wr1", "wr2"]
  w = w.reset_index()
  w["gap"] = w.wr1 - w.wr2
  print(f"team-games with a WR1 and WR2 (2016-25): {len(w)}; WR1 result mean {w.wr1.mean():+.2f}, sd {w.wr1.std():.2f}\n")
  d = w.assign(half=np.where(w.week % 2 == 1, "odd", "even"))
  print("split-half persistence of a defense's effect (correlation of odd-week vs even-week means, defense-seasons):")
  for col, lab in (("wr1", "vs WR1s"), ("wr2", "vs WR2s"), ("gap", "WR1 minus WR2 (shadow signature)")):
    t = d.groupby(["season", "defteam", "half"])[col].mean().unstack()
    print(f"  {lab:<34} r = {t.odd.corr(t.even):+.3f}  (n {len(t.dropna())})")
  print("\nseason-to-season (same defense, next season):")
  ds = w.groupby(["season", "defteam"])[["wr1", "wr2", "gap"]].mean().reset_index()
  m = ds.merge(ds.assign(season=ds.season - 1), on=["season", "defteam"], suffixes=("", "_next"))
  for col, lab in (("wr1", "vs WR1s"), ("wr2", "vs WR2s"), ("gap", "WR1 minus WR2")):
    print(f"  {lab:<34} r = {m[col].corr(m[col + '_next']):+.3f}  (n {len(m)})")
  print("\nmost WR1-suppressing defenses (points below the WR1s' own averages, per game):")
  for s in (2023, 2024, 2025):
    t = ds[ds.season == s].sort_values("gap").head(5)
    print(f"  {s}: " + ", ".join(f"{r.defteam} {r.wr1:+.1f} (WR2 {r.wr2:+.1f})" for r in t.itertuples()))
  den = ds[ds.defteam == "DEN"].sort_values("season")
  print("\nDenver (Surtain drafted 2021): " + ", ".join(f"{r.season} WR1 {r.wr1:+.1f} / WR2 {r.wr2:+.1f}" for r in den.itertuples()))


if __name__ == "__main__":
  main()
