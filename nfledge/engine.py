"""Orchestration: train meta-models on prior seasons, then project any (season, week)."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

import copy

from . import injuries as inj
from .config import ROOT
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
    if cfg.get("experiments", {}).get("depth_per_team"):
      import dataclasses  # (AR) A/B: each team's depth chart as of its own game
      data = dataclasses.replace(data, depth_per_team=True)
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
    if self.cfg.get("experiments", {}).get("debut_prior"):
      self.pm.fit_debut(test_season)
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

  # EXPERIMENT (experiments.rb_split; INSIGHTS (CC), pre-registered 2026-10-21): a sitting back's carries split between
  # the backs left in the rotation and the next man up, as measured (tools/committee_split.py, 2016-20 only): with one
  # rotation back (predicted share >= ROT_MIN) the rotation takes RB_ROT[1] of the vacated share, with two or more
  # RB_ROT[2], the rest goes to the other remaining backs on the board (none: a call-up we don't project). Replaces the
  # redistribution + normalization for those backs' carries (Woody Marks 2026 wk 7: 91% of Houston's RB carries; backs
  # projected 80%+ after a sitter got 70%, n 43).
  RB_SIT_MIN, ROT_MIN, RB_ROT = 0.30, 0.15, {1: 0.50, 2: 0.63}

  def _rb_split(self, p: pd.DataFrame, wind) -> pd.DataFrame:
    if "carry_share_hat" not in p or p.empty:
      return p
    p = p.copy()
    sits = p.get("sits", pd.Series(False, index=p.index)).astype(bool)
    rb = p.pos == "RB"
    # each player's predicted share, normalized as _normalize_shares does but with the sitters counted (the team total
    # corrected for over-subscription without refilling the absence: the split below hands that out)
    a = float(self.cfg.get("experiments", {}).get("share_normalize_carries", self.cfg.get("experiments", {}).get("share_normalize", 0.0)))
    raw = p.carry_share_hat.fillna(0.0).where(p.pos.isin(["QB", "RB", "WR", "TE"]), 0.0)
    tot = (getattr(self, "share_totals", None) or {}).get("carries", 1.0)
    fac = (1 + a * (tot / raw.groupby(p.team).transform("sum").replace(0, np.nan) - 1)).fillna(1.0).clip(0.6, 1.6)
    own = raw * fac

    def split(g: pd.DataFrame, out: pd.Series) -> pd.Series | None:
      """The remaining backs' carry shares when the backs in `out` (index labels) sit: own share + their part of the
      vacated share (rotation / depth as measured). None when no qualifying back sits."""
      gone = [i for i in out if own[i] >= self.RB_SIT_MIN]
      left = g.drop(out)
      if not gone or not len(left):
        return None
      vac = float(own[gone].sum())
      rot = left[own[left.index] >= self.ROT_MIN]
      dep = left.drop(rot.index)  # none on the board: the depth part goes to a call-up we don't project
      f_rot = 0.0 if not len(rot) else self.RB_ROT[min(len(rot), 2)]
      new = own[left.index].copy()
      if len(rot):
        new[rot.index] += vac * f_rot * own[rot.index] / own[rot.index].sum()
      if len(dep):
        wd = own[dep.index] + 0.02
        new[dep.index] += vac * (1 - f_rot) * wd / wd.sum()
      return new

    def with_carries(q: pd.DataFrame, shares: pd.Series) -> pd.DataFrame:
      q = q.copy()
      car = shares * q.loc[shares.index, "team_rush"]
      q.loc[shares.index, "rush"] = q.loc[shares.index, "rush"] + (car - q.loc[shares.index, "carries"])
      q.loc[shares.index, "carries"] = car
      return q

    changed, worlds = False, []
    for team, g in p[rb].groupby("team"):
      out = [i for i in g.index if sits[i]]
      new = split(g, out)
      if new is not None:
        p = with_carries(p, new)
        changed = True
      # the "if he plays / if he sits" worlds of an uncertain back (5-95% to play), under the same rules, so the
      # teammates' pairings show this split, not the old redistribution's (injuries.apply measured those)
      av = p.get("avail", pd.Series(1.0, index=p.index))
      for j in g.index:
        if not (0.05 <= float(av[j]) <= 0.95) or own[j] < self.RB_SIT_MIN:
          continue
        o_sit, o_play = sorted(set(out) | {j}), [i for i in out if i != j]
        sh_sit, sh_play = split(g, o_sit), split(g, o_play)
        sh_play = sh_play if sh_play is not None else own[g.drop(o_play).index]
        if sh_sit is None:
          continue
        worlds.append((p.at[j, "gsis_id"], team, sh_sit, sh_play))
    p = self.pm.stats_from_volume(p, wind) if changed else p
    for pid, team, sh_sit, sh_play in worlds:
      a_ = self.pm.stats_from_volume(with_carries(p, sh_sit), wind).proj
      b_ = self.pm.stats_from_volume(with_carries(p, sh_play), wind).proj
      for i in sh_sit.index.intersection(sh_play.index):
        for k in ("cond", "cond2"):
          if f"{k}_pid" in p and p.at[i, f"{k}_pid"] == pid:
            p.at[i, f"{k}_sits"], p.at[i, f"{k}_plays"] = float(a_[i]), float(b_[i])
    return p

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

  def _journeyman(self, p: pd.DataFrame, season: int, week: int) -> pd.DataFrame:
    """Players who change teams often come in under their projections (owner idea; pre-registered 2026-10-15,
    tools/journeyman_eval.py): k = team changes over his past 5 seasons + this one (weekly rosters), capped at 3,
    scales his whole projected stat line by a measured multiplier (data/history/journeyman.json: 1 / 0.94 / 0.91 /
    0.89). Fit on 2021-23, tested on 2024-25: MAE -0.108 for k >= 1, -0.039 overall; shipped multipliers refit on
    2021-25 (so backtests of those seasons are partly in-sample). His first game with a team is left to the
    newcomer discount."""
    import json
    from pathlib import Path
    from .player_model import STAT_KEYS
    if not hasattr(self, "_jm"):
      f = Path(__file__).resolve().parent.parent / "data" / "history" / "journeyman.json"
      self._jm = {int(k): float(v) for k, v in json.loads(f.read_text(encoding="utf-8"))["mult"].items()} if f.exists() else {}
      self._jm_seq = {}
      r = self.data.rosters[(self.data.rosters.status == "ACT") & self.data.rosters.gsis_id.notna()].sort_values(["season", "week"])
      for (g, s_), x in r.groupby(["gsis_id", "season"]):
        self._jm_seq[(g, int(s_))] = list(zip(x.week.astype(int), team_name_fix(x.team)))
    if not self._jm:
      return p
    p = p.copy()
    first = getattr(self, "_first_game", {})
    now = season * 100 + week
    mult = []
    for g, team in zip(p.gsis_id, p.team.astype(str)):
      fg = first.get((g, team))
      if first and (fg is None or fg >= now):  # first game with this team: the newcomer discount's job
        mult.append(1.0)
        continue
      teams = []
      for y in range(season - 5, season + 1):
        teams += [t for wk, t in self._jm_seq.get((g, y), []) if y < season or wk <= week]
      teams = [t for i, t in enumerate(teams) if i == 0 or t != teams[i - 1]]
      mult.append(self._jm.get(min(3, max(0, len(teams) - 1)), 1.0))
    m = np.array(mult)
    for k in STAT_KEYS + ["proj"]:
      if k in p:
        p[k] = p[k] * m
    if "proj_model" in p:
      p["proj_model"] = p.proj_model * m
    return p

  def _sleeper_blend(self, p: pd.DataFrame, season: int, week: int, weights: dict) -> pd.DataFrame:
    """EXPERIMENT (experiments.sleeper_blend, OFF): final = (1 - w) ours + w Sleeper's projection (RotoWire's, scored
    in our rules), w per position. The backtest passed (2026-10-15, tools/sleeper_compare.py) but Sleeper's saved
    projections are edited after games, and the leak-free version failed; forward test from pre-kickoff snapshots
    (tools/sleeper_snapshot.py). The whole stat line (and both two-world numbers) is scaled by blended / ours, so
    per-league rescoring stays consistent. Sleeper's 0 is their availability call, not a forecast: our projection is
    "if he plays" (availability is shown separately), so those players keep ours, as do players Sleeper doesn't
    project and players we project at 0."""
    from . import sleeper as SL
    from .player_model import STAT_KEYS
    try:
      # the week being played or later (week clock); completed_weeks already counts a live week with one final game
      from .week_clock import Clock
      live = week >= Clock(self.data.schedules).current_week(season) if season == self.data.current_season else False
      sp = SL.week_points(season, week, ROOT / self.cfg["data"]["cache_dir"], self.scoring, self.data.rosters, live=live)
    except Exception as e:  # Sleeper down: ours alone
      _log(f"sleeper projections {season} wk {week}: unavailable ({type(e).__name__}); not blended")
      return p
    p = p.copy()
    p["sleeper"] = p.gsis_id.map(sp)
    w = p.pos.map(lambda x: float(weights.get(x, 0.0)))
    ok = (p.sleeper > 0) & (p.proj > 0) & (w > 0)
    new = (1 - w) * p.proj + w * p.sleeper
    ratio = pd.Series(1.0, index=p.index).where(~ok, new / p.proj.where(ok))
    for k in STAT_KEYS + ["proj"] + [c for c in ("cond_plays", "cond_sits", "cond2_plays", "cond2_sits") if c in p]:
      if k in p:
        p[k] = p[k] * ratio
    return p

  def _newcomers(self, p: pd.DataFrame, scale: float, wind, season: int, week: int) -> pd.DataFrame:
    """EXPERIMENT (experiments.newcomer_scale; pre-registered 2026-10-15): a RB / WR / TE in his first game for a team
    (no snap for it before this week, any season) gets `scale` x his projected targets and carries (mid-season movers'
    first games came in at ~40% of projection, 2021-25); the removed volume goes to same-position teammates who are
    projected to play, in proportion to their own. (v1 keyed on the features' last_team, which isn't 'team of his last
    game': it flagged 13k rows, whole seasons of offseason movers; that run was discarded.)"""
    p = p.copy()
    if not hasattr(self, "_first_game"):
      sn = self.data.snaps.dropna(subset=["gsis_id"])
      sn = sn[(sn.offense_snaps.fillna(0) + sn.defense_snaps.fillna(0) + sn.st_snaps.fillna(0)) > 0]
      sn = sn.assign(team=team_name_fix(sn.team), k=sn.season * 100 + sn.week)
      self._first_game = sn.groupby(["gsis_id", "team"]).k.min().to_dict()
    now = season * 100 + week
    first = [self._first_game.get((g, t)) for g, t in zip(p.gsis_id, p.team.astype(str))]
    new = pd.Series([f is None or f >= now for f in first], index=p.index) & p.pos.isin(["RB", "WR", "TE"])
    # someone who played somewhere BEFORE this week (not a rookie debut). The first-game table spans every loaded
    # season, so in backtests it includes later seasons: checking "played anywhere" alone flagged debuting rookies
    # who play in later seasons (bug found 2026-10-15; harmless while debuts projected 0, not with debut priors).
    if not hasattr(self, "_first_any"):
      fa = {}
      for (g, _), k in self._first_game.items():
        fa[g] = min(k, fa.get(g, k))
      self._first_any = fa
    new &= pd.Series([self._first_any.get(g, now) < now for g in p.gsis_id], index=p.index)
    if not new.any():
      return p
    for v in ("tgt", "carries"):
      cut = (p[v] * (1 - scale)).where(new, 0.0)
      p.loc[new, v] = p.loc[new, v] * scale
      if v == "carries":
        p.loc[new, "rush"] = p.loc[new, "rush"] - cut[new]
      for (team, pos), c in cut[new].groupby([p.team[new], p.pos[new]]):
        mates = p.index[(p.team == team) & (p.pos == pos) & ~new & ~p.get("sits", pd.Series(False, index=p.index)).astype(bool)]
        base = p.loc[mates, v]
        if len(mates) and base.sum() > 0:
          add = c.sum() * base / base.sum()
          p.loc[mates, v] = base + add
          if v == "carries":
            p.loc[mates, "rush"] = p.loc[mates, "rush"] + add
    # recompute only the teams with a newcomer: a second stats_from_volume pass isn't exactly idempotent (rows on
    # untouched teams moved ~0.02 pts), so everyone else keeps his row as it was
    aff = p.team.isin(set(p.team[new]))
    redo = self.pm.stats_from_volume(p[aff], wind)
    p = p.copy()
    for col in redo.columns:
      if col in p.columns:
        p.loc[aff, col] = redo[col].to_numpy()
    return p

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
    # practice-squad players elevated for this week's game (live builds: nfledge/elevations.py; the weekly roster lists
    # them as practice squad until after the game, so the board never had them: Jawhar Jordan, Houston, 2026)
    el = getattr(self.data, "elevated", None)
    if el is not None and len(el):
      el = el.assign(team=team_name_fix(el.team), pos=el.pos.replace({"FB": "RB", "HB": "RB"}))
      el = el[el.team.isin(playing) & el.pos.isin(self.positions) & ~el.gsis_id.isin(c.gsis_id)]
      c = pd.concat([c, el[["gsis_id", "team", "pos", "full_name"]]], ignore_index=True)
    dc = depth_for_week(self.data, season, week)
    dc["team"] = team_name_fix(dc.team)
    # One depth slot per player on his current team (charts can list a player twice: two slots, or a stale team).
    dc = dc[["gsis_id", "team", "rank"]].sort_values("rank").drop_duplicates(["gsis_id", "team"])
    c = c.merge(dc.rename(columns={"rank": "depth_rank"}), on=["gsis_id", "team"], how="left")
    return c.reset_index(drop=True)

  def project_week(self, season: int, week: int, use_injuries: bool = True, use_vegas: bool = True,
                   wind: pd.Series | None = None, quiet: bool = False, ratings=None,
                   blend: bool = True, avail_override: dict | None = None, status_override: dict | None = None,
                   extra_cands: pd.DataFrame | None = None, starters: dict | None = None) -> pd.DataFrame:
    """avail_override / status_override / extra_cands: lookahead weeks, where availability comes from the
    return-timing model and injured-reserve players expected back are added to the roster. starters: team -> the
    QB the game model rates (its points and, with no Vegas line, its own spread); None rates no QB."""
    r = ratings or self.tm.fit(season, week)
    # Past plays are judged against defenses as they were; this week's opponents get personnel adjustments.
    r_game = self.game_ratings(season, week, r) if use_injuries else r
    lu_s = float(self.cfg.get("experiments", {}).get("lineup_epa_scale", 0.0))
    if lu_s and use_injuries:  # EXPERIMENT (BZ): offenses missing (or getting back) regulars, projections only
      r_game = self._lineup_adjust(r_game, season, week, lu_s)
    vf = team_volume_features(self.team_ledger, season, week, self.cfg)
    games = self.games(season, week)
    tp = self.gm.predict(games, r_game, vf, use_vegas=use_vegas, starters=starters)
    f = self.pm.features(season, week, r)
    cands = self.candidates(season, week)
    if extra_cands is not None and len(extra_cands):
      cands = pd.concat([cands, extra_cands[~extra_cands.gsis_id.isin(cands.gsis_id)]], ignore_index=True)
    if wind is None:  # historical games: realized wind from play-by-play
      wind = self.team_ledger.drop_duplicates("game_id").set_index("game_id").wind
    p = self.pm.project(f, cands, tp, r_game, wind)
    # plain Python strings for the row-by-row injury steps: pandas' Arrow-backed "str" columns cost ~0.1 s per row
    # loop in _redistribute / availability (2026-10-22 profile: 26.7M Arrow element reads, ~4 of a build's 7 minutes);
    # values are unchanged
    sc = [c for c in p.columns if pd.api.types.is_string_dtype(p[c].dtype) and p[c].dtype != object]
    if sc:
      p[sc] = p[sc].astype(object)
    p["proj_no_inj"] = p.proj
    p["avail"] = 1.0
    p["injury_boost"] = 0.0
    p["status"] = ""
    p["sits"], p["teammate_out"], p["boost_from"] = False, False, ""
    p["if_sits_gain"], p["if_sits_name"] = 0.0, ""
    if use_injuries and self.injury_model is not None:
      p = self.injury_model.apply(p, season, week, wind, avail_override, status_override)
    p["proj_at_inj"] = p.proj  # the injury boost is measured here; later steps rescale it (below)
    nf = float(self.cfg.get("experiments", {}).get("newcomer_scale", 1.0))
    if nf < 1.0:  # EXPERIMENT (experiments.newcomer_scale): first game for a new team, after who sits is settled
      p = self._newcomers(p, nf, wind, season, week)
    p = self._normalize_shares(p, wind)
    if self.cfg.get("experiments", {}).get("rb_split"):
      p = self._rb_split(p, wind)
    p["proj_neutral"] = self.pm.stats_from_volume(p, wind, neutral=True).proj
    p["matchup_pct"] = p.proj / p.proj_neutral.clip(lower=0.5) - 1
    p["matchup_pts"] = p.proj - p.proj_neutral
    p = self.attach_ecr(p, season, week)
    if blend and (self.ecr_map or getattr(self, "calib", {})):
      p = self.apply_blend(p)
    else:
      p["proj_model"] = p.proj
    if self.cfg.get("experiments", {}).get("journeyman", False):
      p = self._journeyman(p, season, week)
    sw = self.cfg.get("experiments", {}).get("sleeper_blend") or {}
    if sw and blend and avail_override is None:  # tested on the week being played only, not lookahead weeks
      p = self._sleeper_blend(p, season, week, sw)
    # The boost is measured when injuries are applied, but later steps (team-share normalization, the expert blend,
    # journeyman) move the projection: scale it with them so the "+X from injuries" tag is part of the final number
    # and never exceeds it (owner 2026-10-15: Huntley showed +12.7 inj on an 11.6 projection).
    at = p.proj_at_inj.where(p.proj_at_inj > 0)
    p["injury_boost"] = (p.injury_boost * (p.proj / at)).fillna(0.0).clip(lower=0.0, upper=p.proj.clip(lower=0.0))
    p = p.drop(columns=["proj_at_inj"])
    p["low_sample"] = (p.n_db.fillna(0) + p.n_rush.fillna(0) + p.n_tgt.fillna(0)) < 40
    p = self._uncertainty(p)
    p["season"], p["week"] = season, week
    self.last_team_preds = tp
    return p

  def final_teams(self, season: int, week: int) -> set | None:
    """Teams whose final injury report for the week is in (the chronology, at the injury model's moment); None for a
    season without dated reports ((CF): the report-availability term then counts any row this week)."""
    from .injuries import chrono
    c = chrono(self.data, season, week, getattr(self.injury_model, "now", None))
    return None if c is None else c.final_teams()

  def _lineup_adjust(self, r, season: int, week: int, scale: float):
    """(BZ) each offense's pass and rush EPA moved by its lineup sum (nfledge/lineup.py, report availability)."""
    from . import lineup as LU
    if getattr(self, "_lineups", None) is None:
      self._lineups = (LU.Lineups(LU.shares(self.data.snaps)), LU.Values())
    lus, vals = self._lineups
    fin = self.final_teams(season, week)
    d = {t: LU.team_term(lus.regulars(t, season, week), LU.report_available(self.data.rosters, self.data.injuries, season, week, t,
                                                                            None if fin is None else t in fin),
                         lambda p, g: vals(season, p, g))["off"] for t in r.off.index}
    r2 = copy.copy(r)
    r2.off = r.off.copy()
    adj = pd.Series(d).reindex(r.off.index).fillna(0.0) * scale
    for u in ("pass", "rush"):
      r2.off[u] = r.off[u] + adj
    return r2

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
