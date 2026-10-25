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
from nfledge import returns
from nfledge.week_clock import Clock
from nfledge.config import ROOT, load_config, load_scoring
from nfledge.data import forecast_wind, load_all
from nfledge.engine import POSITIONS, Engine
from nfledge.team_model import sunday_refit


def model_code() -> str:
  """Source of everything that affects model outputs (docs.PRESENTATION files only change presentation)."""
  return "".join(p.read_text() for p in sorted((ROOT / "nfledge").glob("*.py")) if p.name not in docs.PRESENTATION)


def frame_hash(df) -> int:
  return 0 if df is None else int(pd.util.hash_pandas_object(df, index=False).sum() % (2 ** 61))


def state_key(data, cfg, scoring, *extra, completed_only: bool = False) -> str:
  """Changes whenever the inputs that matter change: config, scoring, final games, injury report / practice
  updates, expert rankings, rosters, or model code. completed_only (the backtest, which scores finished weeks):
  this season's report rows count only through the last completed week, so a new practice report doesn't rerun it."""
  def done(df):
    if df is None or not completed_only or "week" not in df:
      return df
    return df[(df.season < data.current_season) | (df.week <= data.latest_week)]
  inj = done(data.injuries[data.injuries.season == data.current_season])
  parts = [docs.model_config(cfg), scoring.weights, data.latest_week, data.pending_games, len(data.pbp), frame_hash(inj),
           frame_hash(done(data.practice)), frame_hash(done(data.ecr)), len(data.rosters), model_code(), *extra]
  return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:12]


def training_data(data) -> dict:
  """(2026-10-24, owner: Barkley 33% live vs 65% on a local build of the same code and week) a fingerprint of the
  history the engine trains on. The engine key had only row counts, and the history tables are cached per season
  and never refetched, so two caches built at different times trained different injury models under one key."""
  cur = data.current_season
  past = lambda df: None if df is None else df[df.season < cur] if "season" in df else df  # noqa: E731
  return {"avail_hist": frame_hash(data.avail_hist), "injuries": frame_hash(past(data.injuries)),
          "practice": frame_hash(past(data.practice)), "snaps": frame_hash(past(getattr(data, "snaps", None)))}


LOCK = ROOT / "data" / "history" / "training_fingerprint.json"


def check_training_lock(data) -> None:
  """Stop the build when the training history differs from the locked fingerprint (tools/training_lock.py): the same
  code must train the same model everywhere; a change to that history is a decision (--bless), never silent."""
  if not LOCK.exists():
    return
  want = json.loads(LOCK.read_text(encoding="utf-8")).get("tables", {})
  have = {k: f"{v:x}" for k, v in training_data(data).items()}
  bad = [k for k in want if have.get(k) != want[k]]
  if bad:
    raise SystemExit(f"[run] STOP: the training history differs from the locked fingerprint in {', '.join(bad)} "
                     f"(this cache {', '.join(have[k] for k in bad)}; locked {', '.join(want[k] for k in bad)}). "
                     "Find out why (new season, nflverse revision, refetch), then: python tools/training_lock.py --bless")


def train_key(data, cfg, scoring, season: int) -> str:
  """The trained engine's inputs: everything state_key has except this season's injury reports, practice and expert
  ranks, which training never reads (it fits on earlier seasons; scratch/train_cache_equiv.py checked an engine
  trained without the newest report week, practice week, ECR week and roster week projects identically). Final
  games (len(pbp), latest_week) stay in: the engine carries the team model's play history."""
  parts = [docs.model_config(cfg), scoring.weights, data.latest_week, data.pending_games, len(data.pbp),
           len(data.rosters), model_code(), season, training_data(data)]
  return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:12]


