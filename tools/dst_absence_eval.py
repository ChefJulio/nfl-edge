"""(AN) opponent pass-catcher absences in D/ST sacks and takeaways (pre-registered 2026-10-18, docs/INSIGHTS.md).

Usage: python tools/dst_absence_eval.py
The D/ST model (nfledge/defenses.py, walk-forward as tools/dst_eval.py) projects sacks, INTs and fumbles recovered
from 16-game rates; points allowed come from Vegas implied points (injuries priced in). Input per defense-game,
knowable before kickoff: the OPPONENT's share of targets over its last 3 games held by WR / TE / RB listed Out or
Doubtful on the final report. Variant: each of sack / int / fum_rec x exp(b x missing share), one b per stat fit by
Poisson maximum likelihood on seasons before the test season (2021 on). Test 2022-25, ESPN standard D/ST points.
GATE: games vs a team missing >= 15% of its target share: MAE lower, 95% CI over games excluding 0; all games not
worse (CI upper < +0.01). FAIL -> "unresolved" unless the CI rules out a 0.2-point gain per affected game.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.optimize import minimize_scalar  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.defenses import ESPN_STD, DefenseModel, actual_line, load_games, score  # noqa: E402
from nfledge.kickers import implied_points  # noqa: E402

STATS = ["sack", "int", "fum_rec"]
SEASONS = [2021, 2022, 2023, 2024, 2025]


def missing_shares(d) -> dict:
  """(season, week, team) -> share of the team's targets over its last 3 games held by players listed Out /
  Doubtful for that week (the {#skill-absence-margin} input)."""
  st = d.stats.copy()
  st["team"] = st.team.map(lambda t: D.RELOCATED.get(t, t))
  st = st[st.position.isin(["WR", "TE", "RB", "FB"])]
  st = st.assign(tg=pd.to_numeric(st.targets, errors="coerce").fillna(0))
  sch = d.schedules[d.schedules.game_type == "REG"]
  tw = {}
  for x in sch.itertuples():
    for t in (x.home_team, x.away_team):
      tw.setdefault((int(x.season), D.RELOCATED.get(t, t)), []).append(int(x.week))
  pg = st.groupby(["season", "team", "week", "player_id"]).tg.sum()
  tot = st.groupby(["season", "team", "week"]).tg.sum()
  inj = d.injuries.dropna(subset=["gsis_id"]).drop_duplicates(["season", "week", "gsis_id"], keep="last")
  inj = inj[inj.report_status.isin(["Out", "Doubtful"])]
  gone = {}
  for s, w, t, g in zip(inj.season.astype(int), inj.week.astype(int), inj.team, inj.gsis_id):
    gone.setdefault((s, w, D.RELOCATED.get(t, t)), set()).add(g)
  out = {}
  for (s, t), ws in tw.items():
    ws = sorted(ws)
    for w in ws:
      prev = [x for x in ws if x < w][-3:]
      g = gone.get((s, w, t))
      if not prev or not g:
        continue
      den = sum(float(tot.get((s, t, x), 0.0)) for x in prev)
      if not den:
        continue
      num = 0.0
      for x in prev:
        try:
          sub = pg.loc[(s, t, x)]
        except KeyError:
          continue
        num += float(sub[sub.index.isin(g)].sum())
      out[(s, w, t)] = num / den
  return out


def main():
  cfg = load_config()
  d = D.load_all(cfg)
  c = D.Cache(ROOT / cfg["data"]["cache_dir"])
  sched = c.get("schedules", "since1999", None, stale=False)
  G = load_games(c, list(range(2019, 2026)), sched)
  IMP = implied_points(sched)
  imp_ix = IMP.set_index(["season", "week", "team"]).implied
  miss = missing_shares(d)
  rows = []
  for s in SEASONS:
    for w in range(3, 19):
      te = G[(G.season == s) & (G.week == w)]
      if te.empty:
        continue
      tr = G[((G.season >= s - 2) & (G.season < s)) | ((G.season == s) & (G.week < w))]
      m = DefenseModel().fit(tr, IMP[IMP.season.between(s - 2, s)])
      prior = G[(G.season == s) & (G.week < w)]
      for x in te.itertuples():
        key = (s, w, x.opponent_team)
        if (prior.team == x.team).sum() < 2 or key not in imp_ix.index or pd.isna(x.pa):
          continue
        ln = m.line(x.team, x.opponent_team, float(imp_ix[key]), (s, w))
        act = actual_line(x)
        rows.append({"season": s, "week": w, "team": x.team, "opp": x.opponent_team, "line": ln,
                     "act_pts": score(act, ESPN_STD), "miss": miss.get((s, w, x.opponent_team), 0.0),
                     **{f"p_{k}": ln[k] for k in STATS}, **{f"a_{k}": act[k] for k in STATS}})
  R = pd.DataFrame(rows)
  print(f"[AN] {len(R)} defense-games 2021-25; opponent missing >= 15% of targets: {(R.miss >= 0.15).sum()}")

  def fit_b(tr, k):
    mu, y, x = tr[f"p_{k}"].to_numpy(), tr[f"a_{k}"].to_numpy(), tr.miss.to_numpy()
    nll = lambda b: float((mu * np.exp(b * x) - y * (np.log(np.maximum(mu, 1e-9)) + b * x)).sum())
    return minimize_scalar(nll, bounds=(-3, 3), method="bounded").x

  out = []
  for s in [2022, 2023, 2024, 2025]:
    tr, te = R[R.season < s], R[R.season == s].copy()
    bs = {k: fit_b(tr, k) for k in STATS}
    print(f"{s}: " + ", ".join(f"b_{k} {v:+.2f}" for k, v in bs.items()) + "  (x per 100% of share, fit on seasons before)")
    adj = []
    for x in te.itertuples():
      ln = dict(x.line)
      for k in STATS:
        ln[k] = ln[k] * np.exp(bs[k] * x.miss)
      adj.append(score(ln, ESPN_STD))
    te["base"] = [score(l, ESPN_STD) for l in te.line]
    te["new"] = adj
    out.append(te)
  T = pd.concat(out)
  T["e0"], T["e1"] = (T.base - T.act_pts).abs(), (T.new - T.act_pts).abs()

  def ci(df):
    dd = (df.e1 - df.e0).to_numpy()
    idx = np.random.default_rng(0).integers(0, len(dd), (2000, len(dd)))
    bt = dd[idx].mean(1)
    return dd.mean(), *np.percentile(bt, [2.5, 97.5])

  aff = T[T.miss >= 0.15]
  m1, lo1, hi1 = ci(aff)
  m2, lo2, hi2 = ci(T)
  print(f"[AN] affected games (n {len(aff)}): MAE {aff.e0.mean():.3f} -> {aff.e1.mean():.3f}, diff {m1:+.3f} [{lo1:+.3f}, {hi1:+.3f}]")
  print(f"[AN] all games (n {len(T)}): MAE {T.e0.mean():.3f} -> {T.e1.mean():.3f}, diff {m2:+.3f} [{lo2:+.3f}, {hi2:+.3f}]")
  print(f"[AN] affected: projected {aff.base.mean():.2f} -> {aff.new.mean():.2f}, actual {aff.act_pts.mean():.2f}")
  for k in STATS:
    print(f"[AN]   {k}: projected {aff[f'p_{k}'].mean():.2f}, actual {aff[f'a_{k}'].mean():.2f} (all games {T[f'p_{k}'].mean():.2f} vs {T[f'a_{k}'].mean():.2f})")
  ok = hi1 < 0 and hi2 < 0.01
  print("[AN] GATE:", "PASS" if ok else ("FAIL" if lo1 > -0.2 else "FAIL -> unresolved (CI does not rule out a 0.2-point gain)"))


if __name__ == "__main__":
  main()
