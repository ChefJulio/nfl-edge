"""How good are ESPN's injury statuses and estimated return dates early in the week? Scored on the Wayback backfill
(tools/espn_wayback.py -> cache/espn_injury_history.parquet, 2022-25 Monday / Tuesday captures).

Usage: python tools/espn_return_eval.py
For each player listed early in a week (capture >= 3 days before his team's next game, after its last game), the
bucket the live bridge would use (nfledge/espn_calib.py) and whether he played that week (weekly roster game-day
status: ACT = active). Return dates: days between ESPN's estimate and his first game back (first week ACT).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402

c = D.Cache(ROOT / "cache")
H = pd.read_parquet(ROOT / "cache" / "espn_injury_history.parquet")
players = c.get("players", "all", None, stale=False)
gsis_of = {str(e).replace(".0", ""): g for g, e in zip(players.gsis_id, players.espn_id) if isinstance(g, str) and pd.notna(e)}
teams = c.get("teams", "all", None, stale=False).drop_duplicates("team_abbr")
abbr_of = dict(zip(teams.team_name, teams.team_abbr))
sched = c.get("schedules", "since1999", None, stale=False)
STATUS = {"Out": "Out", "Doubtful": "Doubtful", "Questionable": "Questionable", "Injured Reserve": "IR"}

rows = []
for season, h in H.groupby("season"):
  ros = c.get("rosters", season, None, stale=False)
  done = set(ros[ros.status == "INA"].week)
  st = ros.drop_duplicates(["gsis_id", "week"], keep="last").set_index(["gsis_id", "week"]).status
  s = sched[(sched.season == season) & sched.game_type.isin(["REG", "POST"])]
  g = pd.concat([s[["week", "gameday", "home_team", "home_score"]].set_axis(["week", "day", "team", "score"], axis=1),
                 s[["week", "gameday", "away_team", "home_score"]].set_axis(["week", "day", "team", "score"], axis=1)])
  g["day"] = pd.to_datetime(g.day)
  g = g.sort_values("day")
  by_team = {t: x for t, x in g.groupby("team")}
  for x in h.itertuples():
    status = STATUS.get(str(x.status))
    gsis, team = gsis_of.get(str(x.espn_id)), abbr_of.get(x.team)
    if status is None or gsis is None or team not in by_team:
      continue
    tg, day = by_team[team], pd.Timestamp(x.captured)
    nxt = tg[tg.day > day]
    if nxt.empty or (nxt.day.iloc[0] - day).days < 3:
      continue
    wk, gday = int(nxt.week.iloc[0]), nxt.day.iloc[0]
    if wk not in done:
      continue
    ret = pd.Timestamp(x.ret) if x.ret is not None and pd.notna(x.ret) else None
    b = "Out+ret" if status == "Out" and ret is not None and ret > gday else status
    # first game back: the first team game from this one on where he was active
    back = None
    for w2, d2 in zip(nxt.week, nxt.day):
      if int(w2) in done and st.get((gsis, int(w2))) == "ACT":
        back = d2
        break
    rows.append({"season": season, "gsis_id": gsis, "week": wk, "captured": day, "status": status, "bucket": b,
                 "ret": ret, "game": gday, "played": float(st.get((gsis, wk)) == "ACT"), "back": back, "pos": x.pos})
r = pd.DataFrame(rows).sort_values("captured").drop_duplicates(["gsis_id", "season", "week"], keep="last")


def ci(k, n, z=1.645):  # Wilson 90%
  if n == 0:
    return (np.nan, np.nan)
  p = k / n
  den = 1 + z * z / n
  mid = (p + z * z / (2 * n)) / den
  half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
  return (mid - half, mid + half)


print(f"{len(r)} early-week listings, {r.season.min()}-{r.season.max()}\n")
print("Played that week, by bucket (90% interval):")
for b, x in r.groupby("bucket"):
  lo, hi = ci(x.played.sum(), len(x))
  print(f"  {b:13s} n={len(x):5d}  played {x.played.mean():6.1%}  [{lo:.1%}, {hi:.1%}]")
print("\nOut, by ESPN's return date vs this week's game:")
o = r[r.status == "Out"].copy()
o["gap"] = [(rt - gd).days if rt is not None else None for rt, gd in zip(o.ret, o.game)]
bins = [(-999, -1, "return date before the game"), (0, 0, "return date = game day"), (1, 6, "1-6 days after"),
        (7, 13, "1-2 weeks after"), (14, 999, "2+ weeks after")]
for lo_, hi_, name in bins:
  x = o[o.gap.between(lo_, hi_)]
  if len(x):
    a, b_ = ci(x.played.sum(), len(x))
    print(f"  {name:30s} n={len(x):5d}  played {x.played.mean():6.1%}  [{a:.1%}, {b_:.1%}]")
x = o[o.gap.isna()]
print(f"  {'no return date':30s} n={len(x):5d}  played {x.played.mean():6.1%}")
print("\nReturn-date accuracy (Out / Doubtful / IR with an estimate; actual = first game back):")
q = r[r.ret.notna() & r.back.notna() & r.status.isin(["Out", "Doubtful", "IR"])].copy()
q["err"] = [(bk - rt).days for bk, rt in zip(q.back, q.ret)]
print(f"  n={len(q)}  median error {q.err.median():+.0f} days (+ = came back later than estimated)")
print(f"  within a week: {(q.err.abs() <= 6).mean():.0%}   later than estimated by 7+ days: {(q.err >= 7).mean():.0%}   earlier by 7+ days: {(q.err <= -7).mean():.0%}")
# The two misses cost different things: back EARLIER than estimated = we'd call an active player out; back LATER =
# the estimate was optimistic (harmless for "out this week", wrong for later weeks).
print("\n  Split by direction (game-week granularity: within 3 days counts as on time):")
print(f"  {'':9s} {'n':>5s}  {'on time':>8s}  {'earlier':>8s} {'(median)':>9s}  {'later':>7s} {'(median)':>9s}")
for stt, x in [("All", q)] + list(q.groupby("status")):
  early, late = x[x.err < -3], x[x.err > 3]
  print(f"  {stt:9s} {len(x):5d}  {(x.err.abs() <= 3).mean():8.0%}  {len(early) / len(x):8.0%} {early.err.median() if len(early) else float('nan'):+9.0f}  "
        f"{len(late) / len(x):7.0%} {late.err.median() if len(late) else float('nan'):+9.0f}")
# What matters for the bridge: when ESPN's date is after this week's game, how often was he back for it anyway?
o2 = q[(q.status == "Out") & (q.ret > q.game)]
if len(o2):
  print(f"\n  Out with a return date after this week's game: n={len(o2)}, back for this week's game anyway {(o2.back <= o2.game).mean():.1%}")
  early_by = o2.assign(gap=[(rt - gd).days for rt, gd in zip(o2.ret, o2.game)])
  for lo_, hi_, name in [(1, 6, "date 1-6 days after"), (7, 13, "1-2 weeks after"), (14, 999, "2+ weeks after")]:
    x = early_by[early_by.gap.between(lo_, hi_)]
    if len(x):
      print(f"    {name:20s} n={len(x):4d}  back for this week's game {(x.back <= x.game).mean():6.1%}")

# The bridge's priors (nfledge/espn_calib.py reads them): early-week play rates per bucket, with "Out+ret" = an
# estimated return at least RET_DAYS after this week's game (closer dates are mostly ESPN's next-game placeholder and
# play like a plain Out: 1-6 days after -> 28% played; 7+ days -> 1.7%).
import json  # noqa: E402
RET_DAYS = 7
r["b2"] = ["Out+ret" if st == "Out" and rt is not None and (rt - gd).days >= RET_DAYS else st
           for st, rt, gd in zip(r.status, r.ret, r.game)]
pri = {b: {"n": int(len(x)), "played": int(x.played.sum())} for b, x in r.groupby("b2") if b in ("Out", "Out+ret", "Doubtful")}
pri["ret_days"] = RET_DAYS
pri["source"] = f"Wayback captures of espn.com/nfl/injuries, Mon/Tue {r.season.min()}-{r.season.max()} (tools/espn_return_eval.py)"
(ROOT / "data" / "history" / "espn_early_week.json").write_text(json.dumps(pri, indent=1), encoding="utf-8")
print("\npriors written:", {k: v for k, v in pri.items() if isinstance(v, dict)})
