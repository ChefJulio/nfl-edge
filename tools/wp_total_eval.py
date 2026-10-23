"""(CQ) the game's scoring level in the win model (docs/INSIGHTS.md): the current model vs (A) + the over/under and the
points expected in the time left vs (B) = (A) + this game's scoring pace so far. Walk-forward 2022-25.

  python tools/wp_total_eval.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402

from nfledge import winprob as W  # noqa: E402

FIRST, TESTS = 2006, [2022, 2023, 2024, 2025]
EXTRA = {"base": [], "A": ["total", "exp_rem"], "B": ["total", "exp_rem", "pace"]}


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
  d = pd.concat([pd.read_parquet(ROOT / "cache" / f"pbp_calc_{s}.parquet") for s in range(FIRST, 2026)], ignore_index=True)
  d = d[d.season_type == "REG"]
  r = W.rows(d)
  p = d.loc[r.index]
  r["total"] = p.total_line.fillna(45.0).astype(float)
  scored = (p.posteam_score.fillna(0) + p.defteam_score.fillna(0)).astype(float)
  played = 1 - r.game_sec.astype(float) / 3600
  r["exp_rem"] = r.total * (1 - played)
  r["pace"] = scored - r.total * played
  return d, r


def feats(r, v):
  x = W.features(r)
  for f in EXTRA[v]:
    x[f] = r[f].astype(float)
  return x


def fit(r, v):
  cols = W.FEATURES + EXTRA[v]
  cst = [W.MONOTONIC.get(f, 0) for f in cols]
  return HistGradientBoostingClassifier(monotonic_cst=cst, **W.PARAMS).fit(feats(r, v), r.y.astype(int))


def main():
  d, r = load()
  preds = []
  for s in TESTS:
    tr, te = r[r.season < s], r[r.season == s].copy()
    for v in EXTRA:
      te[f"p_{v}"] = fit(tr, v).predict_proba(feats(te, v))[:, 1]
    preds.append(te)
    print(f"[cq] {s} fit", flush=True)
  t = pd.concat(preds)
  t["late"] = (t.qtr == 4) & (t.score_diff.abs() <= 8)
  rng = np.random.default_rng(0)
  gm = t.game_id.to_numpy(); ug, inv = np.unique(gm, return_inverse=True)

  def paired(a, b, m=None):
    x = t if m is None else t[m]
    g = inv if m is None else inv[m.to_numpy()]
    dd = ((x[a] - x.y) ** 2 - (x[b] - x.y) ** 2).to_numpy()
    sums, cnts = np.bincount(g, dd, minlength=len(ug)), np.bincount(g, minlength=len(ug))
    bs = []
    for _ in range(1000):
      w = np.bincount(rng.integers(0, len(ug), len(ug)), minlength=len(ug))
      bs.append((w * sums).sum() / max((w * cnts).sum(), 1))
    return dd.mean(), *np.percentile(bs, [2.5, 97.5])

  br = lambda c, m=None: float(np.mean(((t if m is None else t[m])[c] - (t if m is None else t[m]).y) ** 2))  # noqa: E731
  print(f"\n[cq] {len(t):,} rows 2022-25. Brier all / late-and-close: base {br('p_base'):.5f} / {br('p_base', t.late):.5f}"
        f"  A {br('p_A'):.5f} / {br('p_A', t.late):.5f}  B {br('p_B'):.5f} / {br('p_B', t.late):.5f}"
        f"  nflfastR {float(np.nanmean((t.vegas_wp - t.y) ** 2)):.5f}")
  for v, ref in (("A", "base"), ("B", "A")):
    m, lo, hi = paired(f"p_{v}", f"p_{ref}")
    ml, lol, hil = paired(f"p_{v}", f"p_{ref}", t.late)
    dec = np.minimum((t[f"p_{v}"] * 10).astype(int), 9)
    cal = t.groupby(dec).agg(n=("y", "size"), f=(f"p_{v}", "mean"), w=("y", "mean"))
    worst = float((cal.w - cal.f).abs().max())
    g1, g2, g3 = hi < 0, ml <= 0.001, worst <= 0.03
    print(f"[cq] {v} vs {ref}: all {m:+.5f} [{lo:+.5f}, {hi:+.5f}]  late-and-close {ml:+.5f} [{lol:+.5f}, {hil:+.5f}]"
          f"  worst decile {100 * worst:.1f} pts -> (1) {g1} (2) {g2} (3) {g3}: {'PASS' if g1 and g2 and g3 else 'FAIL'}")
  # what the total does to a lead, by level (A, fit on everything through 2025)
  mA = fit(r, "A")
  print("\n[cq] A, team with the ball at its own 25, 1st & 10, pick'em, 4th quarter: win chance by lead and total")
  for sec in (480, 240):
    for lead in (3, 7):
      row = {"score_diff": lead, "game_sec": sec, "half_sec": sec, "down": 1, "ydstogo": 10, "yardline_100": 75, "own_to": 3,
             "opp_to": 3, "exp_margin": 0.0, "home": 1, "receive_2h": 0}
      out = []
      for tot in (38, 46, 54):
        q = pd.DataFrame([{**row, "total": tot, "exp_rem": tot * sec / 3600}])
        out.append(f"total {tot}: {100 * mA.predict_proba(feats(q, 'A'))[0, 1]:.1f}")
      print(f"  up {lead}, {sec // 60}:00 left: " + "  ".join(out))


if __name__ == "__main__":
  main()
