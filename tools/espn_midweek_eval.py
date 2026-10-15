"""Midweek ESPN "Out" rulings during practice week (pre-registered in docs/INSIGHTS.md section 9, 2026-10-15).

Usage: python tools/espn_midweek_eval.py
Needs cache/espn_injury_midweek.parquet (tools/espn_wayback.py --seasons=2022-2024 --days=2,3,4
--out=cache/espn_injury_midweek.parquet) and the usual caches (availhist_*, practice_*, rosters, schedules).

Once a team's practice report is out, production (InjuryModel.availability) uses the practice model only and the
ESPN bridge skips the team, so a player ruled out Thursday after a Wednesday full practice stays ~90% to play
(Hurts, 2026 wk 6). For every player ESPN lists Out / IR at a Wed-Fri capture made after at least one of his team's
practice days was published (22:00 UTC that day) and before the final Friday report (Sunday games only; latest
such capture per player-week), compare:
  baseline  the practice model, walk-forward (seasons before the test season), on the days published by then,
            no game status; players not on the report 0.95
  rule      the ESPN bucket's play rate (espn_calib.bucket: Out+ret / Out; IR = 0), leave-one-season-out
Gate: pooled Brier lower, 95% bootstrap CI of the difference excluding 0, lower in >= 2 of 3 seasons, n >= 100.
"""
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.espn_calib import bucket  # noqa: E402
from nfledge.injuries import practice_features  # noqa: E402

SEASONS = [2022, 2023, 2024]
NOT_ON_REPORT = 0.95
c = D.Cache(ROOT / "cache")
cfg = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8")).get("injuries", {})
GB = {"max_iter": int(cfg.get("gb_iterations", 200)), "learning_rate": float(cfg.get("gb_learning_rate", 0.05)),
      "max_depth": int(cfg.get("gb_max_depth", 3))}

H = pd.read_parquet(ROOT / "cache" / "espn_injury_midweek.parquet")
players = c.get("players", "all", None, stale=False)
gsis_of = {str(e).replace(".0", ""): g for g, e in zip(players.gsis_id, players.espn_id) if isinstance(g, str) and pd.notna(e)}
teams = c.get("teams", "all", None, stale=False).drop_duplicates("team_abbr")
abbr_of = dict(zip(teams.team_name, teams.team_abbr))
sched = c.get("schedules", "since1999", None, stale=False)
AH = pd.concat([pd.read_parquet(ROOT / "cache" / f"availhist_{s}.parquet") for s in range(2018, max(SEASONS) + 1)],
               ignore_index=True)


def practice_model(test_season: int):
  d = AH[(AH.season < test_season) & (AH.game_status != "OUT")]
  X = practice_features(d)
  return HistGradientBoostingClassifier(**GB, random_state=0).fit(X, d.played), list(X.columns)


