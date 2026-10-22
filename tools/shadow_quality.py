"""(CG) elite shadow corners only, the pre-registered follow-up to (CF) (docs/INSIGHTS.md, 2026-10-21). Same list,
WR1-games and model miss as tools/shadow_eval.py, 2021-25. Quality = the corner's yards allowed per target in coverage
from his games BEFORE that one that season (nflverse PFR weekly advanced defense; 15+ targets so far, else last
season's full rate; none -> dropped). Shadowed games split at the median quality into better / worse halves.
GATE: better half's miss < 0 with a 95% season-week bootstrap CI excluding 0, >= 0.5 points below the worse half,
negative in both 2021-23 and 2024-25.

  python tools/shadow_quality.py [--plot=path.png]
"""
import glob
import os
import sys
from pathlib import Path

import nflreadpy as nfl
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from experiments import relevant  # noqa: E402
from shadow_eval import TEAM, ci, norm, wr1_games  # noqa: E402

MIN_TGT = 15


def quality(yrs) -> pd.DataFrame:
  """(season, week, key) -> yards per target allowed before that week (or last season's)."""
  a = nfl.load_pfr_advstats(yrs, stat_type="def", summary_level="week").to_pandas()
  a = a[a.game_type == "REG"].assign(key=a.pfr_player_name.map(norm))
  a = a.groupby(["season", "week", "key"])[["def_targets", "def_yards_allowed"]].sum().reset_index().sort_values("week")
  g = a.groupby(["season", "key"])
  a["t_before"] = g.def_targets.transform(lambda x: x.shift().fillna(0).cumsum())
  a["y_before"] = g.def_yards_allowed.transform(lambda x: x.shift().fillna(0).cumsum())
  full = a.groupby(["season", "key"])[["def_targets", "def_yards_allowed"]].sum()
  full = (full.def_yards_allowed / full.def_targets).where(full.def_targets >= MIN_TGT)
  prev = {(s + 1, k): v for (s, k), v in full.dropna().items()}
  a["ypt"] = np.where(a.t_before >= MIN_TGT, a.y_before / a.t_before.replace(0, np.nan),
                      [prev.get((s, k), np.nan) for s, k in zip(a.season, a.key)])
  return a[["season", "week", "key", "ypt"]]


def main():
  opt = dict(x[2:].split("=", 1) for x in sys.argv[1:] if x.startswith("--") and "=" in x)
  lst = pd.read_csv(ROOT / "data" / "history" / "shadow_corners.csv")
  lst = lst[lst.confidence.str.strip().str.lower().isin({"high", "medium"})].copy()
  lst["team"] = lst.team.str.strip().replace(TEAM)
  lst["key"] = lst.player.map(norm)
  yrs = list(range(2020, 2026))
  sn = nfl.load_snap_counts(yrs).to_pandas()
  sn = sn[(sn.game_type == "REG") & (sn.defense_snaps.fillna(0) > 0)]
  played = set(zip(sn.season, sn.week, sn.team.replace(TEAM), sn.player.map(norm)))
  listed = {}
  for r in lst.itertuples():
    listed.setdefault((int(r.season), r.team), []).append((r.key, r.player))
  w = wr1_games(list(range(2021, 2026)))
  on = [[(k, nm) for k, nm in listed.get((int(r.season), r.defteam), []) if (r.season, r.week, r.defteam, k) in played]
        for r in w.itertuples()]
  w["key"] = [o[0][0] if o else "" for o in on]
  w["corner"] = [o[0][1] if o else "" for o in on]
  w = w[w.corner != ""]
  fr = []
  for s in range(2021, 2026):
    fs = sorted(glob.glob(str(ROOT / "cache" / "experiments" / f"baseline_{s}_*.parquet")), key=os.path.getmtime)
    fr.append(relevant(pd.read_parquet(fs[-1])))
  b = pd.concat(fr, ignore_index=True)
  b = b[b.pos == "WR"][["season", "week", "gsis_id", "proj", "actual"]]
  x = w.merge(b, on=["season", "week", "gsis_id"]).merge(quality(yrs), on=["season", "week", "key"], how="left")
  x["miss"] = x.actual - x.proj
  x["sw"] = x.season.astype(str) + "-" + x.week.astype(str)
  n0 = len(x)
  x = x[x.ypt.notna()].copy()
  med = x.ypt.median()
  x["half"] = np.where(x.ypt <= med, "better", "worse")
  print(f"shadowed WR1-games with a projection: {n0}; with a prior coverage rate: {len(x)}; median {med:.2f} yds/target")
  res = {}
  for h in ("better", "worse"):
    y = x[x.half == h]
    m, lo, hi = ci(y.miss, y.sw)
    res[h] = (m, lo, hi)
    print(f"  {h:<6} (yds/tgt {y.ypt.min():.1f}-{y.ypt.max():.1f}): miss {m:+.2f} [{lo:+.2f}, {hi:+.2f}] n {len(y)}")
  bt = x[x.half == "better"]
  e1, e2 = bt[bt.season <= 2023].miss.mean(), bt[bt.season >= 2024].miss.mean()
  gap = res["better"][0] - res["worse"][0]
  print(f"  better minus worse {gap:+.2f}; better half 2021-23 {e1:+.2f}, 2024-25 {e2:+.2f}")
  print("\nby corner (better-half games / all):")
  print(x.groupby("corner").agg(games=("miss", "size"), better=("half", lambda s: int((s == "better").sum())),
                                ypt=("ypt", "mean"), miss=("miss", "mean")).sort_values("ypt").round(2).to_string())
  gate = res["better"][2] < 0 and gap <= -0.5 and e1 < 0 and e2 < 0
  print(f"\nGATE: {'PASS' if gate else 'FAIL'}")
  if "plot" in opt:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(x.ypt, x.miss, s=12, alpha=.35, color="#3b6fb6")
    q = pd.qcut(x.ypt, 6)
    mm = x.groupby(q, observed=True).agg(ypt=("ypt", "mean"), miss=("miss", "mean"))
    ax.plot(mm.ypt, mm.miss, "o-", color="#d9480f", lw=2, label="average per sixth")
    ax.axhline(0, color="#888", lw=1)
    ax.axvline(med, color="#888", lw=1, ls="--", label="median split")
    ax.set_xlabel("Shadow corner's yards allowed per target before the game (lower = better)")
    ax.set_ylabel("WR1 actual minus our projection (pts)")
    ax.set_title(f"Shadowed WR1 games 2021-25 (n {len(x)})")
    ax.legend()
    fig.tight_layout()
    fig.savefig(opt["plot"], dpi=130)
    print(f"plot: {opt['plot']}")


if __name__ == "__main__":
  main()