def trained_engine(data, cfg, scoring, season: int):
  """Engine.train, cached on train_key: an injury / practice / ECR update re-projects in seconds instead of
  retraining (~4-5 min of the build)."""
  cache_dir = ROOT / cfg["data"]["cache_dir"]
  path = cache_dir / f"engine_{train_key(data, cfg, scoring, season)}.pkl"
  check_training_lock(data)
  td = training_data(data)
  print("[run] training data: " + " ".join(f"{k} {v:x}" for k, v in td.items())
        + (f" ({len(data.avail_hist):,} practice weeks, seasons {int(data.avail_hist.season.min())}-{int(data.avail_hist.season.max())})"
           if data.avail_hist is not None else ""), flush=True)
  if data.avail_hist is not None:
    by = data.avail_hist.groupby("season").played.agg(["size", "mean"])
    print("[run] practice weeks by season: " + ", ".join(f"{int(k)} {int(v['size'])}/{v['mean']:.3f}" for k, v in by.iterrows()), flush=True)
  if path.exists():
    with open(path, "rb") as f:
      eng = pickle.load(f)
    attach_data(eng, data)
    print("[run] reusing the trained engine (final games, config and model code unchanged)", flush=True)
    return eng
  eng = Engine(data, cfg, scoring, POSITIONS).train(season)
  attach_data(eng, None)
  with open(path, "wb") as f:
    pickle.dump(eng, f, protocol=pickle.HIGHEST_PROTOCOL)
  attach_data(eng, data)
  prune(cache_dir, "engine_*.pkl")
  return eng


