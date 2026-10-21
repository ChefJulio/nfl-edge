"""(BM) Preseason win totals: ours vs Vegas vs both (pre-registered 2026-10-20, docs/INSIGHTS.md (BM)).

Usage: python tools/preseason_wins_eval.py [--score]
Ours = production's playoff simulation as of week 1, with no Vegas lines, -> projected wins; Vegas = the preseason
over/under (data/history/preseason_win_totals.csv). Scored on final regular-season wins, 2021-25.
Writes cache/preseason_wins_eval.parquet.
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

OUT = ROOT / "cache" / "preseason_wins_eval.parquet"
SEASONS = list(range(2021, 2026))


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
  rw = eng.tm.fit(season, 1)
  a = unit_points(rw, league_volume(eng, season, 1, rw), starters_asof(eng, season, 1), fw).net
  rk = {t: int(r) for t, r in a.rank(ascending=False, method="min").items()}
  res = PO.simulate(sched, teams, season, 1, rk, wm, 2000, np.random.default_rng(1000 * season + 1), lines_weeks=set(), drift=drift)
  print(f"[preseason] {season}", flush=True)
  return pd.DataFrame([{"season": season, "team": r["team"], "ours": r["exp_w"], "net": float(a.get(r["team"], np.nan))} for r in res["rows"]])


def main():
  if "--score" not in sys.argv:
    with ProcessPoolExecutor(5) as ex:
      pd.concat(list(ex.map(season_rows, SEASONS)), ignore_index=True).to_parquet(OUT, index=False)
  df = pd.read_parquet(OUT)
  vg = pd.read_csv(ROOT / "data" / "history" / "preseason_win_totals.csv").rename(columns={"win_total": "vegas"})
  s = pd.read_parquet(ROOT / "cache" / "schedules_all.parquet")
  s = s[(s.game_type == "REG") & s.season.isin(SEASONS)]
  g = pd.concat([pd.DataFrame({"season": s.season, "team": s.home_team, "m": s.home_score - s.away_score}),
                 pd.DataFrame({"season": s.season, "team": s.away_team, "m": s.away_score - s.home_score})])
  fin = g.assign(fw=np.where(g.m > 0, 1, np.where(g.m == 0, .5, 0))).groupby(["season", "team"]).fw.sum().rename("final").reset_index()
  df = df.merge(vg[["season", "team", "vegas"]], on=["season", "team"]).merge(fin, on=["season", "team"])
  assert len(df) == 32 * len(SEASONS), len(df)
  df["mix50"] = (df.ours + df.vegas) / 2
  for se in SEASONS[1:]:
    tr = df[df.season < se]
    X = np.c_[np.ones(len(tr)), tr.vegas, tr.ours]
    beta = np.linalg.lstsq(X, tr.final, rcond=None)[0]
    te = df.season == se
    df.loc[te, "mixfit"] = beta[0] + beta[1] * df.loc[te, "vegas"] + beta[2] * df.loc[te, "ours"]
  rng = np.random.default_rng(0)

  def ci(x, y, d):
    e = (d[x] - d.final).abs().to_numpy() - (d[y] - d.final).abs().to_numpy()
    bt = e[rng.integers(0, len(e), (2000, len(e)))].mean(1)
    return e.mean(), *np.percentile(bt, [2.5, 97.5])

  print(f"(BM) preseason projected wins vs final, {SEASONS[0]}-{SEASONS[-1]}, {len(df)} team-seasons")
  for arm in ("vegas", "ours", "mix50"):
    sp = np.mean([x[arm].corr(x.final, method="spearman") for _, x in df.groupby("season")])
    print(f"  {arm:7s} MAE {(df[arm] - df.final).abs().mean():.3f}  RMSE {np.sqrt(((df[arm] - df.final) ** 2).mean()):.3f}  rank corr {sp:.3f}")
  F = df[df.mixfit.notna()]
  print(f"  mixfit  MAE {(F.mixfit - F.final).abs().mean():.3f} (2022-25; vegas on the same {(F.vegas - F.final).abs().mean():.3f})")
  for x, lab, d in (("ours", "OURS - VEGAS", df), ("mix50", "MIX50 - VEGAS (gate)", df), ("mixfit", "MIXFIT - VEGAS (2022-25)", F)):
    m, lo, hi = ci(x, "vegas", d)
    print(f"  {lab:26s} {m:+.3f} [{lo:+.3f}, {hi:+.3f}] wins")
  per = df.groupby("season").apply(lambda t: pd.Series({a: (t[a] - t.final).abs().mean() for a in ("vegas", "ours", "mix50")}))
  print(per.round(3).to_string())
  print(f"  ours ~ vegas rank corr: {np.mean([x.ours.corr(x.vegas, method='spearman') for _, x in df.groupby('season')]):.3f}")
  m, lo, hi = ci("mix50", "vegas", df)
  better = int((per.mix50 < per.vegas).sum())
  print(f"seasons MIX50 better {better}/5; GATE:", "PASS" if m <= -0.05 and hi < 0 and better >= 3 else "FAIL")
  d = df.assign(diff=df.ours - df.vegas)
  d = d.reindex(d["diff"].abs().sort_values(ascending=False).index).head(10)
  print("\nbiggest disagreements:")
  print(d[["season", "team", "vegas", "ours", "final"]].to_string(index=False))


if __name__ == "__main__":
  main()
