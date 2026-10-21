"""Where does the gap to Vegas live? (descriptive, 2026-10-20, docs/INSIGHTS.md "Gap split").

Usage: python tools/gap_split.py  (needs cache/vegas_prior_eval.parquet from tools/vegas_prior_eval.py)
ours = Matchups win chance; mkt_season = ratings fit to closing spreads through LAST week (no game-specific info for
this game); vegas = this game's closing line. Logistic arms fit walk-forward, scored 2022-25.
"""
import sys; sys.path.insert(0, 'tools'); sys.path.insert(0, '.')
import numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from market_wins_eval import market_ratings
from nfledge.standings import RELOCATED
df = pd.read_parquet('cache/vegas_prior_eval.parquet')
s = pd.read_parquet('cache/schedules_all.parquet'); s = s[(s.game_type == 'REG') & s.season.between(2021, 2026)].copy()
s['home_team'], s['away_team'] = s.home_team.replace(RELOCATED), s.away_team.replace(RELOCATED)
mk = {}
for (se, w), _ in df.groupby(['season', 'week']):
  if w < 2: continue
  reg = s[s.season == se]
  mk[(se, w)] = market_ratings(reg, w - 1, sorted(set(reg.home_team)))  # lines through LAST week only
df = df[df.week >= 2].copy()
df['mgap'] = [mk[(se, w)][h] - mk[(se, w)][a] for se, w, h, a in zip(df.season, df.week, df.home_team, df.away_team)]
ml = lambda m: np.where(m > 0, 100 / (m + 100), -m / (-m + 100))
ph, pa = ml(df.ml_h), ml(df.ml_a); df['vegas'] = ph / (ph + pa)
arms = {'ours': ['home', 'gap', 'elo'], 'mkt_season': ['home', 'mgap'], 'mkt_season+elo': ['home', 'mgap', 'elo']}
for se in [2022, 2023, 2024, 2025, 2026]:
  tr, te = df.season < se, df.season == se
  for a, c in arms.items():
    df.loc[te, a] = LogisticRegression(C=1e6, max_iter=2000).fit(df.loc[tr, c], df.loc[tr, 'y']).predict_proba(df.loc[te, c])[:, 1]
T = df[df.season.between(2022, 2025)]
b = {a: ((T[a] - T.y) ** 2) for a in list(arms) + ['vegas']}
print(f"{len(T)} games 2022-25, weeks 2-18. Brier:")
for a in b: print(f"  {a:16s} {b[a].mean():.4f}")
tot = b['ours'].mean() - b['vegas'].mean()
st = b['ours'].mean() - b['mkt_season'].mean()
print(f"gap ours -> vegas {tot:+.4f}: team strength (ours -> market season view) {st:+.4f} ({st / tot:.0%}), game-specific (season view -> line) {tot - st:+.4f} ({(tot - st) / tot:.0%})")
T = T.assign(band=pd.cut(T.week, [1, 6, 12, 18], labels=['wk 2-6', 'wk 7-12', 'wk 13-18']))
print(T.assign(**{f'b_{a}': b[a] for a in b}).groupby('band', observed=True)[[f'b_{a}' for a in b]].mean().round(4).to_string())
rng = np.random.default_rng(0)
for x, y in (('mkt_season', 'ours'), ('vegas', 'mkt_season')):
  d = (b[x] - b[y]).to_numpy(); bt = d[rng.integers(0, len(d), (2000, len(d)))].mean(1)
  print(f"{x} - {y}: {d.mean():+.4f} [{np.percentile(bt, 2.5):+.4f}, {np.percentile(bt, 97.5):+.4f}]")