def prune(cache_dir: Path, pattern: str, keep: int = 2):
  files = sorted(cache_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
  for f in files[keep:]:
    f.unlink(missing_ok=True)


def attach_data(eng, data):
  eng.data = eng.pm.data = data
  if getattr(eng, "injury_model", None) is not None:
    eng.injury_model.data = data


def cached_model(data, cfg, scoring, season: int, week: int, espn_bridge: dict | None = None, espn_hist: Path | None = None,
                 espn_midweek: dict | None = None, espn_questionable: dict | None = None, espn_gameday: dict | None = None,
                 espn_active: dict | None = None, espn_late: dict | None = None, espn_active_note: dict | None = None):
  """Trained engine + this week's projections, cached on disk. Presentation-only changes (report.py, the
  template) reuse it, so a re-render takes seconds instead of minutes. espn_bridge (live week only): early-week
  ESPN injury statuses (InjuryModel.build_espn_bridge); part of the cache key, so new ESPN news re-projects.
  espn_hist: the daily ESPN snapshot archive, whose outcomes calibrate the bridge's buckets (espn_calib.py); its
  file list is part of the key too, so a new day of snapshots (and with it new outcomes) re-projects. espn_midweek:
  ESPN Out / IR rulings after a team's report started (build_espn_bridge(midweek=True)); also in the key."""
  cache_dir = ROOT / cfg["data"]["cache_dir"]
  hist_files = sorted(f.name for f in espn_hist.glob("*.csv")) if espn_bridge and espn_hist and espn_hist.is_dir() else []
  bridge_key = ("_" + hashlib.sha1(json.dumps([sorted(espn_bridge.items()), hist_files]).encode()).hexdigest()[:8]
                if espn_bridge else "")
  if espn_midweek:
    bridge_key += "_m" + hashlib.sha1(json.dumps(sorted(espn_midweek.items())).encode()).hexdigest()[:8]
  if espn_gameday:  # (AU) game-day actives / inactives
    bridge_key += "_g" + hashlib.sha1(json.dumps(sorted((k, v[0]) for k, v in espn_gameday.items())).encode()).hexdigest()[:8]
  el = getattr(data, "elevated", None)
  if el is not None and len(el):  # practice-squad elevations for this week (nfledge/elevations.py): new ones re-project
    bridge_key += "_e" + hashlib.sha1(json.dumps(sorted(el.gsis_id)).encode()).hexdigest()[:8]
  if espn_questionable:  # display only, but it's in the cached projections' status column
    bridge_key += "_q" + hashlib.sha1(json.dumps(sorted(espn_questionable)).encode()).hexdigest()[:8]
  if espn_active_note:  # {#late-upgrade}: notes decide activated players' designation removal
    bridge_key += "_n" + hashlib.sha1(json.dumps(sorted(espn_active_note.items())).encode()).hexdigest()[:8]
  if espn_late:  # {#late-downgrade}
    bridge_key += "_l" + hashlib.sha1(json.dumps(sorted((k, list(v)) for k, v in espn_late.items())).encode()).hexdigest()[:8]
  if espn_active:  # tags only, but they're in the cached projections
    bridge_key += "_a" + hashlib.sha1(json.dumps(sorted(espn_active.items())).encode()).hexdigest()[:8]
  path = cache_dir / f"model_{state_key(data, cfg, scoring, season, week)}{bridge_key}.pkl"
  if path.exists():
    with open(path, "rb") as f:
      eng, proj = pickle.load(f)
    attach_data(eng, data)
    print("[run] reusing cached model + projections (inputs and model code unchanged)", flush=True)
    return eng, proj
  eng = trained_engine(data, cfg, scoring, season)
  if espn_midweek and eng.injury_model is not None:
    eng.injury_model.espn_midweek = espn_midweek
  if espn_questionable and eng.injury_model is not None:
    eng.injury_model.espn_questionable = espn_questionable
  if espn_active and eng.injury_model is not None:
    eng.injury_model.espn_active = espn_active
  if espn_late and eng.injury_model is not None:
    eng.injury_model.espn_late = espn_late
  if espn_active_note and eng.injury_model is not None:
    eng.injury_model.espn_active_note = espn_active_note
  if espn_gameday and eng.injury_model is not None:
    eng.injury_model.espn_gameday = espn_gameday
  if espn_bridge and eng.injury_model is not None:
    from nfledge.espn_calib import learned_rates
    eng.injury_model.espn_bridge = espn_bridge
    eng.injury_model.espn_rates = learned_rates(espn_hist, data, season, eng.injury_model.p_next) if espn_hist else None
    if eng.injury_model.espn_rates:
      print("[run] ESPN early-week rates: " + ", ".join(f"{b} {v['p']:.0%} active ({v['n']} outcomes)"
                                                         for b, v in eng.injury_model.espn_rates.items()), flush=True)
  # Monday currency (owner 2026-10-19, after (BA)): once the week's games through Sunday are final with their plays
  # in, the current week's ratings take them in (after training, so no training row sees it; Monday night stays out)
  rf = sunday_refit(data.schedules, eng.tm.plays["pass"], season, week)
  if rf:
    eng.tm.set_live(season, week, *rf)
    print(f"[run] ratings include this week's {len(rf[0])} games through Sunday ({len(rf[1])} Monday game(s) to come)", flush=True)
  games = eng.games(season, week)
  if games.empty:
    sys.exit(f"No regular-season games found for {season} week {week}.")
  wind = forecast_wind(games.set_index("game_id"))
  hist_wind = eng.team_ledger.drop_duplicates("game_id").set_index("game_id").wind
  wind = wind.fillna(hist_wind.reindex(wind.index))
  # reserve-list players whose practice window is open are this week's candidates too (returns.window_open)
  proj = eng.project_week(season, week, use_injuries=True, wind=wind, extra_cands=returns.window_open(data, week))
  attach_data(eng, None)  # raw data is reloaded every run; keep the cache small
  with open(path, "wb") as f:
    pickle.dump((eng, proj), f, protocol=pickle.HIGHEST_PROTOCOL)
  attach_data(eng, data)
  prune(cache_dir, "model_*.pkl")
  return eng, proj


def cached_backtest(data, cfg, scoring) -> tuple[pd.DataFrame | None, list[int]]:
  """Walk-forward backtest over last season + this season so far; cached per data/config/model-code state."""
  seasons = [data.current_season - 1, data.current_season]
  path = ROOT / cfg["data"]["cache_dir"] / f"backtest_{state_key(data, cfg, scoring, 'bt', completed_only=True)}.parquet"
  if path.exists():
    return pd.read_parquet(path), seasons
  print("[run] backtesting (cached after the first run for this data/config)...", flush=True)
  eng = Engine(data, cfg, scoring, POSITIONS)
  res = bt.run(eng, seasons, use_injuries=True)
  res.to_parquet(path)
  prune(path.parent, "backtest_*.parquet")
  return res, seasons


def week_chrono(data, season: int, week: int) -> dict:
  """The week's injury chronology for the page (nfledge/chronology.py to_json): per team, each report day's state."""
  from nfledge.injuries import chrono
  c = chrono(data, season, week)
  if c is None:
    return {}
  for t, ds in sorted(c.overdue().items()):
    print(f"[run] WARNING: {t}'s practice report for {', '.join(ds)} is overdue (past the 4 p.m. ET deadline, not on NFL.com)", flush=True)
  return c.to_json()


def display_week(data, now: pd.Timestamp | None = None) -> int:
  """The week the page shows (nfledge/week_clock.py): the week being played until 06:00 ET on the Tuesday after its
  last game (a Monday night game is still 'this week'; a game not final holds it), then the next week."""
  return Clock(data.schedules, now).current_week(data.current_season)


FIRST_ARCHIVE_SEASON = 2021


def week_nav(data, season: int, week: int, current_week: int, prefix: str) -> dict:
  """Season / week picker: every regular-season week from FIRST_ARCHIVE_SEASON on, up to the current week.
  The current week lives at index.html; every other week at <season>/week-<NN>.html. `prefix` is the path from
  this page back to the site root ("" for index.html, "../" for an archived week)."""
  s = data.schedules
  reg = s[s.game_type == "REG"]
  cur = data.current_season
  seasons = {}
  for yr in range(FIRST_ARCHIVE_SEASON, cur + 1):
    last = int(reg[reg.season == yr].week.max())  # current season too: later weeks are lookahead pages
    seasons[str(yr)] = {str(w): (f"{prefix}index.html" if (yr == cur and w == current_week)
                                 else f"{prefix}{yr}/week-{w:02d}.html") for w in range(1, last + 1)}
  return {"seasons": seasons, "season": str(season), "week": str(week),
          "is_current": season == cur and week == current_week, "current_href": f"{prefix}index.html"}


def with_weather(games: list, wk, live: bool) -> list:
  """The live week's games get a display-only forecast (data.forecast_conditions): wind, rain chance, snow."""
  if live and len(wk):
    from nfledge.data import forecast_conditions
    try:
      wx = forecast_conditions(wk)
    except Exception:  # weather is decoration: never fail a build over it
      wx = {}
    for g in games:
      if g["id"] in wx:
        g["wx"] = wx[g["id"]]
  return games


def build_page(eng, data, cfg, scoring, season: int, week: int, proj, nav: dict, res=None, ev=None,
               bt_seasons=(), archive: bool = False, lookahead: int = 0, plan: dict | None = None,
               site_dir: Path | None = None) -> dict:
  """Everything one season / week page needs (shared by run.py and tools/build_archive.py); report.render turns
  it into the page's JSON."""
  # Power's arrows and trend read the season's earlier archived pages (site_dir/<season>/week-NN.json), so they show
  # what those pages show (owner 2026-10-20: week 5's page said 14th, week 6's arrow implied 15th)
  published = {}
  if site_dir is not None and not lookahead:
    for w in range(1, week):
      f = Path(site_dir) / str(season) / f"week-{w:02d}.json"
      if f.exists():
        try:
          published[w] = {r["team"]: (r["rank"], r["net"]) for r in json.loads(f.read_text(encoding="utf-8")).get("power") or []}
        except (ValueError, KeyError):
          pass
  power = rp.team_tables(eng, season, week, cfg, proj, plan=plan, current=not (archive or lookahead), published=published)
  wk = data.schedules[(data.schedules.season == season) & (data.schedules.week == week)
                      & (data.schedules.game_type == "REG")]
  n_final, n_games = int(wk.home_score.notna().sum()), len(wk)
  inj = data.injuries
  injury_report = bool(((inj.season == season) & (inj.week == week)).any())
  return {
    "season": season, "week": week, "pending": data.pending_games, "scoring": scoring.name,
    "n_final": n_final, "n_games": n_games, "has_actuals": n_final > 0, "nav": nav, "archive": archive,
    "lookahead": lookahead, "data_week": int(data.latest_week) if lookahead else week - 1,
    "generated": time.strftime("%Y-%m-%d %H:%M"), "injury_report": injury_report,
    "clock": Clock(data.schedules).to_json(season, week),
    "players": rp.player_rankings(eng, proj, season, week, cfg),
    # every rostered player's official injury tag (InjuryModel.tag_map; owner 2026-10-21): byes and deep backups too
    "tags": (eng.injury_model.tag_map(season, week, proj) if eng.injury_model is not None and not (archive or lookahead) else {}),
    # team -> this week's report days and their state (nfledge/chronology.py; the one report calendar): "not listed =
    # full" only on a filed day; one past its deadline (+ grace) and not in is overdue, shown, never read as "practiced
    # fully" (owner 2026-10-22: "if anything is missing it's not silent")
    "chrono": (week_chrono(data, season, week) if not (archive or lookahead) else {}),
    "games": with_weather(rp.matchups(eng, season, week, cfg, proj, power), wk, live=not (archive or lookahead)),
    # the current week's games the ratings already count (Power's "through Sunday" label; playoff_odds' Elo)
    "refit": ({"through": sorted(eng.tm.live[2]), "pending": sorted(eng.tm.live[3])}
              if eng.tm.live and eng.tm.live[:2] == (season, week) and not (archive or lookahead) else None),
    "power": power, "teams": rp.team_info(data.teams), "power_vol": rp.league_volume(eng, season, week, eng.tm.fit(season, week)),
    "roles": rp.role_changes(eng, season, week, cfg), "backtest": rp.backtest_summary(ev),
    "bt_seasons": " and ".join(map(str, bt_seasons)) or "n/a", "bt_takeaway": backtest_takeaway(ev),
    "score_cfg": rp.scoring_settings(scoring, cfg), "tier_cfg": cfg["tiers"],
    "track": rp.track_record(data.schedules, season, week, cfg["report"]["tossup_below"]),
    "tossup_pct": round(cfg["report"]["tossup_below"] * 100),
    # Only the current week renders the Model tab text; it is written to data/model.json at the site root, which
    # every page (archived and lookahead too) loads, so every page shows the same, current description.
    "site_url": cfg["report"].get("site_url"),
    "model_doc": (None if (archive or lookahead)
                  else docs.render(docs.live_values(eng, cfg, season, week, res, ev))),
  }


def gb_cfg(cfg) -> dict:
  g = cfg.get("injuries", {})
  return {"max_iter": int(g.get("gb_iterations", 200)), "learning_rate": float(g.get("gb_learning_rate", 0.05)),
          "max_depth": int(g.get("gb_max_depth", 3))}


def build_lookahead(eng, data, cfg, scoring, season: int, week: int, site: Path, plan: dict):
  """Every later week of the season, projected from today's data: real opponents, current ratings and depth
  charts, Vegas lines once posted (else the model's own). Injuries: nothing is known that far out, so everyone on
  the active roster is assumed healthy (IR stays off the roster); no weather. Rebuilt every run, never archived."""
  s = data.schedules
  last = int(s[(s.season == season) & (s.game_type == "REG")].week.max())
  t0 = time.time()
  weeks = list(range(week + 1, last + 1))
  # Players out injured now: P(active) each later week from the return-timing model; under 50% he sits and his
  # volume is redistributed (same binary rule as the current week); injured-reserve players expected back return.
  # plan: the build's one availability plan (returns.availability_plan, (AM)): the chain from this week's chance for
  # every player the injury model lists; IR players on the direct return-timing model, fed ESPN's live feed
  avail, status, extra = plan["avail"], plan["status"], plan["extra"]
  for w in weeks:
    proj = eng.project_week(season, w, use_injuries=True, quiet=True, avail_override=avail.get(w, {}),
                            status_override=status.get(w, {}), extra_cands=extra.get(w))
    ctx = build_page(eng, data, cfg, scoring, season, w, proj,
                     nav=week_nav(data, season, w, week, prefix="../"), lookahead=w - week, plan=plan)
    check_script(rp.render(ctx, site / str(season) / f"week-{w:02d}.html"))
  print(f"[run] lookahead weeks {week + 1}-{last} in {time.time() - t0:.0f}s", flush=True)


def main():
  ap = argparse.ArgumentParser(description=__doc__)
  ap.add_argument("--week", type=int, help="week to show (default: the week being played, until Tuesday 06:00 ET)")
  ap.add_argument("--no-backtest", action="store_true", help="skip the backtest section")
  ap.add_argument("--open", action="store_true", help="open the report in a browser when done")
  ap.add_argument("--out", help="output HTML path (default: config [report] output)")
  ap.add_argument("--lookahead", action="store_true",
                  help="also build the rest of the season's weeks next to --out (<season>/week-NN.html)")
  args = ap.parse_args()

  t0 = time.time()
  cfg, scoring = load_config(), load_scoring()
  data = load_all(cfg, force_week=args.week)
  season, week = data.current_season, (args.week or display_week(data))
  print(f"[run] projecting {season} week {week}", flush=True)

  # Early-week bridge (nfledge/espn.py, espn_calib.py): the live week only, never --week rebuilds or backtests.
  bridge, midweek, quest, feed, gameday, active, late, notes = {}, {}, {}, None, {}, {}, {}, {}
  if not args.week:
    from nfledge.espn import fetch_injuries
    from nfledge.injuries import InjuryModel
    feed = fetch_injuries()
    data.espn_feed = feed  # read by Power's QB availability (powerc._newly: ESPN's IR list)
    from nfledge.espn import gameday_rulings
    gf = ((Path(args.out) if args.out else ROOT / cfg["report"]["output"].format(week=week)).parent
          / "data" / "live_inputs" / f"gameday_{season}_{week:02d}.json")  # this week's rulings so far (written below)
    gameday = gameday_rulings(data, feed, saved=json.loads(gf.read_text(encoding="utf-8")) if gf.exists() else None)
    if gameday:
      print(f"[run] game-day rulings (ESPN, past inactives): {sum(v[0] == 'INA' for v in gameday.values())} inactive, "
            f"{sum(v[0] == 'ACT' for v in gameday.values())} active", flush=True)
    bridge = InjuryModel.build_espn_bridge(data, season, week, feed)
    if bridge:
      print(f"[run] ESPN early-week injury news for {len(bridge)} players (official report not out)", flush=True)
    midweek = InjuryModel.build_espn_bridge(data, season, week, feed, midweek=True)
    quest = InjuryModel.build_espn_bridge(data, season, week, feed, questionable=True)  # display only
    active = InjuryModel.build_espn_bridge(data, season, week, feed, active=True)  # tags only
    late = InjuryModel.build_espn_bridge(data, season, week, feed, late=True)  # {#late-downgrade}
    notes = InjuryModel.build_espn_bridge(data, season, week, feed, active=True, notes=True)  # {#late-upgrade}
    if midweek:
      print(f"[run] ESPN midweek Out / Doubtful / IR rulings for {len(midweek)} players (report out, no final status yet)", flush=True)
  if not args.week:  # practice-squad elevations announced for this week's games (live only; Engine.candidates)
    from nfledge.elevations import this_week
    data.elevated = this_week(data, season, week)
    if len(data.elevated):
      print(f"[run] elevated from the practice squad: {', '.join(f'{r.full_name} ({r.team})' for r in data.elevated.itertuples())}", flush=True)
  out_path = Path(args.out) if args.out else ROOT / cfg["report"]["output"].format(week=week)
  eng, proj = cached_model(data, cfg, scoring, season, week, espn_bridge=bridge,
                           espn_hist=out_path.parent / "data" / "espn_injuries", espn_midweek=midweek,
                           espn_questionable=quest, espn_gameday=gameday, espn_active=active, espn_late=late, espn_active_note=notes)

  ev, bt_seasons, res = None, [], None
  if not args.no_backtest:
    res, bt_seasons = cached_backtest(data, cfg, scoring)
    ev = bt.evaluate(res, POSITIONS, ecr_only=True)

  # (AM) the live build's one availability plan, as of this week: every page's projections and Power read it
  plan = None if args.week else returns.availability_plan(data, proj, week, feed, ROOT / cfg["data"]["cache_dir"], gb_cfg(cfg),
                                                          espn_rates=getattr(eng.injury_model, "espn_rates", None))
  ctx = build_page(eng, data, cfg, scoring, season, week, proj,
                   nav=week_nav(data, season, week, display_week(data) if not args.week else week, prefix=""),
                   res=res, ev=ev, bt_seasons=bt_seasons, plan=plan,
                   site_dir=(Path(args.out).parent if args.out else None))
  if ctx["model_doc"]["stale"]:
    print("[run] warning: MODEL.md is out of date (model code/config changed); see tools/model_doc.py", flush=True)
  out = rp.render(ctx, Path(args.out) if args.out else ROOT / cfg["report"]["output"].format(week=week))
  check_script(out)
  if not args.week:  # what this live build fed the model (lines, wind, ECR scrape, projections), for live-vs-backtest checks
    from nfledge import live_inputs
    f = live_inputs.write(out.parent, data, eng.games(season, week), proj, season, week)
    print(f"[run] live inputs archived -> {f.name}", flush=True)
    if gameday and "pre_gameday" in proj:  # (AU) every game-day override with the model's chance before it, for the audit
      gf = out.parent / "data" / "live_inputs" / f"gameday_{season}_{week:02d}.json"
      log = json.loads(gf.read_text(encoding="utf-8")) if gf.exists() else {}
      for x in proj[proj.pre_gameday.notna()].itertuples():
        e = log.setdefault(x.gsis_id, {"name": x.full_name, "team": x.team, "pos": x.pos,
                                       "pre": round(float(x.pre_gameday), 4)})  # pre: the chance before the first ruling
        if e.get("ruling") != gameday[x.gsis_id][0]:  # new, or ESPN reversed it: the latest ruling stands
          e.update(ruling=gameday[x.gsis_id][0], at=gameday[x.gsis_id][1], post=round(float(x.avail), 4), status=x.status)
      gf.write_text(json.dumps(log, indent=0), encoding="utf-8")
      print(f"[run] game-day overrides archived: {len(log)} -> {gf.name}", flush=True)
    if "pre_up" in proj and proj.pre_up.notna().any():  # {#late-upgrade}, for its audit
      uf = out.parent / "data" / "live_inputs" / f"upgraded_{season}_{week:02d}.json"
      log = json.loads(uf.read_text(encoding="utf-8")) if uf.exists() else {}
      for x in proj[proj.pre_up.notna()].itertuples():
        log.setdefault(x.gsis_id, {"name": x.full_name, "team": x.team, "pos": x.pos, "days": x.days,
                                   "pre": round(float(x.pre_up), 4), "post": round(float(x.avail), 4),
                                   "at": (active or {}).get(x.gsis_id)})
      uf.write_text(json.dumps(log, indent=0), encoding="utf-8")
      print(f"[run] designation-removed overrides archived: {len(log)} -> {uf.name}", flush=True)
    if "pre_act" in proj and proj.pre_act.notna().any():  # {#activated}, for its audit
      af = out.parent / "data" / "live_inputs" / f"activated_{season}_{week:02d}.json"
      log = json.loads(af.read_text(encoding="utf-8")) if af.exists() else {}
      for x in proj[proj.pre_act.notna()].itertuples():
        log.setdefault(x.gsis_id, {"name": x.full_name, "team": x.team, "pos": x.pos, "status": x.status,
                                   "pre": round(float(x.pre_act), 4), "post": round(float(x.avail), 4),
                                   "at": (active or {}).get(x.gsis_id)})
      af.write_text(json.dumps(log, indent=0), encoding="utf-8")
      print(f"[run] activation overrides archived: {len(log)} -> {af.name}", flush=True)
    if "pre_late" in proj and proj.pre_late.notna().any():  # {#late-downgrade}, for its audit
      lf = out.parent / "data" / "live_inputs" / f"espnlate_{season}_{week:02d}.json"
      log = json.loads(lf.read_text(encoding="utf-8")) if lf.exists() else {}
      for x in proj[proj.pre_late.notna()].itertuples():
        r_ = (late or {}).get(x.gsis_id, ("", ""))
        log.setdefault(x.gsis_id, {"name": x.full_name, "team": x.team, "pos": x.pos, "ruling": r_[0],
                                   "pre": round(float(x.pre_late), 4), "post": round(float(x.avail), 4), "at": r_[1]})
      lf.write_text(json.dumps(log, indent=0), encoding="utf-8")
      print(f"[run] late-downgrade overrides archived: {len(log)} -> {lf.name}", flush=True)
    if "pre_cleared" in proj and proj.pre_cleared.notna().any():  # ESPN Active before the final report, for its audit
      af = out.parent / "data" / "live_inputs" / f"espnactive_{season}_{week:02d}.json"
      log = json.loads(af.read_text(encoding="utf-8")) if af.exists() else {}
      for x in proj[proj.pre_cleared.notna()].itertuples():
        log.setdefault(x.gsis_id, {"name": x.full_name, "team": x.team, "pos": x.pos, "days": x.days,
                                   "pre": round(float(x.pre_cleared), 4), "post": round(float(x.avail), 4),
                                   "at": (active or {}).get(x.gsis_id)})  # the first sighting stands
      af.write_text(json.dumps(log, indent=0), encoding="utf-8")
      print(f"[run] ESPN-Active overrides archived: {len(log)} -> {af.name}", flush=True)
  if args.lookahead and plan is not None:
    build_lookahead(eng, data, cfg, scoring, season, week, out.parent, plan)
  print(f"[run] wrote {out} in {time.time() - t0:.0f}s")
  if args.open:
    webbrowser.open(out.as_uri())


_scripts_ok = False


def check_script(path: Path):
  """Fail loudly if a site script does not parse (a syntax error silently kills every tab): node --check on every
  assets/*.js the page loads (the page itself is a static shell with one inline line of config). Once per run."""
  import shutil
  import subprocess
  global _scripts_ok
  node = shutil.which("node")
  if _scripts_ok or not node:
    return
  _scripts_ok = True
  for js in sorted((ROOT / "nfledge" / "static").glob("*.js")):
    res = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
    if res.returncode != 0:
      sys.exit(f"[run] {js.name} has a syntax error:\n{res.stderr}")


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
