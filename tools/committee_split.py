import nflreadpy as nfl, numpy as np, pandas as pd
s = nfl.load_player_stats(list(range(2016, 2026))).to_pandas()
s = s[(s.season_type == "REG") & (s.position == "RB")][["season", "week", "team", "player_id", "carries"]]
sch = nfl.load_schedules(list(range(2016, 2026))).to_pandas(); sch = sch[sch.game_type == "REG"]
tw = pd.concat([sch[["season", "week", "home_team"]].rename(columns={"home_team": "team"}), sch[["season", "week", "away_team"]].rename(columns={"away_team": "team"})])
rows = []
for (season, team), g in s[s.season <= int(__import__("os").environ.get("LAST", "2025"))].groupby(["season", "team"]):
  weeks = sorted(tw[(tw.season == season) & (tw.team == team)].week)
  pv = g.pivot_table(index="week", columns="player_id", values="carries", aggfunc="sum").reindex(weeks).fillna(0)
  tot = pv.sum(axis=1)
  for i in range(3, len(weeks)):
    w, prev = weeks[i], weeks[i - 3:i]
    ptot = tot.loc[prev].sum()
    if ptot < 30 or tot.loc[w] < 10: continue
    usual = pv.loc[prev].sum() / ptot
    gone = [p for p in usual.index if usual[p] >= 0.3 and pv.at[w, p] == 0]
    if len(gone) != 1: continue
    gsh = usual[gone[0]]
    now = pv.loc[w] / tot.loc[w]
    est = usual.drop(gone)
    rot = est[est >= 0.15].index            # backs already in the rotation
    dep = [p for p in pv.columns if p not in rot and p not in gone]   # depth / new / call-ups
    kind = "bellcow out (60%+)" if gsh >= 0.6 else "committee back out (30-60%)"
    nrot = len(rot)
    rows.append({"kind": kind, "nrot": min(nrot, 2), "gone": gsh,
                 "rot_before": est[rot].sum(), "rot_after": now[rot].sum(),
                 "dep_before": est.reindex(dep).fillna(0).sum(), "dep_after": now.reindex(dep).fillna(0).sum()})
x = pd.DataFrame(rows)
print(f"games where one RB with 30%+ of carries sat (2016-25, n {len(x)}):\n")
for (k, n), g in x.groupby(["kind", "nrot"]):
    gain_r, gain_d = (g.rot_after - g.rot_before).mean(), (g.dep_after - g.dep_before).mean()
    print(f"{k:<28} backs left in rotation: {n}  n {len(g):>3} | vacated {g.gone.mean():.2f} -> rotation +{gain_r:.2f} ({gain_r / g.gone.mean():.0%}), next man up / depth +{gain_d:.2f} ({gain_d / g.gone.mean():.0%})")
