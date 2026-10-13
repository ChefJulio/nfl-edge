"""Opponent-adjusted team ratings (ridge EPA model), team volume, and game predictions.

Model per unit u in {pass, rush, st}:  play_epa = intercept_u + offense[posteam] + defense[defteam] + home_u * h
with h = +1 for the home offense, -1 away, 0 neutral site. Defense coefficients are "EPA allowed" (higher = worse
defense). Plays are weighted by recency within the season, plus a decaying prior-season weight.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import scipy.linalg as sla
import scipy.sparse as sp

UNITS = ("pass", "rush", "st")


# ----------------------------------------------------------------------------------------------------------------
# Play selection + weighting
# ----------------------------------------------------------------------------------------------------------------

def qb_experience(pbp: pd.DataFrame, career: pd.Series | None) -> pd.DataFrame:
  """Career dropbacks each QB had BEFORE each (season, week): pre-window career attempts + in-window dropbacks
  from earlier weeks. Feeds the inexperienced-QB term (backups/rookies are below average, but ridge alone
  would shrink an unknown QB to league average)."""
  db = pbp[pbp.is_dropback].assign(qb=pbp.passer_player_id.fillna(pbp.rusher_player_id)).dropna(subset=["qb"])
  g = db.groupby(["qb", "season", "week"]).size().rename("n").reset_index().sort_values(["qb", "season", "week"])
  g["prior"] = g.groupby("qb").n.cumsum() - g.n
  if career is not None:
    g["prior"] = g.prior + g.qb.map(career).fillna(0)
  return g


def prior_dropbacks(qbexp: pd.DataFrame, season: int, week: int) -> pd.Series:
  """Career dropbacks per QB entering (season, week)."""
  before = qbexp[(qbexp.season < season) | ((qbexp.season == season) & (qbexp.week < week))]
  last = before.groupby("qb").tail(1)
  return pd.Series((last.prior + last.n).to_numpy(), index=last.qb.to_numpy())


def unit_plays(pbp: pd.DataFrame, cfg: dict, qbexp: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
  tm = cfg["team_model"]
  live = pbp.epa.notna() & pbp.posteam.notna() & pbp.defteam.notna()
  not_garbage = pbp.wp.between(tm["wp_min"], tm["wp_max"])
  sel = {
    "pass": live & pbp.is_dropback & not_garbage,
    "rush": live & pbp.is_designed_rush & not_garbage,
    "st": live & pbp.is_st,
  }
  cols = ["season", "week", "game_id", "posteam", "defteam", "home", "div", "epa"]
  out = {u: pbp.loc[m, cols].reset_index(drop=True) for u, m in sel.items()}
  ps = pbp.loc[sel["pass"]]
  out["pass"]["qb"] = ps.passer_player_id.fillna(ps.rusher_player_id).to_numpy()
  if qbexp is not None:
    pri = qbexp.set_index(["qb", "season", "week"]).prior
    key = pd.MultiIndex.from_arrays([out["pass"].qb, out["pass"].season, out["pass"].week])
    cut = tm.get("qb_inexp_dropbacks", 150)
    out["pass"]["qb_inexp"] = (pri.reindex(key).fillna(0).to_numpy() < cut).astype(float)
  return out


def prior_season_weight(target_week: int, cfg: dict) -> float:
  tm = cfg["team_model"]
  decay = tm["prior_decay_week"]
  return float(tm["prior_weight"] * max(0.0, (decay - target_week) / max(decay - 1, 1)))


def asof_weights(season_col: pd.Series, week_col: pd.Series, season: int, target_week: int, cfg: dict,
                 half_life: float | None = None) -> np.ndarray:
  """Weights for rows usable when projecting (season, target_week): current-season weeks < target_week get
  exponential recency weights; prior-season rows get the decaying prior weight; everything else 0."""
  hl = half_life or cfg["team_model"]["half_life_weeks"]
  s = season_col.to_numpy()
  wk = week_col.to_numpy()
  last = target_week - 1
  cur = (s == season) & (wk < target_week)
  w = np.zeros(len(s))
  w[cur] = 0.5 ** ((last - wk[cur]) / hl)
  w[s == season - 1] = prior_season_weight(target_week, cfg) if target_week > 1 else 1.0
  return w


# ----------------------------------------------------------------------------------------------------------------
# Weighted ridge
# ----------------------------------------------------------------------------------------------------------------

class Design:
  """Sparse design matrix [1 | offense one-hot | defense one-hot | home | home x division game] for one unit.

  Home field is one league-wide term per unit: 20 seasons of results show team-specific home edges do not
  persist (corr -0.02 season to season) and travel distance / time zones have no measurable effect, but the
  home edge is ~0.8 pts smaller in division games (p = 0.03) - hence the optional division interaction."""

  def __init__(self, plays: pd.DataFrame, teams: list[str], division: bool = True, qbs: bool = False):
    """qbs=True (pass unit) appends a quarterback one-hot block and an inexperienced-QB indicator, so pass
    offense = team (line, receivers, scheme) + quarterback, each with its own ridge penalty."""
    self.teams = teams
    n = len(teams)
    idx = {t: i for i, t in enumerate(teams)}
    off = plays.posteam.map(idx).to_numpy()
    dfn = plays.defteam.map(idx).to_numpy()
    rows = np.arange(len(plays))
    h = plays.home.to_numpy(dtype=float)
    hd = h * plays["div"].to_numpy(dtype=float) if division else np.zeros(len(plays))
    data = np.concatenate([np.ones(len(plays)), np.ones(len(plays)), np.ones(len(plays)), h, hd])
    r = np.concatenate([rows, rows, rows, rows, rows])
    c = np.concatenate([np.zeros(len(plays), int), 1 + off, 1 + n + dfn, np.full(len(plays), 1 + 2 * n),
                        np.full(len(plays), 2 + 2 * n)])
    self.base_p = 2 * n + 3
    self.inexp_alpha = 1.0
    self.qbs = []
    if qbs and "qb" in plays:
      q = plays.qb.fillna("UNK")
      self.qbs = sorted(q.unique())
      qi = q.map({k: i for i, k in enumerate(self.qbs)}).to_numpy()
      inexp = plays["qb_inexp"].to_numpy(dtype=float) if "qb_inexp" in plays else np.zeros(len(plays))
      data = np.concatenate([data, np.ones(len(plays)), inexp])
      r = np.concatenate([r, rows, rows])
      c = np.concatenate([c, self.base_p + qi, np.full(len(plays), self.base_p + len(self.qbs))])
    self.p = self.base_p + (len(self.qbs) + 1 if self.qbs else 0)
    self.X = sp.csr_matrix((data, (r, c)), shape=(len(plays), self.p))
    self.y = plays.epa.to_numpy(dtype=float)

  def solve(self, w: np.ndarray, alpha: float, alpha_qb: float = 1e9) -> np.ndarray:
    return self.solve_normal(*self.normal(w), alpha, alpha_qb)

  def normal(self, w: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Weighted normal equations X'WX, X'Wy. They don't depend on the penalties, so CV builds them once per fold
    and reuses them across the whole alpha grid."""
    keep = w > 0
    X = self.X[keep]
    Xw = X.multiply(w[keep][:, None]).tocsr()
    return (X.T @ Xw).toarray(), Xw.T @ self.y[keep]

  def solve_normal(self, A: np.ndarray, b: np.ndarray, alpha: float, alpha_qb: float = 1e9) -> np.ndarray:
    pen = np.full(self.p, alpha)
    pen[0] = 0.0
    if self.qbs:
      pen[self.base_p:self.base_p + len(self.qbs)] = alpha_qb
      pen[-1] = self.inexp_alpha  # inexperienced-QB indicator: lightly penalized league-level effect
    M = A + np.diag(pen) + 1e-9 * np.eye(self.p)
    # Ridge normal equations are symmetric positive-definite: Cholesky is the right solver and ~170x faster
    # than np.linalg.solve here (85 ms vs 0.5 ms for the pass unit; the general LU path thrashes OpenBLAS).
    try:
      return sla.cho_solve(sla.cho_factor(M, check_finite=False), b, check_finite=False)
    except np.linalg.LinAlgError:
      return np.linalg.solve(M, b)


