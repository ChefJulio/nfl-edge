"""(BU) Team-rating shrinkage and recency tuned on game outcomes (pre-registered 2026-10-20, docs/INSIGHTS.md (BU)).

Usage: python tools/engine_tune_eval.py      (~4 min per variant, 9 variants; cached in cache/engine_tune/)
Grid alpha_scale {1/3, 1, 3} x half_life_weeks {2, 3, 4.5}. Every game 2021-26 re-rated with ranks as of the week
before (tools/rank_predictor.season_ranks); win chance = home + rank gap + Elo, refit walk-forward. Choose on 2022-23,
decide on 2024-25, confirm 2026.
"""
import copy
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import rank_predictor as rp  # noqa: E402
from darts import logit_fit  # noqa: E402
from nfledge import data as D, elo  # noqa: E402
from nfledge.config import load_config  # noqa: E402

OUT = ROOT / "cache" / "engine_tune"
GRID = [(a, hl) for a in (1 / 3, 1.0, 3.0) for hl in (2.0, 3.0, 4.5)]
BASE = (1.0, 3.0)
# (BV): input arms (name -> team_model overrides), scored on all of 2022-25: python tools/engine_tune_eval.py --bv
BV = {"base": {}, "fumble": {"epa_fumble_luck": True}, "clip": {"epa_clip": 4.0}, "both": {"epa_fumble_luck": True, "epa_clip": 4.0}}


def games_for(base: dict, v: tuple) -> pd.DataFrame:
  path = OUT / f"a{v[0]:.3f}_hl{v[1]}.parquet"
  if path.exists():
    return pd.read_parquet(path)
  cfg = copy.deepcopy(base)
  cfg["team_model"]["alpha_scale"], cfg["team_model"]["half_life_weeks"] = v
  with ProcessPoolExecutor(max_workers=6) as ex:
    d = pd.concat(list(ex.map(rp.season_ranks, [cfg] * 6, range(2021, 2027))), ignore_index=True)
  d = d.rename(columns={"location_x": "location"}).drop(columns=["location_y"], errors="ignore")
  OUT.mkdir(parents=True, exist_ok=True)
  d.to_parquet(path)
  return d


def games_bv(base: dict, name: str) -> pd.DataFrame:
  path = OUT / f"bv_{name}.parquet"
  if path.exists():
    return pd.read_parquet(path)
  cfg = copy.deepcopy(base)
  cfg["team_model"].update(BV[name])
  with ProcessPoolExecutor(max_workers=6) as ex:
    d = pd.concat(list(ex.map(rp.season_ranks, [cfg] * 6, range(2021, 2027))), ignore_index=True)
  d = d.rename(columns={"location_x": "location"}).drop(columns=["location_y"], errors="ignore")
  OUT.mkdir(parents=True, exist_ok=True)
  d.to_parquet(path)
  return d


def prep(d: pd.DataFrame, elo_diff: dict) -> pd.DataFrame:
  d = d[d.home_score != d.away_score].copy()
  d["won"] = (d.home_score > d.away_score).astype(float)
  d["home"] = (d.location != "Neutral").astype(float)
  d["rank_gap"] = d.away_rank - d.home_rank
  d["elo"] = d.game_id.map(elo_diff) / 100
  d["abs_err"] = (d.model_margin - (d.home_score - d.away_score)).abs()
  d["p"] = np.nan
  for s in range(2022, 2027):
    tr, m = d[d.season < s], (d.season == s)
    w = logit_fit(tr[["home", "rank_gap", "elo"]].to_numpy(float), tr.won.to_numpy(float))
    d.loc[m, "p"] = 1 / (1 + np.exp(-d.loc[m, ["home", "rank_gap", "elo"]].to_numpy(float) @ w))
  return d[d.season.between(2022, 2026) & d.spread_line.notna()].set_index("game_id")


def season_week_ci(e: np.ndarray, sw: np.ndarray) -> tuple:
  keys = np.unique(sw)
  idx = [np.flatnonzero(sw == k) for k in keys]
  rng = np.random.default_rng(0)
  vals = [e[np.concatenate([idx[i] for i in rng.integers(0, len(keys), len(keys))])].mean() for _ in range(2000)]
  return float(np.nanmean(e)), np.percentile(vals, 2.5), np.percentile(vals, 97.5)


