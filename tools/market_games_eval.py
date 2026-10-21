"""(BL) Future-game win chances: our ranks vs market ranks vs both (pre-registered 2026-10-20, docs/INSIGHTS.md (BL)).

Usage: python tools/market_games_eval.py [--score]
For 2021-26, as of each week w = 3..17 (before week w's games): our Power rank basis (net from this week's lineup) and
the market rank (ridge fit to the season's closing spreads through week w). Rows = every regular-season game in weeks
w+1..18, label = home won. Arms (logistic, fit walk-forward on earlier seasons, scored 2022-25, 2026 CONFIRM):
  ours    home + our rank gap + Elo gap     market  home + market rank gap + Elo gap     blend  home + both + Elo gap
Writes cache/market_games_eval.parquet.
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

OUT = ROOT / "cache" / "market_games_eval.parquet"
SEASONS, TEST, CONFIRM = list(range(2021, 2027)), [2022, 2023, 2024, 2025], 2026
ARMS = {"ours": ["home", "gap_ours", "elo"], "market": ["home", "gap_mkt", "elo"], "blend": ["home", "gap_ours", "gap_mkt", "elo"],
        "ours_noelo": ["home", "gap_ours"], "market_noelo": ["home", "gap_mkt"], "blend_noelo": ["home", "gap_ours", "gap_mkt"]}


def season_rows(season: int) -> pd.DataFrame:
  for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(v, "2")
  from nfledge import data as D
  from nfledge import elo
  from nfledge.config import load_config, load_scoring
  from nfledge.engine import Engine
  from nfledge.report import formula_weights, league_volume, starters_asof, unit_points
  from nfledge.standings import RELOCATED
  from market_wins_eval import market_ratings
  cfg = load_config()
  d = D.load_all(cfg)
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  sched = cache.get("schedules", "since1999", None, stale=False)
  wm = cfg["report"]["win_model"]
  eng = Engine(d, cfg, load_scoring(), ["QB", "RB", "WR", "TE"]).train(season)
  fw = formula_weights(eng)
  reg = sched[(sched.season == season) & (sched.game_type == "REG")].copy()
  reg["home_team"], reg["away_team"] = reg.home_team.replace(RELOCATED), reg.away_team.replace(RELOCATED)
  done = reg[reg.home_score.notna()]
  last = int(done.week.max()) if len(done) else 0
  rank = lambda s: s.rank(ascending=False, method="min").to_dict()  # noqa: E731
  rows = []
  for w in range(3, min(17, last - 1) + 1):
    rw = eng.tm.fit(season, w)
    a = unit_points(rw, league_volume(eng, season, w, rw), starters_asof(eng, season, w), fw).net
    ro, rm = rank(a), rank(market_ratings(reg, w, sorted(a.index)))
    el = elo.ratings_before(sched, season, w, wm)
    fut = done[(done.week > w) & (done.home_score != done.away_score)]
    for x in fut.itertuples():
      h, aw = x.home_team, x.away_team
      rows.append({"season": season, "asof": w, "game_id": x.game_id, "ahead": int(x.week) - w, "home": float(x.location != "Neutral"),
                   "gap_ours": ro[aw] - ro[h], "gap_mkt": rm[aw] - rm[h],
                   "elo": (el.get(h, elo.MEAN) - el.get(aw, elo.MEAN)) / 100, "y": int(x.home_score > x.away_score)})
    print(f"[market games] {season} as of week {w}: {len(fut)} future games", flush=True)
  return pd.DataFrame(rows)


def ci(diff: np.ndarray, cl: pd.Series, rng) -> tuple:
  g = pd.DataFrame({"d": diff, "c": cl.to_numpy()}).groupby("c").d.agg(["sum", "size"])
  s_, n_ = g["sum"].to_numpy(), g["size"].to_numpy()
  idx = rng.integers(0, len(g), (2000, len(g)))
  bt = s_[idx].sum(1) / n_[idx].sum(1)
  return diff.mean(), *np.percentile(bt, [2.5, 97.5])


def main():
  if "--score" not in sys.argv:
    with ProcessPoolExecutor(6) as ex:
      pd.concat(list(ex.map(season_rows, SEASONS)), ignore_index=True).to_parquet(OUT, index=False)
  df = pd.read_parquet(OUT)
  for s in TEST + [CONFIRM]:
    tr, te = df.season < s, df.season == s
    for arm, cols in ARMS.items():
      m = LogisticRegression(C=1e6, max_iter=1000).fit(df.loc[tr, cols], df.loc[tr, "y"])
      df.loc[te, arm] = m.predict_proba(df.loc[te, cols])[:, 1]
  for arm in ARMS:
    df[f"b_{arm}"] = (df[arm] - df.y) ** 2
  T = df[df.season.isin(TEST)]
  rng = np.random.default_rng(0)
  print(f"(BL) {T.game_id.nunique()} games, {len(T)} game x as-of rows, 2022-25 (each arm fit on earlier seasons)")
  print("Brier (lower = better):  " + "  ".join(f"{a} {T[f'b_{a}'].mean():.4f}" for a in ARMS))
  for x, yv, lab in (("blend", "ours", "BLEND - OURS (gate)"), ("market", "ours", "MARKET - OURS"), ("blend_noelo", "ours_noelo", "no Elo: BLEND - OURS"),
                     ("market_noelo", "ours_noelo", "no Elo: MARKET - OURS")):
    mm, lo, hi = ci((T[f"b_{x}"] - T[f"b_{yv}"]).to_numpy(), T.game_id, rng)
    print(f"  {lab:24s} {mm:+.5f} [{lo:+.5f}, {hi:+.5f}]")
  per = T.groupby("season")[["b_ours", "b_market", "b_blend"]].mean()
  print(per.round(4).to_string())
  T = T.assign(h=pd.cut(T.ahead, [0, 4, 8, 99], labels=["1-4 wk", "5-8 wk", "9+ wk"]))
  print(T.groupby("h", observed=True)[["b_ours", "b_market", "b_blend", "b_ours_noelo", "b_market_noelo"]].mean().round(4).to_string())
  m = LogisticRegression(C=1e6, max_iter=1000).fit(df.loc[df.season.isin(TEST), ARMS["blend"]], df.loc[df.season.isin(TEST), "y"])
  print("blend coefficients (fit on 2022-25, for reading only):", dict(zip(ARMS["blend"], m.coef_[0].round(4))))
  mm, lo, hi = ci((T.b_blend - T.b_ours).to_numpy(), T.game_id, rng)
  better = int((per.b_blend < per.b_ours).sum())
  C = df[df.season == CONFIRM]
  cd = (C.b_blend - C.b_ours).mean() if len(C) else float("nan")
  print(f"CONFIRM {CONFIRM}: {C.game_id.nunique()} games, BLEND - OURS {cd:+.5f}")
  ok = hi < 0 and mm <= -0.002 and better >= 3 and cd < 0
  print(f"seasons better {better}/4; GATE:", "PASS (owner decides: market becomes an input)" if ok else "FAIL")


if __name__ == "__main__":
  main()
