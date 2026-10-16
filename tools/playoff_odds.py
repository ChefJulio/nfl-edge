"""Playoff odds for Teams > Playoffs (data/playoffs/odds.json) and their walk-forward track record.

Usage:
  python tools/playoff_odds.py [--site=site] [--sims=10000]   live: the current season as of the week the site shows
  python tools/playoff_odds.py --backtest [--sims=1000]         2021-2025: odds as of every week vs what happened
                                                                (data/history/playoff_odds_backtest.json, committed; read by the live run)
Method: every finished game counts as played. Each remaining regular-season game is decided by a coin weighted with
the chance the Matchups tab shows: the market's (Vegas spread through the fitted k) when a line exists, else our
model's (power-rank gap + Elo + home field, config [report.win_model]), with ranks and Elo held at their current
values. Each simulated season is seeded with the NFL tiebreakers (nfledge/standings.py; simulated games add no
points, so the points-based steps use games already played) and the playoffs are played out with the real format:
seed 1 has the bye, the lowest remaining seed visits seed 1 after the wild-card round (reseeding), higher seeds
host, the Super Bowl is neutral. Playoff games use our model's chance.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge import elo  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.report import logistic, vegas_win_k  # noqa: E402
from nfledge.standings import RELOCATED, League, playoff_teams_per_conf  # noqa: E402

V = 1
STAGES = ["playoffs", "div", "bye", "div_round", "conf_game", "sb", "title"]


def model_p(home: str, away: str, neutral: bool, ranks: dict, elo_now: dict, wm: dict) -> float:
  ra, rh = ranks.get(away), ranks.get(home)
  x = (wm["home"] * (not neutral) + wm["elo_per_100"] * (elo_now.get(home, elo.MEAN) - elo_now.get(away, elo.MEAN)) / 100
       + (wm["rank_gap"] * (ra - rh) if ra and rh else 0.0))
  return float(logistic(x))


def simulate(sched, teams, season: int, week: int, ranks: dict, wm: dict, n: int, rng, lines_weeks=None, drift: float = 0.0,
             keep: bool = False, played_before: int | None = None) -> dict:
  """Monte Carlo of the rest of `season` from before `week`'s games. lines_weeks: weeks whose Vegas lines may be used
  (None = every line on file, the live case; the backtest passes {week}: lines known at that time).
  drift: team strength isn't fixed for the rest of the season. Each simulated season gives every team a strength
  shift ~ N(0, drift x sqrt(share of the season left)) in log-odds, added to all its remaining games (and playoff
  games), so far-off games are less certain than next week's. Fit on the backtest (see backtest_drift)."""
  reg = sched[(sched.season == season) & (sched.game_type == "REG")].copy()
  reg["home_team"], reg["away_team"] = reg.home_team.replace(RELOCATED), reg.away_team.replace(RELOCATED)
  # played_before: count only games before that week (pre-week odds with today's lines, for the odds-by-week chart)
  cut = played_before if played_before is not None else (week if lines_weeks is not None else None)
  played = reg[reg.home_score.notna() & (reg.week < cut)] if cut is not None else reg[reg.home_score.notna()]
  left = reg.drop(played.index)
  L0 = League.from_schedule(played.assign(game_type="REG"), teams, season)
  elo_now = elo.ratings_before(sched, season, week, wm)
  k = vegas_win_k(sched, season, week)
  p = []
  for g in left.itertuples():
    use_line = pd.notna(g.spread_line) and (lines_weeks is None or g.week in lines_weeks)
    p.append(float(logistic(k * g.spread_line)) if use_line else model_p(g.home_team, g.away_team, g.location == "Neutral", ranks, elo_now, wm))
  p = np.array(p)
  homes, aways = list(left.home_team), list(left.away_team)
  n_weeks = int(reg.week.max())
  sd = drift * np.sqrt(max(0, n_weeks - week + 1) / n_weeks)
  x0 = np.log(p.clip(1e-6, 1 - 1e-6) / (1 - p.clip(1e-6, 1 - 1e-6)))
  n_po = playoff_teams_per_conf(season)
  all_teams = sorted(L0.div)
  idx = {t: i for i, t in enumerate(all_teams)}
  count = {s: np.zeros(len(all_teams)) for s in STAGES}
  seed_count = np.zeros((len(all_teams), n_po))
  wins = np.zeros(len(all_teams))
  X = np.zeros((n, 3, len(all_teams)), bool) if keep else None  # per sim: made playoffs / won division / top seed
  base_w = np.array([L0.overall(t).w + 0.5 * L0.overall(t).t for t in all_teams])
  shock = rng.normal(0, sd, (n, 32)) if sd > 0 else np.zeros((n, 32))  # per sim, per team (index in all_teams)
  hi, ai = np.array([idx[t] for t in homes], dtype=int), np.array([idx[t] for t in aways], dtype=int)
  ps = 1 / (1 + np.exp(-(x0[None, :] + shock[:, hi] - shock[:, ai]))) if len(p) else np.zeros((n, 0))
  hw = rng.random((n, len(p))) < ps  # home wins
  def pm(h, a, neutral=False):
    x = np.log(1 / model_p(h, a, neutral, ranks, elo_now, wm) - 1) * -1 + cur[idx[h]] - cur[idx[a]]
    return 1 / (1 + np.exp(-x))
  for s in range(n):
    cur = shock[s]
    by = {t: list(v) for t, v in L0.by.items()}
    for t in all_teams:
      by.setdefault(t, [])
    for h, a, w in zip(homes, aways, hw[s]):
      by[h].append((a, 1.0 if w else 0.0, 0.0, 0.0)); by[a].append((h, 0.0 if w else 1.0, 0.0, 0.0))
      wins[idx[h if w else a]] += 1
    L = League.from_results(by, L0.conf, L0.div)
    seeds = L.seeds(n_po)
    champs = []
    for conf, order in seeds.items():
      for i, t in enumerate(order):
        seed_count[idx[t], i] += 1
        count["playoffs"][idx[t]] += 1
        if i < 4:
          count["div"][idx[t]] += 1
        if keep:
          X[s, 0, idx[t]] = True
          X[s, 1, idx[t]] = i < 4
          X[s, 2, idx[t]] = i == 0
      count["bye"][idx[order[0]]] += 1
      # wild card: 2v7, 3v6, 4v5 (higher seed hosts); seed 1 waits
      alive = [order[0]]
      for hi, lo in ((1, 6), (2, 5), (3, 4)):  # 7-team format (2020 on: the only seasons simulated here)
        h, a = order[hi], order[lo]
        alive.append(h if rng.random() < pm(h, a) else a)
      alive.sort(key=lambda t: order.index(t))
      for t in alive:
        count["div_round"][idx[t]] += 1
      # divisional (reseeded): top vs lowest remaining, the other two
      g1 = (alive[0], alive[-1]); g2 = (alive[1], alive[2])
      conf_teams = [g[0] if rng.random() < pm(*g) else g[1] for g in (g1, g2)]
      conf_teams.sort(key=lambda t: order.index(t))
      for t in conf_teams:
        count["conf_game"][idx[t]] += 1
      h, a = conf_teams
      champ = h if rng.random() < pm(h, a) else a
      count["sb"][idx[champ]] += 1
      champs.append(champ)
    a, b = champs
    count["title"][idx[a if rng.random() < pm(a, b, True) else b]] += 1
  rows = []
  for t in all_teams:
    i = idx[t]
    r = L0.overall(t)
    rows.append({"team": t, "conf": L0.conf[t], "div": L0.div[t], "w": int(r.w), "l": int(r.l), "t": int(r.t),
                 "exp_w": round(float(base_w[i] + wins[i] / n), 1), **{f"p_{s}": round(float(count[s][i] / n), 4) for s in STAGES},
                 "seeds": [round(float(x / n), 4) for x in seed_count[i]]})
  out = {"rows": rows, "n": n, "n_po": n_po}
  if keep:
    out["ctx"] = {"by0": L0.by, "conf": L0.conf, "div": L0.div, "teams": all_teams, "n_po": n_po, "X": X, "hw": hw,
                  "games": left.assign(p_home=p).reset_index(drop=True)}
  return out


