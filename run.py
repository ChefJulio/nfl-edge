"""nfl-edge: weekly opponent-adjusted NFL analytics. Usage: python run.py [--week N] [--no-backtest]"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import webbrowser
from pathlib import Path

import pandas as pd

from nfledge import backtest as bt
from nfledge import report as rp
from nfledge.config import ROOT, load_config, load_scoring
from nfledge.data import forecast_wind, load_all
from nfledge.engine import POSITIONS, Engine


def cached_backtest(data, cfg, scoring) -> tuple[pd.DataFrame | None, list[int]]:
  """Walk-forward backtest over last season + this season so far; cached per (final games, config, scoring)."""
  seasons = [data.current_season - 1, data.current_season]
  code = "".join(p.read_text() for p in sorted((ROOT / "nfledge").glob("*.py")))
  key = hashlib.sha1(json.dumps([cfg, scoring.weights, data.latest_week, data.pending_games, len(data.pbp), code],
                                sort_keys=True, default=str).encode()).hexdigest()[:12]
  path = ROOT / cfg["data"]["cache_dir"] / f"backtest_{key}.parquet"
  if path.exists():
    return pd.read_parquet(path), seasons
  print("[run] backtesting (cached after the first run for this data/config)...", flush=True)
  eng = Engine(data, cfg, scoring, POSITIONS)
  res = bt.run(eng, seasons, use_injuries=True)
  res.to_parquet(path)
  return res, seasons


def main():
  ap = argparse.ArgumentParser(description=__doc__)
  ap.add_argument("--week", type=int, help="target week (default: first week with no games played yet)")
  ap.add_argument("--no-backtest", action="store_true", help="skip the backtest section")
  ap.add_argument("--open", action="store_true", help="open the report in a browser when done")
  ap.add_argument("--out", help="output HTML path (default: config [report] output)")
  args = ap.parse_args()

  t0 = time.time()
  cfg, scoring = load_config(), load_scoring()
  data = load_all(cfg, force_week=args.week)
  season, week = data.current_season, data.latest_week + 1
  if args.week:
    week = args.week
  print(f"[run] projecting {season} week {week}", flush=True)

  eng = Engine(data, cfg, scoring, POSITIONS).train(season)
  games = eng.games(season, week)
  if games.empty:
    sys.exit(f"No regular-season games found for {season} week {week}.")
  wind = forecast_wind(games.set_index("game_id"))
  hist_wind = eng.team_ledger.drop_duplicates("game_id").set_index("game_id").wind
  wind = wind.fillna(hist_wind.reindex(wind.index))
  proj = eng.project_week(season, week, use_injuries=True, wind=wind)

  ev, bt_seasons = None, []
  if not args.no_backtest:
    res, bt_seasons = cached_backtest(data, cfg, scoring)
    ev = bt.evaluate(res, POSITIONS, ecr_only=True)

  power, team_luck = rp.team_tables(eng, season, week, cfg)
  inj = data.injuries
  injury_report = bool(((inj.season == season) & (inj.week == week)).any())
  ctx = {
    "season": season, "week": week, "pending": data.pending_games, "scoring": scoring.name,
    "generated": time.strftime("%Y-%m-%d %H:%M"), "injury_report": injury_report,
    "players": rp.player_rankings(proj, cfg), "games": rp.matchups(eng, season, week, cfg),
    "power": power, "team_luck": team_luck, "player_luck": rp.player_luck(eng, proj, season, week),
    "roles": rp.role_changes(eng, season, week, cfg), "backtest": rp.backtest_summary(ev),
    "bt_seasons": " and ".join(map(str, bt_seasons)) or "n/a", "bt_takeaway": backtest_takeaway(ev),
    "margin_disagree": cfg["report"]["margin_disagree"], "total_disagree": cfg["report"]["total_disagree"],
  }
  out = rp.render(ctx, Path(args.out) if args.out else ROOT / cfg["report"]["output"].format(week=week))
  print(f"[run] wrote {out} in {time.time() - t0:.0f}s")
  if args.open:
    webbrowser.open(out.as_uri())


def backtest_takeaway(ev) -> str:
  if ev is None or ev.empty:
    return "Backtest skipped."
  r = ev[ev.subset == "relevant"]
  beats_raw = (r.mae_model < r.mae_raw).sum()
  beats_vegas = (r.mae_model < r.mae_vegas).sum()
  beats_ecr = (r.rank_model > r.rank_ecr).sum() if "rank_ecr" in r else 0
  return (f"The model has a smaller average miss than raw stats at {beats_raw}/{len(r)} positions and than "
          f"Vegas-scaled stats at {beats_vegas}/{len(r)}, and ranks players better than the expert consensus at "
          f"{beats_ecr}/{len(r)}. Expect roughly the average miss shown on any single player each week - weekly "
          f"fantasy scoring is noisy, so use tiers more than exact decimals.")


if __name__ == "__main__":
  main()
