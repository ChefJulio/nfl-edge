"""(CG) the win probability model's pre-registered test (docs/INSIGHTS.md): walk-forward, each of 2022-2025 trained on
2006 through the season before; Brier / log loss on all rows and the late-and-close subset (4th quarter, score within
8) against nflfastR's vegas_wp on the same rows; calibration by decile; scenario sanity checks.

  python tools/wp_eval.py            (fetches the play-by-play it needs once: cache/pbp_calc_<season>.parquet)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import winprob as W  # noqa: E402
from nfledge.data import Cache  # noqa: E402

FIRST, TESTS = 2006, [2022, 2023, 2024, 2025]


def load(seasons) -> pd.DataFrame:
  import nflreadpy as nfl
  cache = Cache(ROOT / "cache")
  fr = []
  for s in seasons:
    d = cache.get("pbp_calc", s, lambda s=s: nfl.load_pbp([s]).select(W.PBP_COLS), stale=False)
    fr.append(d)
  return pd.concat(fr, ignore_index=True)


def brier(p, y):
  return float(np.mean((p - y) ** 2))


def logloss(p, y):
  p = np.clip(p, 1e-6, 1 - 1e-6)
  return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def scenarios(model) -> list:
  """(4) of the gate: [label, P, low, high]."""
  base = dict(score_diff=0, game_sec=3600, half_sec=1800, down=1, ydstogo=10, yardline_100=75, own_to=3, opp_to=3,
              exp_margin=0.0, home=1, receive_2h=0)
  cases = [("up 3, ball, 0:30 left, opponent 0 TO (1st & 10 own 30)", dict(score_diff=3, game_sec=30, half_sec=30, yardline_100=70, opp_to=0), 0.97, 1.0),
           ("down 3, ball at opp 20, 0:05 left (FG to tie)", dict(score_diff=-3, game_sec=5, half_sec=5, down=4, ydstogo=10, yardline_100=20, own_to=0), 0.40, 0.60),
           ("tied, 1st & 10 own 25, opening, pick'em", dict(), 0.48, 0.55)]
  out = []
  for lab, kw, lo, hi in cases:
    x = W.features(pd.DataFrame([{**base, **kw}]))
    out.append([lab, float(model.predict_proba(x)[:, 1][0]), lo, hi])
  return out


def main():
  pbp = load(range(FIRST, max(TESTS) + 1))
  r = W.rows(pbp)
  print(f"[wp] {len(r):,} regulation rows, {FIRST}-{max(TESTS)}", flush=True)
  preds = []
  for s in TESTS:
    tr, te = r[r.season < s], r[r.season == s].copy()
    m = W.fit(tr)
    te["p"] = m.predict_proba(W.features(te))[:, 1]
    preds.append(te)
    ok = te.vegas_wp.notna()
    print(f"  {s}: n {len(te):,}  Brier ours {brier(te.p[ok], te.y[ok]):.4f}  nflfastR {brier(te.vegas_wp[ok], te.y[ok]):.4f}", flush=True)
  t = pd.concat(preds)
  t = t[t.vegas_wp.notna()]
  lc = t[(t.qtr == 4) & (t.score_diff.abs() <= 8)]
  res = {"all": (brier(t.p, t.y), brier(t.vegas_wp, t.y), logloss(t.p, t.y), logloss(t.vegas_wp, t.y), len(t)),
         "late_close": (brier(lc.p, lc.y), brier(lc.vegas_wp, lc.y), logloss(lc.p, lc.y), logloss(lc.vegas_wp, lc.y), len(lc))}
  for k, (b, bv, l, lv, n) in res.items():
    print(f"[wp] {k}: n {n:,}  Brier {b:.4f} vs nflfastR {bv:.4f} ({b - bv:+.4f})  log loss {l:.4f} vs {lv:.4f}")
  t["dec"] = np.minimum((t.p * 10).astype(int), 9)
  cal = t.groupby("dec").agg(pred=("p", "mean"), act=("y", "mean"), n=("y", "size"))
  cal["gap"] = cal.act - cal.pred
  print(cal.round(3).to_string())
  m = W.fit(r[r.season < max(TESTS)])
  sc = scenarios(m)
  for lab, p, lo, hi in sc:
    print(f"  {'ok ' if lo <= p <= hi else 'BAD'} {lab}: {p:.3f} (want {lo}-{hi})")
  g1 = res["all"][0] - res["all"][1] <= 0.003
  g2 = res["late_close"][0] - res["late_close"][1] <= 0.005
  g3 = bool((cal.gap.abs() <= 0.03).all())
  g4 = all(lo <= p <= hi for _, p, lo, hi in sc)
  print(f"[wp] gate: (1) all {g1}  (2) late-close {g2}  (3) calibration {g3}  (4) scenarios {g4}  -> {'PASS' if g1 and g2 and g3 and g4 else 'FAIL'}")


if __name__ == "__main__":
  main()