frames = []
for season in SEASONS:
  rows = []
  model, cols = practice_model(season)
  ros = c.get("rosters", season, None, stale=False)
  done = set(ros.week)
  st = ros.drop_duplicates(["gsis_id", "week"], keep="last").set_index(["gsis_id", "week"]).status
  days = AH[AH.season == season].drop_duplicates(["gsis_id", "week"], keep="last").set_index(["gsis_id", "week"])
  s = sched[(sched.season == season) & (sched.game_type == "REG")]
  g = pd.concat([s[["week", "gameday", "home_team"]].set_axis(["week", "day", "team"], axis=1),
                 s[["week", "gameday", "away_team"]].set_axis(["week", "day", "team"], axis=1)])
  g["day"] = pd.to_datetime(g.day)
  by_team = {t: x.sort_values("day") for t, x in g.groupby("team")}
  for x in H[H.season == season].itertuples():
    gsis, team = gsis_of.get(str(x.espn_id)), abbr_of.get(x.team)
    if gsis is None or team not in by_team:
      continue
    ts = pd.Timestamp(x.ts[:14]).tz_localize("UTC")
    tg = by_team[team]
    nxt = tg[tg.day >= pd.Timestamp(x.captured)]
    if nxt.empty:
      continue
    wk, gday = int(nxt.week.iloc[0]), nxt.day.iloc[0]
    if gday.dayofweek != 6 or wk not in done:  # Sunday games only (Wed/Thu/Fri practice)
      continue
    ret = pd.Timestamp(x.ret).strftime("%Y-%m-%d") if x.ret is not None and pd.notna(x.ret) else None
    b = bucket(x.status, ret, gday.strftime("%Y-%m-%d"))
    if b not in ("Out", "Out+ret", "IR"):
      continue
    # practice days published by the capture: day i (0 = Wed) from 22:00 UTC that day
    k = sum(ts >= (gday - pd.Timedelta(days=4 - i)).tz_localize("UTC") + pd.Timedelta(hours=22) for i in range(3))
    if not 1 <= k <= 2:
      continue
    on = (gsis, wk) in days.index
    dv = days.loc[(gsis, wk)].days if on else ""
    dv = dv if isinstance(dv, str) else ""
    # the strings carry no dates: a short one ("D", "LF") is a player added later in the week, so it covers the
    # LAST days; keep only the days published by the capture ("?" = unknown status, practice_features drops it)
    seen = dv[:max(0, k - (3 - len(dv)))]
    rows.append({"season": season, "week": wk, "gsis_id": gsis, "ts": ts, "bucket": b, "k": k, "on_report": on,
                 "days": seen,
                 "position": days.loc[(gsis, wk)].position if on else x.pos,
                 "played": float(st.get((gsis, wk)) == "ACT"), "name": x.name})
  df = pd.DataFrame(rows)
  if df.empty:
    continue
  df["base"] = NOT_ON_REPORT
  on = df.on_report
  if on.any():
    X = df[on].assign(game_status="None")
    df.loc[on, "base"] = model.predict_proba(practice_features(X)[cols])[:, 1]
  frames.append(df)

R = pd.concat(frames, ignore_index=True).sort_values("ts").drop_duplicates(["season", "week", "gsis_id"], keep="last")
print(f"[midweek] {len(R)} player-weeks ({R.on_report.mean():.0%} on the report), by season:",
      R.groupby("season").size().to_dict(), "by bucket:", R.bucket.value_counts().to_dict(), flush=True)
print("[midweek] play rate by bucket x season:\n", R.pivot_table(index="bucket", columns="season", values="played",
                                                                aggfunc=["mean", "size"]).round(3).to_string())


def loso_rate(b, season):
  if b == "IR":
    return 0.0
  o = R[(R.bucket == b) & (R.season != season)]
  return float(o.played.mean()) if len(o) else float(R[R.season != season].played.mean())


R["rule"] = [loso_rate(b, s) for b, s in zip(R.bucket, R.season)]
R["se_base"], R["se_rule"] = (R.base - R.played) ** 2, (R.rule - R.played) ** 2
d = (R.se_rule - R.se_base).to_numpy()
rng = np.random.default_rng(0)
boot = np.array([d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)])
lo, hi = np.percentile(boot, [2.5, 97.5])
per = R.groupby("season")[["se_base", "se_rule"]].mean()
print("[midweek] Brier by season:\n", per.round(4).to_string())
print(f"[midweek] pooled Brier base {R.se_base.mean():.4f} rule {R.se_rule.mean():.4f}  diff {d.mean():+.4f} "
      f"[{lo:+.4f}, {hi:+.4f}]  seasons better {(per.se_rule < per.se_base).sum()}/{len(per)}", flush=True)
ok = len(R) >= 100 and hi < 0 and (per.se_rule < per.se_base).sum() >= 2
print("[midweek] GATE:", "PASS" if ok else ("INCONCLUSIVE (n < 100)" if len(R) < 100 else "FAIL"))
print("[midweek] on report vs not:\n", R.groupby("on_report")[["played", "base", "rule", "se_base", "se_rule"]].mean()
      .round(3).to_string())
print("[midweek] baseline misses (played <= 0, base >= .5), sample:\n",
      R[(R.played == 0) & (R.base >= .5)][["season", "week", "name", "bucket", "days", "base", "rule"]].head(12).to_string())
R.to_parquet(ROOT / "cache" / "espn_midweek_eval.parquet", index=False)
