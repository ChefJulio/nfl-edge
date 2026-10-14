"""Orchestration: train meta-models on prior seasons, then project any (season, week)."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

import copy

from . import injuries as inj
from .personnel import Personnel
from .data import Data, depth_for_week, team_name_fix
from .player_model import PlayerModel, actual_points
from .team_model import GameModel, Linear, TeamModel, team_game_ledger, team_volume_features

POSITIONS = ["QB", "RB", "WR", "TE"]
QUANTS = (0.10, 0.25, 0.50, 0.75, 0.90)
QCOLS = ("p10", "p25", "p50", "p75", "p90")


def _log(msg):
  print(f"[engine] {msg}", flush=True)


class Engine:
  def __init__(self, data: Data, cfg: dict, scoring, positions=POSITIONS):
    if cfg.get("experiments", {}).get("snap_map") == "rosters" and "gsis_id_roster" in data.snaps:
      import dataclasses  # A/B only: the pre-2026-10-14 roster-only snap id map
      data = dataclasses.replace(data, snaps=data.snaps.assign(gsis_id=data.snaps.gsis_id_roster))
    self.data, self.cfg, self.scoring, self.positions = data, cfg, scoring, list(positions)
    self.tm = TeamModel(data.pbp, cfg, data.qb_career)
    self.team_ledger = team_game_ledger(data.pbp, data.schedules)
    self.pm = PlayerModel(data, self.tm, self.team_ledger, cfg, scoring)
    self.actual = actual_points(data.stats, scoring)
    self.trained_for = None
    self.blend, self.ecr_map = {}, {}

  # -- training --------------------------------------------------------------------------------------------------
  def train(self, test_season: int, use_injuries: bool = True):
    """Fit everything learned from history using only seasons before test_season."""
    if self.trained_for == (test_season, use_injuries):
      return self
    t0 = time.time()
    seasons = [s for s in self.data.seasons if s < test_season and s - 1 in self.data.seasons]
    seasons = seasons[-int(self.cfg["data"].get("train_seasons", 2)):]  # same window as the live site
    folds = [(s, w) for s in seasons for w in range(4, self.data.completed_weeks(s) + 1)]
    self.tm.tune_alphas(folds)
    self.pm.prepare(seasons)
    self.pm.fit_priors(seasons)
    self.gm = GameModel(self.cfg)
    rows = self.gm.training_rows(self.tm, self.team_ledger, seasons)
    # Points formula: optionally a longer window of prior seasons (team_model.points_seasons) than the 2-season
    # training window; volume models keep the training window.
    n_pts = int(self.cfg["team_model"].get("points_seasons", len(seasons)))
    longer = [s for s in self.data.seasons if s < test_season and s - 1 in self.data.seasons][-n_pts:]
    extra = [s for s in longer if s not in seasons]
    pts_rows = pd.concat([self.gm.training_rows(self.tm, self.team_ledger, extra), rows]) if extra else None
    self.gm.fit(rows, pts_rows)
    train = self.pm.training_rows(seasons, self.positions)
    self.pm.fit_meta(train)
    self._fit_share_totals(seasons)
    self.injury_model = inj.InjuryModel(self.data, self.pm, self.cfg).fit(seasons) if use_injuries else None
    self.personnel = None
    if use_injuries and self.cfg["team_model"].get("cb_adjust", True):
      self.personnel = Personnel(self.data, self.cfg).fit(seasons, self.tm, self.team_ledger)
    self.week_adj = {}
    self._fit_blend_and_uncertainty(seasons)
    self.trained_for = (test_season, use_injuries)
    _log(f"trained for {test_season} on {seasons} in {time.time() - t0:.0f}s; alphas {self.tm.alphas}")
    return self

  def _fit_blend_and_uncertainty(self, seasons):
    """From projections on the train seasons: (1) expert-consensus blend per position, (2) residual SD model
    per position (sd^2 = a + b * projection)."""
    self.ecr_map, self.blend, self.sd_model, self.calib = {}, {}, {}, {}
    rows = []
    for s in seasons:
      for w in range(2, self.data.completed_weeks(s) + 1):
        p = self.project_week(s, w, use_injuries=False, quiet=True, blend=False)
        rows.append(self.attach_actuals(p, s, w))
    d = pd.concat(rows)
    d = d[d.played]
    # Optional final calibration per position (experiments.player_calibration = "linear"): actual ~ a + b x
    # projection on the training seasons. Backtest showed projections slightly too extreme at both ends (20+ point
    # projections ~1 pt high, 8-12 ~0.3 low); a fitted slope below 1 pulls them in. Applied before the expert blend.
    if self.cfg.get("experiments", {}).get("player_calibration", "none") == "linear":
      for pos, g in d.groupby("pos"):
        if len(g) >= 200:
          self.calib[pos] = Linear.fit(g, "actual", ["proj"], name=f"calib/{pos}")
      d = self._calibrate(d)
    has = d.ecr.notna()
    blend_pos = set(self.cfg.get("experiments", {}).get("ecr_blend_positions", ["RB", "WR", "TE"]))
    for pos, g in d[has].groupby("pos"):
      if len(g) < 200:
        continue
      # Rank -> points mapping for every position (also the backtest's expert benchmark) ...
      self.ecr_map[pos] = Linear.fit(g.assign(log_ecr=np.log(g.ecr)), "actual", ["log_ecr"], name=f"ecr->{pos}")
      g = g.assign(ecr_pts=self.ecr_map[pos].predict(g.assign(log_ecr=np.log(g.ecr))))
      # ... but blend only where the backtest showed it helps.
      if pos in blend_pos:
        self.blend[pos] = Linear.fit(g, "actual", ["proj", "ecr_pts"], name=f"blend/{pos}")
    d = self.apply_blend(d)
    self._fit_quantiles(d)
    for pos, g in d.groupby("pos"):
      X = np.column_stack([np.ones(len(g)), g.proj.clip(lower=0)])
      coef, *_ = np.linalg.lstsq(X, (g.actual - g.proj) ** 2, rcond=None)
      self.sd_model[pos] = (max(coef[0], 1.0), max(coef[1], 0.0))

  def _fit_share_totals(self, seasons):
    """Typical team totals of the shares the model predicts player by player: targets to RB/WR/TE per team
    dropback, designed carries per team rush. Measured on the training seasons (used by _normalize_shares)."""
    L = self.pm.ledger
    L = L[L.season.isin(seasons) & L.pos.isin(["RB", "WR", "TE", "QB"])]
    g = L.groupby(["game_id", "team"])
    tg = L[L.pos.isin(["RB", "WR", "TE"])].groupby(["game_id", "team"]).tgt.sum() / g.team_db.first()
    ca = g.carries.sum() / g.team_rush.first()
    self.share_totals = {"tgt": float(tg.replace([np.inf, -np.inf], np.nan).median()),
                         "carries": float(ca.replace([np.inf, -np.inf], np.nan).median())}

  def _normalize_shares(self, p: pd.DataFrame, wind) -> pd.DataFrame:
    """Shares are predicted player by player, so a team's projected targets or carries can add up to far more or
    less than a real game holds (projected team target-share totals vary 1.5x as much as actual ones, and players
    on over-subscribed teams come in over-projected). Each team's totals among players expected to play are pulled
    toward the measured typical total: share x (1 + a x (typical / projected total - 1)), a =
    experiments.share_normalize (0 = off, 1 = full constraint), chosen by backtest."""
    exp = self.cfg.get("experiments", {})
    a_all = float(exp.get("share_normalize", 0.0))
    strength = {"tgt": float(exp.get("share_normalize_tgt", a_all)),
                "carries": float(exp.get("share_normalize_carries", a_all))}
    tot = getattr(self, "share_totals", None)
    if max(strength.values()) <= 0 or not tot or p.empty:
      return p
    p = p.copy()
    plays = ~p.get("sits", pd.Series(False, index=p.index)).astype(bool)
    for vol, team_col, poss, key in (("tgt", "team_db", ["RB", "WR", "TE"], "tgt"),
                                     ("carries", "team_rush", ["QB", "RB", "WR", "TE"], "carries")):
      a = strength[key]
      if a <= 0:
        continue
      m = plays & p.pos.isin(poss)
      share = (p[vol] / p[team_col].replace(0, np.nan)).where(m, 0.0).fillna(0.0)
      team_sum = share.groupby(p.team).transform("sum")
      factor = 1 + a * (tot[key] / team_sum.replace(0, np.nan) - 1)
      factor = factor.where(m, 1.0).fillna(1.0).clip(0.6, 1.6)
      p[vol] = p[vol] * factor
      if vol == "carries":
        p["rush"] = p.rush + p.carries * (1 - 1 / factor)  # rush = carries + scrambles; scale the carry part
    return self.pm.stats_from_volume(p, wind)

  # -- projection ------------------------------------------------------------------------------------------------
  def _fit_quantiles(self, d: pd.DataFrame):
    """Empirical outcome ranges: per position, bin train-season projections and take quantiles of what actually
    happened, stored as offsets from the projection (so ranges are skewed like real fantasy outcomes)."""
    self.q_model = {}
    for pos, g in d[d.proj > 0.5].groupby("pos"):
      edges = np.unique(np.quantile(g.proj, np.linspace(0, 1, 13)))
      idx = np.digitize(g.proj, edges[1:-1])
      centers, offs = [], []
      for b in np.unique(idx):
        gb = g[idx == b]
        if len(gb) >= 30:
          centers.append(gb.proj.mean())
          offs.append(np.quantile(gb.actual, QUANTS) - gb.proj.mean())
      if len(centers) >= 3:
        self.q_model[pos] = (np.array(centers), np.array(offs))

  def attach_ecr(self, p: pd.DataFrame, season: int, week: int) -> pd.DataFrame:
    """Expert consensus rank for the week, only if scraped before the player's kickoff (no leakage)."""
    p = p.drop(columns=["ecr", "ecr_flex", "ecr_pts"], errors="ignore")
    e = self.data.ecr
    if e is None:
      return p.assign(ecr=np.nan, ecr_flex=np.nan, ecr_pts=np.nan)
    if "ecr_flex" not in e:  # cached before the flex rank existed
      e = e.assign(ecr_flex=np.nan)
    e = e[(e.season == season) & (e.week == week)][["gsis_id", "ecr", "ecr_flex", "scrape_date"]]
    kick = self.games(season, week)[["game_id", "gameday"]]
    p = p.merge(e, on="gsis_id", how="left").merge(kick, on="game_id", how="left")
    late = pd.to_datetime(p.scrape_date) >= pd.to_datetime(p.gameday)
    p.loc[late, ["ecr", "ecr_flex"]] = np.nan
    return p.drop(columns=["scrape_date", "gameday"]).assign(ecr_pts=np.nan)

  def _calibrate(self, p: pd.DataFrame) -> pd.DataFrame:
    p = p.copy()
    for pos, m in getattr(self, "calib", {}).items():
      sel = p.pos == pos
      if sel.any():
        p.loc[sel, "proj"] = np.clip(m.predict(p[sel]), 0, None)
    return p

  def apply_blend(self, p: pd.DataFrame) -> pd.DataFrame:
    p = self._calibrate(p)
    p["proj_model"] = p.proj
    for pos, m in self.ecr_map.items():
      sel = (p.pos == pos) & p.ecr.notna()
      if sel.any():
        p.loc[sel, "ecr_pts"] = m.predict(p[sel].assign(log_ecr=np.log(p.loc[sel, "ecr"])))
        if pos in self.blend:
          p.loc[sel, "proj"] = np.clip(self.blend[pos].predict(p[sel]), 0, None)
    return p

  def games(self, season: int, week: int) -> pd.DataFrame:
    s = self.data.schedules
    return s[(s.season == season) & (s.week == week) & (s.game_type == "REG")].copy()

  def candidates(self, season: int, week: int) -> pd.DataFrame:
    r = self.data.rosters
    r = r[(r.season == season) & r.gsis_id.notna() & (r.week <= week)].copy()
    # Each team's own latest roster: a league-wide "latest week" drops teams on bye or still to play that week.
    latest = r.groupby("team").week.transform("max")
    # ACT + INA = 53-man roster (INA is last game's inactive list; availability models decide this week).
    r = r[(r.week == latest) & r.status.isin(["ACT", "INA"])].copy()
    r["pos"] = r.position.replace({"FB": "RB", "HB": "RB"})
    r = r[r.pos.isin(self.positions)]
    r["team"] = team_name_fix(r.team)
    g = self.games(season, week)
    playing = set(g.home_team) | set(g.away_team)
    # A player traded while a team was on bye can sit on two teams' latest rosters: keep his most recent one.
    c = (r[r.team.isin(playing)].sort_values("week", ascending=False)[["gsis_id", "team", "pos", "full_name"]]
         .drop_duplicates("gsis_id"))
    dc = depth_for_week(self.data, season, week)
    dc["team"] = team_name_fix(dc.team)
    # One depth slot per player on his current team (charts can list a player twice: two slots, or a stale team).
    dc = dc[["gsis_id", "team", "rank"]].sort_values("rank").drop_duplicates(["gsis_id", "team"])
    c = c.merge(dc.rename(columns={"rank": "depth_rank"}), on=["gsis_id", "team"], how="left")
    return c.reset_index(drop=True)

  def project_week(self, season: int, week: int, use_injuries: bool = True, use_vegas: bool = True,
                   wind: pd.Series | None = None, quiet: bool = False, ratings=None,
                   blend: bool = True, avail_override: dict | None = None, status_override: dict | None = None,
                   extra_cands: pd.DataFrame | None = None) -> pd.DataFrame:
    """avail_override / status_override / extra_cands: lookahead weeks, where availability comes from the
    return-timing model and injured-reserve players expected back are added to the roster."""
    r = ratings or self.tm.fit(season, week)
    # Past plays are judged against defenses as they were; this week's opponents get personnel adjustments.
    r_game = self.game_ratings(season, week, r) if use_injuries else r
    vf = team_volume_features(self.team_ledger, season, week, self.cfg)
    games = self.games(season, week)
    tp = self.gm.predict(games, r_game, vf, use_vegas=use_vegas)
    f = self.pm.features(season, week, r)
    cands = self.candidates(season, week)
    if extra_cands is not None and len(extra_cands):
      cands = pd.concat([cands, extra_cands[~extra_cands.gsis_id.isin(cands.gsis_id)]], ignore_index=True)
    if wind is None:  # historical games: realized wind from play-by-play
      wind = self.team_ledger.drop_duplicates("game_id").set_index("game_id").wind
    p = self.pm.project(f, cands, tp, r_game, wind)
    p["proj_no_inj"] = p.proj
    p["avail"] = 1.0
    p["injury_boost"] = 0.0
    p["status"] = ""
    p["sits"], p["teammate_out"], p["boost_from"] = False, False, ""
    p["if_sits_gain"], p["if_sits_name"] = 0.0, ""
    if use_injuries and self.injury_model is not None:
      p = self.injury_model.apply(p, season, week, wind, avail_override, status_override)
    p = self._normalize_shares(p, wind)
    p["proj_neutral"] = self.pm.stats_from_volume(p, wind, neutral=True).proj
    p["matchup_pct"] = p.proj / p.proj_neutral.clip(lower=0.5) - 1
    p["matchup_pts"] = p.proj - p.proj_neutral
    p = self.attach_ecr(p, season, week)
    if blend and (self.ecr_map or getattr(self, "calib", {})):
      p = self.apply_blend(p)
    else:
      p["proj_model"] = p.proj
    p["low_sample"] = (p.n_db.fillna(0) + p.n_rush.fillna(0) + p.n_tgt.fillna(0)) < 40
    p = self._uncertainty(p)
    p["season"], p["week"] = season, week
    self.last_team_preds = tp
    return p

  def game_ratings(self, season: int, week: int, r=None):
    """Ratings for this week's games: pass defenses adjusted for starting cornerbacks likely out."""
    r = r or self.tm.fit(season, week)
    if self.personnel is None or self.injury_model is None:
      return r
    adj = self.personnel.week_adjustments(season, week, self.injury_model.report_avail(season, week))
    self.week_adj[(season, week)] = adj
    if adj.empty:
      return r
    r2 = copy.copy(r)
    r2.dfn = r.dfn.copy()
    r2.dfn["pass"] = r.dfn["pass"] + adj.adj_pass.astype(float).reindex(r.dfn.index).fillna(0.0)
    return r2

  def _uncertainty(self, p: pd.DataFrame) -> pd.DataFrame:
    a = p.pos.map(lambda x: self.sd_model.get(x, (25.0, 1.0))[0]) if hasattr(self, "sd_model") else 25.0
    b = p.pos.map(lambda x: self.sd_model.get(x, (25.0, 1.0))[1]) if hasattr(self, "sd_model") else 1.0
    # Widening for thin data / injury-driven roles, relative to a typical established player (4+ games).
    u = self.cfg.get("uncertainty", {})
    gf = float(u.get("games_factor", 0.6))
    m = (1 + gf / (1 + p.games.fillna(0))) / (1 + gf / 5)
    m = m * np.where(p.low_sample, float(u.get("low_sample_widen", 1.2)), 1.0)
    m = m * np.where(p.injury_boost > 0.5, float(u.get("injury_boost_widen", 1.25)), 1.0)
    sd = np.sqrt(a + b * p.proj.clip(lower=0)) * m
    for c in QCOLS:
      p[c] = np.nan
    for pos, (centers, offs) in getattr(self, "q_model", {}).items():
      sel = (p.pos == pos).to_numpy()
      if not sel.any():
        continue
      x = p.proj.to_numpy()[sel]
      for k, c in enumerate(QCOLS):
        off = np.interp(x, centers, offs[:, k])
        p.loc[sel, c] = np.clip(x + off * np.asarray(m)[sel], 0, None)
    p["sd"] = sd
    cv = sd / p.proj.clip(lower=1)
    p["confidence"] = np.select([cv <= 0.55, cv <= 0.8], ["High", "Medium"], "Low")
    return p

  def attach_actuals(self, p: pd.DataFrame, season: int, week: int) -> pd.DataFrame:
    a = self.actual[(self.actual.season == season) & (self.actual.week == week)].set_index("gsis_id").actual
    sn = self.data.snaps
    played = set(sn[(sn.season == season) & (sn.week == week) & (sn.offense_snaps > 0)].gsis_id.dropna())
    p = p.copy()
    p["played"] = p.gsis_id.isin(played) | p.gsis_id.isin(a.index)
    p["actual"] = p.gsis_id.map(a).fillna(0.0)
    return p
