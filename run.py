"""nfl-edge: weekly opponent-adjusted NFL analytics. Usage: python run.py [--week N] [--no-backtest]"""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import sys
import time
import webbrowser
from pathlib import Path

import pandas as pd

from nfledge import backtest as bt
from nfledge import docs
from nfledge import report as rp
from nfledge.config import ROOT, load_config, load_scoring
from nfledge.data import forecast_wind, load_all
from nfledge.engine import POSITIONS, Engine


def model_code() -> str:
  """Source of everything that affects model outputs (report.py and templates only change presentation)."""
  return "".join(p.read_text() for p in sorted((ROOT / "nfledge").glob("*.py")) if p.name not in ("report.py", "docs.py"))


def frame_hash(df) -> int:
  return 0 if df is None else int(pd.util.hash_pandas_object(df, index=False).sum() % (2 ** 61))


def state_key(data, cfg, scoring, *extra) -> str:
  """Changes whenever the inputs that matter change: config, scoring, final games, injury report / practice
  updates, expert rankings, rosters, or model code."""
  inj = data.injuries[data.injuries.season == data.current_season]
  parts = [cfg, scoring.weights, data.latest_week, data.pending_games, len(data.pbp), frame_hash(inj),
           frame_hash(data.practice), frame_hash(data.ecr), len(data.rosters), model_code(), *extra]
  return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:12]


def prune(cache_dir: Path, pattern: str, keep: int = 2):
  files = sorted(cache_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
  for f in files[keep:]:
    f.unlink(missing_ok=True)


def attach_data(eng, data):
  eng.data = eng.pm.data = data
  if getattr(eng, "injury_model", None) is not None:
    eng.injury_model.data = data


def cached_model(data, cfg, scoring, season: int, week: int):
  """Trained engine + this week's projections, cached on disk. Presentation-only changes (report.py, the
  template) reuse it, so a re-render takes seconds instead of minutes."""
  cache_dir = ROOT / cfg["data"]["cache_dir"]
  path = cache_dir / f"model_{state_key(data, cfg, scoring, season, week)}.pkl"
  if path.exists():
    with open(path, "rb") as f:
      eng, proj = pickle.load(f)
    attach_data(eng, data)
    print("[run] reusing cached model + projections (inputs and model code unchanged)", flush=True)
    return eng, proj
  eng = Engine(data, cfg, scoring, POSITIONS).train(season)
  games = eng.games(season, week)
  if games.empty:
    sys.exit(f"No regular-season games found for {season} week {week}.")
  wind = forecast_wind(games.set_index("game_id"))
  hist_wind = eng.team_ledger.drop_duplicates("game_id").set_index("game_id").wind
  wind = wind.fillna(hist_wind.reindex(wind.index))
  proj = eng.project_week(season, week, use_injuries=True, wind=wind)
  attach_data(eng, None)  # raw data is reloaded every run; keep the cache small
  with open(path, "wb") as f:
    pickle.dump((eng, proj), f, protocol=pickle.HIGHEST_PROTOCOL)
  attach_data(eng, data)
  prune(cache_dir, "model_*.pkl")
  return eng, proj


def cached_backtest(data, cfg, scoring) -> tuple[pd.DataFrame | None, list[int]]:
  """Walk-forward backtest over last season + this season so far; cached per data/config/model-code state."""
  seasons = [data.current_season - 1, data.current_season]
  path = ROOT / cfg["data"]["cache_dir"] / f"backtest_{state_key(data, cfg, scoring, 'bt')}.parquet"
  if path.exists():
    return pd.read_parquet(path), seasons
  print("[run] backtesting (cached after the first run for this data/config)...", flush=True)
  eng = Engine(data, cfg, scoring, POSITIONS)
  res = bt.run(eng, seasons, use_injuries=True)
  res.to_parquet(path)
  prune(path.parent, "backtest_*.parquet")
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

  eng, proj = cached_model(data, cfg, scoring, season, week)

  ev, bt_seasons, res = None, [], None
  if not args.no_backtest:
    res, bt_seasons = cached_backtest(data, cfg, scoring)
    ev = bt.evaluate(res, POSITIONS, ecr_only=True)

  power, team_luck = rp.team_tables(eng, season, week, cfg, proj)
  inj = data.injuries
  injury_report = bool(((inj.season == season) & (inj.week == week)).any())
  ctx = {
    "season": season, "week": week, "pending": data.pending_games, "scoring": scoring.name,
    "generated": time.strftime("%Y-%m-%d %H:%M"), "injury_report": injury_report,
    "players": rp.player_rankings(eng, proj, season, week, cfg), "games": rp.matchups(eng, season, week, cfg, proj),
    "power": power, "team_luck": team_luck, "power_vol": rp.league_volume(eng, season, week, eng.tm.fit(season, week)), "player_luck": rp.player_luck(eng, proj, season, week),
    "roles": rp.role_changes(eng, season, week, cfg), "backtest": rp.backtest_summary(ev),
    "bt_seasons": " and ".join(map(str, bt_seasons)) or "n/a", "bt_takeaway": backtest_takeaway(ev),
    "margin_disagree": cfg["report"]["margin_disagree"], "total_disagree": cfg["report"]["total_disagree"],
    "model_doc": docs.render(docs.live_values(eng, cfg, season, week, res, ev)),
  }
  if ctx["model_doc"]["stale"]:
    print("[run] warning: MODEL.md is out of date (model code/config changed); see tools/model_doc.py", flush=True)
  out = rp.render(ctx, Path(args.out) if args.out else ROOT / cfg["report"]["output"].format(week=week))
  check_script(out)
  print(f"[run] wrote {out} in {time.time() - t0:.0f}s")
  if args.open:
    webbrowser.open(out.as_uri())


def check_script(path: Path):
  """Fail loudly if the page's JavaScript does not parse (a syntax error silently kills every button)."""
  import re
  import shutil
  import subprocess
  import tempfile
  node = shutil.which("node")
  if not node:
    return
  js = "\n".join(re.findall(r"<script>(.*?)</script>", path.read_text(encoding="utf-8"), re.S))
  with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
    f.write(js)
  res = subprocess.run([node, "--check", f.name], capture_output=True, text=True)
  Path(f.name).unlink(missing_ok=True)
  if res.returncode != 0:
    sys.exit(f"[run] report JavaScript has a syntax error:\n{res.stderr}")


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
