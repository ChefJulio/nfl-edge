"""Thread 6 (pre-registered 2026-10-16, docs/INSIGHTS.md): correlation-aware Fantasy matchup win chance.

Usage: python tools/h2h_eval.py [--n=20000]
Simulated head-to-heads (1 QB / 2 RB / 3 WR / 1 TE each side) from the latest baseline walk-forward backtests.
  current  P(A wins) = Phi((E_a - E_b) / sqrt(sum of every starter's variance)), the Fantasy tab's formula
           (league.js: variance = pa sd^2 + pa (1 - pa) proj^2, sd = (p90 - p10) / 2.563, players independent)
  corr     the same plus 2 rho s_i s_j for each pair of starters in one game (teammates or opponents), within a
           lineup added and across the two lineups subtracted; rho by position pair and relation, the correlation of
           standardized misses on the seasons before the test season
Lineup kinds: unstacked (no two starters from one game), QB+1 / QB+2 (his own pass catchers); the opponent is
unstacked and may share games. Scored by expected calibration error (10 bins) and Brier, 2025 (decide), 2026 (confirm).
"""
import itertools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import norm  # noqa: E402

import fantasy_value_eval as F  # noqa: E402

SLOTS = {"QB": 1, "RB": 2, "WR": 3, "TE": 1}
CATCH = ("WR", "TE")


def prep(res: pd.DataFrame) -> pd.DataFrame:
  d = res[res.pos.isin(SLOTS) & (res.proj >= 3) & res.game_id.notna()].copy()
  d["pa"] = d.avail.fillna(1.0).clip(0, 1)
  d["sd"] = ((d.p90 - d.p10) / 2.563).clip(lower=0.5)
  d["E"] = d.proj * d.pa
  d["s"] = np.sqrt(d.pa * d.sd ** 2 + d.pa * (1 - d.pa) * d.proj ** 2)
  d["z"] = (d.actual.fillna(0) - d.E) / d.s
  d = d[np.isfinite(d.z) & np.isfinite(d.s) & (d.s > 0)]  # rows without a range (p10 / p90) can't be scored
  return d.reset_index(drop=True)


def key(p1, t1, p2, t2) -> tuple:
  a, b = sorted([p1, p2])
  return (a, b, "same" if t1 == t2 else "opp")


def fit_rho(d: pd.DataFrame) -> dict:
  """Correlation of standardized misses for every pair of players in one game, by position pair and relation."""
  acc = {}
  for _, g in d.groupby(["season", "week", "game_id"]):
    pos, team, z = g.pos.to_numpy(), g.team.to_numpy(), g.z.to_numpy()
    for i, j in itertools.combinations(range(len(g)), 2):
      acc.setdefault(key(pos[i], team[i], pos[j], team[j]), []).append((z[i], z[j]))
  out = {}
  for k, v in acc.items():
    a = np.array(v)
    if len(a) >= 200:
      out[k] = float(np.corrcoef(a[:, 0], a[:, 1])[0, 1])
  return out


def lineup(rng, pool: pd.DataFrame, kind: str):
  """Row indices of a lineup: unstacked, or a QB plus 1 / 2 of his own pass catchers."""
  used_games, out = set(), []
  need = dict(SLOTS)
  if kind != "unstacked":
    qbs = pool[pool.pos == "QB"]
    for _ in range(50):
      q = qbs.iloc[rng.integers(len(qbs))]
      mates = pool[(pool.team == q.team) & pool.pos.isin(CATCH)]
      k = 1 if kind == "qb1" else 2
      if len(mates) >= k:
        pick = mates.iloc[rng.choice(len(mates), k, replace=False)]
        out = [q.name] + list(pick.index)
        need["QB"] -= 1
        for p in pick.pos:
          need[p] -= 1
        if min(need.values()) < 0:
          out, need = [], dict(SLOTS)
          continue
        used_games.add(q.game_id)
        break
    if not out:
      return None
  for pos, n in need.items():
    cand = pool[(pool.pos == pos) & ~pool.game_id.isin(used_games)]
    for _ in range(n):
      if not len(cand):
        return None
      r = cand.iloc[rng.integers(len(cand))]
      out.append(r.name)
      used_games.add(r.game_id)
      cand = cand[cand.game_id != r.game_id]
  return out


def covsum(d, A, B, rho, sign: float) -> float:
  """Sum over pairs (i in A, j in B, same game) of rho s_i s_j; for A == B each unordered pair once."""
  tot = 0.0
  pairs = itertools.combinations(A, 2) if B is None else itertools.product(A, B)
  for i, j in pairs:
    if d["game_id"][i] != d["game_id"][j] or i == j:
      continue
    r = rho.get(key(d["pos"][i], d["team"][i], d["pos"][j], d["team"][j]), 0.0)
    tot += r * d["s"][i] * d["s"][j]
  return sign * tot


def ece(p, y, bins=10):
  p, y = np.asarray(p), np.asarray(y)
  idx = np.minimum((p * bins).astype(int), bins - 1)
  return float(sum(abs(p[idx == b].mean() - y[idx == b].mean()) * (idx == b).sum() for b in range(bins) if (idx == b).any()) / len(p))


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  n = int(opt.get("n", 20000))
  d = prep(F.latest("baseline"))
  cols = {c: d[c].to_numpy() for c in ("game_id", "pos", "team", "s", "E", "actual")}
  for s in (2025, 2026):
    rho = fit_rho(d[d.season < s])
    if s == 2025:
      print("rho fit on 2021-24 (same team / opponents):")
      for k in sorted(rho, key=lambda k: (k[2], k[0], k[1])):
        print(f"  {k[2]:4s} {k[0]}-{k[1]}: {rho[k]:+.3f}")
    test = d[d.season == s]
    weeks = sorted(test.week.unique())
    rng = np.random.default_rng(s)
    print(f"\n{s} (weeks {weeks[0]}-{weeks[-1]}):")
    for kind in ("unstacked", "qb1", "qb2"):
      pc, pn, y = [], [], []
      while len(y) < n:
        w = weeks[rng.integers(len(weeks))]
        pool = test[test.week == w]
        A, B = lineup(rng, pool, kind), lineup(rng, pool, "unstacked")
        if A is None or B is None:
          continue
        ea, eb = cols["E"][A].sum(), cols["E"][B].sum()
        va, vb = (cols["s"][A] ** 2).sum(), (cols["s"][B] ** 2).sum()
        cur = norm.cdf((ea - eb) / np.sqrt(va + vb))
        cv = va + vb + 2 * covsum(cols, A, None, rho, 1) + 2 * covsum(cols, B, None, rho, 1) - 2 * covsum(cols, A, B, rho, 1)
        new = norm.cdf((ea - eb) / np.sqrt(max(cv, 1e-6)))
        aa, ab = np.nan_to_num(cols["actual"][A]).sum(), np.nan_to_num(cols["actual"][B]).sum()
        pc.append(cur); pn.append(new); y.append(1.0 if aa > ab else 0.0 if aa < ab else 0.5)
      y = np.array(y)
      bc, bn = ((np.array(pc) - y) ** 2).mean(), ((np.array(pn) - y) ** 2).mean()
      print(f"  {kind:9s} ECE current {ece(pc, y):.4f}  corr {ece(pn, y):.4f}   Brier current {bc:.4f}  corr {bn:.4f}")


if __name__ == "__main__":
  main()
