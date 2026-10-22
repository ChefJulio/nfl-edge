"""(CJ) "hurt in the game, then returned" (pre-registered 2026-10-21, docs/INSIGHTS.md). Walk-forward: the Tuesday
model (T.fit) and the week model (T.week_fit) for test season s train on seasons before s, with and without the
hurt_back input (T.HURT_BACK); test seasons 2025 and 2026 to date (gamebooks log returns from 2024).
GATE: Brier on rows with an injury note lower with the 95% season-week CI excluding 0; all rows not worse (CI upper
< +0.0005).

  python tools/hurt_back_eval.py
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

TEST = (2025, 2026)


def ci(diff: pd.Series, cl: pd.Series):
  gr = pd.DataFrame({"d": diff.to_numpy(), "c": cl.to_numpy()}).groupby("c").d.agg(["sum", "size"])
  s_, n_ = gr["sum"].to_numpy(), gr["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(gr), (4000, len(gr)))
  bt = s_[idx].sum(1) / n_[idx].sum(1)
  return diff.mean(), np.percentile(bt, 2.5), np.percentile(bt, 97.5)


def walk(rows: pd.DataFrame, fit, feats) -> pd.DataFrame:
  out = []
  for s in TEST:
    tr, te = rows[rows.season < s], rows[rows.season == s].copy()
    if not len(te):
      continue
    for flag in (False, True):
      T.HURT_BACK = flag
      te[f"p{int(flag)}"] = fit(tr).predict_proba(feats(te))[:, 1]
    out.append(te)
  T.HURT_BACK = False
  return pd.concat(out, ignore_index=True)


def report(name: str, x: pd.DataFrame) -> bool:
  x = x.assign(cl=x.season.astype(str) + "-" + x.week.astype(str))
  b0, b1 = (x.p0 - x.y) ** 2, (x.p1 - x.y) ** 2
  d = b1 - b0
  h = x.hurt_in_game == 1
  m, lo, hi = ci(d[h], x.cl[h])
  ma, loa, hia = ci(d, x.cl)
  print(f"\n{name}: rows {len(x)}, with an injury note {int(h.sum())} (returned {int((x.hurt_back == 1).sum())})")
  print(f"  injury-note rows Brier {b0[h].mean():.4f} -> {b1[h].mean():.4f}: {m:+.4f} [{lo:+.4f}, {hi:+.4f}]")
  print(f"  all rows         Brier {b0.mean():.4f} -> {b1.mean():.4f}: {ma:+.4f} [{loa:+.4f}, {hia:+.4f}]")
  for s in TEST:
    k = h & (x.season == s)
    if k.any():
      print(f"  {s} injury-note rows: {d[k].mean():+.4f} (n {int(k.sum())})")
  for lab, k in (("returned", x.hurt_back == 1), ("no return", h & (x.hurt_back == 0))):
    print(f"  {lab:<9}: played {x.y[k].mean():.3f}, predicted {x.p0[k].mean():.3f} -> {x.p1[k].mean():.3f} (n {int(k.sum())})")
  return hi < 0 and hia < 0.0005


def main():
  cfg = load_config()
  d = D.load_all(cfg)
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  rep, hurt = T.report_rows(d), T.hurt_notes(d, cache)
  print(f"injury notes {len(hurt)}, with a return {len(hurt.back)}; seasons logging returns {sorted(hurt.ret_seasons)}")
  tue = T.build_rows(d, rep, hurt).dropna(subset=["y"])
  g1 = report("Tuesday model", walk(tue, T.fit, T.features))
  wk = T.week_rows(d, rep, hurt).dropna(subset=["y"])
  g2 = report("Week model", walk(wk, T.week_fit, T.week_features))
  print(f"\nGATE: {'PASS' if g1 and g2 else 'FAIL'} (Tuesday {'pass' if g1 else 'fail'}, week {'pass' if g2 else 'fail'})")


if __name__ == "__main__":
  main()
