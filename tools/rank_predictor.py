"""How well do POWER RANKS alone predict winners? Walk-forward, every regular-season game 2021 to now.

Usage: python tools/rank_predictor.py        (~3 min with 6 workers)

Each game uses both teams' Power-tab ranks as of the week before it (the site's own Net: model margin vs an average
team, units x the fitted points-formula weights, current starting QB). Reports how often the better-ranked team
won, by rank gap and by tier matchup, then a walk-forward win chance from the rank gap (+ home field), scored on
Brier against the model's and Vegas's chances on the same games (lower = better).
"""
import copy
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.report import fit_win_k, logistic  # noqa: E402
from nfledge.team_model import GameModel, TeamModel, game_lines, team_game_ledger, team_volume_features  # noqa: E402

pd.set_option("display.width", 200)


def season_ranks(base: dict, season: int) -> pd.DataFrame:
  cfg = copy.deepcopy(base)
  cfg["data"]["history_seasons"] = 8
  data = D.load_all(cfg)
  train = [s for s in data.seasons if s < season and s - 1 in data.seasons][-int(cfg["data"].get("train_seasons", 2)):]
  tm = TeamModel(data.pbp, cfg, data.qb_career)
  tm.tune_alphas([(s, w) for s in train for w in range(4, data.completed_weeks(s) + 1)])
  ledger = team_game_ledger(data.pbp, data.schedules)
  rows = GameModel(cfg).training_rows(tm, ledger, train)
  prior = [s for s in data.seasons if s < season and s - 1 in data.seasons]
  extra = [GameModel(cfg).training_rows(tm, ledger, [s]) for s in prior[-6:] if s not in train]
  gm = GameModel(cfg).fit(rows, pd.concat(extra + [rows]) if extra else None)
  pc = dict(zip(gm.points.cols, gm.points.coef[1:]))
  b, st_w = float(pc["off_epa_game"]), 2.0 * float(pc["st_net"])
  sched = data.schedules
  sched = sched[(sched.season == season) & (sched.game_type == "REG") & sched.home_score.notna()]
  out = []
  for wk in sorted(sched.week.unique()):
    if wk < 2:
      continue
    games = sched[sched.week == wk]
    r = tm.fit(season, int(wk))
    past = ledger[(ledger.season == season) & (ledger.week < wk) | (ledger.season < season)]
    starters = past.dropna(subset=["qb"]).sort_values(["season", "week"]).groupby("team").qb.last().to_dict()
    vol = r.plays_pg
    net = pd.Series({t: b * ((r.off.at[t, "pass"] + r.qb_term(starters.get(t)) - r.dfn.at[t, "pass"]) * vol["pass"]
                             + (r.off.at[t, "rush"] - r.dfn.at[t, "rush"]) * vol["rush"])
                     + st_w * (r.off.at[t, "st"] - r.dfn.at[t, "st"]) * vol["st"] for t in r.teams})
    rank = net.rank(ascending=False, method="min")
    vf = team_volume_features(ledger, season, int(wk), cfg)
    gl = game_lines(gm.predict(games, r, vf, use_vegas=False, starters=starters), games)
    gl = gl.merge(games[["game_id", "home_score", "away_score", "location"]], on="game_id")
    gl["home_rank"], gl["away_rank"] = gl.home_team.map(rank), gl.away_team.map(rank)
    gl["home_net"], gl["away_net"] = gl.home_team.map(net), gl.away_team.map(net)
    qbt = pd.Series({t: float(r.qb_term(starters.get(t))) for t in r.teams})  # each starter's own effect
    qrank = qbt.rank(ascending=False, method="min")
    gl["home_qbt"], gl["away_qbt"] = gl.home_team.map(qbt), gl.away_team.map(qbt)
    gl["home_qb_rank"], gl["away_qb_rank"] = gl.home_team.map(qrank), gl.away_team.map(qrank)
    gl["season"], gl["week"] = season, int(wk)
    out.append(gl)
  print(f"  {season} done", flush=True)
  return pd.concat(out, ignore_index=True)


def brier(p, y):
  return float(((p - y) ** 2).mean())


