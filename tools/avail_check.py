"""The availability model against history, practice pattern by practice pattern (owner 2026-10-24: "can't we just
compare exact matches to practice participation patterns?"). The one week model (tuesday.week_model, as the site
builds it) trained on seasons before the last complete one predicts that season's rows; for every exact pattern
(stage x game status x his report line so far) with enough rows, its mean prediction vs the share who played.
A pattern fails when the gap is beyond chance for its size (99.9%: 3.29 standard errors) plus 3 points the model may
legitimately differ (its other inputs: games missed, role, injury); the build stops on any failure.

  python tools/avail_check.py            (exit 1 on a failure; the CI step "Availability check")
"""
import sys
from math import sqrt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402

MIN_N = 100
Z = 3.29
SLACK = 0.03


def main():
  from nfledge import tuesday as T
  from nfledge.config import load_config
  from nfledge.data import load_all
  from nfledge.injuries import InjuryModel
  cfg = load_config()
  d = load_all(cfg)
  im = InjuryModel.__new__(InjuryModel)
  im.data, im.cfg = d, cfg
  rep_rows, hurt = im._tues_inputs()
  res = bool(cfg.get("injuries", {}).get("reserve_rows"))
  w = T.week_rows(d, rep_rows, hurt, reserve=res).dropna(subset=["y"])
  w = w[~((w.stage == 3) & (w.gs_now == "Out"))]
  test = int(d.current_season) - 1
  m = T.week_model(w, test)
  x = w[w.season == test].copy()
  x["p"] = T.week_predict(m, x)
  x["key"] = x.stage.astype(int).astype(str) + " " + x.gs_now.astype(str) + " " + x.days_now.astype(str)
  g = x.groupby("key").agg(n=("y", "size"), pred=("p", "mean"), won=("y", "mean"))
  g = g[g.n >= MIN_N]
  g["band"] = Z * np.sqrt(g.won * (1 - g.won) / g.n).clip(lower=1 / g.n) + SLACK
  g["gap"] = g.pred - g.won
  bad = g[g.gap.abs() > g.band]
  print(f"[avail-check] {test} rows predicted by a model trained before it: {len(x):,}; patterns with {MIN_N}+ rows: "
        f"{len(g)}; overall predicted {x.p.mean():.3f} vs played {x.y.mean():.3f}")
  for k, r in g.sort_values("n", ascending=False).head(12).iterrows():
    print(f"  {k:28s} n {int(r.n):5d}  predicted {r.pred:.3f}  played {r.won:.3f}  ({r.gap:+.3f}, allowed {r.band:.3f})")
  if len(bad):
    for k, r in bad.iterrows():
      print(f"[avail-check] FAIL {k}: predicted {r.pred:.3f} vs played {r.won:.3f} (n {int(r.n)}, allowed +/-{r.band:.3f})")
    sys.exit(1)
  print("[avail-check] PASS: every pattern within what chance allows")


if __name__ == "__main__":
  main()
