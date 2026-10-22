import sys; sys.path.insert(0, "tools")
import tier_x_defense as T, glob, os, numpy as np, pandas as pd
from experiments import relevant
fr = []
for s in range(2021, 2026):
  fs = sorted(glob.glob(f"cache/experiments/baseline_{s}_*.parquet"), key=os.path.getmtime)
  fr.append(pd.read_parquet(fs[-1]))
full = pd.concat(fr, ignore_index=True)
# WR fantasy points allowed per game by each defense, before the week (all WRs who played, our scoring)
wr = full[(full.pos == "WR") & (full.played == 1)]
allowed = wr.groupby(["season", "week", "opp"]).actual.sum().rename("pa").reset_index().sort_values(["season", "opp", "week"])
allowed["pa_before"] = allowed.groupby(["season", "opp"]).pa.transform(lambda x: x.shift().expanding().mean())
d = pd.concat([relevant(f) for f in fr], ignore_index=True)
d = d[(d.pos == "WR") & (d.week >= 4) & (d.raw_games >= 3)].merge(allowed[["season", "week", "opp", "pa_before"]], on=["season", "week", "opp"]).dropna(subset=["pa_before"])
d["res"] = d.actual - d.proj
d["sw"] = d.season.astype(str) + "-" + d.week.astype(str)
d["rk"] = d.groupby(["season", "week"]).raw_fpg.rank(ascending=False, method="first")
d["tier"] = pd.cut(d.rk, [0, 12, 36, 999], labels=["top 12", "13-36", "37+"])
d["defense"] = d.groupby(["season", "week"]).pa_before.transform(lambda x: pd.qcut(x.rank(method="first"), 3, labels=["tough", "middle", "soft"]))
print("actual minus season FP/G by defense third (OPRK-style):", d.assign(rel=d.actual - d.raw_fpg).groupby("defense", observed=True).rel.mean().round(2).to_dict())
print(f"{'tier':<8}" + "".join(f"{c:>30}" for c in ("tough", "middle", "soft")))
for t in ("top 12", "13-36", "37+"):
  row = []
  for c in ("tough", "middle", "soft"):
    x = d[(d.tier == t) & (d.defense == c)]; m, lo, hi = T.ci(x); row.append(f"{m:+.2f} [{lo:+.2f},{hi:+.2f}] n{len(x)}")
  print(f"{t:<8}" + "".join(f"{c:>30}" for c in row))
f = lambda b, t, c: b[(b.tier.isin(t)) & (b.defense == c)].res.mean()
inter = lambda b: (f(b, ["top 12"], "tough") - f(b, ["top 12"], "soft")) - (f(b, ["13-36", "37+"], "tough") - f(b, ["13-36", "37+"], "soft"))
sws = d.sw.unique(); rng = np.random.default_rng(1); di = d.set_index("sw")
bs = [inter(di.loc[rng.choice(sws, len(sws))].reset_index()) for _ in range(1000)]
print(f"interaction: {inter(d):+.2f} [{np.percentile(bs, 2.5):+.2f}, {np.percentile(bs, 97.5):+.2f}]")
