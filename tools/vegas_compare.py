"""Model vs Vegas on games, 2021 to now: winner picks when they disagree, model + Vegas blends, and against-the-
spread / totals hit rates by size of disagreement. Usage: python tools/vegas_compare.py (about 3 min, 6 workers)."""
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

import game_eval as ge  # noqa: E402
from nfledge.config import load_config  # noqa: E402

if __name__ == "__main__":
  base = load_config()
  seasons = [2021, 2022, 2023, 2024, 2025, 2026]
  with ProcessPoolExecutor(max_workers=6) as ex:
    parts = list(ex.map(ge.season_games, [base] * 6, [8] * 6, seasons))
  d = pd.concat([p[0] for p in parts], ignore_index=True)
  d = d[d.variant == "fitted_6yr"].copy()  # the live configuration (points formula on 6 seasons)
  d["actual"] = d.home_score - d.away_score
  d = d[d.spread_line.notna() & (d.actual != 0)]
  d["model_home"] = d.model_margin > 0
  d["vegas_home"] = d.spread_line > 0
  d["home_won"] = d.actual > 0
  dis = d[(d.model_home != d.vegas_home) & (d.spread_line != 0)]
  for name, g in (("2021-2025", dis[dis.season < 2026]), ("2026 wk 1-5", dis[dis.season == 2026])):
    print(f"{name}: {len(g)} games with different picks; model right {(g.model_home == g.home_won).mean():.0%}, "
          f"Vegas right {(g.vegas_home == g.home_won).mean():.0%}")
  print(f"all games: model picks winner {(d.model_home == d.home_won).mean():.1%}, "
        f"Vegas {(d.vegas_home == d.home_won).mean():.1%} (n={len(d)})")
  print("\nBlend margin = w x model + (1-w) x Vegas; margin MAE (lower = better):")
  for w in (0.0, 0.1, 0.2, 0.3, 0.5, 1.0):
    m = w * d.model_margin + (1 - w) * d.spread_line
    per = "  ".join(f"{s}: {(m - d.actual)[d.season == s].abs().mean():.2f}" for s in seasons)
    print(f"  w={w:.1f}: {per}   all: {(m - d.actual).abs().mean():.3f}")

  # Against the spread: when the model's margin differs from the spread, does its side cover?
  d["edge"] = d.model_margin - d.spread_line          # + = model likes home more than Vegas
  d["cover_home"] = d.actual - d.spread_line           # + = home covered
  d = d[d.cover_home != 0]                              # pushes out
  d["lean_right"] = (d.edge > 0) == (d.cover_home > 0)
  print("\nAgainst the spread (break-even 52.4%): model lean covers, by size of disagreement")
  for lo, hi in ((0, 1.5), (1.5, 3), (3, 5), (5, 8), (8, 99)):
    g = d[(d.edge.abs() >= lo) & (d.edge.abs() < hi)]
    print(f"  |edge| {lo:>4}-{hi:<3}: {len(g):4d} games, lean covers {g.lean_right.mean():.1%}")
  print(f"  all: {len(d)} games, {d.lean_right.mean():.1%}")
  d["tot_edge"] = d.model_total - d.total_line
  d["over"] = (d.home_score + d.away_score) - d.total_line
  t = d[(d.over != 0) & d.total_line.notna()]
  t_right = (t.tot_edge > 0) == (t.over > 0)
  print("Totals: model over/under lean hits, by size of disagreement")
  for lo, hi in ((0, 2), (2, 4), (4, 7), (7, 99)):
    m = (t.tot_edge.abs() >= lo) & (t.tot_edge.abs() < hi)
    print(f"  |edge| {lo:>3}-{hi:<3}: {m.sum():4d} games, lean hits {t_right[m].mean():.1%}")
