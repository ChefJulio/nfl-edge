"""Throw darts: does any simple, pre-game-knowable signal predict winners, alone or on top of what we have?

Usage: python tools/darts.py [--refresh]      (first run ~3 min to rebuild walk-forward ranks, then seconds)

Every regular-season game 2021 to now (weeks 2+), each dart oriented home minus away (or a home-side flag), all
from data before kickoff. Win chance = logistic regression, fit walk-forward (each season 2022-26 on the seasons
before it), scored by Brier on the games with a Vegas line. Three tests per dart:
  alone     home field + the dart
  + rank    our best in-house chance (power-rank gap + home field) + the dart: does it add anything?
  + Vegas   the Vegas spread + the dart: does it know something the market doesn't?
Diffs vs the base get a 95% bootstrap CI over season-weeks and a count of test seasons it improved. With ~25 darts,
one or two will clear a 95% CI by luck, so trust only darts that also improve in most seasons.
"""
import copy
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import rank_predictor as rp  # noqa: E402
from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402

pd.set_option("display.width", 220)
CACHE = ROOT / "cache" / "darts_base.parquet"
# Home time zone, hours from UTC in standard time (Arizona keeps Mountain standard time all year).
TZ = {**{t: -5 for t in ("ATL", "BAL", "BUF", "CAR", "CIN", "CLE", "DET", "IND", "JAX", "MIA", "NE", "NYG", "NYJ",
                          "PHI", "PIT", "TB", "WAS")},
      **{t: -6 for t in ("CHI", "DAL", "GB", "HOU", "KC", "MIN", "NO", "TEN")},
      **{t: -7 for t in ("ARI", "DEN")}, **{t: -8 for t in ("LA", "LAC", "LV", "SEA", "SF")}}


def logit_fit(X: np.ndarray, y: np.ndarray, ridge: float = 1e-3) -> np.ndarray:
  """Logistic regression by Newton's method (tiny ridge for stability)."""
  w = np.zeros(X.shape[1])
  for _ in range(50):
    p = 1 / (1 + np.exp(-X @ w))
    g = X.T @ (y - p) - ridge * w
    H = (X * (p * (1 - p))[:, None]).T @ X + ridge * np.eye(X.shape[1])
    step = np.linalg.solve(H, g)
    w += step
    if np.abs(step).max() < 1e-8:
      break
  return w


def team_history(sched: pd.DataFrame, pbp: pd.DataFrame) -> pd.DataFrame:
  """One row per team-game with that team's season-to-date numbers BEFORE the game."""
  s = sched[sched.home_score.notna()].copy()
  cols = ["game_id", "season", "week", "game_type"]
  h = s[cols].assign(team=s.home_team, pf=s.home_score, pa=s.away_score, coach=s.home_coach)
  a = s[cols].assign(team=s.away_team, pf=s.away_score, pa=s.home_score, coach=s.away_coach)
  t = pd.concat([h, a], ignore_index=True)
  t["win"] = (t.pf > t.pa) + 0.5 * (t.pf == t.pa)
  t["margin"] = t.pf - t.pa
  t["close_net"] = np.where(t.margin.abs() <= 8, np.sign(t.margin), 0)  # one-score games: +1 win, -1 loss
  give = (pbp.interception.fillna(0) + pbp.fumble_lost.fillna(0))
  gv = give.groupby([pbp.game_id, pbp.posteam]).sum()
  tk = give.groupby([pbp.game_id, pbp.defteam]).sum()
  t["to_margin"] = [tk.get((g, tm), np.nan) - gv.get((g, tm), np.nan) for g, tm in zip(t.game_id, t.team)]
  t = t.sort_values(["season", "team", "week"])
  reg = t.game_type == "REG"
  g = t[reg].groupby(["season", "team"])
  t.loc[reg, "gp"] = g.cumcount()
  for c in ("win", "pf", "pa", "close_net", "to_margin"):
    t.loc[reg, f"cum_{c}"] = g[c].transform(lambda x: x.shift(1).fillna(0).cumsum())
  t.loc[reg, "last_win"] = g.win.shift(1)
  # streak before the game: +n after n straight wins, -n after n straight losses
  streaks = []
  for _, grp in t[reg].groupby(["season", "team"]):
    run, out = 0, []
    for w in grp.win:
      out.append(run)
      run = (run + 1 if run >= 0 else 1) if w == 1 else ((run - 1 if run <= 0 else -1) if w == 0 else 0)
    streaks += list(zip(grp.index, out))
  t.loc[[i for i, _ in streaks], "streak"] = [v for _, v in streaks]
  final = t[reg].groupby(["season", "team"]).win.mean()
  t["last_season_wp"] = [final.get((s_ - 1, tm), np.nan) for s_, tm in zip(t.season, t.team)]
  coach_prev = t[reg].groupby(["season", "team"]).coach.last()
  t["new_coach"] = [float(coach_prev.get((s_ - 1, tm), c) != c) for s_, tm, c in zip(t.season, t.team, t.coach)]
  return t.set_index(["game_id", "team"])


