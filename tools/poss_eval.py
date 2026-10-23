"""(CL) the possessions model's pre-registered test (docs/INSIGHTS.md): fit on 2006-18 (drives 2012-18), tested on 2019-25
4th-quarter 1st downs against the general model (CG) fit on 2006-18. Gate: (1) mean absolute calibration gap over lead
(-9..+9) x time (0:00-3:00 / 3:00-6:00 / 6:00-10:00 / 10:00-15:00) cells of 40+ lower than the general model's; (2) Brier
no worse than the general model's + 0.002. Also prints the try at 18-20 at 12:00 / 8:00 / 4:00.

  python tools/poss_eval.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import possessions as P  # noqa: E402
from nfledge import winprob as W  # noqa: E402


def main():
  d = pd.concat([pd.read_parquet(ROOT / "cache" / f"pbp_calc_{s}.parquet") for s in range(2006, 2026)], ignore_index=True)
  r = W.rows(d)
  gen = W.fit(r[r.season <= 2018])
  m = P.fit(d[d.season <= 2018])
  xp = float(d[(d.season <= 2018) & (d.season >= 2015) & d.extra_point_result.notna()].extra_point_result.eq("good").mean())
  tot = d.drop_duplicates("game_id").set_index("game_id").total_line
  t = r[(r.season >= 2019) & (r.qtr == 4) & (r.down == 1) & r.score_diff.between(-16, 16)].copy()
  t["total"] = t.game_id.map(tot).fillna(45.0)
  t["p_gen"] = gen.predict_proba(W.features(t))[:, 1]
  S = pd.DataFrame({"diff": t.score_diff, "sec": t.game_sec, "yl": t.yardline_100, "down": 1, "togo": t.ydstogo,
                    "line": t.exp_margin, "total": t.total})
  t["p_pos"] = P.wp(m, S, xp)
  t["tb"] = pd.cut(t.game_sec, [0, 180, 360, 600, 900], labels=["0:00-3:00", "3:00-6:00", "6:00-10:00", "10:00-15:00"])
  c = t[t.score_diff.between(-9, 9)].groupby(["tb", "score_diff"], observed=True).agg(n=("y", "size"), won=("y", "mean"),
                                                                                       pos=("p_pos", "mean"), gen=("p_gen", "mean"),
                                                                                       nflfastR=("vegas_wp", "mean"))
  c = c[c.n >= 40]
  c["gap_pos"], c["gap_gen"] = (c.pos - c.won).abs(), (c.gen - c.won).abs()
  print(c.round(3).to_string())
  a, b = float(c.gap_pos.mean()), float(c.gap_gen.mean())
  bp, bg = float(np.mean((t.p_pos - t.y) ** 2)), float(np.mean((t.p_gen - t.y) ** 2))
  bn = float(np.nanmean((t.vegas_wp - t.y) ** 2))
  print(f"\n[poss] {len(t):,} 4th-quarter 1st downs 2019-25: Brier possessions {bp:.4f}, general {bg:.4f}, nflfastR {bn:.4f}")
  print(f"[poss] mean calibration gap over {len(c)} cells: possessions {a:.3f}, general {b:.3f}")
  g1, g2 = a < b, bp <= bg + 0.002
  print(f"[poss] gate: (1) {g1}  (2) {g2}  -> {'PASS' if g1 and g2 else 'FAIL'}")
  mm = P.fit(d)
  for sec in (720, 480, 240):
    # the try at 18-20: the other team receives after it (its 1st & 10 at its own 30), our margin -1 / 0 / -2
    v = {k: 1 - P.wp_one(mm, -k, sec - 10, 70, 1, 10, 0, 45, 0.95) for k in (-1, 0, -2)}
    xp_ = 0.95 * v[-1] + 0.05 * v[-2]
    two_ = 0.476 * v[0] + 0.524 * v[-2]
    print(f"[poss] down 2 after a touchdown, {sec // 60}:00 left: extra point {100 * xp_:.1f}%  two {100 * two_:.1f}%  (two minus kick {100 * (two_ - xp_):+.1f})")


if __name__ == "__main__":
  main()
