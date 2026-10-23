"""(CS) how teams that defied the calculator fared (docs/INSIGHTS.md): loss rates by agreement, and when it said go by 3+, the
choice made against each option's forecast, ours and nfl4th's. Reads scratch/calc_val/graded_*.json (tools/calc_validate.py).

  python tools/calc_defied.py
"""
import sys; sys.path.insert(0, __import__('os').path.dirname(__file__))
import numpy as np, pandas as pd, calc_validate as V
g = V._load('graded')
w = g[['w_go','w_fg','w_punt']].rename(columns=lambda c: c[2:])
g['cost'] = 100 * (w.max(axis=1) - g.f_chosen)
g['dis'] = g.best != g.choice
print(f"2022-25, {len(g):,} 4th downs (walk-forward)")
print(f"  overall the deciding team lost {1 - g.won.mean():.1%}")
for lab, m in [("agree with the call", ~g.dis), ("disagree, any margin", g.dis), ("disagree by 1.25+ (outside toss-up)", g.cost >= 1.25),
               ("disagree by 3+", g.cost >= 3), ("disagree by 5+", g.cost >= 5)]:
  x = g[m]; print(f"  {lab:38s} n {len(x):5d}  lost {1 - x.won.mean():.1%}   (forecast of their call: lose {1 - x.f_chosen.mean():.1%})")
L = g[g.won == 0]
print(f"\n  of {len(L):,} decisions by teams that went on to lose: we disagreed with {L.dis.mean():.1%} (3+ points: {(L.cost >= 3).mean():.1%})")
W = g[g.won == 1]
print(f"  of {len(W):,} decisions by teams that went on to win: we disagreed with {W.dis.mean():.1%} (3+ points: {(W.cost >= 3).mean():.1%})")
# the fair test: when we say go by 3+, did going beat kicking against each one's own forecast?
k = g[[c for c in ['w_fg','w_punt']]].max(axis=1)
gap = 100 * (g.w_go - k)
for lo, hi in [(3, 99), (1.25, 3)]:
  s = g[(gap >= lo) & (gap < hi)]
  went, kicked = s[s.choice == 'go'], s[s.choice != 'go']
  print(f"\n  we said go by {lo}-{hi if hi < 99 else '+'}: went {len(went)} (won {went.won.mean():.1%}, our go forecast {went.w_go.mean():.1%}), "
        f"kicked {len(kicked)} (won {kicked.won.mean():.1%}, our kick forecast {k[kicked.index].mean():.1%}, our go forecast for them {kicked.w_go.mean():.1%})")
rng = np.random.default_rng(0)
def ci(x, f):
  gm = x.game_id.to_numpy(); ug, inv = np.unique(gm, return_inverse=True); d = (x.won - f).to_numpy()
  s, c = np.bincount(inv, d), np.bincount(inv)
  b = [(w*s).sum()/(w*c).sum() for w in (np.bincount(rng.integers(0,len(ug),len(ug)), minlength=len(ug)) for _ in range(1000))]
  return f"{100*d.mean():+.1f} [{100*np.percentile(b,2.5):+.1f}, {100*np.percentile(b,97.5):+.1f}]"
n4k = g[['fg_wp','punt_wp']].max(axis=1)
for lo in (3, 5):
  s = g[(gap >= lo)]; kk = s[s.choice != 'go']; kk = kk[n4k[kk.index].notna()]; ww = s[s.choice == 'go']; ww = ww[ww.go_wp.notna()]
  print(f"\n  go by {lo}+ (ours), teams that kicked (n {len(kk)}): won minus our kick forecast {ci(kk, k[kk.index])}; minus nfl4th's kick {ci(kk, n4k[kk.index])}")
  print(f"     teams that went (n {len(ww)}): won minus our go forecast {ci(ww, ww.w_go)}; minus nfl4th's go {ci(ww, ww.go_wp)}")
  print(f"     kicked by period: " + ", ".join(f"{y}: {ci(kk[kk.game_id.str[:4]==str(y)], k[kk[kk.game_id.str[:4]==str(y)].index])}" for y in (2022,2023,2024,2025)))
  print(f"     kicked: punts {(kk.choice=='punt').sum()} {ci(kk[kk.choice=='punt'], k[kk[kk.choice=='punt'].index])}, field goals {(kk.choice=='fg').sum()} {ci(kk[kk.choice=='fg'], k[kk[kk.choice=='fg'].index])}")