def elo(sched: pd.DataFrame) -> dict:
  """Pre-game Elo per (game_id, team): the FiveThirtyEight NFL recipe (K 20, home 48, margin multiplier, revert 1/3
  to the mean each season). Its constants are theirs, not fitted here: a classic baseline, used as one dart."""
  s = sched[sched.home_score.notna()].sort_values(["season", "gameday", "gametime"])
  r, season, out = {}, None, {}
  for g in s.itertuples():
    if g.season != season:
      r = {t: 1505 + (v - 1505) * 2 / 3 for t, v in r.items()}
      season = g.season
    rh, ra = r.get(g.home_team, 1505), r.get(g.away_team, 1505)
    out[(g.game_id, g.home_team)], out[(g.game_id, g.away_team)] = rh, ra
    hfa = 0 if g.location == "Neutral" else 48
    p = 1 / (1 + 10 ** (-(rh + hfa - ra) / 400))
    mov = g.home_score - g.away_score
    res = 1.0 if mov > 0 else 0.0 if mov < 0 else 0.5
    win_diff = (rh + hfa - ra) if mov > 0 else (ra - rh - hfa)
    mult = np.log(abs(mov) + 1) * 2.2 / (win_diff * 0.001 + 2.2) if mov else 1.0
    r[g.home_team], r[g.away_team] = rh + 20 * mult * (res - p), ra - 20 * mult * (res - p)
  return out