@dataclass
class Ratings:
  season: int
  target_week: int
  teams: list[str]
  intercept: dict
  home: dict
  off: pd.DataFrame  # index team, columns units
  dfn: pd.DataFrame
  se_off: pd.DataFrame | None = None
  se_def: pd.DataFrame | None = None
  raw_off: pd.DataFrame | None = None  # unadjusted current-season EPA/play (for schedule luck)
  raw_def: pd.DataFrame | None = None
  plays_pg: dict = field(default_factory=dict)  # league plays per team-game per unit
  home_div: dict = field(default_factory=dict)  # change in home edge for division games
  qb: pd.Series | None = None  # quarterback effects on pass EPA/play (shrunk); team 'pass' offense excludes them
  qb_inexp: float = 0.0  # extra effect for QBs with little career experience
  qb_prior: pd.Series | None = None  # career dropbacks entering this week
  inexp_cut: float = 150.0

  def qb_term(self, qb) -> float:
    """Pass EPA/play contribution of a specific quarterback (0 when QB effects are off or QB unknown)."""
    if self.qb is None or qb is None or (isinstance(qb, float) and np.isnan(qb)):
      return 0.0
    prior = self.qb_prior.get(qb, 0.0) if self.qb_prior is not None else 0.0
    return float(self.qb.get(qb, 0.0)) + self.qb_inexp * float(prior < self.inexp_cut)

  def expected_epa(self, off_team: str, def_team: str, unit: str, home: int, div: int = 0, qb=None) -> float:
    q = self.qb_term(qb) if unit == "pass" else 0.0
    return (self.intercept[unit] + self.off.at[off_team, unit] + self.dfn.at[def_team, unit] + q
            + (self.home[unit] + self.home_div.get(unit, 0.0) * div) * home)


