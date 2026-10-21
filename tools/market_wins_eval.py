"""(BK) Projected final wins, ours vs the market (pre-registered 2026-10-20, docs/INSIGHTS.md (BK)). Descriptive.

Usage: python tools/market_wins_eval.py [--score]
2021-25 at weeks 3 / 5 / 9 / 13, production's playoff simulation two ways with the same random draws:
  ours     Power's ranks from this week's lineup (+ Elo + home, this week's Vegas lines for this week's games)
  market   the same with market ranks: ridge fit to every closing spread of the season through this week
           (spread = home - away + home field; half-life 4 weeks; ridge 1.0)
  ceiling  wins so far + vig-free closing-moneyline chances of every remaining game (uses future lines: not a test)
Scored on final regular-season wins: MAE and within-season Spearman. Writes cache/market_wins_eval.parquet.
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

OUT = ROOT / "cache" / "market_wins_eval.parquet"
WEEKS, SIMS, HALF_LIFE, RIDGE = [3, 5, 9, 13], 2000, 4.0, 1.0


def market_ratings(reg: pd.DataFrame, week: int, teams: list) -> pd.Series:
  """Team ratings in points from closing spreads of weeks <= week (nflverse spread_line: + = home favored)."""
  g = reg[(reg.week <= week) & reg.spread_line.notna()]
  ix = {t: i for i, t in enumerate(teams)}
  X = np.zeros((len(g), len(teams) + 1))
  for r, x in enumerate(g.itertuples()):
    X[r, ix[x.home_team]], X[r, ix[x.away_team]] = 1.0, -1.0
    X[r, -1] = 0.0 if x.location == "Neutral" else 1.0
  wt = 0.5 ** ((week - g.week.to_numpy()) / HALF_LIFE)
  Xw, yw = X * np.sqrt(wt)[:, None], g.spread_line.to_numpy() * np.sqrt(wt)
  pen = np.eye(len(teams) + 1) * RIDGE
  pen[-1, -1] = 0.0  # home field unpenalized
  beta = np.linalg.solve(Xw.T @ Xw + pen, Xw.T @ yw)
  return pd.Series(beta[:-1], index=teams)


def ml_prob(ml: float) -> float:
  return 100 / (ml + 100) if ml > 0 else -ml / (-ml + 100)


def season_rows(season: int) -> pd.DataFrame:
  for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(v, "2")
  from nfledge import data as D
  from nfledge.config import load_config, load_scoring
  from nfledge.engine import Engine
  from nfledge.report import formula_weights, league_volume, starters_asof, unit_points
  import playoff_odds as PO
  cfg = load_config()
  d = D.load_all(cfg)
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  sched = cache.get("schedules", "since1999", None, stale=False)
  teams = cache.get("teams", "all", None, stale=False)
  wm, drift = cfg["report"]["win_model"], float(cfg["report"].get("playoff_drift", 0.0))
  eng = Engine(d, cfg, load_scoring(), ["QB", "RB", "WR", "TE"]).train(season)
  fw = formula_weights(eng)
  reg = sched[(sched.season == season) & (sched.game_type == "REG")].copy()
  reg["home_team"], reg["away_team"] = reg.home_team.replace(PO.RELOCATED), reg.away_team.replace(PO.RELOCATED)
  rank = lambda s: {t: int(r) for t, r in s.rank(ascending=False, method="min").items()}  # noqa: E731
  rows = []
  for week in WEEKS:
    rw = eng.tm.fit(season, week)
    a = unit_points(rw, league_volume(eng, season, week, rw), starters_asof(eng, season, week), fw).net
    mk = market_ratings(reg, week, sorted(a.index))
    res = {}
    for name, rk in (("ours", rank(a)), ("market", rank(mk))):
      res[name] = {r["team"]: r for r in PO.simulate(sched, teams, season, week, rk, wm, SIMS, np.random.default_rng(1000 * season + week),
                                                      lines_weeks={week}, drift=drift)["rows"]}
    left = reg[reg.week >= week]
    ceil = {t: 0.0 for t in a.index}
    for x in left.itertuples():
      ph, pa = ml_prob(x.home_moneyline), ml_prob(x.away_moneyline)
      ceil[x.home_team] += ph / (ph + pa)
      ceil[x.away_team] += pa / (ph + pa)
    for t, r in res["ours"].items():
      base = r["w"] + r["t"] / 2
      rows.append({"season": season, "week": week, "team": t, "w": r["w"], "l": r["l"], "t": r["t"], "ours": r["exp_w"],
                   "market": res["market"][t]["exp_w"], "ceiling": base + ceil.get(t, 0.0), "rank_ours": rank(a)[t], "rank_market": rank(mk)[t]})
    print(f"[market wins] {season} week {week}", flush=True)
  return pd.DataFrame(rows)


def main():
  if "--score" not in sys.argv:
    with ProcessPoolExecutor(5) as ex:
      pd.concat(list(ex.map(season_rows, range(2021, 2026))), ignore_index=True).to_parquet(OUT, index=False)
  df = pd.read_parquet(OUT)
  s = pd.read_parquet(ROOT / "cache" / "schedules_all.parquet")
  s = s[(s.game_type == "REG") & s.season.between(2021, 2025)]
  g = pd.concat([pd.DataFrame({"season": s.season, "team": s.home_team, "m": s.home_score - s.away_score}),
                 pd.DataFrame({"season": s.season, "team": s.away_team, "m": s.away_score - s.home_score})])
  g["team"] = g.team.replace({"OAK": "LV", "SD": "LAC", "STL": "LA"})
  fin = g.assign(fw=np.where(g.m > 0, 1, np.where(g.m == 0, .5, 0))).groupby(["season", "team"]).fw.sum().rename("final").reset_index()
  df = df.merge(fin, on=["season", "team"])
  assert len(df) == 640, len(df)
  rng = np.random.default_rng(0)
  print("(BK) projected final wins vs actual, 2021-25 (160 team-seasons per checkpoint)")
  print(f"{'':8s} {'MAE ours':>9s} {'market':>7s} {'ceiling':>8s}  {'ours - market [95% CI]':>26s}   {'Spearman ours':>13s} {'market':>7s} {'ceiling':>8s}  rank corr ours~market")
  for wk, t in df.groupby("week"):
    e = {c: (t[c] - t.final).abs().to_numpy() for c in ("ours", "market", "ceiling")}
    dd = e["ours"] - e["market"]
    bt = dd[rng.integers(0, len(dd), (2000, len(dd)))].mean(1)
    lo, hi = np.percentile(bt, [2.5, 97.5])
    sp = {c: np.mean([x[c].corr(x.final, method="spearman") for _, x in t.groupby("season")]) for c in ("ours", "market", "ceiling")}
    agree = np.mean([x.rank_ours.corr(x.rank_market, method="spearman") for _, x in t.groupby("season")])
    print(f"week {wk:<3d} {e['ours'].mean():9.2f} {e['market'].mean():7.2f} {e['ceiling'].mean():8.2f}  {dd.mean():+8.3f} [{lo:+.3f}, {hi:+.3f}]   "
          f"{sp['ours']:13.3f} {sp['market']:7.3f} {sp['ceiling']:8.3f}  {agree:.3f}")
  print("\nby season, MAE ours / market (all checkpoints):")
  for se, t in df.groupby("season"):
    print(f"  {se}: {(t.ours - t.final).abs().mean():.2f} / {(t.market - t.final).abs().mean():.2f}")
  t = df[df.week == 5].assign(gap=lambda x: x.rank_ours - x.rank_market)
  t = t.reindex(t.gap.abs().sort_values(ascending=False).index).head(8)
  print("\nweek 5, biggest disagreements (our rank vs market rank):")
  print(t[["season", "team", "w", "l", "rank_ours", "rank_market", "ours", "market", "final"]].to_string(index=False))


if __name__ == "__main__":
  main()