def _outcomes(args) -> np.ndarray:
  """Worker: playoff / division / top-seed indicators (rows x 3 x teams) for full sets of simulated results."""
  by0, conf, div, teams, n_po, homes, aways, rows = args
  idx = {t: i for i, t in enumerate(teams)}
  out = np.zeros((len(rows), 3, len(teams)), bool)
  for r, row in enumerate(rows):
    by = {t: list(by0.get(t, [])) for t in teams}
    for h, a, w in zip(homes, aways, row):
      by[h].append((a, 1.0 if w else 0.0, 0.0, 0.0)); by[a].append((h, 0.0 if w else 1.0, 0.0, 0.0))
    for order in League.from_results(by, conf, div).seeds(n_po).values():
      for i, t in enumerate(order):
        out[r, 0, idx[t]] = True
        out[r, 1, idx[t]] = i < 4
        out[r, 2, idx[t]] = i == 0
  return out


def _run_rows(ctx, rows: list, jobs: int) -> np.ndarray:
  g = ctx["games"]
  base = (ctx["by0"], ctx["conf"], ctx["div"], ctx["teams"], ctx["n_po"], list(g.home_team), list(g.away_team))
  if jobs <= 1 or len(rows) < 200:
    return _outcomes((*base, rows))
  from concurrent.futures import ProcessPoolExecutor
  k = -(-len(rows) // (jobs * 4))
  with ProcessPoolExecutor(jobs) as ex:
    parts = list(ex.map(_outcomes, [(*base, rows[i:i + k]) for i in range(0, len(rows), k)]))
  return np.concatenate(parts)


def rooting(res: dict, week: int, n_flip: int = 2000, n_case: int = 500, jobs: int = 1) -> dict:
  """Rooting guide for `week`'s unplayed games (owner 2026-10-15; PFF's paired flip). For each of the first n_flip
  simulated seasons and each game, the standings are re-run with only that game's result flipped, so P(X | home wins)
  and P(X | away wins) come from the same seasons and the swing is the game's own effect (splitting seasons by who won
  mixes in noise from every other game). X = make playoffs / win division / top seed. Conditional odds = full-run odds
  plus the paired change. Per team, best / worst case = this week's games all going its preferred / other way
  (preferred = sign of its playoff swing, else division, else top seed), on the first n_case seasons."""
  ctx = res["ctx"]
  g = ctx["games"]
  wk = np.flatnonzero((g.week == week).to_numpy())
  if not len(wk):
    return {}
  X, hw = ctx["X"], ctx["hw"]
  nf, nc = min(n_flip, len(X)), min(n_case, len(X))
  rows = []
  for s in range(nf):
    for j in wk:
      r = hw[s].copy(); r[j] = not r[j]; rows.append(r)
  F = _run_rows(ctx, rows, jobs).reshape(nf, len(wk), 3, -1)
  base = X[:nf, None]
  home_won = hw[:nf, wk][:, :, None, None]
  Xh, Xa = np.where(home_won, base, F), np.where(home_won, F, base)
  d = Xh.astype(np.int8) - Xa.astype(np.int8)
  swing, se = d.mean(0), d.std(0) / np.sqrt(nf)
  p0 = X.mean(0)
  ph = p0[None] + (Xh.astype(float) - base).mean(0)
  pa = p0[None] + (Xa.astype(float) - base).mean(0)
  T = len(ctx["teams"])
  pref = np.zeros((T, len(wk)), bool)
  for t in range(T):
    for gi in range(len(wk)):
      sw = swing[gi, :, t]
      m = next((m for m in range(3) if abs(sw[m]) >= 0.001), 0)
      pref[t, gi] = sw[m] >= 0
  rows = []
  for t in range(T):
    for want in (True, False):
      for s in range(nc):
        r = hw[s].copy(); r[wk] = pref[t] if want else ~pref[t]; rows.append(r)
  C = _run_rows(ctx, rows, jobs).reshape(T, 2, nc, 3, T)
  clip = lambda v: round(float(min(1.0, max(0.0, v))), 4)  # noqa: E731
  out = {"week": int(week), "n_flip": nf, "n_case": nc, "teams": {},
         "games": [{"id": x.game_id, "home": x.home_team, "away": x.away_team, "p_home": round(float(x.p_home), 3),
                    "day": str(x.gameday), "time": str(getattr(x, "gametime", "") or "")} for x in g.iloc[wk].itertuples()]}
  for t, team in enumerate(ctx["teams"]):
    case = p0[:, t][None] + (C[t, :, :, :, t].astype(float) - X[None, :nc, :, t]).mean(1)  # 2 x 3
    out["teams"][team] = {
      # per game: [swing (P | home wins - P | away wins) x3, its standard error x3, P | home wins x3, P | away wins x3]
      # for make playoffs / win division / top seed
      "g": [[[round(float(v), 4) for v in swing[gi, :, t]], [round(float(v), 4) for v in se[gi, :, t]],
             [clip(v) for v in ph[gi, :, t]], [clip(v) for v in pa[gi, :, t]]] for gi in range(len(wk))],
      "best": [clip(v) for v in case[0]], "worst": [clip(v) for v in case[1]]}
  return out


def odds_history(sched, teams, wm, site: Path, archive: Path, season: int, week: int, drift: float, ranks_now: dict) -> dict:
  """Odds going into each week of `season` (make playoffs / division / top seed): the odds-by-week chart. Kept in
  <site>/data/playoffs/hist_<season>.json (committed to the archive branch by CI). The current week is recomputed every
  run (games before it only, today's ranks and lines); past weeks are kept once written, and missing ones are rebuilt
  as of that week (that week's archived power ranks, the lines known then)."""
  f = site / "data" / "playoffs" / f"hist_{season}.json"
  h = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"season": season, "weeks": {}}
  rng = np.random.default_rng(season * 100 + week)
  snap = lambda res: {r["team"]: [r["p_playoffs"], r["p_div"], r["p_bye"]] for r in res["rows"]}  # noqa: E731
  for w in range(1, week):
    if str(w) in h["weeks"]:
      continue
    rk = week_ranks(site, season, w) or week_ranks(archive, season, w)
    if rk:
      h["weeks"][str(w)] = snap(simulate(sched, teams, season, w, rk, wm, 2000, rng, lines_weeks={w}, drift=drift))
  h["weeks"][str(week)] = snap(simulate(sched, teams, season, week, ranks_now, wm, 4000, rng, lines_weeks=None, drift=drift,
                                        played_before=week))
  f.parent.mkdir(parents=True, exist_ok=True)
  f.write_text(json.dumps(h, separators=(",", ":")), encoding="utf-8")
  return h