def _unpack(beta: np.ndarray, teams: list[str]):
  n = len(teams)
  return beta[0], beta[1:1 + n], beta[1 + n:1 + 2 * n], beta[1 + 2 * n], beta[2 + 2 * n]


class TeamModel:
  """Holds unit play tables + designs for all loaded seasons; fits ratings as-of any (season, week)."""

  def __init__(self, pbp: pd.DataFrame, cfg: dict, qb_career: pd.Series | None = None):
    self.cfg = cfg
    self.use_qb = cfg["team_model"].get("qb_effects", True)
    self.qbexp = qb_experience(pbp, qb_career)
    self.plays = unit_plays(pbp, cfg, self.qbexp)
    self.teams = sorted(set(pbp.posteam.dropna()) | set(pbp.defteam.dropna()))
    div = cfg["team_model"].get("division_hfa", True)
    self.designs = {u: Design(p, self.teams, division=div, qbs=(u == "pass" and self.use_qb))
                    for u, p in self.plays.items()}
    for d in self.designs.values():
      d.inexp_alpha = float(cfg["team_model"].get("qb_inexp_alpha", 1.0))
    self.alphas = {u: 100.0 for u in UNITS}
    self.alpha_qb = 1e9
    self.cv_loss = {}
    self._cache: dict = {}

  # -- fitting ---------------------------------------------------------------------------------------------------
  def weights(self, unit: str, season: int, target_week: int) -> np.ndarray:
    p = self.plays[unit]
    w = asof_weights(p.season, p.week, season, target_week, self.cfg)
    ex = self.cfg.get("experiments", {})
    if float(ex.get("elite_boost", 0) or 0):
      w = self._elite_weights(unit, w, ex)
    return w

  def _elite_weights(self, unit: str, w: np.ndarray, ex: dict) -> np.ndarray:
    """EXPERIMENT (experiments.elite_*; off unless set): count plays against strong opposing UNITS more. A pass
    play facing a top pass defense weighs more for that offense, and one facing a top pass offense weighs more
    for that defense (the same play carries both). Opposing strength comes from an ordinary fit on the same as-of
    weights, so nothing looks ahead. Modes: "top" = units ranked in the top elite_top get 1 + elite_boost each;
    "linear" = 1 + elite_boost x (opponent percentile - 0.5), summed over both sides (average weight stays ~1)."""
    beta = self.designs[unit].solve(w, self.alphas[unit], self.alpha_qb)
    _, o, d, _, _ = _unpack(beta, self.teams)
    p = self.plays[unit]
    active = sorted(set(p.posteam[w > 0]) | set(p.defteam[w > 0]))
    o = pd.Series(o, index=self.teams).reindex(active)
    d = pd.Series(d, index=self.teams).reindex(active)
    off_rank = o.rank(ascending=False)  # 1 = best offense
    def_rank = d.rank(ascending=True)  # 1 = best defense (least EPA allowed)
    opp_def = p.defteam.map(def_rank).to_numpy(float)  # the defense this offense faced
    opp_off = p.posteam.map(off_rank).to_numpy(float)  # the offense this defense faced
    b = float(ex["elite_boost"])
    if ex.get("elite_mode", "top") == "linear":
      n = len(active)
      pct = lambda r: 1 - (r - 1) / max(n - 1, 1)  # 1 = best, 0 = worst
      mult = 1 + b * ((pct(opp_def) - 0.5) + (pct(opp_off) - 0.5))
    else:
      k = float(ex.get("elite_top", 8))
      mult = 1 + b * ((opp_def <= k).astype(float) + (opp_off <= k).astype(float))
    return w * np.nan_to_num(np.clip(mult, 0.05, None), nan=1.0)

  def fit(self, season: int, target_week: int, bootstrap: int = 0, alphas: dict | None = None) -> Ratings:
    key = (season, target_week, bootstrap)
    if key in self._cache and alphas is None:
      return self._cache[key]
    alphas = alphas or self.alphas
    icpt, home, off, dfn, se_off, se_def, hdiv = {}, {}, {}, {}, {}, {}, {}
    raw_off, raw_def, plays_pg = {}, {}, {}
    qb, qb_inexp = None, 0.0
    for u in UNITS:
      w = self.weights(u, season, target_week)
      d = self.designs[u]
      beta = d.solve(w, alphas[u], self.alpha_qb)
      icpt[u], off[u], dfn[u], home[u], hdiv[u] = _unpack(beta, self.teams)
      if d.qbs:
        qb = pd.Series(beta[d.base_p:d.base_p + len(d.qbs)], index=d.qbs)
        qb_inexp = float(beta[-1])
      p = self.plays[u]
      cur = (p.season == season) & (p.week < target_week)
      if cur.any():
        raw_off[u] = p[cur].groupby("posteam").epa.mean()
        raw_def[u] = p[cur].groupby("defteam").epa.mean()
        plays_pg[u] = cur.sum() / (p[cur].groupby(["game_id", "posteam"]).ngroups or 1)
      if bootstrap:
        se_off[u], se_def[u] = self._bootstrap(u, w, alphas[u], bootstrap)
    frame = lambda d: pd.DataFrame(d, index=self.teams)
    r = Ratings(season, target_week, self.teams, icpt, home, frame(off), frame(dfn),
                frame(se_off) if bootstrap else None, frame(se_def) if bootstrap else None,
                pd.DataFrame(raw_off).reindex(self.teams) if raw_off else None,
                pd.DataFrame(raw_def).reindex(self.teams) if raw_def else None, plays_pg, hdiv,
                qb, qb_inexp, prior_dropbacks(self.qbexp, season, target_week),
                float(self.cfg["team_model"].get("qb_inexp_dropbacks", 150)))
    if alphas is self.alphas:
      self._cache[key] = r
    return r

  def _bootstrap(self, unit: str, w: np.ndarray, alpha: float, n: int):
    """Cluster bootstrap over games: resample games with replacement, refit, take coefficient SDs."""
    rng = np.random.default_rng(self.cfg["team_model"]["seed"])
    games = self.plays[unit].game_id.to_numpy()
    active = w > 0
    codes, uniq = pd.factorize(games[active])
    offs, defs = [], []
    for _ in range(n):
      mult = np.bincount(rng.integers(0, len(uniq), len(uniq)), minlength=len(uniq))
      wb = w.copy()
      wb[active] = w[active] * mult[codes]
      _, o, d, _, _ = _unpack(self.designs[unit].solve(wb, alpha, self.alpha_qb), self.teams)
      offs.append(o)
      dfn_ = d
      defs.append(dfn_)
    return np.std(offs, axis=0), np.std(defs, axis=0)

  # -- alpha tuning ----------------------------------------------------------------------------------------------
  def tune_alphas(self, folds: list[tuple[int, int]]) -> dict:
    """Time-split CV: for each (season, week) fold, fit on everything before that week, predict that week's
    team-game offensive EPA/play, score weighted MSE. Never random CV."""
    grid = self.cfg["team_model"]["alpha_grid"]
    best = {}
    for u in UNITS:
      p = self.plays[u]
      d = self.designs[u]
      losses = np.zeros(len(grid))
      for season, week in folds:
        test = ((p.season == season) & (p.week == week)).to_numpy()
        if not test.any():
          continue
        w = self.weights(u, season, week)
        tg = p[test].groupby(["game_id", "posteam"]).agg(epa=("epa", "mean"), n=("epa", "size"))
        Xt = d.X[test]
        A, b = d.normal(w)
        for i, a in enumerate(grid):
          pred = Xt @ d.solve_normal(A, b, a)
          pg = pd.Series(pred).groupby([p.game_id[test].to_numpy(), p.posteam[test].to_numpy()]).mean()
          pg.index.names = ["game_id", "posteam"]
          err = tg.epa - pg.reindex(tg.index)
          losses[i] += float(np.sum(tg.n * err ** 2))
      best[u] = float(grid[int(np.argmin(losses))])
      self.cv_loss[u] = float(np.min(losses))
    self.alphas = best
    if self.use_qb:
      self._tune_qb_alpha(folds)
    self._cache.clear()
    return best

  def _tune_qb_alpha(self, folds):
    """Pass unit: tune team and QB penalties jointly (how much of a passing offense is the quarterback vs the
    rest of the roster is exactly what the data has to decide). 1e9 removes QB effects, so CV can reject them.
    Walk-forward on 2024-26: CV loss 2974.5 (team 300, QB 300) vs 3017.2 without QB terms."""
    p, d = self.plays["pass"], self.designs["pass"]
    qgrid = self.cfg["team_model"].get("qb_alpha_grid", [30, 100, 300, 1000, 1e9])
    tgrid = [a for a in self.cfg["team_model"]["alpha_grid"] if 30 <= a <= 1000]
    grid = [(a, b) for a in tgrid for b in qgrid]
    losses = np.zeros(len(grid))
    for season, week in folds:
      test = ((p.season == season) & (p.week == week)).to_numpy()
      if not test.any():
        continue
      w = self.weights("pass", season, week)
      tg = p[test].groupby(["game_id", "posteam"]).agg(epa=("epa", "mean"), n=("epa", "size"))
      Xt = d.X[test]
      keys = [p.game_id[test].to_numpy(), p.posteam[test].to_numpy()]
      A, rhs = d.normal(w)
      for i, (a, b) in enumerate(grid):
        pred = Xt @ d.solve_normal(A, rhs, a, b)
        pg = pd.Series(pred).groupby(keys).mean()
        pg.index.names = ["game_id", "posteam"]
        losses[i] += float(np.sum(tg.n * (tg.epa - pg.reindex(tg.index)) ** 2))
    a, b = grid[int(np.argmin(losses))]
    self.alphas["pass"], self.alpha_qb = float(a), float(b)
    self.cv_loss["pass"] = float(np.min(losses))
    self.qb_cv = dict(zip(grid, losses))


