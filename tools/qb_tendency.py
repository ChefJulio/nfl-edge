import nflreadpy as nfl, numpy as np, pandas as pd
yrs = list(range(2016, 2026))
p = nfl.load_pbp(yrs).select(["season", "season_type", "posteam", "passer_player_id", "receiver_player_id", "pass_attempt", "sack"]).to_pandas()
p = p[(p.season_type == "REG") & (p.pass_attempt == 1) & (p.sack != 1) & p.receiver_player_id.notna() & p.passer_player_id.notna()]
pos = nfl.load_players().to_pandas().set_index("gsis_id").position
p["rpos"] = p.receiver_player_id.map(pos).replace({"FB": "RB", "HB": "RB"})
rows = []
for (s, qb, tm), g in p.groupby(["season", "passer_player_id", "posteam"]):
  if len(g) < 200: continue
  sh = g.receiver_player_id.value_counts(normalize=True)
  rows.append({"season": s, "qb": qb, "team": tm, "n": len(g), "top1": sh.iloc[0], "top2": sh.iloc[:2].sum(), "hhi": (sh ** 2).sum(),
               "te": (g.rpos == "TE").mean(), "rb": (g.rpos == "RB").mean()})
x = pd.DataFrame(rows)
print(f"QB-team-seasons with 200+ targeted throws: {len(x)}\n")
nx = x.assign(season=x.season - 1)
m = x.merge(nx, on=["season", "qb"], suffixes=("", "_next"))
same, moved = m[m.team == m.team_next], m[m.team != m.team_next]
# team side: same team, different QB the next season
tx = x.merge(x.assign(season=x.season - 1), on=["season", "team"], suffixes=("", "_next"))
newqb = tx[tx.qb != tx.qb_next]
print(f"{'tendency':<26}{'same QB+team':>14}{'QB moved teams':>16}{'same team, new QB':>19}   (year-to-year correlation)")
for c, lab in (("top1", "top target's share"), ("top2", "top-2 targets' share"), ("hhi", "concentration (HHI)"), ("te", "TE share of targets"), ("rb", "RB share (dump-offs)")):
  print(f"{lab:<26}{same[c].corr(same[c + '_next']):>14.2f}{moved[c].corr(moved[c + '_next']):>16.2f}{newqb[c].corr(newqb[c + '_next']):>19.2f}")
print(f"\nn: same {len(same)}, QB moved {len(moved)}, team with new QB {len(newqb)}")
print("\n=== Aaron Rodgers ===")
names = nfl.load_players().to_pandas().set_index("gsis_id").display_name
x["pct_top1"] = x.groupby("season").top1.rank(pct=True)
x["pct_hhi"] = x.groupby("season").hhi.rank(pct=True)
r = x[x.qb == "00-0023459"].sort_values("season")
for t in r.itertuples():
  g = p[(p.season == t.season) & (p.passer_player_id == t.qb) & (p.posteam == t.team)]
  top = g.receiver_player_id.value_counts()
  print(f"{t.season} {t.team}: top target {names.get(top.index[0], top.index[0])} {t.top1:.0%} of his targets (league pctile {t.pct_top1:.0%}); concentration pctile {t.pct_hhi:.0%}; #2 {names.get(top.index[1], '')} {top.iloc[1] / len(g):.0%}")
print(f"\nleague median top-target share {x.top1.median():.0%}; Rodgers' seasons average {r.top1.mean():.0%} (pctile avg {r.pct_top1.mean():.0%})")
