"""(BN) Vegas preseason win totals as an early-season prior (pre-registered 2026-10-20, docs/INSIGHTS.md (BN)).

Usage: python tools/vegas_prior_eval.py [--score]
Every regular-season game 2021-26, predicted as of its own week (Matchups' win chance: home + rank gap of this week's
lineup + Elo gap). PRIOR adds the preseason win-total gap by week band (1-4, 5-8, 9+). Logistic fit walk-forward on
earlier seasons, scored 2022-25, 2026 weeks 1-6 CONFIRM. Writes cache/vegas_prior_eval.parquet.
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
from sklearn.linear_model import LogisticRegression  # noqa: E402

OUT = ROOT / "cache" / "vegas_prior_eval.parquet"
SEASONS, TEST, CONFIRM = list(range(2021, 2027)), [2022, 2023, 2024, 2025], 2026
BASE = ["home", "gap", "elo"]
PRIOR = BASE + ["vt_1_4", "vt_5_8", "vt_9"]


def season_rows(season: int) -> pd.DataFrame:
  for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(v, "2")
  from nfledge import data as D
  from nfledge import elo
  from nfledge.config import load_config, load_scoring
  from nfledge.engine import Engine
  from nfledge.report import formula_weights, league_volume, starters_asof, unit_points
  from nfledge.standings import RELOCATED
  cfg = load_config()
  d = D.load_all(cfg)
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  sched = cache.get("schedules", "since1999", None, stale=False)
  wm = cfg["report"]["win_model"]
  eng = Engine(d, cfg, load_scoring(), ["QB", "RB", "WR", "TE"]).train(season)
  fw = formula_weights(eng)
  reg = sched[(sched.season == season) & (sched.game_type == "REG") & sched.home_score.notna()].copy()
  reg["home_team"], reg["away_team"] = reg.home_team.replace(RELOCATED), reg.away_team.replace(RELOCATED)
  rows = []
  for w in sorted(reg.week.unique()):
    rw = eng.tm.fit(season, int(w))
    a = unit_points(rw, league_volume(eng, season, int(w), rw), starters_asof(eng, season, int(w)), fw).net
    rk = a.rank(ascending=False, method="min").to_dict()
    el = elo.ratings_before(sched, season, int(w), wm)
    for x in reg[reg.week == w].itertuples():
      if x.home_score == x.away_score:
        continue
      rows.append({"season": season, "week": int(w), "game_id": x.game_id, "home_team": x.home_team, "away_team": x.away_team,
                   "home": float(x.location != "Neutral"), "gap": rk[x.away_team] - rk[x.home_team],
                   "rk_h": rk[x.home_team], "rk_a": rk[x.away_team], "net_h": float(a[x.home_team]), "net_a": float(a[x.away_team]),
                   "elo": (el.get(x.home_team, elo.MEAN) - el.get(x.away_team, elo.MEAN)) / 100,
                   "ml_h": x.home_moneyline, "ml_a": x.away_moneyline, "y": int(x.home_score > x.away_score)})
    print(f"[vegas prior] {season} week {w}", flush=True)
  return pd.DataFrame(rows)


def ml_prob(ml: pd.Series) -> pd.Series:
  return np.where(ml > 0, 100 / (ml + 100), -ml / (-ml + 100))


def ci(diff: np.ndarray, rng) -> tuple:
  bt = diff[rng.integers(0, len(diff), (2000, len(diff)))].mean(1)
  return diff.mean(), *np.percentile(bt, [2.5, 97.5])


def main():
  if "--score" not in sys.argv:
    with ProcessPoolExecutor(6) as ex:
      pd.concat(list(ex.map(season_rows, SEASONS)), ignore_index=True).to_parquet(OUT, index=False)
  df = pd.read_parquet(OUT)
  vt = pd.read_csv(ROOT / "data" / "history" / "preseason_win_totals.csv").set_index(["season", "team"]).win_total
  df["vt"] = [vt.get((s, h), np.nan) - vt.get((s, a), np.nan) for s, h, a in zip(df.season, df.home_team, df.away_team)]
  assert df.vt.notna().all(), df[df.vt.isna()][["season", "home_team", "away_team"]].drop_duplicates().head()
  df["vt_1_4"] = df.vt * (df.week <= 4)
  df["vt_5_8"] = df.vt * df.week.between(5, 8)
  df["vt_9"] = df.vt * (df.week >= 9)
  ph, pa = ml_prob(df.ml_h), ml_prob(df.ml_a)
  df["vegas"] = ph / (ph + pa)
  for s in TEST + [CONFIRM]:
    tr, te = df.season < s, df.season == s
    for arm, cols in (("base", BASE), ("prior", PRIOR)):
      m = LogisticRegression(C=1e6, max_iter=2000).fit(df.loc[tr, cols], df.loc[tr, "y"])
      df.loc[te, arm] = m.predict_proba(df.loc[te, cols])[:, 1]
  for arm in ("base", "prior", "vegas"):
    df[f"b_{arm}"] = (df[arm] - df.y) ** 2
  df["band"] = pd.cut(df.week, [0, 4, 8, 99], labels=["wk 1-4", "wk 5-8", "wk 9+"])
  T = df[df.season.isin(TEST)]
  rng = np.random.default_rng(0)
  print(f"(BN) {len(T)} games 2022-25 (each fit on earlier seasons)")
  print(T.groupby("band", observed=True)[["b_base", "b_prior", "b_vegas"]].mean().round(4).assign(n=T.groupby("band", observed=True).size()).to_string())
  E = T[T.week <= 8]
  g1 = ci((E.b_prior - E.b_base).to_numpy(), rng)
  g2 = ci((T.b_prior - T.b_base).to_numpy(), rng)
  per = E.groupby("season")[["b_base", "b_prior"]].mean()
  better = int((per.b_prior < per.b_base).sum())
  print(f"(1) weeks 1-8: {E.b_base.mean():.4f} -> {E.b_prior.mean():.4f}, {g1[0]:+.5f} [{g1[1]:+.5f}, {g1[2]:+.5f}]")
  print(f"(2) all weeks: {T.b_base.mean():.4f} -> {T.b_prior.mean():.4f}, {g2[0]:+.5f} [{g2[1]:+.5f}, {g2[2]:+.5f}]")
  print(f"(3) weeks 1-8 by season:\n{per.round(4).to_string()}")
  w1 = T[T.week <= 4]
  g4 = ci((w1.b_prior - w1.b_base).to_numpy(), rng)
  print(f"weeks 1-4 alone: {g4[0]:+.5f} [{g4[1]:+.5f}, {g4[2]:+.5f}];  vs Vegas lines weeks 1-8: prior - vegas {(E.b_prior - E.b_vegas).mean():+.5f}")
  m = LogisticRegression(C=1e6, max_iter=2000).fit(df.loc[df.season.isin(TEST + [2021]), PRIOR], df.loc[df.season.isin(TEST + [2021]), "y"])
  print("weights (fit 2021-25, reading only):", dict(zip(PRIOR, m.coef_[0].round(4))))
  C = df[(df.season == CONFIRM) & (df.week <= 6)]
  cd = (C.b_prior - C.b_base).mean()
  print(f"CONFIRM {CONFIRM} weeks 1-6: {len(C)} games, {cd:+.5f}")
  ok = g1[2] < 0 and g1[0] <= -0.002 and g2[2] < 0.0005 and better >= 3 and cd < 0
  print("GATE:", "PASS" if ok else "FAIL")


if __name__ == "__main__":
  main()
