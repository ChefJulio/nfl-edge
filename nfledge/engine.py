"""Orchestration: train meta-models on prior seasons, then project any (season, week)."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from . import injuries as inj
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
    folds = [(s, w) for s in seasons for w in range(4, self.data.completed_weeks(s) + 1)]
    self.tm.tune_alphas(folds)
    self.pm.prepare(seasons)
    self.pm.fit_priors(seasons)
    self.gm = GameModel(self.cfg)
    self.gm.fit(self.gm.training_rows(self.tm, self.team_ledger, seasons))
    train = self.pm.training_rows(seasons, self.positions)
    self.pm.fit_meta(train)
    self.injury_model = inj.InjuryModel(self.data, self.pm, self.cfg).fit(seasons) if use_injuries else None
    self._fit_blend_and_uncertainty(seasons)
    self.trained_for = (test_season, use_injuries)
    _log(f"trained for {test_season} on {seasons} in {time.time() - t0:.0f}s; alphas {self.tm.alphas}")
    return self

  def _fit_blend_and_uncertainty(self, seasons):
    """From projections on the train seasons: (1) expert-consensus blend per position, (2) residual SD model
    per position (sd^2 = a + b * projection)."""
    self.ecr_map, self.blend, self.sd_model = {}, {}, {}
    rows = []
    for s in seasons:
      for w in range(2, self.data.completed_weeks(s) + 1):
        p = self.project_week(s, w, use_injuries=False, quiet=True, blend=False)
        rows.append(self.attach_actuals(p, s, w))
    d = pd.concat(rows)
    d = d[d.played]
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
    p = p.drop(columns=["ecr", "ecr_pts"], errors="ignore")
    e = self.data.ecr
    if e is None:
      return p.assign(ecr=np.nan, ecr_pts=np.nan)
    e = e[(e.season == season) & (e.week == week)][["gsis_id", "ecr", "scrape_date"]]
    kick = self.games(season, week)[["game_id", "gameday"]]
    p = p.merge(e, on="gsis_id", how="left").merge(kick, on="game_id", how="left")
    late = pd.to_datetime(p.scrape_date) >= pd.to_datetime(p.gameday)
    p.loc[late, "ecr"] = np.nan
    return p.drop(columns=["scrape_date", "gameday"]).assign(ecr_pts=np.nan)

  def apply_blend(self, p: pd.DataFrame) -> pd.DataFrame:
    p = p.copy()
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
    c = r[r.team.isin(playing)][["gsis_id", "team", "pos", "full_name"]].drop_duplicates("gsis_id")
    dc = depth_for_week(self.data, season, week)
    dc["team"] = team_name_fix(dc.team)
    c = c.merge(dc[["gsis_id", "rank"]].rename(columns={"rank": "depth_rank"}), on="gsis_id", how="left")
    return c.reset_index(drop=True)

  def project_week(self, season: int, week: int, use_injuries: bool = True, use_vegas: bool = True,
                   wind: pd.Series | None = None, quiet: bool = False, ratings=None,
                   blend: bool = True) -> pd.DataFrame:
    r = ratings or self.tm.fit(season, week)
    vf = team_volume_features(self.team_ledger, season, week, self.cfg)
    games = self.games(season, week)
    tp = self.gm.predict(games, r, vf, use_vegas=use_vegas)
    f = self.pm.features(season, week, r)
    cands = self.candidates(season, week)
    if wind is None:  # historical games: realized wind from play-by-play
      wind = self.team_ledger.drop_duplicates("game_id").set_index("game_id").wind
    p = self.pm.project(f, cands, tp, r, wind)
    p["proj_no_inj"] = p.proj
    p["avail"] = 1.0
    p["injury_boost"] = 0.0
    p["status"] = ""
    p["sits"], p["teammate_out"], p["boost_from"] = False, False, ""
    p["if_sits_gain"], p["if_sits_name"] = 0.0, ""
    if use_injuries and self.injury_model is not None:
      p = self.injury_model.apply(p, season, week, wind)
    p["proj_neutral"] = self.pm.stats_from_volume(p, wind, neutral=True).proj
    p["matchup_pct"] = p.proj / p.proj_neutral.clip(lower=0.5) - 1
    p["matchup_pts"] = p.proj - p.proj_neutral
    p = self.attach_ecr(p, season, week)
    if blend and self.ecr_map:
      p = self.apply_blend(p)
    else:
      p["proj_model"] = p.proj
    p["low_sample"] = (p.n_db.fillna(0) + p.n_rush.fillna(0) + p.n_tgt.fillna(0)) < 40
    p = self._uncertainty(p)
    p["season"], p["week"] = season, week
    self.last_team_preds = tp
    return p

  def _uncertainty(self, p: pd.DataFrame) -> pd.DataFrame:
    a = p.pos.map(lambda x: self.sd_model.get(x, (25.0, 1.0))[0]) if hasattr(self, "sd_model") else 25.0
    b = p.pos.map(lambda x: self.sd_model.get(x, (25.0, 1.0))[1]) if hasattr(self, "sd_model") else 1.0
    # Widening for thin data / injury-driven roles, relative to a typical established player (4+ games).
    m = (1 + 0.6 / (1 + p.games.fillna(0))) / (1 + 0.6 / 5)
    m = m * np.where(p.low_sample, 1.2, 1.0) * np.where(p.injury_boost > 0.5, 1.25, 1.0)
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