def team_schedules(sched, season: int) -> dict:
  """Per team: [week, opponent, home (1/0), points for, points against, 'Oct 25'] for every regular-season game."""
  reg = sched[(sched.season == season) & (sched.game_type == "REG")]
  out = {}
  for g in reg.itertuples():
    h, a = RELOCATED.get(g.home_team, g.home_team), RELOCATED.get(g.away_team, g.away_team)
    d = pd.to_datetime(g.gameday)
    day = f"{d:%b} {d.day}"
    hs, as_ = (None, None) if pd.isna(g.home_score) else (int(g.home_score), int(g.away_score))
    out.setdefault(h, []).append([int(g.week), a, 1, hs, as_, day])
    out.setdefault(a, []).append([int(g.week), h, 0, as_, hs, day])
  return {t: sorted(v) for t, v in out.items()}


def likely_seeding(rows: list[dict], n_po: int) -> dict:
  """Most likely team in each seed slot per conference (greedy by probability, each team once), with its chance."""
  out = {}
  for conf in ("AFC", "NFC"):
    rs = [r for r in rows if r["conf"] == conf]
    cand = sorted(((r["seeds"][s], s, r["team"]) for r in rs for s in range(n_po)), reverse=True)
    taken_s, taken_t, slots = set(), set(), {}
    for pr, s, t in cand:
      if s in taken_s or t in taken_t:
        continue
      slots[s] = {"seed": s + 1, "team": t, "p": pr}; taken_s.add(s); taken_t.add(t)
    out[conf] = [slots[s] for s in sorted(slots)]
  return out