# ----------------------------------------------------------------------------------------------------------------
# Team-game ledger + volume features
# ----------------------------------------------------------------------------------------------------------------

def team_game_ledger(pbp: pd.DataFrame, schedules: pd.DataFrame) -> pd.DataFrame:
  off = pbp[pbp.posteam.notna() & (pbp.qb_kneel == 0) & (pbp.qb_spike == 0) & (pbp.two_point_attempt == 0)]
  g = off.groupby(["season", "week", "game_id", "posteam"])
  led = pd.DataFrame({
    "opp": g.defteam.first(),
    "home": g.home.first(),
    "div": g["div"].first(),
    "dropbacks": g.is_dropback.sum(),
    "rushes": g.is_designed_rush.sum(),
    "scrambles": g.qb_scramble.sum(),
    "wind": g.game_wind.first(),
    "indoor": g.indoor.first(),
  }).reset_index().rename(columns={"posteam": "team"})
  # Neutral-situation pace: seconds between consecutive snaps by the same offense in the same quarter, in close
  # games before the 4th quarter (excludes hurry-up / clock-killing script). Gaps over 45s (timeouts, reviews,
  # injuries) are dropped.
  sc = pbp[pbp.posteam.notna() & (pbp.play_type.isin(["pass", "run"]))].sort_values(["game_id", "play_id"])
  nxt = sc.groupby("game_id")
  gap = sc.game_seconds_remaining - nxt.game_seconds_remaining.shift(-1)
  same = (nxt.posteam.shift(-1) == sc.posteam) & (nxt.qtr.shift(-1) == sc.qtr)
  neutral_pace = same & gap.between(5, 45) & sc.wp.between(0.2, 0.8) & (sc.qtr <= 3)
  spp = gap[neutral_pace].groupby([sc.game_id[neutral_pace], sc.posteam[neutral_pace]]).mean()
  spp = spp.rename("sec_pp").reset_index().rename(columns={"posteam": "team"})
  led = led.merge(spp, on=["game_id", "team"], how="left")
  dbp = off[off.is_dropback].assign(qb=off.passer_player_id.fillna(off.rusher_player_id)).dropna(subset=["qb"])
  main_qb = (dbp.groupby(["game_id", "posteam", "qb"]).size().rename("n").reset_index()
             .sort_values("n").drop_duplicates(["game_id", "posteam"], keep="last")
             .rename(columns={"posteam": "team"})[["game_id", "team", "qb"]])
  led = led.merge(main_qb, on=["game_id", "team"], how="left")
  neutral = off[off.wp.between(0.2, 0.8) & (off.qtr <= 3) & off.pass_oe.notna()]
  led = led.merge(neutral.groupby(["game_id", "posteam"]).pass_oe.mean().rename("proe").reset_index()
                  .rename(columns={"posteam": "team"}), on=["game_id", "team"], how="left")
  led["proe"] = led.proe.fillna(0.0) / 100.0
  led["plays"] = led.dropbacks + led.rushes
  led["pass_rate"] = led.dropbacks / led.plays.clip(lower=1)
  sch = schedules[["game_id", "home_team", "home_score", "away_score", "spread_line", "total_line"]]
  led = led.merge(sch, on="game_id", how="left")
  is_home = led.team == led.home_team
  led["points"] = np.where(is_home, led.home_score, led.away_score)
  led["opp_points"] = np.where(is_home, led.away_score, led.home_score)
  led["spread_team"] = np.where(is_home, led.spread_line, -led.spread_line)  # + = this team favored
  led = led.drop(columns=["home_team", "home_score", "away_score", "spread_line"])
  allowed = led[["game_id", "team", "plays"]].rename(columns={"team": "opp", "plays": "opp_plays"})
  return led.merge(allowed, on=["game_id", "opp"], how="left")


