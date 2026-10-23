"""(CT) shrinking the calculator's margin toward the team's choice (docs/INSIGHTS.md). Fit 2022-23, test 2024-25.
Reads scratch/calc_val/graded_*.json (tools/calc_validate.py).

  python tools/calc_shrink_eval.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import numpy as np  # noqa: E402

import calc_validate as V  # noqa: E402


def main():
  g = V._load("graded")
  g["season"] = g.game_id.str[:4].astype(int)
  g["kick"] = g[["w_fg", "w_punt"]].max(axis=1)
  g = g[g.kick.notna() & g.w_go.notna()].copy()
  g["gk"] = (g.w_go - g.kick).clip(lower=0)   # go preferred by
  g["gg"] = (g.kick - g.w_go).clip(lower=0)   # kick preferred by
  went = g.choice == "go"
  tr = g.season <= 2023
  k, w = g[tr & ~went & (g.gk > 0)], g[tr & went & (g.gg > 0)]
  a = float((k.gk * (k.won - k.f_chosen)).sum() / (k.gk ** 2).sum())
  b = float((w.gg * (w.won - w.f_chosen)).sum() / (w.gg ** 2).sum())
  print(f"[ct] fit 2022-23: a (kick toward go) {a:.3f} on {len(k)} plays, b (go toward kick) {b:.3f} on {len(w)}")
  adj = g.f_chosen + np.where(went, b * g.gg, a * g.gk)
  g["adj"] = adj.clip(0, 1)
  te = g[(g.season >= 2024) & (((~went) & (g.gk > 0)) | (went & (g.gg > 0)))]
  d = ((te.adj - te.won) ** 2 - (te.f_chosen - te.won) ** 2).to_numpy()
  ug, inv = np.unique(te.game_id.to_numpy(), return_inverse=True)
  s, c = np.bincount(inv, d), np.bincount(inv)
  rng = np.random.default_rng(0)
  bs = [(x * s).sum() / (x * c).sum() for x in (np.bincount(rng.integers(0, len(ug), len(ug)), minlength=len(ug)) for _ in range(2000))]
  lo, hi = np.percentile(bs, [2.5, 97.5])
  print(f"[ct] 2024-25, {len(te)} plays against the calculator: Brier {np.mean((te.f_chosen - te.won) ** 2):.5f} -> "
        f"{np.mean((te.adj - te.won) ** 2):.5f}, change {d.mean():+.5f} [{lo:+.5f}, {hi:+.5f}] -> (1) {'PASS' if hi < 0 else 'FAIL'}")
  for lab, m in (("kicked when go preferred", ~te.choice.eq("go")), ("went when a kick preferred", te.choice.eq("go"))):
    x = te[m]
    print(f"  {lab}: n {len(x)} won {x.won.mean():.3f} forecast {x.f_chosen.mean():.3f} adjusted {x.adj.mean():.3f}")
  # (2) the chosen-option calibration with the adjustment
  t = g[g.season >= 2022]
  ok = True
  for ch in ("go", "fg", "punt"):
    x = t[t.choice == ch]
    gap = x.won.mean() - x.adj.mean()
    ok &= abs(gap) <= 0.03
    print(f"  (2) {ch:4s} n {len(x)} won {x.won.mean():.3f} adjusted {x.adj.mean():.3f} ({gap:+.3f})")
  dec = np.minimum((t.adj * 10).astype(int), 9)
  cal = t.groupby([t.choice, dec]).agg(n=("won", "size"), f=("adj", "mean"), w=("won", "mean"))
  bad = cal[(cal.n >= 50) & ((cal.w - cal.f).abs() > 0.06)]
  ok &= bad.empty
  print(f"  (2) deciles off by more than 6: {len(bad)} -> {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
  main()
