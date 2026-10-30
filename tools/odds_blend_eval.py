"""(DX) the market rating as a third input in the playoff odds' unlined games (pre-registered 2026-10-30, docs/INSIGHTS.md).

Usage:
  python tools/odds_blend_eval.py --fit                    game table + leave-one-season-out weights (cache/dx_*.json)
  python tools/odds_blend_eval.py --part=B3|BLEND --season=Y   one arm's playoff-odds backtest for one season
  python tools/odds_blend_eval.py --score                  BASE ((DW)'s parts) vs B3 vs BLEND, the gate
Game table: every 2021-25 regular-season game with what was known before its week: Power's rank gap (archived page),
the Elo gap, the market-rating gap (lines of earlier games only) and home. B3 = home + rank + Elo, BLEND = B3 + market,
each fit on the other four seasons.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge import elo  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.standings import RELOCATED  # noqa: E402
import playoff_odds as po  # noqa: E402

SEASONS = [2021, 2022, 2023, 2024, 2025]
ARMS = {"B3": ["home", "rank_gap", "elo_per_100"], "BLEND": ["home", "rank_gap", "elo_per_100", "mkt"]}
CFG = load_config()
CACHE = ROOT / CFG["data"]["cache_dir"]
ARCHIVE = ROOT.parent / "nfl-edge-archive"


def inputs():
  cache = D.Cache(CACHE)
  sched = cache.get("schedules", "since1999", None, stale=False)
  teams = cache.get("teams", "all", None, stale=False)
  return sched, teams


def game_table(sched) -> pd.DataFrame:
  wm = CFG["report"]["win_model"]
  reg = sched[sched.season.isin(SEASONS) & (sched.game_type == "REG") & sched.home_score.notna()].copy()
  reg["home_team"], reg["away_team"] = reg.home_team.replace(RELOCATED), reg.away_team.replace(RELOCATED)
  reg = reg[reg.home_score != reg.away_score]
  rows = []
  for (s, w), g in reg.groupby(["season", "week"]):
    rk = po.week_ranks(ARCHIVE, s, w)
    e = elo.ratings_before(sched, s, w, wm)
    mr, _ = po.market_ratings(sched, s, w, set())  # lines of games before week w only
    for r in g.itertuples():
      ra, rh = rk.get(r.away_team), rk.get(r.home_team)
      if not (ra and rh):
        continue
      rows.append({"season": s, "week": w, "home": float(r.location != "Neutral"), "rank_gap": float(ra - rh),
                   "elo_per_100": (e.get(r.home_team, elo.MEAN) - e.get(r.away_team, elo.MEAN)) / 100,
                   "mkt": mr.get(r.home_team, 0.0) - mr.get(r.away_team, 0.0), "y": float(r.home_score > r.away_score)})
  return pd.DataFrame(rows)


def fit():
  sched, _ = inputs()
  g = game_table(sched)
  g.to_parquet(CACHE / "dx_games.parquet")
  wm = CFG["report"]["win_model"]
  shipped = sum(wm[c] * g[c] for c in ARMS["B3"])
  g["p_BASE"] = 1 / (1 + np.exp(-shipped))
  weights = {a: {} for a in ARMS}
  for s in SEASONS:
    tr, te = g.season != s, g.season == s
    for a, cols in ARMS.items():
      m = LogisticRegression(C=1e6, fit_intercept=False, max_iter=3000).fit(g.loc[tr, cols], g.loc[tr, "y"])
      weights[a][s] = dict(zip(cols, map(float, m.coef_[0])))
      g.loc[te, f"p_{a}"] = m.predict_proba(g.loc[te, cols])[:, 1]
  (CACHE / "dx_weights.json").write_text(json.dumps(weights, indent=1), encoding="utf-8")
  print(f"(DX) game table: {len(g)} games 2021-25 (held-out season predictions)")
  for a in ["BASE", *ARMS]:
    b = (g[f"p_{a}"] - g.y) ** 2
    print(f"  {a:6s} Brier {b.mean():.4f}   by season " + " ".join(f"{b[g.season == s].mean():.4f}" for s in SEASONS))
  for a in ARMS:
    for s in SEASONS:
      print(f"  {a} weights (fit without {s}): " + ", ".join(f"{k} {v:+.4f}" for k, v in weights[a][s].items()))
  print("  correlation of the gaps:", g[["rank_gap", "elo_per_100", "mkt"]].corr().round(2).to_dict())


def part(arm: str, season: int):
  sched, teams = inputs()
  w = json.loads((CACHE / "dx_weights.json").read_text(encoding="utf-8"))[arm][str(season)]
  wm = {**CFG["report"]["win_model"], **w}
  drift = float(CFG["report"].get("playoff_drift", 0.0))
  d = po.backtest_records(sched, teams, wm, 1000, ARCHIVE, drift, seasons=[season])
  d.to_parquet(CACHE / f"dx_{arm}_{season}.parquet")


def score():
  def load(a):
    pre = "dw" if a == "BASE" else "dx"
    return pd.concat([pd.read_parquet(CACHE / f"{pre}_{a}_{y}.parquet") for y in SEASONS], ignore_index=True)
  arms = {a: load(a) for a in ("BASE", "B3", "BLEND")}
  b = lambda x, m="playoffs": float(((x[f"p_{m}"] - x[f"y_{m}"]) ** 2).mean())  # noqa: E731
  for m in ("playoffs", "div", "bye", "title"):
    print(f"{m:9s} " + "  ".join(f"{a} {b(d, m):.4f}" for a, d in arms.items()))
  better = 0
  for y in SEASONS:
    v = {a: b(d[d.season == y]) for a, d in arms.items()}
    better += v["BLEND"] < v["B3"]
    print(f"  {y} make-playoffs " + "  ".join(f"{a} {x:.4f}" for a, x in v.items()) + f"   BLEND - B3 {v['BLEND'] - v['B3']:+.4f}")
  for a, d in arms.items():
    sm = po.summarize(d.copy(), 1000, 0.9)
    print(a, "by week", [(w["weeks"], w["brier"]) for w in sm["by_week"]])
    print(a, "calibration", [(c["bin"], c["predicted"], c["actual"]) for c in sm["calibration"]])
  ok = b(arms["BLEND"]) < b(arms["B3"]) and better >= 4 and b(arms["BLEND"]) < b(arms["BASE"])
  print(f"GATE: {'PASS' if ok else 'FAIL'} (BLEND better than B3 in {better}/5 seasons)")


if __name__ == "__main__":
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  if "--fit" in sys.argv:
    fit()
  elif "part" in opt:
    part(opt["part"], int(opt["season"]))
  elif "--score" in sys.argv:
    score()