def team_volume_features(ledger: pd.DataFrame, season: int, target_week: int, cfg: dict) -> pd.DataFrame:
  """As-of team pace / pass-rate features from games before target_week (plus decaying prior season)."""
  w = asof_weights(ledger.season, ledger.week, season, target_week, cfg)
  d = ledger.assign(w=w)
  d = d[d.w > 0]
  out = {}
  for col, name in (("plays", "pace"), ("proe", "proe"), ("pass_rate", "pass_rate"), ("scrambles", "scr_pg")):
    out[name] = (d[col] * d.w).groupby(d.team).sum() / d.w.groupby(d.team).sum()
  ok = d.sec_pp.notna() if "sec_pp" in d else pd.Series(False, index=d.index)
  out["sec_pp"] = ((d.sec_pp.where(ok, 0) * d.w * ok).groupby(d.team).sum() / (d.w * ok).groupby(d.team).sum()
                   if ok.any() else pd.Series(dtype=float))
  out["pace_allowed"] = (d.opp_plays * d.w).groupby(d.opp).sum() / d.w.groupby(d.opp).sum()
  f = pd.DataFrame(out)
  league = {k: float(np.average(d[c], weights=d.w)) for k, c in (("pace", "plays"), ("pass_rate", "pass_rate"))}
  league_spp = float(d.loc[ok, "sec_pp"].mean()) if ok.any() else 28.0
  return f.fillna({"pace": league["pace"], "pace_allowed": league["pace"], "proe": 0.0,
                   "pass_rate": league["pass_rate"], "sec_pp": league_spp})


