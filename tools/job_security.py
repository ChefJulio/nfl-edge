"""Job security: when do teams take the job from a HEALTHY starter? (owner 2026-10-15)

Usage: python tools/job_security.py [--pos=QB] [--from=2012]

Descriptive first (the model test is pre-registered separately in docs/INSIGHTS.md). A starter-week: he played 70%+
of the offensive snaps (QB) or led his position group (RB / WR / TE: 50%+ ) in his team's previous game, and he is
not listed Out / Doubtful / on a reserve list this week. Benched: zero snaps while a teammate at his position played
50%+ (a few snaps then out = hurt in the game, not benched). Week 18 is reported separately (rest games). Performance as of
the week, season to date: EPA per dropback (QB) or fantasy points per game (others), as a percentile among that
week's starters at the position. Also: draft round, years of experience, team win %, and whether a first-round
rookie at the position sits behind him.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402

pd.set_option("display.width", 220)


def load(first: int, last: int):
  import nflreadpy as nfl
  c = D.Cache(ROOT / "cache")
  sn, st, inj, ro = [], [], [], []
  for s in range(first, last + 1):
    sn.append(c.get("snaps", s, lambda: nfl.load_snap_counts([s]), stale=False))
    st.append(c.get("pstats_week", s, lambda: nfl.load_player_stats([s], summary_level="week").to_pandas(), stale=False))
    inj.append(c.get("injuries", s, lambda: nfl.load_injuries([s]), stale=False))
    ro.append(c.get("rosters", s, lambda: nfl.load_rosters_weekly([s]), stale=False))
  sch = c.get("schedules", "since1999", None, stale=False)
  dp = c.get("draft", "all", None, stale=False)
  return [pd.concat([x for x in l if x is not None], ignore_index=True) for l in (sn, st, inj, ro)] + [sch, dp]


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  pos, first, last = opt.get("pos", "QB"), int(opt.get("from", 2012)), 2025
  sn, st, inj, ro, sch, dp = load(first, last)
  sn = sn[sn.game_type == "REG"]
  pfr = ro.dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates("pfr_id").set_index("pfr_id").gsis_id
  sn = sn.assign(gsis_id=sn.pfr_player_id.map(pfr)).dropna(subset=["gsis_id"])
  sn = sn[sn.position.replace({"FB": "RB"}) == pos][["season", "week", "team", "gsis_id", "player", "offense_pct"]]
  # team games in order, so "previous game" skips byes
  tg = sn[["season", "team", "week"]].drop_duplicates().sort_values(["season", "team", "week"])
  tg["prev_week"] = tg.groupby(["season", "team"]).week.shift(1)
  sn = sn.merge(tg, on=["season", "team", "week"])
  prev = sn[["season", "team", "week", "gsis_id", "offense_pct"]].rename(columns={"week": "prev_week", "offense_pct": "prev_pct"})
  # the candidate: his previous team game; this game's share (0 if he had no snaps)
  cur = sn[["season", "team", "week", "gsis_id", "offense_pct"]]
  base = prev.merge(tg[["season", "team", "week", "prev_week"]], on=["season", "team", "prev_week"])
  base = base.merge(cur, on=["season", "team", "week", "gsis_id"], how="left").fillna({"offense_pct": 0.0})
  thr = 0.7 if pos == "QB" else 0.5
  if pos != "QB":  # led his position group last game
    lead = base.groupby(["season", "team", "week"]).prev_pct.transform("max")
    base = base[base.prev_pct >= lead - 1e-9]
  base = base[base.prev_pct >= thr]
  # healthy: not Out / Doubtful this week, not on a reserve list
  # healthy = not on the injury report at all that week (a Questionable starter who sits is an injury absence)
  bad = inj[inj.report_status.notna() & (inj.report_status.astype(str) != "")][["season", "week", "gsis_id"]].assign(hurt=True)
  base = base.merge(bad.drop_duplicates(), on=["season", "week", "gsis_id"], how="left")
  res = ro[ro.status.isin(["RES", "INA"]) & ~ro.status_description_abbr.isin(["A01"])][["season", "week", "gsis_id", "status"]]
  base = base.merge(res.drop_duplicates(["season", "week", "gsis_id"]), on=["season", "week", "gsis_id"], how="left")
  # INA = game-day inactive: healthy scratch or injury not on the report; keep it, flag it
  base = base[base.hurt.isna() & (base.status != "RES")]
  other = cur.rename(columns={"gsis_id": "o", "offense_pct": "o_pct"})
  mx = other.groupby(["season", "team", "week"]).o_pct.max().rename("team_max")
  base = base.join(mx, on=["season", "team", "week"])
  # zero snaps (a starter who plays a few snaps and leaves was hurt in the game, not benched)
  base["benched"] = (base.offense_pct <= 0) & (base.team_max >= 0.5)
  # performance to date (games before this week, same season)
  st = st[st.season_type == "REG"]
  if pos == "QB":
    st = st.assign(db=st.attempts.fillna(0) + st.sacks_suffered.fillna(0), epa=st.passing_epa.fillna(0) + st.rushing_epa.fillna(0))
    perf_num, perf_den = "epa", "db"
  else:
    st = st.assign(fp=st.fantasy_points_ppr.fillna(0) - 0.5 * st.receptions.fillna(0), g=1.0)
    perf_num, perf_den = "fp", "g"
  s2 = st[["player_id", "season", "week", perf_num, perf_den]].sort_values(["player_id", "season", "week"])
  s2["cn"] = s2.groupby(["player_id", "season"])[perf_num].cumsum()
  s2["cd"] = s2.groupby(["player_id", "season"])[perf_den].cumsum()
  s2 = s2.rename(columns={"player_id": "gsis_id"})
  base = base.sort_values("week")
  # through his last game before this week (a benched starter has no stat line the week he sat)
  parts = []
  for season_, b_ in base.groupby("season"):
    a_ = s2[s2.season == season_][["gsis_id", "week", "cn", "cd"]].sort_values("week").rename(columns={"week": "w_stat"})
    parts.append(pd.merge_asof(b_.sort_values("week"), a_, left_on="week", right_on="w_stat", by="gsis_id",
                               allow_exact_matches=False))
  base = pd.concat(parts, ignore_index=True)
  base["perf"] = base.cn / base.cd.replace(0, np.nan)
  base["perf_pct"] = base.groupby(["season", "week"]).perf.rank(pct=True)
  # career: draft round, experience
  info = ro.dropna(subset=["gsis_id"]).sort_values("season").drop_duplicates(["gsis_id", "season"])[["gsis_id", "season", "years_exp", "draft_number"]]
  base = base.merge(info, on=["gsis_id", "season"], how="left")
  dn = pd.to_numeric(base.draft_number, errors="coerce")
  base["draft"] = np.select([dn <= 32, dn <= 96, dn.notna()], ["R1", "R2-3", "R4-7"], "UDFA")
  # contract in force that season (OverTheCap via nflverse): APY as a share of the cap; guaranteed money
  c = D.Cache(ROOT / "cache").get("contracts", "all", None, stale=False)
  if c is not None:
    c = c.dropna(subset=["gsis_id", "year_signed"])
    pairs = base[["gsis_id", "season"]].drop_duplicates()
    m = pairs.merge(c[["gsis_id", "year_signed", "last_year", "apy_cap_pct", "guaranteed", "apy"]], on="gsis_id")
    m = m[(m.year_signed <= m.season) & (m.last_year.fillna(m.year_signed) >= m.season)]
    m = m.sort_values("year_signed").drop_duplicates(["gsis_id", "season"], keep="last")
    base = base.merge(m[["gsis_id", "season", "apy_cap_pct", "guaranteed", "apy"]], on=["gsis_id", "season"], how="left")
  # team record before this week
  g = sch[(sch.game_type == "REG") & sch.home_score.notna()]
  rec = pd.concat([pd.DataFrame({"season": g.season, "week": g.week, "team": g.home_team, "w": (g.home_score > g.away_score) + 0.5 * (g.home_score == g.away_score)}),
                   pd.DataFrame({"season": g.season, "week": g.week, "team": g.away_team, "w": (g.away_score > g.home_score) + 0.5 * (g.home_score == g.away_score)})])
  rec["team"] = rec.team.map(lambda x: D.RELOCATED.get(x, x))
  rec = rec.sort_values(["team", "season", "week"])
  rec["wins"] = rec.groupby(["team", "season"]).w.cumsum() - rec.w
  rec["games"] = rec.groupby(["team", "season"]).cumcount()
  base["team"] = base.team.map(lambda x: D.RELOCATED.get(x, x))
  base = base.merge(rec[["team", "season", "week", "wins", "games"]], on=["team", "season", "week"], how="left")
  base["winpct"] = base.wins / base.games.replace(0, np.nan)
  # a first-round rookie at the position on the roster that week (not him)
  rr = ro[(ro.position == pos) & (pd.to_numeric(ro.years_exp, errors="coerce") == 0) & (pd.to_numeric(ro.draft_number, errors="coerce") <= 32)]
  rr = rr.assign(team=rr.team.map(lambda x: D.RELOCATED.get(x, x)))[["season", "week", "team", "gsis_id"]].rename(columns={"gsis_id": "rk"})
  base = base.merge(rr.drop_duplicates(["season", "week", "team"]), on=["season", "week", "team"], how="left")
  base["r1_rookie_behind"] = base.rk.notna() & (base.rk != base.gsis_id)

  # incumbent: he started (70%+ / led the group) his team's first game of the season; otherwise an interim starter
  first_g = sn.groupby(["season", "team"]).week.transform("min") == sn.week
  inc = sn[first_g & (sn.offense_pct >= thr)][["season", "team", "gsis_id"]].assign(incumbent=True)
  inc["team"] = inc.team.map(lambda x: D.RELOCATED.get(x, x))
  base = base.merge(inc.drop_duplicates(), on=["season", "team", "gsis_id"], how="left")
  base["incumbent"] = base.incumbent.fillna(False).astype(bool)
  wk18 = base[base.week >= 18]
  b = base[base.week < 18].copy()
  print(f"{pos} healthy starter-weeks {first}-{last} (weeks 1-17): {len(b)}; benched {int(b.benched.sum())} ({100 * b.benched.mean():.2f}%)")
  print(f"   week 18: {len(wk18)} starter-weeks, {100 * wk18.benched.mean():.1f}% sat (rest / tanking)\n")

  def tab(by, label):
    t = b.groupby(by, observed=True).benched.agg(["size", "sum", "mean"]).rename(columns={"size": "n", "sum": "benched", "mean": "rate"})
    t["rate"] = (100 * t.rate).round(2)
    print(f"by {label}:\n{t}\n")
  b["perf_tier"] = pd.cut(b.perf_pct, [0, .1, .25, .5, .75, 1.0], labels=["bottom 10%", "10-25%", "25-50%", "50-75%", "top 25%"], include_lowest=True)
  b.loc[b.cd.fillna(0) == 0, "perf_tier"] = np.nan
  tab("perf_tier", "season-to-date performance percentile among starters (" + ("EPA per dropback" if pos == "QB" else "fantasy pts/g") + ")")
  tab("incumbent", "season-opening starter (False = interim starter)")
  b = b[b.incumbent].copy()
  print(f"INCUMBENT starters only from here: {len(b)} starter-weeks, benched {int(b.benched.sum())} ({100 * b.benched.mean():.2f}%)")
  print()
  tab("perf_tier", "performance percentile (incumbents)")
  tab("draft", "draft round")
  b["exp"] = pd.cut(pd.to_numeric(b.years_exp, errors="coerce"), [-1, 0, 2, 5, 30], labels=["rookie", "2-3 yrs", "4-6 yrs", "7+ yrs"])
  tab("exp", "experience")
  b["rec_tier"] = pd.cut(b.winpct, [-0.01, 0.3, 0.5, 0.7, 1.0], labels=["<30% wins", "30-50%", "50-70%", "70%+"])
  tab("rec_tier", "team record")
  tab("r1_rookie_behind", "first-round rookie behind him")
  if "apy_cap_pct" in b:
    b["cap_tier"] = pd.cut(b.apy_cap_pct, [-0.001, 0.01, 0.03, 0.07, 0.12, 1.0],
                           labels=["<1% of cap", "1-3%", "3-7%", "7-12%", "12%+"])
    tab("cap_tier", "contract: average pay as a share of the cap")
    w2 = b[b.perf_tier.notna() & b.cap_tier.notna()]
    w2 = w2.assign(perf2=np.where(w2.perf_tier.isin(["bottom 10%", "10-25%"]), "bottom 25%", "top 75%"),
                   pay2=np.where(w2.apy_cap_pct >= 0.07, "paid 7%+ of cap", "paid <7%"))
    t = w2.groupby(["perf2", "pay2"]).benched.agg(["size", "sum", "mean"])
    t["mean"] = (100 * t["mean"]).round(2)
    print("sunk cost? performance x pay:")
    print(t, "\n")
  w = b[b.perf_tier.notna()]
  low = w[w.perf_tier.isin(["bottom 10%", "10-25%"])]
  print("bottom-25% performers by team record:")
  print((low.groupby("rec_tier", observed=True).benched.agg(["size", "mean"]).assign(mean=lambda x: (100 * x["mean"]).round(1))), "\n")
  print("benchings of top-half performers (rare cases):")
  top = w[w.perf_tier.isin(["50-75%", "top 25%"]) & w.benched]
  print(top[["season", "week", "team", "gsis_id", "perf_pct", "winpct", "draft", "r1_rookie_behind"]].merge(
    sn[["gsis_id", "player"]].drop_duplicates("gsis_id"), on="gsis_id", how="left").to_string(index=False))
  base.assign(draft_number=pd.to_numeric(base.draft_number, errors="coerce"), years_exp=pd.to_numeric(base.years_exp, errors="coerce")).to_parquet(ROOT / "cache" / f"job_security_{pos}.parquet")


if __name__ == "__main__":
  main()
