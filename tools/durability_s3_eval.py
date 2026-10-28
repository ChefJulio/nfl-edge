"""(S3) durability by episodes, re-shrunk, recency-weighted (pre-registered 2026-10-28, docs/INSIGHTS.md).

On (S2)'s harness (tools/durability_snaps_eval.py): player-seasons 2014-25, target unit snaps survived in T before his
first game missed injured, C-index within position group weighted by rows. Today's score B: games missed injured per
1,000 unit snaps, shrunk 250 (TE 2,000). Candidates: (E) injury episodes that cost a game instead of games missed;
(K) the shrink re-chosen on 2014-19; (R) past seasons weighted 0.5^(age / h), h chosen on 2014-19. GATE on 2020-25
against B: better, 95% player-cluster bootstrap interval excluding 0, better in 4+ of 6 seasons.

  python tools/durability_s3_eval.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import durability_snaps_eval as S2  # noqa: E402

CHOOSE, DECIDE = range(2014, 2020), range(2020, 2026)
KS, HS = (250, 500, 1000, 2000, 4000), (2, 3, 5)


def load():
  """(S2)'s players, plus each season's count of injury episodes that cost a game."""
  import player_logs as PL
  P = S2.load()
  # S2.load drops the episodes; read them again from the same history (cached)
  inj = S2.PL.injury_history.__wrapped__ if hasattr(S2.PL.injury_history, "__wrapped__") else None  # noqa: F841
  return P


def load_eps():
  """gsis -> {season: episodes that cost a game}, from player_logs.injury_history (the same call S2.load makes)."""
  import nflreadpy as nfl
  from nfledge import data as D
  from nfledge.config import ROOT, load_config
  import player_logs as PL
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
  out = {}
  for g, v in inj.items():
    e = {}
    for ep in v["eps"]:
      if ep.get("missed"):
        e[ep["s"]] = e.get(ep["s"], 0) + 1
    out[g] = e
  return out


def rows(P: dict, E: dict, T: int, h: float | None) -> pd.DataFrame:
  """(S2)'s rows for season T, with history weighted by age (h None: every season the same) and both event kinds."""
  r = []
  for g, (grp, gs, missed, snaps, weeks) in P.items():
    if gs.get(T, 0) < 8 or T not in weeks:
      continue
    hist = [s for s in gs if 2013 <= s < T]
    if not hist:
      continue
    w = {s: (0.5 ** ((T - 1 - s) / h) if h else 1.0) for s in hist}
    M = sum(missed.get(s, 0) * w[s] for s in hist)
    N = sum(E.get(g, {}).get(s, 0) * w[s] for s in hist)
    Sn = sum(snaps.get(s, 0.0) * w[s] for s in hist)
    ws = sorted(weeks[T])
    if ws[0][1]:
      continue
    t, ev = 0.0, 0
    for wk, o, s_ in ws:
      if o:
        ev = 1
        break
      t += s_
    if t <= 0:
      continue
    r.append((g, grp, M, N, Sn, t, ev))
  return pd.DataFrame(r, columns=["gsis", "grp", "M", "N", "S", "t", "e"])


def score(d: pd.DataFrame, ev: str, k: int) -> np.ndarray:
  """Events per 1,000 snaps shrunk toward the group's rate by k snaps (TE 2,000 unless k is larger), negated."""
  s = np.zeros(len(d))
  for grp, x in d.groupby("grp"):
    r0 = x[ev].sum() / max(1.0, x.S.sum()) * 1000
    kk = max(k, 2000) if grp == "TE" else k
    s[d.index.get_indexer(x.index)] = -((x[ev] + r0 * kk / 1000) / ((x.S + kk) / 1000))
  return s


def c_of(d: pd.DataFrame, s: np.ndarray) -> float:
  return S2.season_c(d.assign(sc=s), "sc")


def main():
  P = S2.load()
  E = load_eps()
  base = {T: rows(P, E, T, None) for T in list(CHOOSE) + list(DECIDE)}
  # today's B, per season
  B = {T: c_of(d, score(d, "M", 250)) for T, d in base.items()}
  # choose K (for games and for episodes) and h on 2014-19
  def mean_c(ev, k, h):
    return np.mean([c_of(d, score(d, ev, k)) for T in CHOOSE for d in [rows(P, E, T, h) if h else base[T]]])
  grid = {(ev, k, h): mean_c(ev, k, h) for ev in ("M", "N") for k in KS for h in (None,) + HS}
  for ev in ("M", "N"):
    print(f"choose 2014-19, events={'games missed' if ev == 'M' else 'episodes'}:",
          {f"K{k}/h{h}": round(v, 4) for (e_, k, h), v in grid.items() if e_ == ev})
  kE = max(KS, key=lambda k: grid[("N", k, None)])
  kK = max(KS, key=lambda k: grid[("M", k, None)])
  hR = max(HS, key=lambda h: grid[("M", 250, h)])
  print(f"chosen: (E) episodes with K {kE}; (K) games with K {kK}; (R) games, K 250, h {hR}")
  cand = {"E episodes": ("N", kE, None), "K re-shrunk": ("M", kK, None), "R recency": ("M", 250, hR)}

  def gate(ev, k, h, lab):
    per = {T: c_of(d, score(d, ev, k)) for T in DECIDE for d in [rows(P, E, T, h) if h else base[T]]}
    diffs = [per[T] - B[T] for T in DECIDE]
    allr = pd.concat([(rows(P, E, T, h) if h else base[T]).assign(T=T) for T in DECIDE], ignore_index=True)
    allr["new"] = np.concatenate([score(d, ev, k) for T in DECIDE for d in [allr[allr["T"] == T].reset_index(drop=True)]])
    # today's B from the unweighted history (the same players and rows; a weighted candidate's M and S differ)
    old = pd.concat([base[T].assign(T=T, old=score(base[T], "M", 250)) for T in DECIDE], ignore_index=True)
    allr = allr.merge(old[["T", "gsis", "old"]], on=["T", "gsis"], how="left")
    ids, by = allr.gsis.unique(), {g: x for g, x in allr.groupby("gsis")}
    rng, bs = np.random.default_rng(7), []
    for _ in range(300):
      smp = pd.concat([by[g] for g in rng.choice(ids, len(ids))], ignore_index=True)
      bs.append(np.mean([S2.season_c(x, "new") - S2.season_c(x, "old") for _, x in smp.groupby("T")]))
    lo, hi = np.percentile(bs, [2.5, 97.5])
    better = sum(d_ > 0 for d_ in diffs)
    ok = lo > 0 and better >= 4
    print(f"  {lab:28s} C - B {np.mean(diffs):+.4f} [{lo:+.4f}, {hi:+.4f}], better {better}/6  {'PASS' if ok else 'FAIL'}")
    return ok

  print("GATE 2020-25 vs today's B:")
  passed = {lab: gate(*v, lab) for lab, v in cand.items()}
  ev = "N" if passed["E episodes"] else "M"
  k = (kE if ev == "N" else kK) if (passed["K re-shrunk"] or passed["E episodes"]) else 250
  h = hR if passed["R recency"] else None
  if sum(passed.values()) > 1:
    # the passing ones together (K re-chosen for that event kind and weighting on 2014-19)
    k = max(KS, key=lambda kk: mean_c(ev, kk, h))
    gate(ev, k, h, f"together ({ev}, K {k}, h {h})")
  print(f"\nShipped score if any passed: events={ev}, K {k}, h {h}")
  # where Allen and the short clean QBs land (2026 view: every season through 2025)
  return ev, k, h


if __name__ == "__main__":
  main()
