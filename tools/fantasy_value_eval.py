"""Thread 4 (INSIGHTS 2026-10-16): score where fantasy value is, next to the usual relevant() rows (not replacing them).

Usage: python tools/fantasy_value_eval.py [--variant=baseline]
Reads the latest cached walk-forward backtest per season (cache/experiments/<variant>_<season>_*.parquet, 2021-25;
2026 too if cached). Reports:
  1. Extended set: every player-week that played with >= 30% offensive snaps that week OR a projection >= 3,
     including players with < 2 earlier games. Model vs ECR MAE by position on the rows where ECR exists, plus the
     model's MAE where ECR has no rank. (Selecting on snaps played uses the outcome; both forecasts are scored on the
     same rows, so the comparison is fair, but the absolute MAE is not a forecast-time number.)
  2. Breakouts: each player's first top-24 RB / top-36 WR / top-12 TE / top-12 QB week of a season (by actual
     points among all who played). His position rank by our projection vs by ECR, that week and the next.
  3. Decision metric: for every pair of players at a position in a week whose consensus ranks (mean of our rank and
     ECR's) are within 6 inside the top 36 (QB / TE 18), starting the one a source ranks higher gains
     (actual of that one - actual of the other) / 2 over a coin flip. Mean points gained per pair, 95% CI over
     season-weeks, model vs ECR.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

TOP = {"QB": 12, "RB": 24, "WR": 36, "TE": 12}
PAIR_DEPTH = {"QB": 18, "RB": 36, "WR": 36, "TE": 18}


def latest(variant: str) -> pd.DataFrame:
  parts = []
  for s in range(2021, 2027):
    fs = sorted((ROOT / "cache" / "experiments").glob(f"{variant}_{s}_*.parquet"), key=lambda f: f.stat().st_mtime)
    if fs:
      parts.append(pd.read_parquet(fs[-1]))
  return pd.concat(parts, ignore_index=True)


def boot(v: np.ndarray, g: np.ndarray, n=2000):
  df = pd.DataFrame({"v": v, "g": g}).groupby("g").v.agg(["sum", "size"])
  s, c = df["sum"].to_numpy(), df["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(df), (n, len(df)))
  m = s[idx].sum(1) / c[idx].sum(1)
  return v.mean(), np.percentile(m, 2.5), np.percentile(m, 97.5)


def decision_gain(d: pd.DataFrame, col: str, other: str = "ecr_pts") -> pd.DataFrame:
  """Per pair (same season / week / position, consensus ranks within 6 inside the pair depth): points gained over a
  coin flip by starting the one `col` ranks higher. Pairs come from rows where both col and `other` exist, so every
  source is scored on the same pairs."""
  out = []
  d = d.dropna(subset=[col, other, "actual"])
  for (s, w, pos), g in d.groupby(["season", "week", "pos"]):
    g = g.assign(r1=g[col].rank(ascending=False), r2=g[other].rank(ascending=False))
    g["cr"] = (g.r1 + g.r2) / 2
    g = g[g.cr <= PAIR_DEPTH[pos]].sort_values("cr")
    a, p, cr = g.actual.to_numpy(), g[col].to_numpy(), g.cr.to_numpy()
    for i in range(len(g)):
      for j in range(i + 1, len(g)):
        if cr[j] - cr[i] > 6:
          break
        if p[i] == p[j]:
          continue
        pick = (a[i] - a[j]) if p[i] > p[j] else (a[j] - a[i])
        out.append((s, w, pos, pick / 2))
  return pd.DataFrame(out, columns=["season", "week", "pos", "gain"])


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  res = latest(opt.get("variant", "baseline"))
  res = res[res.pos.isin(TOP)]
  from nfledge import data as D
  from nfledge.config import load_config
  d = D.load_all(load_config())
  sn = d.snaps.dropna(subset=["gsis_id"])[["season", "week", "gsis_id", "offense_pct"]].drop_duplicates(["season", "week", "gsis_id"])
  res = res.merge(sn, on=["season", "week", "gsis_id"], how="left")
  pl = res[res.played]
  print(f"backtest rows {len(res):,} ({sorted(res.season.unique())}); played {len(pl):,}")

  # 1. extended set
  ext = pl[(pl.offense_pct.fillna(0) >= 0.30) | (pl.proj >= 3)]
  rel = pl[pl.raw_games >= 2].copy()
  rel["consensus"] = rel[["proj", "raw_fpg", "vegas"]].mean(axis=1)
  rel["crank"] = rel.groupby(["season", "week", "pos"]).consensus.rank(ascending=False)
  from nfledge.backtest import RELEVANT_TOP
  relset = set(rel[rel.crank <= rel.pos.map(RELEVANT_TOP)].index)
  print(f"\n1. Extended set: {len(ext):,} player-weeks ({ext.index.isin(relset).sum():,} also in the scored 'relevant' rows; "
        f"{(ext.raw_games.fillna(0) < 2).sum():,} with < 2 earlier games)")
  print(f"{'pos':4s} {'n (ECR)':>8s} {'model':>7s} {'ECR':>7s} {'diff [95% CI]':>24s}   {'n (no ECR)':>10s} {'model':>7s}")
  for pos in ["ALL", *TOP]:
    g = ext if pos == "ALL" else ext[ext.pos == pos]
    e = g[g.ecr_pts.notna()]
    m, lo, hi = boot(((e.proj - e.actual).abs() - (e.ecr_pts - e.actual).abs()).to_numpy(),
                     (e.season.astype(str) + e.week.astype(str)).to_numpy())
    ne = g[g.ecr_pts.isna()]
    print(f"{pos:4s} {len(e):8,d} {(e.proj - e.actual).abs().mean():7.3f} {(e.ecr_pts - e.actual).abs().mean():7.3f} "
          f"{m:+8.3f} [{lo:+.3f}, {hi:+.3f}]   {len(ne):10,d} {(ne.proj - ne.actual).abs().mean():7.3f}")
  outside = ext[~ext.index.isin(relset)]
  e2 = outside[outside.ecr_pts.notna()]
  print(f"  only the rows OUTSIDE the scored set (n {len(e2):,} with ECR): model {(e2.proj - e2.actual).abs().mean():.3f} "
        f"vs ECR {(e2.ecr_pts - e2.actual).abs().mean():.3f}; bias (actual - proj) model {(e2.actual - e2.proj).mean():+.2f}, "
        f"ECR {(e2.actual - e2.ecr_pts).mean():+.2f}")

  # 2. breakouts
  pl = pl.copy()
  pl["arank"] = pl.groupby(["season", "week", "pos"]).actual.rank(ascending=False, method="min")
  pl["mrank"] = res.loc[pl.index].groupby(["season", "week", "pos"]).proj.rank(ascending=False, method="min")
  allp = res.copy()
  allp["mrank"] = allp.groupby(["season", "week", "pos"]).proj.rank(ascending=False, method="min")
  allp["erank"] = allp.groupby(["season", "week", "pos"]).ecr_pts.rank(ascending=False, method="min")
  hit = pl[pl.arank <= pl.pos.map(TOP)].sort_values("week").groupby(["season", "gsis_id"]).head(1)
  hit = hit[hit.week >= 4]  # a breakout, not a week-3 starter we already rank
  key = allp.set_index(["season", "week", "gsis_id"])[["mrank", "erank"]]
  rows = []
  for x in hit.itertuples():
    for lag, lab in ((0, "that week"), (1, "next week")):
      k = (x.season, x.week + lag, x.gsis_id)
      if k in key.index:
        r = key.loc[k]
        r = r.iloc[0] if isinstance(r, pd.DataFrame) else r
        rows.append({"pos": x.pos, "when": lab, "ours": r.mrank, "ecr": r.erank})
  b = pd.DataFrame(rows)
  print(f"\n2. Breakouts: first top-{'/'.join(map(str, TOP.values()))} week of a season, week 4 on: {len(hit):,} player-seasons")
  for (pos, when), g in b.groupby(["pos", "when"], sort=False):
    both = g.dropna()
    print(f"  {pos} {when:9s} n {len(g):4d}  median rank ours {g.ours.median():5.1f}  ECR {g.ecr.median():5.1f} "
          f"(ECR ranks him: {g.ecr.notna().mean():.0%}); where both rank him, ours higher {(both.ours < both.ecr).mean():.0%}, "
          f"ECR higher {(both.ours > both.ecr).mean():.0%} (n {len(both)})")

  # 3. decision metric
  print("\n3. Start / sit decisions between near-equal players (consensus ranks within 6), points gained per pair over a coin flip:")
  dm, de = decision_gain(res[res.played], "proj"), decision_gain(res[res.played], "ecr_pts", "proj")
  for pos in ["ALL", *TOP]:
    a = dm if pos == "ALL" else dm[dm.pos == pos]
    e = de if pos == "ALL" else de[de.pos == pos]
    ma = boot(a.gain.to_numpy(), (a.season.astype(str) + a.week.astype(str)).to_numpy())
    me = boot(e.gain.to_numpy(), (e.season.astype(str) + e.week.astype(str)).to_numpy())
    print(f"  {pos:4s} pairs {len(a):6,d}  model {ma[0]:+.3f} [{ma[1]:+.3f}, {ma[2]:+.3f}]   ECR {me[0]:+.3f} [{me[1]:+.3f}, {me[2]:+.3f}]")
  for s in sorted(dm.season.unique()):
    print(f"  {s}: model {dm[dm.season == s].gain.mean():+.3f}  ECR {de[de.season == s].gain.mean():+.3f}")


if __name__ == "__main__":
  main()