def main_bv(base: dict, elo_diff: dict):
  res = {n: prep(games_bv(base, n), elo_diff) for n in BV}
  b = res["base"]
  m = (b.season <= 2025).to_numpy()
  print(f"(BV) {int(m.sum())} games 2022-25; base Brier {((b.p - b.won) ** 2)[m].mean():.4f}")
  sw = (b.season.astype(str) + "-" + b.week.astype(str)).to_numpy()
  passed = {}
  for n in ("fumble", "clip", "both"):
    t = res[n].reindex(b.index)
    eb = ((t.p - b.won) ** 2 - (b.p - b.won) ** 2).to_numpy()
    em = (t.abs_err - b.abs_err).to_numpy()
    mb, lo, hi = season_week_ci(eb[m], sw[m])
    mm, mlo, mhi = season_week_ci(em[m], sw[m])
    per = pd.Series(eb[m]).groupby(b.season.to_numpy()[m]).mean()
    c26 = float(np.nanmean(eb[(b.season == 2026).to_numpy()]))
    better = int((per < 0).sum())
    ok = mb <= -0.002 and hi < 0 and better >= 3 and mhi < 0.05 and c26 < 0
    if ok:
      passed[n] = mb
    print(f"  {n:6s}: Brier {mb:+.5f} [{lo:+.5f}, {hi:+.5f}], seasons better {better}/4 {per.round(4).to_dict()}; "
          f"margin MAE {mm:+.3f} [{mlo:+.3f}, {mhi:+.3f}]; 2026 {c26:+.5f} -> {'PASS' if ok else 'FAIL'}")
  print("GATE:", f"PASS: {min(passed, key=passed.get)} (fantasy MAE guard next)" if passed else "FAIL")


def main():
  base = load_config()
  wm = base["report"]["win_model"]
  cfg = copy.deepcopy(base)
  cfg["data"]["history_seasons"] = 9
  g = elo.finished(D.load_all(cfg).schedules)
  elo_diff = dict(zip(g.game_id, elo.run(g, wm["elo_k"], wm["elo_hfa"], wm["elo_revert"], wm["elo_margin"])[0]))
  if "--bv" in sys.argv:
    return main_bv(base, elo_diff)
  res = {}
  for v in GRID:
    d = games_for(base, v)
    d = d[d.home_score != d.away_score].copy()
    d["won"] = (d.home_score > d.away_score).astype(float)
    d["home"] = (d.location != "Neutral").astype(float)
    d["rank_gap"] = d.away_rank - d.home_rank
    d["elo"] = d.game_id.map(elo_diff) / 100
    d["abs_err"] = (d.model_margin - (d.home_score - d.away_score)).abs()
    d["p"] = np.nan
    for s in range(2022, 2027):
      tr, m = d[d.season < s], (d.season == s)
      w = logit_fit(tr[["home", "rank_gap", "elo"]].to_numpy(float), tr.won.to_numpy(float))
      d.loc[m, "p"] = 1 / (1 + np.exp(-d.loc[m, ["home", "rank_gap", "elo"]].to_numpy(float) @ w))
    res[v] = d[d.season.between(2022, 2026) & d.spread_line.notna()].set_index("game_id")
    print(f"  alpha x{v[0]:.2f} half-life {v[1]}: {len(res[v])} games", flush=True)
  b = res[BASE]

  def diff(v, seasons, col):
    t = res[v].reindex(b.index)
    m = b.season.isin(seasons).to_numpy()
    e = ((t.abs_err - b.abs_err) if col == "mae" else ((t.p - b.won) ** 2 - (b.p - b.won) ** 2)).to_numpy()[m]
    sw = (b.season.astype(str) + "-" + b.week.astype(str)).to_numpy()[m]
    keys = np.unique(sw)
    idx = [np.flatnonzero(sw == k) for k in keys]
    rng = np.random.default_rng(0)
    vals = [e[np.concatenate([idx[i] for i in rng.integers(0, len(keys), len(keys))])].mean() for _ in range(2000)]
    return float(np.nanmean(e)), np.percentile(vals, 2.5), np.percentile(vals, 97.5)

  print("CHOOSE on 2022-23 (win-chance Brier vs today; margin MAE):")
  ch = {}
  for v in GRID:
    ch[v] = diff(v, [2022, 2023], "brier")
    mm = diff(v, [2022, 2023], "mae")
    print(f"  alpha x{v[0]:.2f} hl {v[1]}: Brier {ch[v][0]:+.5f} [{ch[v][1]:+.5f}, {ch[v][2]:+.5f}]  MAE {mm[0]:+.3f}")
  best = min(ch, key=lambda v: ch[v][0])
  print(f"  chosen: alpha x{best[0]:.2f}, half-life {best[1]}")
  for v in GRID:  # reported: every variant on the decide seasons
    dd = diff(v, [2024, 2025], "brier")
    print(f"  (decide seasons, reported) alpha x{v[0]:.2f} hl {v[1]}: {dd[0]:+.5f} [{dd[1]:+.5f}, {dd[2]:+.5f}]")
  if best == BASE:
    print("GATE: today's setting is the choice -> keep (now tested)")
    return
  m, lo, hi = diff(best, [2024, 2025], "brier")
  mm, mlo, mhi = diff(best, [2024, 2025], "mae")
  cm, _, _ = diff(best, [2026], "brier")
  print(f"DECIDE 2024-25: Brier {m:+.5f} [{lo:+.5f}, {hi:+.5f}]; margin MAE {mm:+.3f} [{mlo:+.3f}, {mhi:+.3f}]; CONFIRM 2026 {cm:+.5f}")
  ok = m <= -0.002 and hi < 0 and mhi < 0.05 and cm < 0
  print("GATE:", "PASS (fantasy MAE guard next)" if ok else "FAIL")


if __name__ == "__main__":
  main()
