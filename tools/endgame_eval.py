"""(CH) the end-of-half drive model's pre-registered test (docs/INSIGHTS.md): walk-forward 2022-2025, each season's drive
model fit on 2012 through the season before and its general model (CG) on 2006 through the season before; rows =
4th-quarter snaps with 2:00 or less, score within 8. Gate: (1) pooled Brier lower than the general model's; (2) mean
absolute calibration gap over time x field position cells (tied, behind 1-3, behind 4-8 separately; cells of 30+)
lower than the general model's. Kickoff landing spots come from the test season's own kickoffs (set by the rules,
which changed in 2024 and 2025).

  python tools/endgame_eval.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import calc_inputs as C  # noqa: E402
from nfledge import endgame as G  # noqa: E402
from nfledge import winprob as W  # noqa: E402

TESTS = [2022, 2023, 2024, 2025]


def main():
  d = pd.concat([pd.read_parquet(ROOT / "cache" / f"pbp_calc_{s}.parquet") for s in range(2006, 2026)], ignore_index=True)
  wr = W.rows(d)
  er = G.rows(d[d.season >= 2012])
  out = []
  for s in TESTS:
    gen = W.fit(wr[wr.season < s])
    m = G.fit(er[er.season < s])
    k = C.kickoff(d[d.season == s])["rec"]
    comp = G.Composer(m, gen, G.spots(er[er.season < s]), [k[2], k[5], k[7]], C.tries(d[d.season < s])["xp"])
    t = wr[(wr.season == s) & (wr.qtr == 4) & (wr.game_sec <= 120) & (wr.score_diff.abs() <= 8) & wr.down.notna()].copy()
    t["p_gen"] = gen.predict_proba(W.features(t))[:, 1]
    t["p_end"] = comp.wp(t.reset_index(drop=True)).copy()
    out.append(t)
    b = lambda c: np.mean((t[c] - t.y) ** 2)  # noqa: E731
    print(f"  {s}: n {len(t):,}  Brier drive model {b('p_end'):.4f}  general {b('p_gen'):.4f}  nflfastR {np.nanmean((t.vegas_wp - t.y) ** 2):.4f}", flush=True)
  t = pd.concat(out)
  br = {c: float(np.mean((t[c] - t.y) ** 2)) for c in ("p_end", "p_gen")}
  br["nflfastR"] = float(np.nanmean((t.vegas_wp - t.y) ** 2))
  print(f"[endgame] pooled n {len(t):,}: Brier drive model {br['p_end']:.4f}, general {br['p_gen']:.4f}, nflfastR {br['nflfastR']:.4f}")
  t["tb"] = pd.cut(t.game_sec, [0, 30, 60, 120], labels=["<=0:30", "0:31-1:00", "1:01-2:00"])
  t["yb"] = pd.cut(t.yardline_100, [0, 35, 60, 100], labels=["inside opp 35", "opp 35-own 40", "deeper"])
  t["sg"] = np.where(t.score_diff == 0, "tied", np.where(t.score_diff.between(-3, -1), "behind 1-3",
                     np.where(t.score_diff.between(-8, -4), "behind 4-8", "ahead")))
  g = t[t.sg != "ahead"].groupby(["sg", "tb", "yb"], observed=True).agg(n=("y", "size"), actual=("y", "mean"), drive=("p_end", "mean"),
                                                                          general=("p_gen", "mean"), nflfastR=("vegas_wp", "mean"))
  g = g[g.n >= 30]
  g["gap_drive"], g["gap_general"] = (g.drive - g.actual).abs(), (g.general - g.actual).abs()
  print(g.round(3).to_string())
  cal = (float(g.gap_drive.mean()), float(g.gap_general.mean()))
  print(f"[endgame] mean calibration gap over {len(g)} cells: drive model {cal[0]:.3f}, general {cal[1]:.3f}")
  g1, g2 = br["p_end"] < br["p_gen"], cal[0] < cal[1]
  print(f"[endgame] gate: (1) Brier {g1}  (2) calibration {g2}  -> {'PASS' if g1 and g2 else 'FAIL'}")


if __name__ == "__main__":
  main()
