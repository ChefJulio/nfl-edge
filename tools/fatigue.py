"""Do defenses wear down? Defensive fatigue from snap load and short rest, measured inside each game.

Usage: python tools/fatigue.py        (~1-2 min; play-by-play only)

Question (from a friend of the owner): a bad offense keeps its defense on the field; does the defense then play
worse per play? Every comparison is WITHIN one defense's own game (EPA allowed minus that defense's average in that
game), so team quality, the opponent and game conditions cancel. Plays: regular-season scrimmage plays the team
ratings use (pass/rush, no kneels/spikes/2-pt, offense win probability 10-90%).

  wear      EPA allowed per play vs defensive snaps already played this game (controls: quarter, 2-minute drill,
            score margin, pass vs run)
  rest      EPA allowed on a defensive series vs (a) its own offense's preceding possession, in seconds and plays
            (a quick three-and-out = little rest), and (b) the length of the defense's previous series
Effects come with 95% intervals from resampling games, then are scaled to what they could mean for a defense's
rating (EPA per 100 plays) given how much teams differ in snap load.
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


def plays(pbp: pd.DataFrame) -> pd.DataFrame:
  p = pbp[(pbp.season_type == "REG") & (pbp["pass"].eq(1) | pbp.rush.eq(1)) & pbp.epa.notna()
          & pbp.posteam.notna() & pbp.defteam.notna() & ~pbp.qb_kneel.eq(1) & ~pbp.qb_spike.eq(1)
          & ~pbp.two_point_attempt.eq(1)].copy()
  p = p.sort_values(["game_id", "play_id"]).reset_index(drop=True)
  p["half"] = np.where(p.qtr <= 2, 1, np.where(p.qtr <= 4, 2, 3))
  # possessions: consecutive scrimmage plays by the same offense within a half
  new = (p.game_id != p.game_id.shift()) | (p.posteam != p.posteam.shift()) | (p.half != p.half.shift())
  p["poss"] = new.cumsum()
  # defensive snaps already played by this defense in this game (all scrimmage plays, before the filter below)
  p["def_snaps"] = p.groupby(["game_id", "defteam"]).cumcount()
  ps = p.groupby("poss").agg(game_id=("game_id", "first"), off=("posteam", "first"), dfn=("defteam", "first"),
                             half=("half", "first"), n=("epa", "size"),
                             t0=("game_seconds_remaining", "first"), t1=("game_seconds_remaining", "last"),
                             start_yl=("yardline_100", "first"), int_last=("interception", "last"),
                             fum_last=("fumble_lost", "last"))
  ps["turnover"] = (ps.int_last.fillna(0) + ps.fum_last.fillna(0)) > 0
  ps["secs"] = (ps.t0 - ps.t1).clip(lower=0) + 25  # + roughly the last play's own duration
  # For each defensive series: the previous possession in the same half (normally this defense's own offense)
  # and this defense's previous series in the same half.
  prev = ps.shift(1)
  same = (prev.game_id == ps.game_id) & (prev.half == ps.half) & (prev.off == ps.dfn)
  ps["rest_secs"] = np.where(same, prev.secs, np.nan)
  ps["rest_plays"] = np.where(same, prev.n, np.nan)
  ps["after_turnover"] = np.where(same, prev.turnover, False).astype(bool)
  ps["series_start"] = ps.start_yl / 10  # where this series began (yards from the end zone, / 10)
  prev2 = ps.shift(2)
  same2 = same & (prev2.game_id == ps.game_id) & (prev2.half == ps.half) & (prev2.dfn == ps.dfn)
  ps["prev_series"] = np.where(same2, prev2.n, np.nan)
  p = p.join(ps[["rest_secs", "rest_plays", "prev_series", "after_turnover", "series_start"]], on="poss")
  p = p[(p.wp >= 0.10) & (p.wp <= 0.90)].copy()  # same garbage-time filter as the ratings
  p["dg"] = p.game_id + "_" + p.defteam
  return p


def demean(df: pd.DataFrame, cols: list, by: str) -> pd.DataFrame:
  return df[cols] - df.groupby(by)[cols].transform("mean")


def ols_ci(df: pd.DataFrame, y: str, xs: list, by: str, n_boot: int = 400) -> pd.DataFrame:
  """Within-group OLS (group = one defense in one game), with a games-resampling 95% interval."""
  d = demean(df, [y] + xs, by)
  X, Y = d[xs].to_numpy(float), d[y].to_numpy(float)
  beta = np.linalg.lstsq(X, Y, rcond=None)[0]
  games = df.game_id.to_numpy()
  ug, inv = np.unique(games, return_inverse=True)
  rows = [np.flatnonzero(inv == i) for i in range(len(ug))]
  bs = []
  for _ in range(n_boot):
    idx = np.concatenate([rows[i] for i in RNG.integers(0, len(ug), len(ug))])
    bs.append(np.linalg.lstsq(X[idx], Y[idx], rcond=None)[0])
  bs = np.array(bs)
  return pd.DataFrame({"coef": beta, "lo": np.percentile(bs, 2.5, axis=0), "hi": np.percentile(bs, 97.5, axis=0)},
                      index=xs)


if __name__ == "__main__":
  cfg = copy.deepcopy(load_config())
  cfg["data"]["history_seasons"] = 8
  data = D.load_all(cfg)
  p = plays(data.pbp)
  p["is_pass"] = p["pass"].eq(1).astype(float)
  p["q4"] = (p.qtr >= 4).astype(float)
  p["q2"] = (p.qtr == 2).astype(float)
  p["two_min"] = (((p.qtr == 2) | (p.qtr == 4)) & (p.game_seconds_remaining % 1800 <= 120)).astype(float)
  p["margin"] = p.score_differential.clip(-17, 17).fillna(0) / 7  # offense's lead, in touchdowns
  p["snaps10"] = p.def_snaps / 10
  print(f"{len(p):,} plays, {p.game_id.nunique():,} games, {p.season.min()}-{p.season.max()} (regular season, win prob 10-90%)")
  print(f"defensive snaps per game in this set: median {p.groupby('dg').size().median():.0f}\n")

  print("1. WEAR: EPA allowed per play, per +10 defensive snaps already played this game (within defense-game)")
  r = ols_ci(p, "epa", ["snaps10", "q2", "q4", "two_min", "margin", "is_pass"], "dg")
  print((r * 100).round(2).rename(columns=lambda c: c + " (EPA/100)").to_string())
  for kind in ("pass", "rush"):
    sub = p[p.is_pass.eq(1.0 if kind == "pass" else 0.0)]
    rr = ols_ci(sub, "epa", ["snaps10", "q2", "q4", "two_min", "margin"], "dg", n_boot=200)
    print(f"   {kind}: {100 * rr.at['snaps10', 'coef']:+.2f} [{100 * rr.at['snaps10', 'lo']:+.2f}, "
          f"{100 * rr.at['snaps10', 'hi']:+.2f}] EPA/100 per +10 snaps")
  # raw shape, within defense-game
  p["epa_w"] = demean(p, ["epa"], "dg")["epa"]
  bins = pd.cut(p.def_snaps, [-1, 15, 30, 45, 60, 200], labels=["0-15", "16-30", "31-45", "46-60", "61+"])
  print("   shape (EPA/100 vs the same defense's game average, no controls):",
        "  ".join(f"{b} {100 * v:+.1f}" for b, v in p.groupby(bins, observed=True).epa_w.mean().items()))

  print("\n2. REST: EPA allowed on a series vs the rest before it (within defense-game; first series of each half excluded)")
  s = p.dropna(subset=["rest_secs"]).copy()
  s["rest_min"] = s.rest_secs / 60
  s["quick"] = (s.rest_plays <= 3).astype(float)  # own offense went three-and-out or faster
  s["prev10"] = s.prev_series.fillna(s.prev_series.median()) / 10
  r2 = ols_ci(s, "epa", ["rest_min", "prev10", "snaps10", "q2", "q4", "two_min", "margin", "is_pass"], "dg")
  print((r2.loc[["rest_min", "prev10"]] * 100).round(2).rename(
    index={"rest_min": "per extra minute of own-offense possession", "prev10": "per +10 plays in the defense's previous series"},
    columns=lambda c: c + " (EPA/100)").to_string())
  r3 = ols_ci(s, "epa", ["quick", "snaps10", "q2", "q4", "two_min", "margin", "is_pass"], "dg")
  print(f"   after a quick own possession (3 plays or fewer) vs longer: {100 * r3.at['quick', 'coef']:+.2f} "
        f"[{100 * r3.at['quick', 'lo']:+.2f}, {100 * r3.at['quick', 'hi']:+.2f}] EPA/100 "
        f"({s.quick.mean():.0%} of series)")

  # Robustness: is "quick rest" really turnovers (short fields, momentum) rather than fatigue?
  ctrl = ["snaps10", "q2", "q4", "two_min", "margin", "is_pass"]
  print("   robustness of the quick-possession effect (EPA/100, 95% interval):")
  for label, sub, extra in (("all series", s, []),
                            ("+ control for where the series starts", s, ["series_start"]),
                            ("own possession did NOT end in a turnover", s[~s.after_turnover], []),
                            ("no turnover + series-start control", s[~s.after_turnover], ["series_start"])):
    rr = ols_ci(sub, "epa", ["quick"] + extra + ctrl, "dg", n_boot=200)
    print(f"     {label:42s} {100 * rr.at['quick', 'coef']:+.2f} [{100 * rr.at['quick', 'lo']:+.2f}, "
          f"{100 * rr.at['quick', 'hi']:+.2f}]   n={len(sub):,}")
  rr = ols_ci(s[~s.after_turnover], "epa", ["quick", "series_start"] + ctrl, "dg", n_boot=200)
  q_eff = rr.at["quick", "coef"]
  qshare = s[~s.after_turnover].drop_duplicates(["dg", "rest_secs", "series_start"]).groupby(
    ["season", "defteam"]).quick.mean()
  print(f"   team-seasons' share of series after a quick (non-turnover) own possession: mean {qshare.mean():.0%}, "
        f"sd {qshare.std():.0%}, range {qshare.min():.0%}-{qshare.max():.0%}; at {100 * q_eff:+.2f} EPA/100 that moves "
        f"a defense's rating by about {100 * q_eff * qshare.std():.2f} EPA/100 per sd "
        f"(worst offense vs average: {100 * q_eff * (qshare.max() - qshare.mean()):.2f})")

  # What it could mean for ratings: team-seasons differ in snap load; the wear slope x that difference.
  load = p.groupby(["season", "defteam"]).agg(snaps_pg=("dg", lambda x: x.value_counts().mean()))
  slope = r.at["snaps10", "coef"]
  sd_load = load.snaps_pg.std()
  print(f"\n3. SCALE: team-seasons' defensive snaps per game (in this set) vary with sd {sd_load:.1f}; at the wear slope "
        f"that is {100 * slope * sd_load / 10:+.2f} EPA/100 on the ratings, vs a spread of ~3.9 EPA/100 between pass "
        f"defenses and ~4.5 between run defenses.")
  heavy = load.sort_values("snaps_pg", ascending=False).head(5)
  print("   heaviest snap loads: " + ", ".join(f"{t} {s_} {v:.0f}/g" for (s_, t), v in heavy.snaps_pg.items()))
