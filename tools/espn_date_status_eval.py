"""(BI) a return date on a Doubtful / Questionable ESPN listing (pre-registered 2026-10-20, docs/INSIGHTS.md (BI)).

Usage: python tools/espn_date_status_eval.py
For QB / RB / WR / TE: the latest ESPN capture between his team's previous game and its next (return_timing.CAPTURES,
Wayback 2022-25), status Doubtful or Questionable, with a return date 7+ days past that next game: did he play it?
GATE: n >= 30, played <= 5%, 95% Wilson upper bound <= 10% -> they join the "Out+ret" bucket (1.8%).
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

import run  # noqa: E402
from nfledge import return_timing as RT  # noqa: E402
from nfledge.returns import played_set  # noqa: E402

POS = {"QB", "RB", "WR", "TE"}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
  if not n:
    return float("nan"), float("nan")
  p = k / n
  c = (p + z * z / (2 * n)) / (1 + z * z / n)
  h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
  return c - h, c + h


def main():
  d = run.load_all(run.load_config())
  played = played_set(d)
  esp = pd.read_parquet(RT.CAPTURES)
  esp["captured"] = pd.to_datetime(esp.captured)
  esp["ret"] = pd.to_datetime(esp.ret, errors="coerce")
  r = d.rosters.dropna(subset=["espn_id", "gsis_id"])
  r = r[r.position.isin(POS)]
  by = {str(e).split(".")[0]: g for e, g in zip(r.espn_id, r.gsis_id)}
  esp = esp[esp.espn_id.astype(str).isin(by)].assign(gsis_id=lambda x: x.espn_id.astype(str).map(by)).sort_values("captured")
  eg = {g: x for g, x in esp.groupby("gsis_id")}
  s = d.schedules[(d.schedules.game_type == "REG") & d.schedules.season.between(2022, 2025)]
  games = pd.concat([s[["season", "week", "gameday", "home_team"]].set_axis(["season", "week", "day", "team"], axis=1),
                     s[["season", "week", "gameday", "away_team"]].set_axis(["season", "week", "day", "team"], axis=1)])
  games["day"] = pd.to_datetime(games.day)
  games = games.sort_values(["team", "season", "week"])
  games["prev_day"] = games.groupby(["team", "season"]).day.shift()
  games = games.dropna(subset=["prev_day"])
  rost = d.rosters[d.rosters.season.between(2022, 2025) & d.rosters.position.isin(POS)][["season", "week", "gsis_id", "team"]]
  rows = []
  for x in rost.drop_duplicates(["season", "week", "gsis_id"]).merge(games, on=["season", "week", "team"]).itertuples():
    c = eg.get(x.gsis_id)
    if c is None:
      continue
    w = c[(c.captured > x.prev_day) & (c.captured < x.day)]
    if not len(w):
      continue
    last = w.iloc[-1]
    if last.status not in ("Doubtful", "Questionable") or pd.isna(last.ret):
      continue
    days = (last.ret - x.day).days
    rows.append({"status": last.status, "days": days, "y": (x.season, x.week, x.gsis_id) in played})
  t = pd.DataFrame(rows)
  g = t[t.days >= 7]
  k, n = int(g.y.sum()), len(g)
  lo, hi = wilson(k, n)
  print(f"Doubtful / Questionable with a return date 7+ days past the game: {n} cases, {k} played ({k / max(n, 1):.1%}), "
        f"95% {lo:.1%}-{hi:.1%}")
  print(g.groupby("status").y.agg(["size", "mean"]).round(3).to_string())
  m = t[t.days.between(1, 6)]
  print(f"\nreported: date 1-6 days past the game: {len(m)} cases, played {m.y.mean():.1%}")
  print(m.groupby("status").y.agg(["size", "mean"]).round(3).to_string())
  ok = n >= 30 and k / n <= 0.05 and hi <= 0.10
  print("GATE:", "PASS" if ok else "FAIL")


if __name__ == "__main__":
  main()
