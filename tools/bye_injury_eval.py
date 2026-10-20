"""(BG) injured right before a bye (pre-registered 2026-10-20, docs/INSIGHTS.md (BG)).

Usage: python tools/bye_injury_eval.py
For every QB / RB / WR / TE whose team is on bye and whose ESPN status, at the latest capture between his last game
and 4 days before his next game (return_timing.CAPTURES, Wayback 2022-25), is Out / Doubtful / Questionable: did he
play his next game? Today the site reads him 1.0. Variant: the bye rate for his bucket (Out with a return date 7+ days
past that game = "Out+ret", Out, Doubtful, Questionable), measured on bye cases of earlier seasons and shrunk toward the
normal-week rate (same captures, teams not on bye, the same window rule) with 10 pseudo-cases; 2022 uses the normal-week
rates. GATE: (1) Brier vs 1.0 lower, 95% CI over team-byes upper < 0, improvement >= 0.01; (2) mean predicted within 5
points of the played rate.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import run  # noqa: E402
from nfledge import return_timing as RT  # noqa: E402
from nfledge.returns import played_set  # noqa: E402

POS = {"QB", "RB", "WR", "TE"}
K = 10.0


def bucket(status, ret, day) -> str | None:
  if status == "Out":
    return "Out+ret" if pd.notna(ret) and (pd.Timestamp(ret) - day).days >= 7 else "Out"
  return status if status in ("Doubtful", "Questionable") else None


def main():
  d = run.load_all(run.load_config())
  played = played_set(d)
  esp = pd.read_parquet(RT.CAPTURES)
  esp["captured"] = pd.to_datetime(esp.captured)
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
  games["prev_week"] = games.groupby(["team", "season"]).week.shift()
  games = games.dropna(subset=["prev_day"])
  games["bye"] = games.week - games.prev_week > 1  # this game comes right after his team's bye
  rost = d.rosters[d.rosters.season.between(2022, 2025) & d.rosters.position.isin(POS)][["season", "week", "gsis_id", "team"]]
  rost = rost.drop_duplicates(["season", "week", "gsis_id"])
  # players on the team for this game who also played its previous game (hurt after his last game)
  rows = []
  for x in rost.merge(games, on=["season", "week", "team"]).itertuples():
    c = eg.get(x.gsis_id)
    if c is None or (x.season, int(x.prev_week), x.gsis_id) not in played:
      continue
    w = c[(c.captured > x.prev_day) & (c.captured <= x.day - pd.Timedelta(days=4))]
    if not len(w):
      continue
    last = w.iloc[-1]
    b = bucket(last.status, last.ret, x.day)
    if b is None:
      continue
    rows.append({"season": x.season, "week": x.week, "team": x.team, "gsis_id": x.gsis_id, "bye": bool(x.bye),
                 "bucket": b, "y": float((x.season, x.week, x.gsis_id) in played)})
  t = pd.DataFrame(rows)
  print(f"{len(t)} player-games with an ESPN status after the last game ({int(t.bye.sum())} right after a bye)")
  print(t.groupby(["bucket", "bye"]).y.agg(["size", "mean"]).round(3).to_string())
  B = t[t.bye].copy()
  pred = []
  for x in B.itertuples():
    normal = t[(~t.bye) & (t.bucket == x.bucket)]
    nr = normal.y.mean() if len(normal) else 1.0  # normal-week rate (every season: a descriptive prior)
    prior = B[(B.season < x.season) & (B.bucket == x.bucket)]
    pred.append((prior.y.sum() + K * nr) / (len(prior) + K))
  B["p"] = pred
  B["cl"] = B.season.astype(str) + "-" + B.week.astype(str) + "-" + B.team
  B["sb"], B["sv"] = (1.0 - B.y) ** 2, (B.p - B.y) ** 2
  gr = B.groupby("cl").apply(lambda g: pd.Series({"d": (g.sv - g.sb).sum(), "n": len(g)}))
  idx = np.random.default_rng(0).integers(0, len(gr), (4000, len(gr)))
  bt = gr.d.to_numpy()[idx].sum(1) / gr.n.to_numpy()[idx].sum(1)
  diff = (B.sv - B.sb).mean()
  lo, hi = np.percentile(bt, [2.5, 97.5])
  print(f"\nright after a bye: {len(B)} players, {B.cl.nunique()} team-byes, played {B.y.mean():.3f}")
  print(f"(1) Brier vs 1.0: {B.sb.mean():.4f} -> {B.sv.mean():.4f}, {diff:+.4f} [{lo:+.4f}, {hi:+.4f}]  "
        f"{'PASS' if hi < 0 and diff <= -0.01 else 'FAIL'}")
  gap = abs(B.p.mean() - B.y.mean())
  print(f"(2) mean predicted {B.p.mean():.3f} vs played {B.y.mean():.3f}: {'PASS' if gap <= 0.05 else 'FAIL'}")
  print(B.groupby("bucket").agg(n=("y", "size"), played=("y", "mean"), predicted=("p", "mean")).round(3).to_string())
  print("GATE:", "PASS" if hi < 0 and diff <= -0.01 and gap <= 0.05 else "FAIL")


if __name__ == "__main__":
  main()
