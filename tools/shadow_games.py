"""(CH) game-level shadow matchups, pre-registered (docs/INSIGHTS.md, 2026-10-21). The list
(data/history/shadow_games_<season>.csv) names, per game, a corner who shadowed a named receiver, from after-the-fact
reporting only (kind "recap" where the column exists). Measure: that receiver's miss (actual - projected) in the
cached baseline for that season (relevant rows).
(CH) 2025 GATE: mean miss < 0 with a 95% week-bootstrap CI excluding 0, <= -1.0 points, negative in weeks 1-9 and
10-18. (CI) 2026 replication, weeks 1-6: 2026 mean <= -1.0 and pooled 2025+2026 CI excluding 0.

  python tools/shadow_games.py                      (2025, CH)
  python tools/shadow_games.py --season=2026 [--drop-note=borderline]   (CI)
"""
import glob
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from experiments import relevant  # noqa: E402
from shadow_eval import TEAM, ci, norm  # noqa: E402


def score(season: int, drop_note: str = "", max_week: int = 18):
  g = pd.read_csv(ROOT / "data" / "history" / f"shadow_games_{season}.csv")
  if "kind" in g:
    g = g[g.kind == "recap"]
  if drop_note:
    g = g[~g.note.fillna("").str.contains(drop_note, case=False)]
  g = g[g.week <= max_week].copy()
  g["offteam"] = g.offteam.str.strip().replace(TEAM)
  g["key"] = g.receiver.map(norm)
  fs = sorted(glob.glob(str(ROOT / "cache" / "experiments" / f"baseline_{season}_*.parquet")), key=os.path.getmtime)
  b = relevant(pd.read_parquet(fs[-1]))
  b = b[b.pos.isin(["WR", "TE"])].copy()
  b["team"] = b.team.replace(TEAM)
  b["key"] = b.full_name.map(norm)
  b["miss"] = b.actual - b.proj
  x = g.merge(b[["week", "team", "key", "gsis_id", "proj", "actual", "miss"]],
              left_on=["week", "offteam", "key"], right_on=["week", "team", "key"], how="left")
  gone = x[x.miss.isna()]
  print(f"{season} listed shadow games: {len(g)}; with a projection (played, 2+ prior games): {int(x.miss.notna().sum())}")
  if len(gone):
    print("  not scored (weeks 1-2, did not play, or name / team mismatch):")
    print("   " + "; ".join(f"wk{r.week} {r.receiver} {r.offteam} vs {r.corner}" for r in gone.itertuples()))
  x = x[x.miss.notna()].copy()
  sid = set(zip(x.week, x.gsis_id))
  oth = b[b.gsis_id.isin(x.gsis_id) & ~pd.Series(list(zip(b.week, b.gsis_id)), index=b.index).isin(sid)]
  return x.assign(season=season), oth


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  season = int(opt.get("season", 2025))
  if season == 2025:
    x, oth = score(2025, opt.get("drop-note", ""))
    m, lo, hi = ci(x.miss, x.week)
    print(f"\nshadowed receiver miss (actual - projected): {m:+.2f} [{lo:+.2f}, {hi:+.2f}] n {len(x)}; median {x.miss.median():+.2f}")
    print(f"same receivers, other games: {oth.miss.mean():+.2f} n {len(oth)}")
    e1, e2 = x[x.week <= 9].miss.mean(), x[x.week >= 10].miss.mean()
    print(f"weeks 1-9 {e1:+.2f} (n {int((x.week <= 9).sum())}), 10-18 {e2:+.2f} (n {int((x.week >= 10).sum())})")
    gate = hi < 0 and m <= -1.0 and e1 < 0 and e2 < 0
  else:
    x, oth = score(season, opt.get("drop-note", ""), max_week=6)
    x0, _ = score(2025)
    m = x.miss.mean()
    print(f"\n{season} weeks 1-6 shadowed receiver miss: {m:+.2f} n {len(x)}; same receivers' other games {oth.miss.mean():+.2f} n {len(oth)}")
    print(x[["week", "corner", "receiver", "proj", "actual", "miss"]].round(1).to_string(index=False))
    p = pd.concat([x0, x], ignore_index=True)
    pm, plo, phi = ci(p.miss, p.season.astype(str) + "-" + p.week.astype(str))
    print(f"pooled 2025 + {season}: {pm:+.2f} [{plo:+.2f}, {phi:+.2f}] n {len(p)}")
    gate = m <= -1.0 and phi < 0
  print("\nby corner:")
  print(x.groupby("corner").miss.agg(["size", "mean"]).sort_values("mean").round(2).to_string())
  print(f"\nGATE: {'PASS' if gate else 'FAIL'}")


if __name__ == "__main__":
  main()
