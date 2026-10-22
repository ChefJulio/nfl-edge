"""(CN) the Tuesday model learns elapsed time (pre-registered 2026-10-22, docs/INSIGHTS.md). Walk-forward: the model
for test season s trains on seasons before s; base = production rows and inputs; time = TIME_ROWS (gap_days input +
the 2-week training rows). Scored on real rows only (the next team game), 2021-25 + 2026 to date.
GATE: Brier on rows whose next game follows a bye lower with the 95% season-week CI excluding 0; all rows not worse
(CI upper < +0.0005).

  python tools/time_rows_eval.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge import tuesday as T  # noqa: E402
from nfledge.config import load_config  # noqa: E402


def ci(diff: pd.Series, cl: pd.Series):
  gr = pd.DataFrame({"d": diff.to_numpy(), "c": cl.to_numpy()}).groupby("c").d.agg(["sum", "size"])
  s_, n_ = gr["sum"].to_numpy(), gr["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(gr), (4000, len(gr)))
  bt = s_[idx].sum(1) / n_[idx].sum(1)
  return diff.mean(), np.percentile(bt, 2.5), np.percentile(bt, 97.5)


def main():
  cfg = load_config()
  d = D.load_all(cfg)
  rep, hurt = T.report_rows(d), T.hurt_notes(d, D.Cache(ROOT / cfg["data"]["cache_dir"]))
  T.TIME_ROWS = True
  x = T.build_rows(d, rep, hurt).dropna(subset=["y"])
  print(f"rows {len(x)}: real {int((x.aug == 0).sum())}, 2-week training rows {int((x.aug == 1).sum())} "
        f"(played {x[x.aug == 1].y.mean():.3f})", flush=True)
  out = []
  for s in sorted(set(range(2021, 2026)) | {int(x.season.max())}):
    te = x[(x.season == s) & (x.aug == 0)].copy()
    tr = x[x.season < s]
    T.TIME_ROWS = False
    te["p_base"] = T.fit(tr[tr.aug == 0]).predict_proba(T.features(te))[:, 1]
    T.TIME_ROWS = True
    te["p_time"] = T.fit(tr).predict_proba(T.features(te))[:, 1]
    out.append(te)
  T.TIME_ROWS = False
  r = pd.concat(out, ignore_index=True)
  r["cl"] = r.season.astype(str) + "-" + r.week.astype(str)
  dlt = (r.p_time - r.y) ** 2 - (r.p_base - r.y) ** 2
  hist = r.season <= 2025
  bye = r.gap_days >= 12
  m, lo, hi = ci(dlt[hist & bye], r.cl[hist & bye])
  ma, loa, hia = ci(dlt[hist], r.cl[hist])
  print(f"\nbye rows 2021-25 (n {int((hist & bye).sum())}): {m:+.4f} [{lo:+.4f}, {hi:+.4f}]; played {r.y[hist & bye].mean():.3f}, "
        f"base {r.p_base[hist & bye].mean():.3f}, time {r.p_time[hist & bye].mean():.3f}")
  print(f"all rows 2021-25 (n {int(hist.sum())}): {ma:+.4f} [{loa:+.4f}, {hia:+.4f}]; 2026 all {dlt[~hist].mean():+.4f}, "
        f"bye {dlt[~hist & bye].mean():+.4f} (n {int((~hist & bye).sum())})")
  hb = hist & bye & (r.hurt_in_game == 1)
  print(f"hurt in his last game, bye next (n {int(hb.sum())}): played {r.y[hb].mean():.3f}, base {r.p_base[hb].mean():.3f}, time {r.p_time[hb].mean():.3f}")
  for lo_, hi_ in ((0, .3), (.3, .6), (.6, .9), (.9, 1.01)):
    k = hist & bye & (r.p_time >= lo_) & (r.p_time < hi_)
    if k.any():
      print(f"  bye rows, time model {lo_:.0%}-{min(hi_, 1):.0%}: n {int(k.sum())}, predicted {r.p_time[k].mean():.3f}, played {r.y[k].mean():.3f}")
  gate = hi < 0 and hia < 0.0005
  print(f"\nGATE: {'PASS' if gate else 'FAIL'}")


if __name__ == "__main__":
  main()