@dataclass
class Linear:
  cols: list[str]
  coef: np.ndarray
  name: str = ""

  @classmethod
  def fit(cls, df: pd.DataFrame, y: str, cols: list[str], weight: str | None = None, name: str = ""):
    d = df.dropna(subset=cols + [y])
    X = np.column_stack([np.ones(len(d))] + [d[c].to_numpy(float) for c in cols])
    w = np.sqrt(d[weight].to_numpy(float)) if weight else np.ones(len(d))
    coef, *_ = np.linalg.lstsq(X * w[:, None], d[y].to_numpy(float) * w, rcond=None)
    return cls(cols, coef, name)

  def predict(self, df: pd.DataFrame) -> np.ndarray:
    X = np.column_stack([np.ones(len(df))] + [df[c].to_numpy(float) for c in self.cols])
    return X @ self.coef

  def describe(self) -> str:
    return ", ".join([f"b0={self.coef[0]:+.3f}"] + [f"{c}={b:+.3f}" for c, b in zip(self.cols, self.coef[1:])])


def matchup_frame(games: pd.DataFrame, starters: dict | None = None) -> pd.DataFrame:
  """Expand schedule games to one row per team (offense perspective). starters: team -> projected QB."""
  rows = []
  for _, g in games.iterrows():
    neutral = g.get("location") == "Neutral"
    for team, opp, h in ((g.home_team, g.away_team, 1), (g.away_team, g.home_team, -1)):
      spread = g.spread_line if h == 1 else -g.spread_line if pd.notna(g.spread_line) else np.nan
      rows.append({"game_id": g.game_id, "season": g.season, "week": g.week, "team": team, "opp": opp,
                   "home": 0 if neutral else h, "div": int(g.get("div_game") == 1),
                   "qb": (starters or {}).get(team), "spread_team": spread, "total_line": g.total_line,
                   "gameday": g.gameday})
  return pd.DataFrame(rows)