def week_ranks(site_like: Path, season: int, week: int) -> dict:
  f = site_like / str(season) / f"week-{week:02d}.json"
  if not f.exists():
    return {}
  d = json.loads(f.read_text(encoding="utf-8"))
  return {RELOCATED.get(r["team"], r["team"]): r["rank"] for r in d.get("power") or []}


def backtest_records(sched, teams, wm, sims: int, archive: Path, drift: float, seasons=range(2021, 2026)) -> pd.DataFrame:
  """Odds as of every week of each season (ranks from that week's archived page) next to what happened."""
  rng = np.random.default_rng(7)
  recs = []
  for season in seasons:
    final = League.from_schedule(sched, teams, season)
    seeds = final.seeds(playoff_teams_per_conf(season))
    made = {t for o in seeds.values() for t in o}
    divw = {o[0] for o in final.division_order().values()}
    bye = {o[0] for o in seeds.values()}
    sb = sched[(sched.season == season) & (sched.game_type == "SB")]
    champ = None
    if len(sb):
      g = sb.iloc[0]
      champ = RELOCATED.get(g.home_team if g.home_score > g.away_score else g.away_team, g.home_team if g.home_score > g.away_score else g.away_team)
    n_weeks = int(sched[(sched.season == season) & (sched.game_type == "REG")].week.max())
    for week in range(1, n_weeks + 1):
      ranks = week_ranks(archive, season, week)
      res = simulate(sched, teams, season, week, ranks, wm, sims, rng, lines_weeks={week}, drift=drift)
      for r in res["rows"]:
        recs.append({"season": season, "week": week, "team": r["team"], "p_playoffs": r["p_playoffs"], "p_div": r["p_div"],
                     "p_bye": r["p_bye"], "p_title": r["p_title"], "y_playoffs": int(r["team"] in made), "y_div": int(r["team"] in divw),
                     "y_bye": int(r["team"] in bye), "y_title": int(r["team"] == champ)})
    print(f"[odds backtest] drift {drift}: {season}", flush=True)
  return pd.DataFrame(recs)


