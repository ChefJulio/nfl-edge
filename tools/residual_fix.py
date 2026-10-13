"""Can the game model learn from its own past mistakes? Walk-forward residual corrections.

1. Flat recalibration: actual margin ~ a + b x model margin, fit on prior seasons, applied to the next.
2. Team mistake memory: each team's average miss (actual - model, from its own side) over its previous k games
   this season; corrected margin = model + c x (home team's recent miss - away team's recent miss), c fit on prior
   seasons.
Scored on margin MAE and against the spread (lean covers; break-even 52.4%).
"""
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import game_eval as ge  # noqa: E402
from nfledge.config import load_config  # noqa: E402


def team_memory(d: pd.DataFrame, k: int) -> pd.DataFrame:
  """Each team's mean miss over its previous k games in the same season (0 before any)."""
  d = d.sort_values(["season", "week"]).copy()
  rows = []
  for _, g in d.iterrows():
    rows.append((g.season, g.week, g.home_team, g.actual - g.model_margin))
    rows.append((g.season, g.week, g.away_team, -(g.actual - g.model_margin)))
  t = pd.DataFrame(rows, columns=["season", "week", "team", "miss"]).sort_values(["season", "team", "week"])
  t["mem"] = t.groupby(["season", "team"]).miss.transform(lambda s: s.shift(1).rolling(k, min_periods=1).mean())
  t["mem"] = t.mem.fillna(0.0)
  m = t.set_index(["season", "week", "team"]).mem
  d["mem_home"] = [m.get((s, w, h), 0.0) for s, w, h in zip(d.season, d.week, d.home_team)]
  d["mem_away"] = [m.get((s, w, a), 0.0) for s, w, a in zip(d.season, d.week, d.away_team)]
  d["mem_diff"] = d.mem_home - d.mem_away
  return d


def score(name, d, pred):
  ok = d.spread_line.notna() & ((d.actual - d.spread_line) != 0)
  lean = ((pred - d.spread_line) > 0) == ((d.actual - d.spread_line) > 0)
  print(f"  {name:34s} margin MAE {np.abs(pred - d.actual).mean():.3f}   ATS lean covers {lean[ok].mean():.1%} "
        f"(n={int(ok.sum())})")


if __name__ == "__main__":
  base = load_config()
  seasons = [2021, 2022, 2023, 2024, 2025, 2026]
  with ProcessPoolExecutor(max_workers=6) as ex:
    parts = list(ex.map(ge.season_games, [base] * 6, [8] * 6, seasons))
  d = pd.concat([p[0] for p in parts], ignore_index=True)
  d = d[d.variant == "fitted_6yr"].copy()
  d["actual"] = d.home_score - d.away_score
  for k in (3, 6):
    dk = team_memory(d, k)
    out = []
    for s in seasons[1:]:  # each test season learns from the seasons before it (2021 only trains)
      tr, te = dk[dk.season < s], dk[dk.season == s].copy()
      b, a = np.polyfit(tr.model_margin, tr.actual, 1)
      te["flat"] = a + b * te.model_margin
      X = tr.mem_diff.to_numpy()
      c = float(np.dot(X, tr.actual - tr.model_margin) / max(np.dot(X, X), 1e-9))
      te["memory"] = te.model_margin + c * te.mem_diff
      bb, aa = np.polyfit(tr.model_margin + c * tr.mem_diff, tr.actual, 1)
      te["both"] = aa + bb * (te.model_margin + c * te.mem_diff)
      te["fit_b"], te["fit_a"], te["fit_c"] = b, a, c
      out.append(te)
    o = pd.concat(out)
    print(f"\nTest seasons 2022-2026 (each fit on earlier seasons); team memory over last {k} games")
    print(f"  fitted: flat slope b {o.fit_b.min():.2f}-{o.fit_b.max():.2f}, intercept a {o.fit_a.min():.2f}-{o.fit_a.max():.2f}"
          f" (home edge), memory weight c {o.fit_c.min():.2f}-{o.fit_c.max():.2f}")
    score("model as is", o, o.model_margin)
    score("flat recalibration (a + b x model)", o, o.flat)
    score("team mistake memory", o, o.memory)
    score("both", o, o.both)
    score("Vegas closing line", o, o.spread_line)
