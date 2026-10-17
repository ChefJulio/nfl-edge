"""(S) durability per snap vs per game (docs/INSIGHTS.md, pre-registered 2026-10-17).

For each player-season T (2014-2025, 8+ team games on the roster in T), two scores from his history 2013..T-1:
  A  share of team games available (not out injured), shrunk to the group's pooled rate by 17 games (the site today)
  B  games missed injured per 1,000 snaps, shrunk to the group's pooled rate by K snaps (K chosen on T = 2014-2019)
scored by the within-group Spearman correlation with fewer games missed in T; gate on T = 2020-2025.

  python tools/durability_eval.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from nfledge import data as D  # noqa: E402
from nfledge.config import ROOT, load_config  # noqa: E402
import player_logs as PL  # noqa: E402

GRP = {**{p: "OL" for p in "T OT G OG C OL".split()}, **{p: "DL" for p in "DE DT NT DL".split()},
       **{p: "LB" for p in "LB ILB OLB MLB".split()}, **{p: "DB" for p in "CB S SS FS SAF DB".split()}, "FB": "RB"}
OFFENSE = {"QB", "RB", "WR", "TE", "OL"}
DEFENSE = {"DL", "LB", "DB"}
KS = (250, 500, 1000, 2000)
CHOOSE, DECIDE = range(2014, 2020), range(2020, 2026)


def load():
  """Per player: group, {season: team games on the roster}, {season: games missed injured}, {season: unit snaps}."""
  import nflreadpy as nfl
  cfg = load_config()
  data = D.load_all(cfg)
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  first = min(data.seasons)
  players = cache.get("players", "all", lambda: nfl.load_players(), stale=False)
  pfr = players.dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates("pfr_id").set_index("pfr_id").gsis_id
  old = [cache.get("snaps", s, lambda: nfl.load_snap_counts([s]), stale=False) for s in range(2012, first)]
  old = [x[x.game_type == "REG"] for x in old if x is not None and len(x)]
  sn = pd.concat(old + [data.snaps], ignore_index=True)
  sn["gsis_id"] = sn.pfr_player_id.map(pfr).fillna(sn.gsis_id) if "gsis_id" in sn else sn.pfr_player_id.map(pfr)
  sn = sn.dropna(subset=["gsis_id"])
  allsched = cache.get("schedules", "since1999", lambda: None, stale=False)
  allsched = allsched[allsched.game_type == "REG"]
  ros_cols = ["season", "week", "team", "gsis_id", "position", "status", "status_description_abbr"]
  all_ros = pd.concat([x[[c for c in ros_cols if c in x]] for x in
                       [cache.get("rosters", s, lambda: None, stale=False) for s in range(2002, first)] + [data.rosters]
                       if x is not None and len(x)], ignore_index=True)
  tot = sn[["offense_snaps", "defense_snaps", "st_snaps"]].fillna(0).sum(axis=1)
  played = set(zip(sn.gsis_id[tot > 0], sn.season[tot > 0].astype(int), sn.week[tot > 0].astype(int)))
  inj = PL.injury_history(cache, nfl, data.current_season, all_ros, allsched, played)
  pos = all_ros.dropna(subset=["gsis_id"]).sort_values(["season", "week"]).drop_duplicates("gsis_id", keep="last").set_index("gsis_id").position
  off = sn.groupby(["gsis_id", "season"]).offense_snaps.sum()
  dfn = sn.groupby(["gsis_id", "season"]).defense_snaps.sum()
  out = {}
  for g, v in inj.items():
    grp = GRP.get(str(pos.get(g)), str(pos.get(g)))
    if grp not in OFFENSE | DEFENSE:
      continue
    unit = off if grp in OFFENSE else dfn
    missed = {}
    for e in v["eps"]:
      if e.get("missed") is not None:
        missed[e["s"]] = missed.get(e["s"], 0) + e["missed"]
    snaps = {int(s): float(unit.get((g, s), 0.0)) for s in v["gs"]}
    out[g] = (grp, v["gs"], missed, snaps)
  return out


def rows(P: dict, T: int) -> pd.DataFrame:
  """Player-season rows for target season T with both scores' raw history (shrinking happens per K)."""
  r = []
  for g, (grp, gs, missed, snaps) in P.items():
    if gs.get(T, 0) < 8:
      continue
    hist = [s for s in gs if 2013 <= s < T]
    if not hist:
      continue
    G = sum(gs[s] for s in hist)
    M = sum(missed.get(s, 0) for s in hist)
    S = sum(snaps.get(s, 0.0) for s in hist)
    r.append((g, grp, G, M, S, missed.get(T, 0) / gs[T]))
  return pd.DataFrame(r, columns=["gsis", "grp", "G", "M", "S", "y"])


