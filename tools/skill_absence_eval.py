"""Missing pass catchers and backs in the team rating (pre-registered 2026-10-16, docs/INSIGHTS.md (P)).

Usage: python tools/skill_absence_eval.py [--games=PATH]   (PATH: tools/game_eval.py --save output, 2021-25)
Per team-game, knowable before kickoff: the share of the team's targets (and carries) over its last 3 games held by
WR / TE / RB listed Out or Doubtful on the final report. Margin adjustment b_pass x (home - away missing target
share) + b_rush x (same for carries), b fit by least squares on the game model's margin misses in earlier seasons.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

GAMES = Path(r"C:\Users\hunte\AppData\Local\Temp\claude\C--Users-hunte\e847d357-6c86-407f-8c67-67c02542deb8\scratchpad\games.parquet")


def main():
  from nfledge import data as D
  from nfledge.config import load_config
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  g = pd.read_parquet(opt.get("games", GAMES))
  g = g[g.variant == "fitted"].copy()
  cfg = load_config()
  d = D.load_all(cfg)
  st = d.stats.copy()
  st["team"] = st.team.map(lambda t: D.RELOCATED.get(t, t))
  st = st[st.position.isin(["WR", "TE", "RB", "FB"])]
  st = st.assign(tg=pd.to_numeric(st.targets, errors="coerce").fillna(0), ca=pd.to_numeric(st.carries, errors="coerce").fillna(0))
  sch = d.schedules[d.schedules.game_type == "REG"]
  tw = {}
  for x in sch.itertuples():
    for t in (x.home_team, x.away_team):
      tw.setdefault((int(x.season), D.RELOCATED.get(t, t)), []).append(int(x.week))
  tw = {k: sorted(v) for k, v in tw.items()}
  pg = st.groupby(["season", "team", "week", "player_id"])[["tg", "ca"]].sum()
  team_tot = st.groupby(["season", "team", "week"])[["tg", "ca"]].sum()
  inj = d.injuries.dropna(subset=["gsis_id"]).drop_duplicates(["season", "week", "gsis_id"], keep="last")
  out = inj[inj.report_status.isin(["Out", "Doubtful"])]
  out_set = {}
  for s, w, t, gid in zip(out.season.astype(int), out.week.astype(int), out.team, out.gsis_id):
    out_set.setdefault((s, w, D.RELOCATED.get(t, t)), set()).add(gid)

  def missing(season, week, team):
    prev = [x for x in tw.get((season, team), []) if x < week][-3:]
    gone = out_set.get((season, week, team), set())
    if not prev or not gone:
      return 0.0, 0.0
    try:
      tot = team_tot.loc[[(season, team, x) for x in prev if (season, team, x) in team_tot.index]].sum()
      sub = pg.loc[(season, team)]
    except KeyError:
      return 0.0, 0.0
    sub = sub[sub.index.get_level_values(0).isin(prev)]
    mine = sub[sub.index.get_level_values(1).isin(gone)].sum()
    return (float(mine.tg / tot.tg) if tot.tg else 0.0), (float(mine.ca / tot.ca) if tot.ca else 0.0)
  feats = []
  for x in g.itertuples():
    h, a = D.RELOCATED.get(x.home_team, x.home_team), D.RELOCATED.get(x.away_team, x.away_team)
    mh, ma = missing(int(x.season), int(x.week), h), missing(int(x.season), int(x.week), a)
    feats.append((mh[0] - ma[0], mh[1] - ma[1], max(mh[0], ma[0], mh[1], ma[1])))
  g[["d_tgt", "d_car", "worst"]] = np.array(feats)
  g["resid"] = g.actual_margin - g.model_margin
  rows = []
  for s in range(2022, 2026):
    tr, te = g[g.season < s], g[g.season == s].copy()
    X = tr[["d_tgt", "d_car"]].to_numpy()
    b = np.linalg.lstsq(X, tr.resid.to_numpy(), rcond=None)[0]
    te["adj"] = te.model_margin + te[["d_tgt", "d_car"]].to_numpy() @ b
    te["b_tgt"], te["b_car"] = b
    rows.append(te)
    print(f"{s}: b_pass {b[0]:+.1f}, b_rush {b[1]:+.1f} points per 100% of share (fit on seasons before)")
  r = pd.concat(rows)
  r["e0"], r["e1"] = (r.model_margin - r.actual_margin).abs(), (r.adj - r.actual_margin).abs()
  rng = np.random.default_rng(0)

  def ci(v):
    v = np.asarray(v)
    b_ = rng.choice(v, (4000, len(v))).mean(1)
    return v.mean(), np.percentile(b_, 2.5), np.percentile(b_, 97.5)
  big = r[r.worst >= 0.15]
  m, lo, hi = ci(big.e1 - big.e0)
  ma_, la, ha = ci(r.e1 - r.e0)
  print(f"\ngames with a team missing >= 15% of its targets or carries: {len(big)} of {len(r)}")
  print(f"  margin MAE {big.e0.mean():.3f} -> {big.e1.mean():.3f}  diff {m:+.3f} [{lo:+.3f}, {hi:+.3f}]  {'ok' if hi < 0 else 'FAIL'}")
  print(f"all games: {r.e0.mean():.3f} -> {r.e1.mean():.3f}  diff {ma_:+.3f} [{la:+.3f}, {ha:+.3f}]  {'ok' if ha < 0.02 else 'FAIL'}")
  print("GATE:", "PASS" if hi < 0 and ha < 0.02 else "FAIL")


if __name__ == "__main__":
  main()