def features(d: pd.DataFrame, data) -> pd.DataFrame:
  sched = data.schedules.set_index("game_id")
  th = team_history(data.schedules, data.pbp)
  el = elo(data.schedules)
  home_roof = data.schedules[data.schedules.location != "Neutral"].groupby("home_team").roof.agg(
    lambda x: x.mode().iloc[0] if len(x.mode()) else "outdoors")
  home_surface = data.schedules[data.schedules.location != "Neutral"].groupby("home_team").surface.agg(
    lambda x: x.mode().iloc[0] if len(x.mode()) else "")
  # referee's home-team win rate over his earlier games (shrunk toward the league home rate with 50 games of prior)
  sc = data.schedules[data.schedules.home_score.notna()].sort_values(["season", "week"])
  sc = sc.assign(hw=(sc.home_score > sc.away_score).astype(float))
  league = sc.hw.mean()
  sc["ref_n"] = sc.groupby("referee").cumcount()
  sc["ref_hw"] = sc.groupby("referee").hw.transform(lambda x: x.shift(1).fillna(0).cumsum())
  ref_rate = ((sc.ref_hw + 50 * league) / (sc.ref_n + 50)).set_axis(sc.game_id)
  # Referee x team bias: how the team did against the spread in this referee's EARLIER games (actual margin minus
  # the line, from that team's side), shrunk toward 0 with 10 games of prior. Pairs are rare (a few games each).
  sl = sc[sc.spread_line.notna()].sort_values(["gameday", "gametime"])
  resid = sl.home_score - sl.away_score - sl.spread_line
  rt = pd.concat([pd.DataFrame({"game_id": sl.game_id, "ref": sl.referee, "team": sl.home_team, "res": resid}),
                  pd.DataFrame({"game_id": sl.game_id, "ref": sl.referee, "team": sl.away_team, "res": -resid})])
  rt = rt.set_index(sl.index.append(sl.index)).sort_index(kind="stable")
  grp = rt.groupby(["ref", "team"]).res
  rt["bias"] = grp.transform(lambda x: x.shift(1).fillna(0).cumsum()) / (grp.cumcount() + 10)
  ref_team = rt.set_index(["game_id", "team"]).bias

  def side(col, g, team):
    return th.at[(g, team), col] if (g, team) in th.index else np.nan

  rows = []
  for g in d.itertuples():
    s = sched.loc[g.game_id]
    hm, aw = g.home_team, g.away_team
    f = {}
    gp_h, gp_a = side("gp", g.game_id, hm), side("gp", g.game_id, aw)

    def per_game(col):
      vh, va = side(f"cum_{col}", g.game_id, hm), side(f"cum_{col}", g.game_id, aw)
      return (vh / gp_h if gp_h else 0.0) - (va / gp_a if gp_a else 0.0)
    f["record (win %)"] = per_game("win")
    f["point diff per game"] = per_game("pf") - per_game("pa")

    def pyth(team, gp):
      pf, pa = side("cum_pf", g.game_id, team), side("cum_pa", g.game_id, team)
      return pf ** 2.37 / (pf ** 2.37 + pa ** 2.37) if gp and pf + pa > 0 else 0.5
    f["Pythagorean win %"] = pyth(hm, gp_h) - pyth(aw, gp_a)
    f["close-game luck (1-score W-L)"] = side("cum_close_net", g.game_id, hm) - side("cum_close_net", g.game_id, aw)
    f["turnover margin per game"] = per_game("to_margin")
    f["won last game"] = np.nan_to_num(side("last_win", g.game_id, hm) - side("last_win", g.game_id, aw))
    f["win/loss streak"] = np.nan_to_num(side("streak", g.game_id, hm) - side("streak", g.game_id, aw))
    lsw = side("last_season_wp", g.game_id, hm) - side("last_season_wp", g.game_id, aw)
    f["last season win %"] = np.nan_to_num(lsw)
    f["last season win %, weeks 2-5"] = np.nan_to_num(lsw) * (g.week <= 5)
    f["first-year head coach"] = side("new_coach", g.game_id, hm) - side("new_coach", g.game_id, aw)
    f["Elo (538 recipe)"] = el.get((g.game_id, hm), 1505) - el.get((g.game_id, aw), 1505)
    f["top-5 QB"] = float(g.home_qb_rank <= 5) - float(g.away_qb_rank <= 5)
    f["bottom-5 QB"] = float(g.home_qb_rank >= 28) - float(g.away_qb_rank >= 28)
    f["QB rating (extra weight)"] = g.home_qbt - g.away_qbt
    f["rest days"] = np.clip(np.nan_to_num(s.home_rest - s.away_rest), -7, 7)
    f["off a bye"] = float(s.home_rest >= 13) - float(s.away_rest >= 13)
    f["Thursday game"] = float(s.weekday == "Thursday")
    f["prime time (7pm ET+)"] = float(str(s.gametime) >= "19:00")
    f["division game"] = float(s.div_game == 1)
    f["division game x rank gap"] = float(s.div_game == 1) * (g.away_rank - g.home_rank)
    tz_h, tz_a = TZ.get(hm, -5), TZ.get(aw, -5)
    f["time zones traveled east"] = 0.0 if s.location == "Neutral" else float(tz_h - tz_a)
    f["West team, 1pm ET game in the East"] = float(tz_a <= -7 and tz_h == -5 and str(s.gametime) < "14:00"
                                                   and s.location != "Neutral")
    cold = s.roof == "outdoors" and pd.notna(s.temp) and s.temp <= 40
    f["dome team in the cold"] = float(cold) * (float(home_roof.get(aw) in ("dome", "closed"))
                                                - float(home_roof.get(hm) in ("dome", "closed")))
    f["visitor's home surface differs"] = float(s.location != "Neutral" and home_surface.get(aw) != s.surface)
    f["referee's home win rate"] = float(ref_rate.get(g.game_id, league)) - league
    f["referee x team bias (vs spread)"] = (float(ref_team.get((g.game_id, hm), 0.0))
                                           - float(ref_team.get((g.game_id, aw), 0.0)))
    f["our model margin"] = g.model_margin
    f["net rating gap"] = g.home_net - g.away_net
    rows.append(f)
  return pd.DataFrame(rows, index=d.index).fillna(0.0)


