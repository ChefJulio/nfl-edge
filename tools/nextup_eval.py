"""(AY4) the next-up QB is not a healthy scratch (pre-registered 2026-10-18, docs/INSIGHTS.md).

Usage: python tools/nextup_eval.py
Walk-forward 2021-25: production's healthy-scratch model (AY3, label = the game-day active list) refit on 2019..s-1;
on the rule's rows (InjuryModel.nextup_rows) its P(dressed) against 1 - the inactive rate of those rows in 2019..s-1.
GATE: Brier on the rule's rows not worse (95% CI upper < +0.0005 over season-weeks) and the rule within 1 point of the
actual inactive rate. Other rows are untouched by construction.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402

import run as RUN  # noqa: E402
from nfledge.config import load_config, load_scoring  # noqa: E402
from nfledge.data import load_all  # noqa: E402


def main():
  cfg, sc = load_config(), load_scoring()
  data = load_all(cfg)
  eng, _ = RUN.cached_model(data, cfg, sc, data.current_season, RUN.display_week(data))
  im = eng.injury_model
  seasons = [s for s in range(2019, 2026) if s in data.seasons]
  tab = {}
  for s in seasons:
    t = im.scratch_table(s)
    tab[s] = t[t.final & (t.week <= data.completed_weeks(s)) & ~t.on_report & t.observable & (t.week >= 2)].copy()
  cols = im.scratch_cols
  out = []
  for s in range(2021, 2026):
    tr = pd.concat([tab[x] for x in seasons if x < s])
    m = HistGradientBoostingClassifier(**im._gb_params(), random_state=0).fit(tr[cols], tr.active)
    nr = tr[im.nextup_rows(tr)]
    rate = 1 - nr.active.mean() if len(nr) else 0.0
    te = tab[s][im.nextup_rows(tab[s])].copy()
    te["pA"] = m.predict_proba(te[cols])[:, 1]
    te["pB"] = 1 - rate
    te["season"] = s
    out.append(te)
    print(f"[AY4] {s}: rule rows {len(te)}, inactive {(~te.active.astype(bool)).sum()}, rate from earlier seasons {rate:.2%}")
  T = pd.concat(out)
  y = T.active.astype(float)
  T["d"] = (T.pB - y) ** 2 - (T.pA - y) ** 2
  T["g"] = T.season.astype(str) + "-" + T.week.astype(str)
  gs = T.groupby("g").d.agg(["sum", "size"])
  idx = np.random.default_rng(0).integers(0, len(gs), (4000, len(gs)))
  bt = gs["sum"].to_numpy()[idx].sum(1) / gs["size"].to_numpy()[idx].sum(1)
  lo, hi = np.percentile(bt, [2.5, 97.5])
  act = 1 - y.mean()
  print(f"[AY4] rows {len(T)}: inactive {act:.2%}; model says {1 - T.pA.mean():.2%}, rule {1 - T.pB.mean():.2%}")
  print(f"[AY4] Brier {((T.pA - y) ** 2).mean():.5f} -> {((T.pB - y) ** 2).mean():.5f}, {T.d.mean():+.5f} [{lo:+.5f}, {hi:+.5f}]")
  print(f"[AY4] model's max on these rows {1 - T.pA.min():.1%} (how far it strays from the group)")
  print("[AY4] GATE:", "PASS" if hi < 0.0005 and abs((1 - T.pB.mean()) - act) <= 0.01 else "FAIL")
  allr = pd.concat(tab.values())
  print(f"[AY4] live rate (2019-25): {1 - allr[im.nextup_rows(allr)].active.mean():.4f}")


if __name__ == "__main__":
  main()
