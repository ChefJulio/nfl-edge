"""Early-week ESPN statuses, calibrated on their own outcomes (owner-approved 2026-10-14; replaces the flat mapping).

Between a team's game and its next official injury report, the bridge (injuries.InjuryModel.espn_bridge) has only
ESPN's feed. Each bridged player falls in one bucket:
  "Out+ret"   ESPN Out with an estimated return date after this week's game (the news, as a date: "miss a couple
              of weeks" -> a return date weeks out)
  "Out"       ESPN Out, no return date past the game
  "Doubtful"  ESPN Doubtful (early in the week ESPN uses it for multi-week injuries too)
  "IR"        injured reserve: a roster rule (4+ games), certainly inactive
Each bucket's P(active) is learned from outcomes: every early-week snapshot in the daily ESPN archive
(tools/espn_snapshot.py; ESPN keeps no history, so it starts 2026-10-13) is matched to whether the player then
played, from the weekly roster's game-day status (INA / reserve = inactive; a week counts once its game-day
inactives are published). Rate = (prior x PRIOR_WEIGHT + actives) / (PRIOR_WEIGHT + cases). Priors, all measured:
  "Out+ret"   how often a player the team lists Out on the final official report plays (2021-25: 0.1% of 5,350):
              a return date after the game says the same thing early (owner, 2026-10-14: the generic early-week Out
              rate treated the return date as if it carried no information)
  "Out", "Doubtful"   the designation's carry-forward rate (how often a player with it last week plays next week)
so each new week of outcomes moves a rate toward what actually happened.
Pre-registered check (2026-10-14): after 4 weeks of outcomes, if "Out+ret" isn't clearly less likely to play than
"Out" (its 90% interval below Out's rate), merge it back into "Out".
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

PRIOR_WEIGHT = 5.0  # the prior counts as this many past cases (small: outcomes take over within a couple of weeks)
STATUS = {"Out": "Out", "Doubtful": "Doubtful", "Injured Reserve": "IR"}
EARLY_DAYS = 3  # a snapshot counts as early-week when taken at least this many days before the game (report day)


def bucket(status: str, return_date, game_day) -> str | None:
  rep = STATUS.get(str(status))
  if rep == "Out" and isinstance(return_date, str) and return_date and game_day is not None:
    if pd.Timestamp(return_date[:10]) > pd.Timestamp(game_day):
      return "Out+ret"
  return rep


def team_games(data, season: int) -> pd.DataFrame:
  s = data.schedules[(data.schedules.season == season) & data.schedules.game_type.isin(["REG", "POST"])]
  g = pd.concat([s[["week", "gameday", "home_team", "home_score"]].set_axis(["week", "day", "team", "score"], axis=1),
                 s[["week", "gameday", "away_team", "home_score"]].set_axis(["week", "day", "team", "score"], axis=1)])
  g["day"] = pd.to_datetime(g.day)
  g["team"] = g.team.replace({"LAR": "LA"})
  return g.sort_values("day")


def cases(hist_dir: Path, data, season: int) -> pd.DataFrame:
  """One row per (player, week) seen early in the week: bucket, and inactive (1 / 0) once known (NaN while pending)."""
  files = sorted(Path(hist_dir).glob("[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].csv")) if hist_dir else []
  if not files:
    return pd.DataFrame(columns=["gsis_id", "week", "bucket", "inactive"])
  r = data.rosters[(data.rosters.season == season) & data.rosters.espn_id.notna() & data.rosters.gsis_id.notna()]
  latest = r.sort_values("week").drop_duplicates("gsis_id", keep="last")
  by_espn = {str(e).split(".")[0]: (g, "LA" if t == "LAR" else t) for e, g, t in zip(latest.espn_id, latest.gsis_id, latest.team)}
  games = team_games(data, season)
  rows = []
  for f in files:
    day = pd.Timestamp(f.stem)
    snap = pd.read_csv(f, dtype=str)
    for x in snap.itertuples():
      hit = by_espn.get(str(x.espn_id))
      if hit is None or STATUS.get(str(x.status)) is None:
        continue
      gsis, team = hit
      tg = games[games.team == team]
      nxt, prev = tg[tg.day > day], tg[(tg.day < day) & tg.score.notna()]
      if nxt.empty or prev.empty:
        continue
      g = nxt.iloc[0]
      if (g.day - day).days < EARLY_DAYS:
        continue  # the official report is out by then: the bridge isn't used
      upd = pd.to_datetime(x.updated, utc=True, errors="coerce")
      if pd.isna(upd) or upd.tz_convert("America/New_York").date() < prev.day.iloc[-1].date():
        continue  # news from before his last game: not a bridge case
      rows.append({"gsis_id": gsis, "week": int(g.week), "day": day, "bucket": bucket(x.status, x.return_date, g.day)})
  if not rows:
    return pd.DataFrame(columns=["gsis_id", "week", "bucket", "inactive"])
  c = pd.DataFrame(rows).sort_values("day").drop_duplicates(["gsis_id", "week"], keep="last")  # the latest early look
  ros = data.rosters[data.rosters.season == season]
  done = set(ros[ros.status == "INA"].week)  # weeks whose game-day inactives are published
  st = ros.drop_duplicates(["gsis_id", "week"], keep="last").set_index(["gsis_id", "week"]).status
  c["inactive"] = [(float(st.get((g, w), "INA") != "ACT") if w in done else float("nan")) for g, w in zip(c.gsis_id, c.week)]
  return c[["gsis_id", "week", "bucket", "inactive"]]


def official_out_rate(data) -> float:
  """P(plays | final official report says Out), from the loaded seasons: injury report x game-day roster status."""
  inj = data.injuries[(data.injuries.report_status == "Out") & (data.injuries.game_type == "REG")]
  # only weeks whose game-day inactives are published (some 2019 weeks lack them: their Out players read as active)
  done = set(zip(data.rosters[data.rosters.status == "INA"].season, data.rosters[data.rosters.status == "INA"].week))
  inj = inj[[(a, b) in done for a, b in zip(inj.season, inj.week)]]
  st = data.rosters.drop_duplicates(["season", "gsis_id", "week"], keep="last").set_index(["season", "gsis_id", "week"]).status
  s = [st.get((a, b, c)) for a, b, c in zip(inj.season, inj.gsis_id, inj.week)]
  s = [v for v in s if v is not None]
  return sum(v == "ACT" for v in s) / len(s) if s else 0.0


def learned_rates(hist_dir: Path, data, season: int, p_next: dict) -> dict:
  """bucket -> {"p": P(active), "n": outcomes seen, "inactive": of them inactive, "prior": prior P(active)}."""
  c = cases(hist_dir, data, season)
  c = c[c.inactive.notna()]
  out = {"IR": {"p": 0.0, "n": int((c.bucket == "IR").sum()), "inactive": int(c[c.bucket == "IR"].inactive.sum()), "prior": 0.0}}
  priors = {"Out": float(p_next.get("Out", 0.5)), "Out+ret": official_out_rate(data), "Doubtful": float(p_next.get("Doubtful", 0.5))}
  for b in ("Out", "Out+ret", "Doubtful"):
    prior = priors[b]
    x = c[c.bucket == b]
    act = float((1 - x.inactive).sum())
    out[b] = {"p": (prior * PRIOR_WEIGHT + act) / (PRIOR_WEIGHT + len(x)), "n": int(len(x)),
              "inactive": int(x.inactive.sum()), "prior": prior}
  return out