def run_test(d: pd.DataFrame, base_cols: list, dart: str | None, seasons: list) -> pd.Series:
  """Walk-forward chances on the test games (Vegas line present) for base (+ dart)."""
  p = pd.Series(np.nan, index=d.index)
  cols = base_cols + ([dart] if dart else [])
  for s in seasons:
    tr, te = d[d.season < s], d[(d.season == s) & d.spread_line.notna()]
    tr = tr[tr[cols].notna().all(axis=1)]
    w = logit_fit(tr[cols].to_numpy(float), tr.won.to_numpy(float))
    p.loc[te.index] = 1 / (1 + np.exp(-te[cols].to_numpy(float) @ w))
  return p


if __name__ == "__main__":
  base = load_config()
  seasons = list(range(2021, 2027))
  if CACHE.exists() and "--refresh" not in sys.argv:
    d = pd.read_parquet(CACHE)
  else:
    with ProcessPoolExecutor(max_workers=6) as ex:
      d = pd.concat(list(ex.map(rp.season_ranks, [base] * len(seasons), seasons)), ignore_index=True)
    d.to_parquet(CACHE)
  d = d.rename(columns={"location_x": "location"}).drop(columns=["location_y"], errors="ignore")
  d = d[d.home_score != d.away_score].reset_index(drop=True)
  d["won"] = (d.home_score > d.away_score).astype(float)
  cfg = copy.deepcopy(base)
  cfg["data"]["history_seasons"] = 8
  data = D.load_all(cfg)
  F = features(d, data)
  darts = list(F.columns)
  d = pd.concat([d, F], axis=1)
  d["home"] = (d.location != "Neutral").astype(float)
  d["rank_gap"] = d.away_rank - d.home_rank
  d["vegas"] = d.spread_line
  test = list(range(2022, 2027))
  te = d[d.season.isin(test) & d.spread_line.notna()]
  sw = (te.season.astype(str) + "-" + te.week.astype(str)).to_numpy()
  keys = np.unique(sw)
  idx = [np.flatnonzero(sw == k) for k in keys]
  rng = np.random.default_rng(0)
  boot = [np.concatenate([idx[i] for i in rng.integers(0, len(keys), len(keys))]) for _ in range(1000)]
  y = te.won.to_numpy()

  def score(p_base, p_new):
    e = (p_new.loc[te.index].to_numpy() - y) ** 2 - (p_base.loc[te.index].to_numpy() - y) ** 2
    bs = [e[b].mean() for b in boot]
    seas = sum(e[te.season.to_numpy() == s].mean() < 0 for s in test)
    return e.mean(), np.percentile(bs, 2.5), np.percentile(bs, 97.5), seas

  bases = {"alone": ["home"], "+ rank": ["home", "rank_gap"], "+ Vegas": ["vegas"]}
  base_p = {k: run_test(d, v, None, test) for k, v in bases.items()}
  for k, p in base_p.items():
    b = ((p.loc[te.index] - y) ** 2).mean()
    print(f"base {k:7s} ({' + '.join(bases[k])}): Brier {b:.4f}")
  rows = []
  for dart in darts:
    r = {"dart": dart}
    p_alone = run_test(d, bases["alone"], dart, test)
    r["alone Brier"] = ((p_alone.loc[te.index] - y) ** 2).mean()
    r["alone right"] = ((p_alone.loc[te.index] > .5) == (y > .5)).mean()
    for k in ("+ rank", "+ Vegas"):
      m, lo, hi, seas = score(base_p[k], run_test(d, bases[k], dart, test))
      r[f"{k} diff"], r[f"{k} CI"], r[f"{k} seasons"] = m, f"[{lo:+.4f}, {hi:+.4f}]", f"{seas}/5"
      r[f"{k} sig"] = "HELPS" if hi < 0 else ("hurts" if lo > 0 else "")
    rows.append(r)
  out = pd.DataFrame(rows).sort_values("+ rank diff")
  print(f"\n{len(te)} test games 2022-2026. Brier diff vs base: negative = the dart helps. "
        f"Home field alone: {((base_p['alone'].loc[te.index] - y) ** 2).mean():.4f}\n")
  print(out.to_string(index=False, float_format=lambda x: f"{x:+.4f}" if abs(x) < 0.1 else f"{x:.4f}"))