class GameModel:
  """Volume regressions + points calibration, trained on as-of features from historical team-games."""

  def __init__(self, cfg: dict):
    self.cfg = cfg

  def training_rows(self, tm: TeamModel, ledger: pd.DataFrame, seasons: list[int]) -> pd.DataFrame:
    """ledger must include the season before each training season (prior-season features)."""
    rows = []
    for s in seasons:
      for wk in sorted(ledger[ledger.season == s].week.unique()):
        r = tm.fit(s, wk)
        vf = team_volume_features(ledger, s, wk, self.cfg)
        g = ledger[(ledger.season == s) & (ledger.week == wk)].copy()
        rows.append(self._features(g, r, vf))
    return pd.concat(rows, ignore_index=True)

  def _features(self, g: pd.DataFrame, r: Ratings, vf: pd.DataFrame) -> pd.DataFrame:
    g = g.copy()
    g["pace"] = g.team.map(vf.pace)
    g["sec_pp"] = g.team.map(vf.sec_pp)
    g["opp_sec_pp"] = g.opp.map(vf.sec_pp)
    g["opp_pace_allowed"] = g.opp.map(vf.pace_allowed)
    g["proe_team"] = g.team.map(vf.proe)
    g["pass_rate_team"] = g.team.map(vf.pass_rate)
    for u in UNITS:
      qbs = g.qb.tolist() if "qb" in g else [None] * len(g)
      qb_of = dict(zip(zip(g.game_id, g.team), qbs))
      oq = [qb_of.get((gid, o)) for gid, o in zip(g.game_id, g.opp)]
      g[f"epa_{u}"] = [r.expected_epa(t, o, u, h, dv, q)
                       for t, o, h, dv, q in zip(g.team, g.opp, g.home, g["div"], qbs)]
      g[f"opp_epa_{u}"] = [r.expected_epa(o, t, u, -h, dv, q)
                           for t, o, h, dv, q in zip(g.team, g.opp, g.home, g["div"], oq)]
    # Net special-teams edge per game: our ST plays vs theirs, scaled to league ST plays per team-game.
    n_st = r.plays_pg.get("st", 11.0)
    g["st_net"] = n_st * (g.epa_st - g.opp_epa_st)
    return g

  def fit(self, train: pd.DataFrame, points_rows: pd.DataFrame | None = None):
    """Volume models fit on `train`; the points formula fits on `points_rows` when given (a longer window of
    seasons: two seasons pin down the special-teams weight poorly; it drifted 0.9-3.3 between windows)."""
    vf_mode = self.cfg["team_model"].get("volume_features", "base")
    more = {"base": [], "pace": ["sec_pp", "opp_sec_pp"],
            "extended": ["sec_pp", "opp_sec_pp", "epa_pass", "epa_rush", "opp_epa_pass", "opp_epa_rush"]}[vf_mode]
    self.plays_vegas = Linear.fit(train, "plays", ["pace", "opp_pace_allowed", "total_line", "spread_team"] + more,
                                  name="plays (Vegas)")
    self.plays_model = Linear.fit(train, "plays", ["pace", "opp_pace_allowed"] + more, name="plays (model)")
    self.pass_rate = Linear.fit(train, "pass_rate", ["proe_team", "pass_rate_team", "spread_team"],
                                weight="plays", name="pass rate")
    t = (points_rows if points_rows is not None else train).copy()
    t["dropbacks_hat"] = self.plays_model.predict(t) * self.pass_rate.predict(t.assign(spread_team=0.0))
    t["rushes_hat"] = self.plays_model.predict(t) - t.dropbacks_hat
    t["off_epa_game"] = t.dropbacks_hat * t.epa_pass + t.rushes_hat * t.epa_rush
    # Points per unit of special-teams EPA edge: "fitted" (least squares, the default) or a fixed number, so the
    # game-level backtest (tools/game_eval.py) can test the fitted weight against alternatives.
    st_w = self.cfg["team_model"].get("points_st_weight", "fitted")
    if st_w == "fitted":
      self.points = Linear.fit(t, "points", ["off_epa_game", "st_net"], name="points")
    else:
      m = Linear.fit(t.assign(points=t.points - float(st_w) * t.st_net), "points", ["off_epa_game"], name="points")
      self.points = Linear(["off_epa_game", "st_net"], np.append(m.coef, float(st_w)), "points")
    return self

  def predict(self, games: pd.DataFrame, r: Ratings, vf: pd.DataFrame, use_vegas: bool,
              starters: dict | None = None) -> pd.DataFrame:
    """Team-perspective predictions: plays, dropbacks, rushes, expected points. Model-only mode replaces the
    Vegas spread with the model's own margin (one fixed-point iteration) and drops the Vegas total."""
    g = self._features(matchup_frame(games, starters), r, vf)
    if use_vegas and g.spread_team.notna().all() and g.total_line.notna().all():
      g["plays_hat"] = self.plays_vegas.predict(g)
      g["pass_rate_hat"] = self.pass_rate.predict(g)
    else:
      g["plays_hat"] = self.plays_model.predict(g)
      g["spread_team"] = 0.0
      for _ in range(2):
        pts = self._points(g)
        game_total = pts.groupby(g.game_id).transform("sum")
        g["spread_team"] = 2 * pts - game_total  # our points minus opponent points
      g["pass_rate_hat"] = self.pass_rate.predict(g)
    g["dropbacks_hat"] = g.plays_hat * g.pass_rate_hat
    g["rushes_hat"] = g.plays_hat - g.dropbacks_hat
    g["points_hat"] = self._points(g)
    return g

  def _points(self, g: pd.DataFrame) -> pd.Series:
    dbh = g.plays_hat * self.pass_rate.predict(g)
    off = dbh * g.epa_pass + (g.plays_hat - dbh) * g.epa_rush
    return pd.Series(self.points.predict(g.assign(off_epa_game=off)), index=g.index)


def game_lines(team_preds: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
  """Collapse team-perspective model predictions into home margin / total, next to Vegas."""
  p = team_preds.set_index(["game_id", "team"]).points_hat
  out = games[["game_id", "week", "gameday", "away_team", "home_team", "spread_line", "total_line",
               "location"]].copy()
  out["home_pts"] = [p.get((g, h), np.nan) for g, h in zip(out.game_id, out.home_team)]
  out["away_pts"] = [p.get((g, a), np.nan) for g, a in zip(out.game_id, out.away_team)]
  out["model_margin"] = out.home_pts - out.away_pts
  out["model_total"] = out.home_pts + out.away_pts
  return out
