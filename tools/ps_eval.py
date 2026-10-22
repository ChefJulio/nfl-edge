"""(CE) stage 1: P(plays) for practice-squad players (pre-registered 2026-10-21, amended; docs/INSIGHTS.md).
Walk-forward: season s trained on earlier seasons (2020 on). GATE: Brier better than a per-position constant base
rate (earlier seasons) with the 95% season-week CI excluding 0, 2022-25; reported: 2026 to date, calibration, the
rows that clear 50%.

  python tools/ps_eval.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge import practice_squad as PS  # noqa: E402
from nfledge.config import load_config  # noqa: E402


def ci(diff, cl):
  gr = pd.DataFrame({"d": diff.to_numpy(), "c": cl.to_numpy()}).groupby("c").d.agg(["sum", "size"])
  s_, n_ = gr["sum"].to_numpy(), gr["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(gr), (4000, len(gr)))
  bt = s_[idx].sum(1) / n_[idx].sum(1)
  return diff.mean(), np.percentile(bt, 2.5), np.percentile(bt, 97.5)


def main():
  PS.V2 = "--v2" in sys.argv
  print(f"(CE{'2' if PS.V2 else ''})")
  d = D.load_all(load_config())
  seasons = [s for s in d.seasons if s >= 2020]
  x = PS.rows(d, seasons)
  lab = x.dropna(subset=["y"])
  print(f"pool rows {len(x)} ({len(lab)} labelled), played {lab.y.mean():.3f}; elevated that week {lab.elev_now.mean():.3f} "
        f"(played when elevated {lab[lab.elev_now].y.mean():.3f}, not {lab[~lab.elev_now].y.mean():.3f})", flush=True)
  out = []
  for s in sorted(set(lab.season)):
    if s < 2022:
      continue
    tr, te = lab[lab.season < s], x[x.season == s].copy()
    base = tr.groupby("pos").y.mean()
    te["p_base"] = te.pos.map(base).fillna(tr.y.mean())
    te["p"] = PS.fit(tr).predict_proba(PS.features(te))[:, 1]
    out.append(te)
  r = pd.concat(out).dropna(subset=["y"])
  r["cl"] = r.season.astype(str) + "-" + r.week.astype(str)
  dlt = (r.p - r.y) ** 2 - (r.p_base - r.y) ** 2
  hist = r.season <= 2025
  m, lo, hi = ci(dlt[hist], r.cl[hist])
  print(f"\n2022-25 (n {int(hist.sum())}): Brier base {((r.p_base - r.y) ** 2)[hist].mean():.4f} -> model {((r.p - r.y) ** 2)[hist].mean():.4f}: "
        f"{m:+.4f} [{lo:+.4f}, {hi:+.4f}]; 2026 {dlt[~hist].mean():+.4f} (n {int((~hist).sum())})")
  for s in sorted(r.season.unique()):
    print(f"  {s}: {dlt[r.season == s].mean():+.4f}")
  r["band"] = pd.cut(r.p, [0, .05, .1, .2, .35, .5, .7, 1.0001], include_lowest=True)
  print(r[hist].groupby("band", observed=True).agg(n=("y", "size"), predicted=("p", "mean"), played=("y", "mean")).round(3).to_string())
  hi50 = r[hist & (r.p >= 0.5)]
  print(f"\nrows at 50%+ (would count as playing): {len(hi50)}, played {hi50.y.mean():.3f}; by position {hi50.groupby('pos').size().to_dict()}")
  gate = hi < 0
  print(f"\nGATE (stage 1): {'PASS' if gate else 'FAIL'}")


if __name__ == "__main__":
  main()
