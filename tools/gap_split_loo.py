import sys; sys.path.insert(0, 'tools'); sys.path.insert(0, '.')
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from nfledge.standings import RELOCATED
df = pd.read_parquet('cache/vegas_prior_eval.parquet'); df = df[df.week >= 2].copy()
s = pd.read_parquet('cache/schedules_all.parquet'); s = s[(s.game_type == 'REG') & s.season.between(2021, 2026)].copy()
s['home_team'], s['away_team'] = s.home_team.replace(RELOCATED), s.away_team.replace(RELOCATED)
def fit(g, teams, week):
  ix = {t: i for i, t in enumerate(teams)}; X = np.zeros((len(g), len(teams) + 1))
  for r, x in enumerate(g.itertuples()):
    X[r, ix[x.home_team]], X[r, ix[x.away_team]] = 1, -1; X[r, -1] = 0 if x.location == 'Neutral' else 1
  wt = 0.5 ** ((week - g.week.to_numpy()) / 4.0); Xw, yw = X * np.sqrt(wt)[:, None], g.spread_line.to_numpy() * np.sqrt(wt)
  pen = np.eye(X.shape[1]); pen[-1, -1] = 0
  b = np.linalg.solve(Xw.T @ Xw + pen, Xw.T @ yw); return dict(zip(teams, b[:-1])), b[-1]
loo = []
for x in df.itertuples():
  reg = s[(s.season == x.season) & (s.week <= x.week) & (s.game_id != x.game_id) & s.spread_line.notna()]
  r, hfa = fit(reg, sorted(set(s[s.season == x.season].home_team)), x.week)
  loo.append(r[x.home_team] - r[x.away_team])
df['mgap_loo'] = loo
ml = lambda m: np.where(m > 0, 100 / (m + 100), -m / (-m + 100)); ph, pa = ml(df.ml_h), ml(df.ml_a); df['vegas'] = ph / (ph + pa)
arms = {'ours': ['home', 'gap', 'elo'], 'mkt_now': ['home', 'mgap_loo']}
for se in [2022, 2023, 2024, 2025]:
  tr, te = df.season < se, df.season == se
  for a, c in arms.items():
    df.loc[te, a] = LogisticRegression(C=1e6, max_iter=2000).fit(df.loc[tr, c], df.loc[tr, 'y']).predict_proba(df.loc[te, c])[:, 1]
T = df[df.season.between(2022, 2025)]
b = {a: (T[a] - T.y) ** 2 for a in ['ours', 'mkt_now', 'vegas']}
for a in b: print(f"{a:8s} {b[a].mean():.4f}")
rng = np.random.default_rng(0)
for x, y in (('mkt_now', 'ours'), ('vegas', 'mkt_now')):
  d = (b[x] - b[y]).to_numpy(); bt = d[rng.integers(0, len(d), (2000, len(d)))].mean(1)
  print(f"{x} - {y}: {d.mean():+.4f} [{np.percentile(bt, 2.5):+.4f}, {np.percentile(bt, 97.5):+.4f}]")
T = T.assign(band=pd.cut(T.week, [1, 6, 12, 18], labels=['wk 2-6', 'wk 7-12', 'wk 13-18']))
print(T.assign(**{f'b_{a}': b[a] for a in b}).groupby('band', observed=True)[[f'b_{a}' for a in b]].mean().round(4).to_string())
print('corr of market LOO gap with line:', round(T.mgap_loo.corr(T.spread_line if 'spread_line' in T else pd.Series(dtype=float)), 3) if 'spread_line' in T else '')
sp = s.set_index('game_id').spread_line
T = T.assign(line=T.game_id.map(sp))
from numpy.linalg import lstsq
X = np.c_[np.ones(len(T)), T.mgap_loo]; beta = lstsq(X, T.line, rcond=None)[0]; res = T.line - X @ beta
print(f"line vs LOO market rating gap: corr {T.line.corr(T.mgap_loo):.3f}, residual sd {res.std():.2f} pts, line sd {T.line.std():.2f}")
print('residual sd by band:', T.assign(r=res).groupby('band', observed=True).r.std().round(2).to_dict())
