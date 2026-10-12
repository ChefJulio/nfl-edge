"""Backtest config variants against each other. Decide on one season, confirm on the next.

Usage: python tools/experiments.py [variant,variant,...] [season]
Variants are config overrides keyed 'section__key'; add your own to VARIANTS below."""
import sys, copy, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd
pd.set_option('display.width',250)
from nfledge.config import load_config, load_scoring
from nfledge import data as D, backtest as B
from nfledge.engine import Engine
base=load_config(); sc=load_scoring(); d=D.load_all(base)
POS=['QB','RB','WR','TE']
def variant(**kw):
  c=copy.deepcopy(base)
  for k,v in kw.items():
    sec,key=k.split('__'); c[sec][key]=v
  return c
VARIANTS={
 'baseline':variant(),
 'implied_total':variant(experiments__implied_total=True),
 'air_yards':variant(experiments__air_yards=True),
 'snap_input':variant(experiments__snap_input=True),
 'share_hl_2':variant(player_model__share_half_life_weeks=2.0),
 'share_hl_5':variant(player_model__share_half_life_weeks=5.0),
 'team_hl_3':variant(team_model__half_life_weeks=3.0),
 'team_hl_8':variant(team_model__half_life_weeks=8.0),
 'td_k_50':variant(player_model__td_blend_k=50),
 'td_k_400':variant(player_model__td_blend_k=400),
 'combo':variant(experiments__implied_total=True, player_model__share_half_life_weeks=5.0, team_model__half_life_weeks=3.0),
 'combo_hl8':variant(experiments__implied_total=True, player_model__share_half_life_weeks=8.0, team_model__half_life_weeks=3.0),
 'combo_air':variant(experiments__implied_total=True, experiments__air_yards=True, player_model__share_half_life_weeks=5.0, team_model__half_life_weeks=3.0),
 'combo_t2':variant(experiments__implied_total=True, player_model__share_half_life_weeks=5.0, team_model__half_life_weeks=2.0),
}
sel=sys.argv[1].split(',') if len(sys.argv)>1 else list(VARIANTS)
season=int(sys.argv[2]) if len(sys.argv)>2 else 2025
rows=[]
for name in sel:
  t=time.time(); e=Engine(d,VARIANTS[name],sc,positions=POS)
  res=B.run(e,[season]); ev=B.evaluate(res,POS); ev=ev[ev.subset=='relevant']
  for _,r in ev.iterrows(): rows.append({'variant':name,'pos':r.pos,'mae':r.mae_model,'r':r.r_model,'rank':r.rank_model})
  print(name, f'{time.time()-t:.0f}s', flush=True)
out=pd.DataFrame(rows)
piv=out.pivot(index='variant',columns='pos',values=['mae','rank']).round(3)
piv['mae_avg']=out.pivot(index='variant',columns='pos',values='mae').mean(axis=1).round(3)
piv['rank_avg']=out.pivot(index='variant',columns='pos',values='rank').mean(axis=1).round(3)
print(piv.loc[sel].to_string())
