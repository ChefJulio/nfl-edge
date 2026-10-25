"""(DF) is the calculator's late-game blind spot era drift? (docs/INSIGHTS.md; owner 2026-10-25: "i want this calculator to
be something we're proud of"). The 4th quarter's last 3:00, score within 8, 2022-25: the engine's wp() with a model
fit on 2006-18 (as every late-game test so far) vs walk-forward models fit through the season before each test
season, on (CH)'s calibration cells. Diagnostic, no gate.

  python tools/late_era_check.py export     -> scratch/calc_val/late_rows.json
  node tools/late_era_check.mjs             -> scratch/calc_val/late_scored.json
  python tools/late_era_check.py analyze
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

OUT = ROOT / "scratch" / "calc_val"


def export():
  rows = []
  for s in range(2022, 2026):
    d = pd.read_parquet(ROOT / "cache" / f"pbp_calc_{s}.parquet")
    d = d[(d.season_type == "REG") & (d.qtr == 4) & d.down.notna() & d.posteam.notna() & d.result.notna()
          & d.play_type.isin(["run", "pass", "punt", "field_goal", "qb_kneel", "qb_spike"])]
    d = d[(d.game_seconds_remaining <= 180) & (d.score_differential.abs() <= 8) & (d.result != 0)]
    home = d.posteam == d.home_team
    for r, h in zip(d.itertuples(), home):
      rows.append({"game_id": r.game_id, "season": s, "won": int((r.result > 0) == h), "diff": float(r.score_differential),
                   "sec": float(r.game_seconds_remaining), "down": int(r.down), "togo": float(r.ydstogo),
                   "yl": float(r.yardline_100), "to": float(r.posteam_timeouts_remaining), "oppTo": float(r.defteam_timeouts_remaining),
                   "line": float(r.spread_line if h else -r.spread_line), "total": float(r.total_line), "home": int(h)})
  (OUT / "late_rows.json").write_text(json.dumps(rows), encoding="utf-8")
  print(f"[df] {len(rows):,} late snaps 2022-25")


def analyze():
  t = pd.DataFrame(json.loads((OUT / "late_scored.json").read_text(encoding="utf-8")))
  t["tb"] = pd.cut(t.sec, [0, 30, 60, 120, 180], labels=["0:30", "1:00", "2:00", "3:00"], include_lowest=True)
  t["fz"] = np.select([t.yl <= 35, t.yl <= 60], ["inside opp 35", "to own 40"], "deeper")
  t["mg"] = np.select([t["diff"] == 0, t["diff"].between(-3, -1), t["diff"] <= -4, t["diff"].between(1, 3)],
                      ["tied", "behind 1-3", "behind 4-8", "ahead 1-3"], "ahead 4-8")
  rng = np.random.default_rng(0)

  def ci(d):
    gm = t.game_id.to_numpy(); ug, inv = np.unique(gm, return_inverse=True)
    s, c = np.bincount(inv, d), np.bincount(inv)
    b = [(w * s).sum() / (w * c).sum() for w in (np.bincount(rng.integers(0, len(ug), len(ug)), minlength=len(ug)) for _ in range(1000))]
    return d.mean(), *np.percentile(b, [2.5, 97.5])

  print(f"[df] {len(t):,} snaps 2022-25, {t.game_id.nunique():,} games")
  for col, lab in (("p_old", "fit 2006-18"), ("p_wf", "walk-forward (fit through the season before)")):
    print(f"  Brier {lab}: {np.mean((t[col] - t.won) ** 2):.4f}")
  m, lo, hi = ci(((t.p_wf - t.won) ** 2 - (t.p_old - t.won) ** 2).to_numpy())
  print(f"  walk-forward minus 2006-18: {m:+.4f} [{lo:+.4f}, {hi:+.4f}]")
  c = t.groupby(["mg", "tb", "fz"], observed=True).agg(n=("won", "size"), won=("won", "mean"), old=("p_old", "mean"), wf=("p_wf", "mean"))
  c = c[c.n >= 30]
  c["gap_old"], c["gap_wf"] = (c.old - c.won).abs(), (c.wf - c.won).abs()
  print(f"  calibration gap over {len(c)} cells of 30+: 2006-18 {c.gap_old.mean():.4f}, walk-forward {c.gap_wf.mean():.4f}")
  print(c.sort_values("gap_old", ascending=False).head(12).round(3).to_string())


if __name__ == "__main__":
  {"export": export, "analyze": analyze}[sys.argv[1] if len(sys.argv) > 1 else "analyze"]()