def scores(d: pd.DataFrame, K: dict) -> pd.DataFrame:
  d = d.copy()
  d["A"] = np.nan
  d["B"] = np.nan
  for grp, x in d.groupby("grp"):
    pool = x[x.G >= 17]
    a0 = 1 - pool.M.sum() / max(1, pool.G.sum())
    r0 = x.M.sum() / max(1.0, x.S.sum()) * 1000  # missed per 1,000 snaps, the group's history
    d.loc[x.index, "A"] = ((1 - x.M / x.G.where(x.G > 0, 1)) * x.G + a0 * 17) / (x.G + 17)
    k = K.get(grp, 1000)
    d.loc[x.index, "B"] = -((x.M + r0 * k / 1000) / ((x.S + k) / 1000))  # higher = more durable
  return d


def season_corr(d: pd.DataFrame, col: str) -> float:
  tot, n = 0.0, 0
  for _, x in d.groupby("grp"):
    if len(x) < 20 or x.y.nunique() < 2:
      continue
    c = spearmanr(x[col], -x.y).correlation
    if np.isfinite(c):
      tot += c * len(x)
      n += len(x)
  return tot / n if n else np.nan


def main():
  P = load()
  data = {T: rows(P, T) for T in range(2014, 2026)}
  print("rows per season:", {T: len(d) for T, d in data.items()})
  # K per group, chosen on 2014-2019
  K = {}
  for grp in sorted({v[0] for v in P.values()}):
    best = max(KS, key=lambda k: np.nanmean([season_corr(scores(data[T][data[T].grp == grp], {grp: k}), "B") for T in CHOOSE]))
    K[grp] = best
  print("K chosen on 2014-19:", K)
  S = {T: scores(data[T], K) for T in DECIDE}
  per = {T: (season_corr(d, "A"), season_corr(d, "B")) for T, d in S.items()}
  for T, (a, b) in per.items():
    print(f"{T}: A {a:+.4f}  B {b:+.4f}  B-A {b - a:+.4f}")
  diff = np.mean([b - a for a, b in per.values()])
  better = sum(b > a for a, b in per.values())
  # player-cluster bootstrap over the decide seasons
  allr = pd.concat([d.assign(T=T) for T, d in S.items()], ignore_index=True)
  ids = allr.gsis.unique()
  by = {g: x for g, x in allr.groupby("gsis")}
  rng = np.random.default_rng(7)
  boots = []
  for _ in range(1000):
    smp = pd.concat([by[g] for g in rng.choice(ids, len(ids))], ignore_index=True)
    boots.append(np.mean([season_corr(x, "B") - season_corr(x, "A") for _, x in smp.groupby("T")]))
  lo, hi = np.percentile(boots, [2.5, 97.5])
  print(f"DECIDE 2020-25: B-A {diff:+.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]  B better {better}/6  CI width {hi - lo:.4f}")
  for grp in sorted(K):
    a = np.nanmean([season_corr(d[d.grp == grp], "A") for d in S.values()])
    b = np.nanmean([season_corr(d[d.grp == grp], "B") for d in S.values()])
    n = sum((d.grp == grp).sum() for d in S.values())
    print(f"  {grp}: A {a:+.4f}  B {b:+.4f}  (rows {n})")
  gate = lo > 0 and better >= 4
  print("GATE:", "PASS" if gate else "FAIL")


if __name__ == "__main__":
  main()