def summarize(d: pd.DataFrame, sims: int, drift: float) -> dict:
  out = {"seasons": f"{d.season.min()}-{d.season.max()}", "sims": sims, "drift": drift, "rows": len(d), "brier": {}, "calibration": []}
  for m in ("playoffs", "div", "bye", "title"):
    p, y = d[f"p_{m}"], d[f"y_{m}"]
    out["brier"][m] = {"model": round(float(((p - y) ** 2).mean()), 4), "base_rate": round(float(((y.mean() - y) ** 2).mean()), 4)}
  bins = [0, .05, .15, .3, .5, .7, .85, .95, 1.0001]
  d["bin"] = pd.cut(d.p_playoffs, bins, right=False)
  for b, g in d.groupby("bin", observed=True):
    out["calibration"].append({"bin": f"{round(b.left * 100)}-{min(100, round(b.right * 100))}%", "n": int(len(g)),
                               "predicted": round(float(g.p_playoffs.mean()) * 100, 1), "actual": round(float(g.y_playoffs.mean()) * 100, 1)})
  by_week = []
  for lo, hi in ((1, 4), (5, 9), (10, 14), (15, 18)):
    g = d[d.week.between(lo, hi)]
    by_week.append({"weeks": f"{lo}-{hi}", "brier": round(float(((g.p_playoffs - g.y_playoffs) ** 2).mean()), 4),
                    "base_rate": round(float(((g.y_playoffs.mean() - g.y_playoffs) ** 2).mean()), 4)})
  out["by_week"] = by_week
  return out


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = Path(opt.get("site", "site"))
  import nflreadpy as nfl
  cfg = load_config()
  wm = cfg["report"]["win_model"]
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  current = int(nfl.get_current_season())
  sched = cache.get("schedules", "since1999", lambda: nfl.load_schedules(list(range(1999, current + 1))),
                    stale=cache.age_hours("schedules", "since1999") > 6)
  teams = cache.get("teams", "all", lambda: nfl.load_teams(), stale=False)
  # The track record is committed (it needs the archive worktree, which CI does not check out); rerun --backtest
  # after any change to the odds method and commit the file.
  bt_path = ROOT / "data" / "history" / "playoff_odds_backtest.json"
  if "--backtest" in sys.argv:
    archive = Path(opt.get("archive", ROOT.parent / "nfl-edge-archive"))
    sims, drift = int(opt.get("sims", 1000)), float(cfg["report"].get("playoff_drift", 0.0))
    res = summarize(backtest_records(sched, teams, wm, sims, archive, drift), sims, drift)
    bt_path.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))
    return
  if "--weekly" in sys.argv:
    # (INSIGHTS (L)) every team's odds as of every week (before that week's games), 2019 on, for the late-season stakes
    # inputs of the availability models: cache/playoff_odds_weekly.parquet
    archive = Path(opt.get("archive", ROOT.parent / "nfl-edge-archive"))
    sims, drift = int(opt.get("sims", 1000)), float(cfg["report"].get("playoff_drift", 0.0))
    rng, recs = np.random.default_rng(7), []
    reg = sched[sched.game_type == "REG"]
    for season in range(int(opt.get("first", 2019)), current + 1):
      r_ = reg[reg.season == season]
      last = int(r_.week.max()) if season < current else int(r_[r_.home_score.notna()].week.max()) + 1
      for week in range(1, last + 1):
        res = simulate(sched, teams, season, week, week_ranks(archive, season, week), wm, sims, rng, lines_weeks={week}, drift=drift)
        recs += [{"season": season, "week": week, "team": r["team"], "p_playoffs": r["p_playoffs"], "p_div": r["p_div"],
                  "p_bye": r["p_bye"]} for r in res["rows"]]
      print(f"[odds weekly] {season} weeks 1-{last}", flush=True)
    pd.DataFrame(recs).to_parquet(ROOT / cfg["data"]["cache_dir"] / "playoff_odds_weekly.parquet", index=False)
    return
  if "--fit-drift" in sys.argv:
    # Pre-registered: pick the drift with the lowest make-playoffs Brier on 2021-2023; adopt only if it also beats
    # no drift on 2024-2025 (never used to pick it).
    archive = Path(opt.get("archive", ROOT.parent / "nfl-edge-archive"))
    sims, grid = int(opt.get("sims", 500)), [0.0, 0.3, 0.6, 0.9, 1.2, 1.5]
    briers = {}
    for dr in grid:
      d = backtest_records(sched, teams, wm, sims, archive, dr)
      fit, test = d[d.season <= 2023], d[d.season >= 2024]
      b = lambda x: float(((x.p_playoffs - x.y_playoffs) ** 2).mean())
      briers[dr] = (b(fit), b(test), summarize(test, sims, dr)["calibration"])
      print(f"drift {dr}: Brier 2021-23 {briers[dr][0]:.4f}  2024-25 {briers[dr][1]:.4f}", flush=True)
    best = min(grid, key=lambda dr: briers[dr][0])
    print(f"best on 2021-23: {best}; 2024-25 Brier {briers[best][1]:.4f} vs no drift {briers[0.0][1]:.4f}")
    print("2024-25 calibration, best:", [(c["bin"], c["predicted"], c["actual"]) for c in briers[best][2]])
    print("2024-25 calibration, none:", [(c["bin"], c["predicted"], c["actual"]) for c in briers[0.0][2]])
    return
  idx = json.loads((site / "index.json").read_text(encoding="utf-8"))
  week = int(idx["week"])
  if int(idx["season"]) != current:
    return
  ranks = {RELOCATED.get(r["team"], r["team"]): r["rank"] for r in idx.get("power") or []}
  drift = float(cfg["report"].get("playoff_drift", 0.0))
  res = simulate(sched, teams, current, week, ranks, wm, int(opt.get("sims", 10000)), np.random.default_rng(), lines_weeks=None,
                 drift=drift, keep=True)
  root = rooting(res, week, int(opt.get("flip", 2000)), int(opt.get("case", 500)), int(opt.get("jobs", os.cpu_count() or 1)))
  hist = odds_history(sched, teams, wm, site, Path(opt.get("archive", ROOT.parent / "nfl-edge-archive")), current, week, drift, ranks)
  info = teams.assign(team_abbr=teams.team_abbr.replace(RELOCATED)).drop_duplicates("team_abbr").set_index("team_abbr")
  for r in res["rows"]:
    r.update({"nick": info.at[r["team"], "team_nick"], "logo": info.at[r["team"], "team_logo_espn"], "color": info.at[r["team"], "team_color"]})
  doc = {"v": V, "season": current, "as_of_week": week, "sims": res["n"], "playoff_teams": res["n_po"], "teams": res["rows"],
         "seeding": likely_seeding(res["rows"], res["n_po"]), "root": root, "hist": hist["weeks"],
         "sched": team_schedules(sched, current),
         "track": json.loads(bt_path.read_text(encoding="utf-8")) if bt_path.exists() else None}
  out = site / "data" / "playoffs"
  out.mkdir(parents=True, exist_ok=True)
  (out / "odds.json").write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
  print(f"[odds] {current} as of week {week}: {res['n']} simulated seasons -> {out / 'odds.json'}", flush=True)


if __name__ == "__main__":
  main()