def fit_rank_home(tr: pd.DataFrame) -> tuple[float, float]:
  """P(home wins) = logistic(a + k x (away rank - home rank)): grid MLE (a = home field, k per rank place)."""
  best, ab = -1e18, (0.0, 0.0)
  gap, y = (tr.away_rank - tr.home_rank).to_numpy(float), tr.won.to_numpy(float)
  for a in np.linspace(-0.3, 0.6, 46):
    for k in np.linspace(0.0, 0.12, 121):
      p = logistic(a + k * gap).clip(1e-9, 1 - 1e-9)
      ll = float((y * np.log(p) + (1 - y) * np.log(1 - p)).sum())
      if ll > best:
        best, ab = ll, (a, k)
  return ab


if __name__ == "__main__":
  base = load_config()
  seasons = list(range(2021, 2027))
  with ProcessPoolExecutor(max_workers=6) as ex:
    d = pd.concat(list(ex.map(season_ranks, [base] * len(seasons), seasons)), ignore_index=True)
  d = d[d.home_score != d.away_score].copy()
  d["won"] = (d.home_score > d.away_score).astype(float)
  d["better_home"] = d.home_rank < d.away_rank
  d["better_won"] = np.where(d.better_home, d.won, 1 - d.won)
  d["gap"] = (d.home_rank - d.away_rank).abs()
  d["fav_rank"] = d[["home_rank", "away_rank"]].min(axis=1)
  d["dog_rank"] = d[["home_rank", "away_rank"]].max(axis=1)
  n = len(d)
  print(f"\n{n} games (weeks 2+, 2021-2026), ranks as of the week before each game\n")
  print("Pick rate, all games:")
  print(f"  better power rank wins   {d.better_won.mean():.1%}")
  print(f"  our model's favorite     {((d.model_margin > 0) == (d.won > 0)).mean():.1%}")
  v = d[d.spread_line.notna() & (d.spread_line != 0)]
  print(f"  Vegas favorite           {((v.spread_line > 0) == (v.won > 0)).mean():.1%}  (n={len(v)})")
  print(f"  home team                {d.won.mean():.1%}")
  early = d.week <= 6
  print(f"  better rank, weeks 2-6 / 7+: {d[early].better_won.mean():.1%} / {d[~early].better_won.mean():.1%}")

  print("\nBetter-ranked team's win rate by rank gap (90% interval):")
  bins = [(1, 3), (4, 7), (8, 12), (13, 19), (20, 31)]
  for lo, hi in bins:
    s = d[(d.gap >= lo) & (d.gap <= hi)]
    se = 1.645 * np.sqrt(.25 / max(len(s), 1))
    print(f"  gap {lo:2d}-{hi:2d}: {len(s):4d} games, better rank won {s.better_won.mean():.1%} +/- {se:.1%}")

  print("\nTier vs tier (row = better-ranked team's tier; % = row team won):")
  tiers = [(1, 4, "top 4"), (5, 8, "5-8"), (9, 16, "9-16"), (17, 24, "17-24"), (25, 32, "25-32")]
  tbl = {}
  for flo, fhi, fn in tiers:
    row = {}
    for dlo, dhi, dn in tiers:
      s = d[d.fav_rank.between(flo, fhi) & d.dog_rank.between(dlo, dhi)]
      row[dn] = f"{s.better_won.mean():.0%} ({len(s)})" if len(s) >= 10 else ("-" if len(s) == 0 else f"n={len(s)}")
    tbl[fn] = row
  print(pd.DataFrame(tbl).T.to_string())

  print("\nExamples the question asked about (better rank won, games):")
  for (a1, a2), (b1, b2), label in (((1, 3), (4, 7), "top 3 vs 4-7"), ((1, 5), (20, 32), "top 5 vs 20-32"),
                                    ((4, 7), (22, 28), "4-7 vs 22-28"), ((10, 14), (15, 19), "10-14 vs 15-19")):
    s = d[d.fav_rank.between(a1, a2) & d.dog_rank.between(b1, b2)]
    print(f"  {label:16s} {s.better_won.mean():.0%} of {len(s)}")

  # Walk-forward win chances on games with a Vegas line: rank gap + home field vs model vs Vegas.
  res = []
  for s in seasons[1:]:
    tr, te = d[d.season < s], d[(d.season == s) & d.spread_line.notna()].copy()
    a, k = fit_rank_home(tr)
    te["p_rank"] = logistic(a + k * (te.away_rank - te.home_rank))
    te["p_model"] = logistic(fit_win_k(tr.model_margin.to_numpy(float), tr.won.to_numpy()) * te.model_margin)
    tv = tr[tr.spread_line.notna()]
    te["p_vegas"] = logistic(fit_win_k(tv.spread_line.to_numpy(float), tv.won.to_numpy()) * te.spread_line)
    te["a"], te["k"] = a, k
    res.append(te)
  o = pd.concat(res)
  print(f"\nWin chances, walk-forward 2022-2026 ({len(o)} games with a line). Rank model: home field "
        f"{o.a.min():.2f}-{o.a.max():.2f}, {o.k.min():.3f}-{o.k.max():.3f} per rank place (logit)")
  for name, col in (("power-rank gap + home", "p_rank"), ("our model", "p_model"), ("Vegas", "p_vegas")):
    print(f"  {name:22s} Brier {brier(o[col], o.won):.4f}   right {((o[col] > .5) == (o.won > 0)).mean():.1%}")
  print(f"  {'home-team rate':22s} Brier {brier(d[d.season < 2022].won.mean(), o.won):.4f}")
  # Same ratings, different conversions to a win chance: is the gap the rank itself, or the missing home term?
  def fit_ak(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    best, ab = -1e18, (0.0, 0.0)
    for a in np.linspace(-0.3, 0.6, 46):
      for k in np.linspace(0.0, 0.3, 301):
        p = logistic(a + k * x).clip(1e-9, 1 - 1e-9)
        ll = float((y * np.log(p) + (1 - y) * np.log(1 - p)).sum())
        if ll > best:
          best, ab = ll, (a, k)
    return ab
  d["net_diff"] = d.home_net - d.away_net
  o["net_diff"] = o.home_net - o.away_net
  for s in seasons[1:]:
    tr = d[d.season < s]
    m = o.season == s
    for col, x in (("p_model_home", "model_margin"), ("p_net_home", "net_diff")):
      a_, k_ = fit_ak(tr[x].to_numpy(float), tr.won.to_numpy(float))
      o.loc[m, col] = logistic(a_ + k_ * o.loc[m, x])
  sw = o.season.astype(str) + "-" + o.week.astype(str)
  keys = sw.unique()
  rng = np.random.default_rng(0)
  idx = {k_: np.flatnonzero(sw.to_numpy() == k_) for k_ in keys}

  def ci(col):  # Brier(col) - Brier(rank), 95% bootstrap over season-weeks; negative = col better than rank
    e = (o[col] - o.won) ** 2 - (o.p_rank - o.won) ** 2
    bs = [e.to_numpy()[np.concatenate([idx[k_] for k_ in rng.choice(keys, len(keys))])].mean() for _ in range(2000)]
    return e.mean(), np.percentile(bs, 2.5), np.percentile(bs, 97.5)
  print("\nSame ratings, other conversions (Brier; diff vs rank gap + home with 95% CI, negative = better):")
  for name, col in (("model margin, no home term (site)", "p_model"), ("model margin + fitted home term", "p_model_home"),
                    ("net rating gap + home", "p_net_home"), ("Vegas", "p_vegas")):
    m_, lo, hi = ci(col)
    print(f"  {name:36s} {brier(o[col], o.won):.4f}   {m_:+.4f} [{lo:+.4f}, {hi:+.4f}]")
  a, k = fit_rank_home(d)
  print(f"\nFitted on every game: P(home wins) = logistic({a:.2f} + {k:.3f} x (away rank - home rank))")
  for g in (1, 4, 10, 20, 31):
    print(f"  {g:2d} places better: neutral field {logistic(k * g):.0%}; at home {logistic(a + k * g):.0%}; "
          f"on the road {logistic(-a + k * g):.0%}")
