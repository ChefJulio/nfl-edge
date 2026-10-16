"""Playoff odds with week-by-week, injury-aware ratings (pre-registered 2026-10-16, docs/INSIGHTS.md (N)).

Usage: python tools/odds_c_eval.py [--sims=1000] [--jobs=5]
For every week of 2021-25, simulates the rest of the season three ways with the same random draws:
  A        today's rule: each team's rank from this week's lineup, held for every remaining game
  weekly   each remaining game uses its own week's ranks: P(usual starter plays that week) x net with him + (1 - P) x
           net with the backup (nfledge/powerc.py); playoff games use the last regular week's ranks
  C        the rest-of-season rank (Power's rank), held for every remaining game (reported, not gated)
Scores make-playoffs / division / bye Brier against what happened; writes cache/odds_c_eval.parquet.
"""
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

OUT = ROOT / "cache" / "odds_c_eval.parquet"


def season_rows(args) -> pd.DataFrame:
  season, sims = args
  for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(v, "2")
  from nfledge import data as D
  from nfledge import powerc
  from nfledge.config import load_config, load_scoring
  from nfledge.engine import Engine
  from nfledge.report import formula_weights, league_volume, starters_asof, unit_points
  from nfledge.standings import League, playoff_teams_per_conf
  import playoff_odds as PO
  cfg = load_config()
  d = D.load_all(cfg)
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  sched = cache.get("schedules", "since1999", None, stale=False)
  teams = cache.get("teams", "all", None, stale=False)
  wm, drift = cfg["report"]["win_model"], float(cfg["report"].get("playoff_drift", 0.0))
  eng = Engine(d, cfg, load_scoring(), ["QB", "RB", "WR", "TE"]).train(season)
  fw = formula_weights(eng)
  final = League.from_schedule(sched, teams, season)
  seeds = final.seeds(playoff_teams_per_conf(season))
  made = {t for o in seeds.values() for t in o}
  divw = {o[0] for o in final.division_order().values()}
  bye = {o[0] for o in seeds.values()}
  reg = sched[(sched.season == season) & (sched.game_type == "REG")]
  n_weeks = int(reg.week.max())
  rank = lambda s: {t: int(r) for t, r in s.rank(ascending=False, method="min").items()}  # noqa: E731
  rows = []
  for week in range(1, n_weeks + 1):
    rw = eng.tm.fit(season, week)
    vol = league_volume(eng, season, week, rw)
    recent = starters_asof(eng, season, week)
    a = unit_points(rw, vol, recent, fw).net
    ranks_a = rank(a)
    by_week_ranks, ranks_c = None, ranks_a
    if week >= 2:
      by = {}
      usual, backup, pbar = powerc.inputs(eng, season, week, recent, by_week=by)
      nu, nb = unit_points(rw, vol, usual, fw).net, unit_points(rw, vol, backup, fw).net
      ranks_c = rank(powerc.blend(unit_points(rw, vol, usual, fw), unit_points(rw, vol, backup, fw), pbar).net)
      future = sorted(set(reg[reg.week >= week].week))
      by_week_ranks = {}
      for k in future:
        r_k = pd.Series({t: (by[t].get(k, 1.0) * nu[t] + (1 - by[t].get(k, 1.0)) * nb.get(t, nu[t])) if t in by else a[t]
                         for t in a.index})
        by_week_ranks[k] = rank(r_k)
    res = {}
    for name, rk_, bw in (("A", ranks_a, None), ("weekly", by_week_ranks[max(by_week_ranks)] if by_week_ranks else ranks_a, by_week_ranks),
                          ("C", ranks_c, None)):
      rng = np.random.default_rng(1000 * season + week)  # the same draws for every variant
      res[name] = {r["team"]: r for r in PO.simulate(sched, teams, season, week, rk_, wm, sims, rng, lines_weeks={week},
                                                      drift=drift, ranks_by_week=bw)["rows"]}
    for t in res["A"]:
      rows.append({"season": season, "week": week, "team": t, "y_playoffs": int(t in made), "y_div": int(t in divw),
                   "y_bye": int(t in bye),
                   **{f"{m}_{v}": res[v][t][f"p_{m}"] for v in res for m in ("playoffs", "div", "bye")}})
    print(f"[odds C] {season} week {week}", flush=True)
  return pd.DataFrame(rows)


def ci(diff: pd.Series, cl: pd.Series):
  g = pd.DataFrame({"d": diff.to_numpy(), "c": cl.to_numpy()}).groupby("c").d.agg(["sum", "size"])
  s_, n_ = g["sum"].to_numpy(), g["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(g), (4000, len(g)))
  bt = s_[idx].sum(1) / n_[idx].sum(1)
  return diff.mean(), np.percentile(bt, 2.5), np.percentile(bt, 97.5)


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  sims, seasons = int(opt.get("sims", 1000)), list(range(2021, 2026))
  if "--score" not in sys.argv:
    with ProcessPoolExecutor(int(opt.get("jobs", len(seasons)))) as ex:
      df = pd.concat(list(ex.map(season_rows, [(s, sims) for s in seasons])), ignore_index=True)
    df.to_parquet(OUT, index=False)
  df = pd.read_parquet(OUT)
  cl = df.season.astype(str) + "-" + df.week.astype(str)
  ok = True
  for m in ("playoffs", "div", "bye"):
    y = df[f"y_{m}"]
    b = {v: (df[f"{m}_{v}"] - y) ** 2 for v in ("A", "weekly", "C")}
    mm, lo, hi = ci(b["weekly"] - b["A"], cl)
    mc, lc, hc = ci(b["C"] - b["A"], cl)
    gate = (hi < 0) if m == "playoffs" else (hi < 0.001)
    ok &= gate
    print(f"{m:9s} Brier A {b['A'].mean():.4f}  weekly {b['weekly'].mean():.4f} ({mm:+.5f} [{lo:+.5f}, {hi:+.5f}]) {'ok' if gate else 'FAIL'}"
          f"   | C {b['C'].mean():.4f} ({mc:+.5f} [{lc:+.5f}, {hc:+.5f}])")
  for s, g in df.groupby("season"):
    print(f"  {s}: playoffs A {((g.playoffs_A - g.y_playoffs) ** 2).mean():.4f} -> weekly {((g.playoffs_weekly - g.y_playoffs) ** 2).mean():.4f}")
  print("GATE:", "PASS" if ok else "FAIL")


if __name__ == "__main__":
  main()
