"""Player projections: projected volume x adjusted efficiency, matchup-adjusted.

Pipeline (all "as-of": only games before the target week are used):
  ledger      one row per player-game with opportunities (dropbacks, rushes, targets), component sums
              (yards, TDs, catches, INTs), expected TDs, and EPA.
  features    recency-weighted usage shares + empirical-Bayes-shrunk efficiency rates (prior = position x
              draft-capital tier) + opponent-adjusted EPA/opportunity (raw EPA minus the opponent's ridge
              defensive coefficient).
  meta-models learned on prior seasons only: share calibration (regression to the mean) and per-component
              efficiency regressions  rate ~ shrunk_rate + adj_epa + opponent_defense + home.
  projection  team volume (GameModel) x share -> opportunities; opportunities x component rates -> stats;
              stats x scoring file -> fantasy points.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .team_model import Linear, asof_weights

# Opportunity types -> (team denominator, defensive unit, components)
OPP_TYPES = {
  "db": ("team_db", "pass", ["pass_yd", "pass_td", "interception"]),
  "rush": ("team_rush", "rush", ["rush_yd", "rush_td"]),
  "tgt": ("team_db", "pass", ["reception", "rec_yd", "rec_td"]),
}
TD_COMPONENTS = {"pass_td": "pass_xtd", "rush_td": "rush_xtd", "rec_td": "rec_xtd"}
STAT_KEYS = ["pass_yd", "pass_td", "interception", "rush_yd", "rush_td", "reception", "rec_yd", "rec_td",
             "fumble_lost"]
YARD_BINS = [0, 1, 2, 3, 4, 5, 7, 10, 15, 20, 30, 50, 100]
EFF_SEASON_WEIGHTS = (1.0, 0.6, 0.3)  # current, last, two seasons back


def EFF_FEATURES(comp: str, opp: str, unit: str, exp: dict | None = None) -> list[str]:
  """Efficiency regression inputs: player's shrunk rate, player's opponent-adjusted EPA/opp, the opponent's
  defensive coefficient (the matchup), our own unit's offensive coefficient (supporting cast), home field.
  Optional (config [experiments]): Vegas implied team total; average depth of target for receiving yards."""
  exp = exp or {}
  cols = [f"{comp}_per_{opp}", f"{opp}_adj_per_{opp}", f"def_{unit}", f"off_{unit}", "home"]
  # Wind as a fitted input to passing efficiency (instead of the fixed penalty): the data sets its size.
  wind_mode = exp.get("wind_mode", "fixed")
  if unit == "pass" and wind_mode in ("linear", "quadratic"):
    cols.append("wind")
    if wind_mode == "quadratic":
      cols.append("wind_sq")
  if exp.get("implied_total"):
    cols.append("implied_pts")
  if exp.get("air_yards") and comp == "rec_yd":
    cols.append("adot")
  # EXPERIMENT: goal-line role. A back whose share of the team's inside-10 carries runs above his overall carry
  # share (a "vulture") should score more TDs per carry than his history of all carries alone says.
  if exp.get("gl_share") and comp == "rush_td":
    cols.append("i10_tilt")
  # EXPERIMENT (owner): goal-line role x how often the team gets there. gl_frac = the expected share of HIS carries
  # that come inside the 10 = (team's expected inside-10 fraction of rushes, from its implied points and run
  # offense) x (his inside-10 share relative to his carry share). TDs = carries x rate, so this term's weight is
  # the extra TDs per expected goal-line carry: a goal-line back only gains where his team reaches the goal line.
  if exp.get("gl_struct") and comp == "rush_td":
    cols.append("gl_frac")
  return cols


GL_RATIO_K = 10.0  # pseudo team goal-line carries pulling a player's goal-line ratio toward 1
GL_TEAM_DEFAULT = 0.08  # league-typical share of a team's designed rushes inside the 10 (fallback)


RB_DEFAULT_CONC = 0.65  # league-typical lead-back share of RB carries, for teams with no history in the window


def add_rb_inputs(d: pd.DataFrame, conc: dict | None) -> pd.DataFrame:
  """Derived inputs for the RB experiments (in place): team committee tendency, its interaction with the
  player's carry share, and the goal-line tilt (inside-10 carry share minus overall carry share)."""
  d["team_conc"] = d.team.map(conc or {}).fillna(RB_DEFAULT_CONC).astype(float)
  cs = d["carry_share"].fillna(0.0) if "carry_share" in d else 0.0
  d["carry_share_x_conc"] = cs * d.team_conc
  if "i10_share" in d:
    d["i10_tilt"] = d.i10_share.fillna(cs) - cs
  else:
    d["i10_tilt"] = 0.0
  return d


def SHARE_FEATURES(share: str, exp: dict | None = None) -> list[str]:
  exp = exp or {}
  cols = [share, f"{share}_long"]
  # Game script: the team's Vegas spread, and spread x the player's own share so lead roles and change-of-pace
  # roles can respond differently (favorites run the lead back more; trailing teams throw to receiving backs).
  if exp.get("spread_shares"):
    cols += ["spread_team", f"{share}_x_spread"]
  if exp.get("air_yards") and share == "tgt_share":
    cols += ["ay_share", "ay_share_long"]
  if exp.get("snap_input"):
    cols.append("snap_pct")
  # EXPERIMENT: committee vs bellcow teams. The team's lead-back concentration, and concentration x the player's
  # own share (on a committee team a big recent share should regress more; on a bellcow team it should stick).
  if exp.get("rbbc") and share == "carry_share":
    cols += ["team_conc", "carry_share_x_conc"]
  return cols


def pos_group(opp: str, pos: pd.Series) -> pd.Series:
  """Which efficiency-model group a player falls into for an opportunity type."""
  if opp == "db":
    return pd.Series("QB", index=pos.index)
  if opp == "rush":
    return pos.where(pos == "QB", "RB")
  return pos.where(pos != "QB", "WR")  # QB targets (trick plays) are negligible; lump with WR


def mom_prior(g: pd.DataFrame, num: str, den: str) -> tuple[float, float] | None:
  """Empirical-Bayes prior for a rate num/den by method of moments over player-seasons: mean = pooled rate,
  strength k = within-player (game-to-game) variance / between-player variance, in units of den."""
  g = g[g[den] > 0]
  if len(g) < 100:
    return None
  ps = g.groupby(["gsis_id", "season"])
  n_i, s_i = ps[den].sum(), ps[num].sum()
  mean_i = s_i / n_i
  rate_g = g[num] / g[den]
  dev = g[den] * (rate_g - mean_i.reindex(pd.MultiIndex.from_frame(g[["gsis_id", "season"]])).to_numpy()) ** 2
  sigma2 = float(dev.sum() / max(len(g) - len(n_i), 1))
  big = n_i >= np.percentile(n_i, 50)
  m, n = mean_i[big], n_i[big]
  grand = float(s_i.sum() / n_i.sum())
  tau2 = float(np.average((m - np.average(m, weights=n)) ** 2, weights=n) - sigma2 * np.mean(1.0 / n))
  k = sigma2 / tau2 if tau2 > 0 else 2000.0
  return grand, float(np.clip(k, 5.0, 2000.0))


def draft_tier(rnd) -> str:
  if pd.isna(rnd):
    return "UDFA"
  return "R1" if rnd == 1 else "R2-3" if rnd <= 3 else "R4-7"


# ----------------------------------------------------------------------------------------------------------------
# Ledger
# ----------------------------------------------------------------------------------------------------------------

def _ybin(y: pd.Series) -> pd.Series:
  return pd.cut(y, YARD_BINS, labels=False, include_lowest=True)


class XTD:
  """Expected-TD lookup: TD rate by play type x yardline bin (x end-zone target for passes), fit on history."""

  def fit(self, pbp: pd.DataFrame):
    rush = pbp[((pbp.rush == 1) | (pbp.qb_scramble == 1)) & (pbp.qb_kneel == 0) & (pbp.two_point_attempt == 0) & pbp.rusher_player_id.notna()]
    self.rush = rush.groupby(_ybin(rush.yardline_100)).rush_touchdown.mean()
    tg = self._targets(pbp)
    self.tgt = tg.groupby([_ybin(tg.yardline_100), tg.endzone]).pass_touchdown.mean()
    self.tgt_bin = tg.groupby(_ybin(tg.yardline_100)).pass_touchdown.mean()
    return self

  @staticmethod
  def _targets(pbp):
    tg = pbp[(pbp.pass_attempt == 1) & (pbp.sack == 0) & pbp.receiver_player_id.notna() &
             (pbp.two_point_attempt == 0)].copy()
    tg["endzone"] = (tg.air_yards.fillna(0) >= tg.yardline_100).astype(int)
    return tg

  def rush_xtd(self, plays):
    return _ybin(plays.yardline_100).map(self.rush).fillna(0.0).to_numpy()

  def tgt_xtd(self, plays):
    key = pd.MultiIndex.from_arrays([_ybin(plays.yardline_100), plays.endzone])
    v = pd.Series(self.tgt.reindex(key).to_numpy(), index=plays.index)
    return v.fillna(_ybin(plays.yardline_100).map(self.tgt_bin)).fillna(0.0).to_numpy()


def build_ledger(pbp: pd.DataFrame, xtd: XTD, team_ledger: pd.DataFrame, snaps: pd.DataFrame,
                 routes: pd.DataFrame | None, exclusions: pd.DataFrame | None) -> pd.DataFrame:
  base = ["season", "week", "game_id", "posteam", "defteam", "home", "game_wind", "indoor"]
  live = pbp[(pbp.two_point_attempt == 0) & pbp.posteam.notna()]

  db = live[live.is_dropback].copy()
  db["gsis_id"] = db.passer_player_id.fillna(db.rusher_player_id)
  tgt_mask = (db.pass_attempt == 1) & (db.sack == 0) & db.receiver_player_id.notna()
  db["endzone"] = (db.air_yards.fillna(0) >= db.yardline_100).astype(int)
  db["pass_xtd"] = 0.0
  db.loc[tgt_mask, "pass_xtd"] = xtd.tgt_xtd(db[tgt_mask])
  db = db.assign(db=1, db_epa=db.epa.fillna(0), pass_yd=db.passing_yards.fillna(0) * (db.qb_scramble == 0),
                 pass_td=db.pass_touchdown * (db.qb_scramble == 0), interception=db.interception)
  a = db.groupby(base + ["gsis_id"])[["db", "db_epa", "pass_yd", "pass_td", "interception", "pass_xtd"]].sum()

  # nflverse flags scrambles as pass plays (pass=1, rush=0), so include them explicitly.
  ru = live[((live.rush == 1) | (live.qb_scramble == 1)) & (live.qb_kneel == 0) & live.rusher_player_id.notna()].copy()
  ru = ru.assign(gsis_id=ru.rusher_player_id, rush=1, carries=ru.is_designed_rush.astype(int),
                 scrambles=ru.qb_scramble, rush_epa=ru.epa.fillna(0), rush_yd=ru.rushing_yards.fillna(0),
                 rush_td=ru.rush_touchdown, rush_xtd=xtd.rush_xtd(ru),
                 carries_i10=(ru.is_designed_rush.astype(bool) & (ru.yardline_100 <= 10)).astype(int))
  b = ru.groupby(base + ["gsis_id"])[["rush", "carries", "scrambles", "rush_epa", "rush_yd", "rush_td",
                                      "rush_xtd", "carries_i10"]].sum()

  tg = XTD._targets(live)
  tg = tg.assign(gsis_id=tg.receiver_player_id, tgt=1, tgt_epa=tg.epa.fillna(0), reception=tg.complete_pass,
                 rec_yd=tg.receiving_yards.fillna(0), rec_td=tg.pass_touchdown, rec_xtd=xtd.tgt_xtd(tg),
                 air_yd=tg.air_yards.fillna(0))
  c = tg.groupby(base + ["gsis_id"])[["tgt", "tgt_epa", "reception", "rec_yd", "rec_td", "rec_xtd",
                                      "air_yd"]].sum()

  fm = live[(live.fumble_lost == 1) & live.fumbled_1_player_id.notna()]
  f = fm.assign(gsis_id=fm.fumbled_1_player_id, fumble_lost=1).groupby(base + ["gsis_id"])[["fumble_lost"]].sum()

  led = a.join(b, how="outer").join(c, how="outer").join(f, how="outer").fillna(0).reset_index()
  led = led.rename(columns={"posteam": "team", "defteam": "opp", "game_wind": "wind"})

  # Games played with no touches still count (share = 0): add snap-only rows from snap counts.
  sn = snaps.dropna(subset=["gsis_id"])
  sn = sn[sn.offense_snaps > 0][["season", "week", "gsis_id", "offense_pct", "offense_snaps"]]
  led = led.merge(sn, on=["season", "week", "gsis_id"], how="outer")
  missing = led.game_id.isna()
  if missing.any():
    tl = team_ledger[["season", "week", "game_id", "team", "opp", "home", "wind", "indoor"]]
    tm_of = snaps.dropna(subset=["gsis_id"]).drop_duplicates(["season", "week", "gsis_id"]).set_index(
      ["season", "week", "gsis_id"]).team.rename("snap_team")
    fill = led[missing].drop(columns=["game_id", "team", "opp", "home", "wind", "indoor"]).join(
      tm_of, on=["season", "week", "gsis_id"]).merge(tl, left_on=["season", "week", "snap_team"],
                                                     right_on=["season", "week", "team"], how="inner")
    led = pd.concat([led[~missing], fill.drop(columns=["snap_team"])], ignore_index=True)
  num = [c for c in led.columns if c not in ("season", "week", "game_id", "team", "opp", "gsis_id", "indoor")]
  led[num] = led[num].fillna(0)
  led["offense_pct"] = led.offense_pct.replace(0, np.nan)

  tl = team_ledger[["game_id", "team", "dropbacks", "rushes"]].rename(columns={"dropbacks": "team_db",
                                                                              "rushes": "team_rush"})
  led = led.merge(tl, on=["game_id", "team"], how="left")
  led["team_ay"] = led.groupby(["game_id", "team"]).air_yd.transform("sum")
  led["team_rush_i10"] = led.groupby(["game_id", "team"]).carries_i10.transform("sum")  # designed runs inside the 10
  if routes is not None and len(routes):
    led = led.merge(routes[["season", "week", "gsis_id", "dropbacks_on_field"]], on=["season", "week", "gsis_id"],
                    how="left")
  else:
    led["dropbacks_on_field"] = np.nan
  if exclusions is not None and len(exclusions):
    ex = exclusions.assign(excluded=True)[["gsis_id", "season", "week", "excluded"]]
    led = led.merge(ex, on=["gsis_id", "season", "week"], how="left")
    led["excluded"] = led.excluded.fillna(False).astype(bool)
  else:
    led["excluded"] = False
  return led.dropna(subset=["team_db"]).reset_index(drop=True)


# ----------------------------------------------------------------------------------------------------------------
# Player model
# ----------------------------------------------------------------------------------------------------------------

@dataclass
class Prior:
  mu: dict  # (opp, group, tier) -> {component: rate}
  mu_pos: dict  # (opp, group) -> {component: rate}
  k: dict  # (opp, group, component) -> pseudo-opportunities


class PlayerModel:
  def __init__(self, data, tm, team_ledger: pd.DataFrame, cfg: dict, scoring):
    self.data, self.tm, self.cfg, self.scoring = data, tm, cfg, scoring
    self.pcfg = cfg["player_model"]
    self.exp = cfg.get("experiments", {})
    self.team_ledger = team_ledger
    self.info = self._player_info()

  def __getstate__(self):
    state = dict(self.__dict__)
    state.pop("_feat_cache", None)  # a per-run memo (~100 MB); never pickled into the model cache
    return state

  # -- static player info ----------------------------------------------------------------------------------------
  def _player_info(self) -> pd.DataFrame:
    r = self.data.rosters.dropna(subset=["gsis_id"]).sort_values(["season", "week"])
    info = r.drop_duplicates("gsis_id", keep="last").set_index("gsis_id")[["full_name", "position", "team"]]
    info["position"] = info.position.replace({"FB": "RB", "HB": "RB"})
    dr = self.data.draft
    if dr is not None:
      dr = dr.dropna(subset=["gsis_id"]).drop_duplicates("gsis_id").set_index("gsis_id")
      info["draft_round"] = dr["round"].reindex(info.index)
      info["draft_pick"] = dr["pick"].reindex(info.index)
    picks = self.pcfg.get("draft_tier_picks")  # e.g. [16, 32, 64, 100]: tiers by overall pick, else by round
    if picks and "draft_pick" in info:
      edges = sorted(int(x) for x in picks)
      def by_pick(pk):
        if pd.isna(pk):
          return "UDFA"
        lo = 0
        for e in edges:
          if pk <= e:
            return f"P{lo + 1}-{e}"
          lo = e
        return f"P{lo + 1}+"
      info["tier"] = info.draft_pick.map(by_pick)
    else:
      info["tier"] = info.get("draft_round", pd.Series(np.nan, index=info.index)).map(draft_tier)
    return info

  # -- setup -----------------------------------------------------------------------------------------------------
  def prepare(self, train_seasons: list[int]):
    """Fit xTD + build the player-game ledger. xTD is fit on train seasons only (no test leakage)."""
    pbp = self.data.pbp
    self._feat_cache = {}
    self.xtd = XTD().fit(pbp[pbp.season.isin(train_seasons)])
    self.ledger = build_ledger(pbp, self.xtd, self.team_ledger, self.data.snaps, self.data.routes,
                               self.data.exclusions)
    pos = self.info.position.reindex(self.ledger.gsis_id).to_numpy()
    self.ledger["pos"] = pos
    self.ledger["tier"] = self.info.tier.reindex(self.ledger.gsis_id).fillna("UDFA").to_numpy()
    self.ledger = self.ledger[self.ledger.pos.isin(["QB", "RB", "WR", "TE"])].reset_index(drop=True)
    return self

  def fit_priors(self, seasons: list[int]):
    """Empirical-Bayes priors per (opportunity type, position group, draft tier) and prior strength k per
    component estimated by method of moments (k = within-player variance / between-player variance)."""
    L = self.ledger[self.ledger.season.isin(seasons) & ~self.ledger.excluded]
    self._feat_cache = {}  # features depend on the priors
    mu, mu_pos, k = {}, {}, {}
    for opp, (_, unit, comps) in OPP_TYPES.items():
      d = L[L[opp] > 0].copy()
      d["grp"] = pos_group(opp, d.pos).to_numpy()
      d = self._with_adj_epa_season(d, opp, unit)
      for grp, g in d.groupby("grp"):
        cols = comps + [f"{opp}_adj"]
        tot = g[cols].sum() / g[opp].sum()
        mu_pos[(opp, grp)] = tot.to_dict()
        for tier, gt in g.groupby("tier"):
          if gt[opp].sum() >= 300:
            mu[(opp, grp, tier)] = (gt[cols].sum() / gt[opp].sum()).to_dict()
        ps = g.groupby(["gsis_id", "season"])
        n_i = ps[opp].sum()
        for c in cols:
          # TD features are mostly expected TDs (role), so their shrinkage is estimated on xTD, not noisy TDs.
          src = TD_COMPONENTS.get(c, c)
          rate_g = g[src] / g[opp]
          mean_i = (ps[src].sum() / n_i)
          dev = g[opp] * (rate_g - mean_i.reindex(pd.MultiIndex.from_frame(g[["gsis_id", "season"]])).to_numpy()) ** 2
          dof = max(len(g) - len(n_i), 1)
          sigma2 = float(dev.sum() / dof)
          big = n_i >= np.percentile(n_i, 50)
          m, n = mean_i[big], n_i[big]
          grand = np.average(m, weights=n)
          var_between = np.average((m - grand) ** 2, weights=n)
          tau2 = var_between - sigma2 * np.mean(1.0 / n)
          kk = sigma2 / tau2 if tau2 > 0 else 2000.0
          k[(opp, grp, c)] = float(np.clip(kk, 5.0, 2000.0))
    self.prior = Prior(mu, mu_pos, k)
    self._fit_minor_priors(L)
    return self.prior

  # Fixed defaults (mean, strength in pseudo-opportunities) for the small rates; minor_priors = "fitted" replaces
  # them with method-of-moments estimates from the training seasons.
  MINOR_DEFAULTS = {"scr_rate": (0.04, 40.0), "fum_rate": (0.005, 150.0), "adot": (7.0, 30.0), "tprr": (0.17, 60.0)}

  def _fit_minor_priors(self, L: pd.DataFrame):
    self.minor_prior = dict(self.MINOR_DEFAULTS)
    # Starting QB's share of team dropbacks: measured (the top QB's share in each team-game, injuries included).
    qb = L[L.pos == "QB"]
    top = qb.groupby(["game_id", "team"]).db.max() / qb.groupby(["game_id", "team"]).team_db.first()
    self.starter_db_share = (float(top.mean()) if self.pcfg.get("starter_share") == "fitted" and len(top)
                             else float(self.pcfg.get("starter_db_share", 0.96)))
    if self.pcfg.get("minor_priors", "fixed") != "fitted":
      return
    touches = L.db + L.rush + L.reception
    specs = {"scr_rate": (L[L.pos == "QB"], "scrambles", "db"),
             "fum_rate": (L.assign(touch=touches), "fumble_lost", "touch"),
             "adot": (L[L.pos.isin(["WR", "TE", "RB"])], "air_yd", "tgt"),
             "tprr": (L[L.dropbacks_on_field > 0], "tgt", "dropbacks_on_field")}
    for name, (g, num, den) in specs.items():
      est = mom_prior(g, num, den)
      if est is not None:
        self.minor_prior[name] = est

  def _with_adj_epa_season(self, d: pd.DataFrame, opp: str, unit: str) -> pd.DataFrame:
    """Adjusted EPA sum using end-of-season defensive ratings (for prior estimation only)."""
    d = d.copy()
    d[f"{opp}_adj"] = 0.0
    for s in d.season.unique():
      r = self.tm.fit(int(s), 19)
      m = d.season == s
      d.loc[m, f"{opp}_adj"] = d.loc[m, f"{opp}_epa"] - d.loc[m, opp] * d.loc[m, "opp"].map(r.dfn[unit]).fillna(0)
    return d

  # -- as-of features --------------------------------------------------------------------------------------------
  def features(self, season: int, week: int, ratings) -> pd.DataFrame:
    """As-of player features. Training asks for the same (season, week) several times (meta-model rows, injury
    absorption, blend/range projections), always with the team model's cached ratings for that week, so those
    calls are memoized; any other ratings object is computed fresh."""
    cache = self.__dict__.setdefault("_feat_cache", {})
    key = (season, week, id(ratings))
    hit = cache.get(key)
    if hit is not None and hit[0] is ratings:
      return hit[1].copy()
    f = self._features(season, week, ratings)
    cache[key] = (ratings, f)
    return f.copy()

  def _features(self, season: int, week: int, ratings) -> pd.DataFrame:
    L = self.ledger
    L = L[(L.season < season) | (L.week < week)]
    L = L[(L.season >= season - 2) & ~L.excluded]
    # Usage weights: recency within season + decaying prior season (as team model, but share half-life).
    # Share half-life: one number, or per position ({QB = .., RB = .., ...}; missing positions use "default").
    hl = self.pcfg["share_half_life_weeks"]
    if isinstance(hl, dict):
      pos = L.pos.fillna("WR").to_numpy()
      w_use = np.zeros(len(L))
      for h in set(hl.values()) | {hl.get("default", 3.0)}:
        m = np.array([hl.get(x, hl.get("default", 3.0)) == h for x in pos])
        if m.any():
          w_use[m] = asof_weights(L.season, L.week, season, week, self.cfg, h)[m]
    else:
      w_use = asof_weights(L.season, L.week, season, week, self.cfg, hl)
    # Efficiency weights: flat by season age.
    w_eff = np.select([L.season == season, L.season == season - 1, L.season == season - 2],
                      list(self.pcfg.get("eff_season_weights", EFF_SEASON_WEIGHTS)), 0.0)
    L = L.assign(w_use=w_use, w_eff=w_eff)
    # Players are factorized once and every weighted sum is one bincount (this runs ~40 sums per week, every week
    # of every backtest; a pandas groupby per sum re-factorized the ids each time and dominated training time).
    codes, ids = pd.factorize(L.gsis_id)
    ids = pd.Index(ids, name="gsis_id")
    f = pd.DataFrame(index=ids)

    def wsum(col, wcol):
      v = np.nan_to_num(L[col].to_numpy(float) * L[wcol].to_numpy(float))  # NaN counts as 0, as groupby.sum did
      return pd.Series(np.bincount(codes, weights=v, minlength=len(ids)), index=ids)

    # Usage shares (games played only; exclusions removed).
    for name, num, den in (("db_share", "db", "team_db"), ("carry_share", "carries", "team_rush"),
                           ("tgt_share", "tgt", "team_db"), ("route_share", "dropbacks_on_field", "team_db"),
                           ("ay_share", "air_yd", "team_ay"), ("i10_share", "carries_i10", "team_rush_i10")):
      f[name] = wsum(num, "w_use") / wsum(den, "w_use").replace(0, np.nan)
      f[name + "_long"] = wsum(num, "w_eff") / wsum(den, "w_eff").replace(0, np.nan)
    # Goal-line role (experiments.gl_struct): his share of the team's inside-10 carries relative to his overall carry
    # share, shrunk toward 1 (no special role) with GL_RATIO_K pseudo team goal-line carries, so a couple of
    # goal-line totes don't make a "vulture". Capped to keep a tiny overall share from exploding the ratio.
    gl_n = wsum("team_rush_i10", "w_use")
    cs = f["carry_share"].fillna(0.0)
    sh = (wsum("carries_i10", "w_use") + GL_RATIO_K * cs) / (gl_n + GL_RATIO_K)
    f["gl_ratio"] = (sh / cs.where(cs > 0)).clip(0, 4).fillna(1.0)
    # Team committee tendency (experiments.rbbc): in each team-game, the lead back's share of the RBs' designed
    # carries, averaged over the team's recent games (usage weights). ~1 = bellcow team, ~0.5 = even committee.
    rb = L[(L.pos == "RB") & (L.carries > 0)]
    if len(rb):
      g = rb.groupby(["game_id", "team"]).agg(top=("carries", "max"), tot=("carries", "sum"), w=("w_use", "max"))
      g = g[(g.tot > 0) & (g.w > 0)]
      conc = (g.top / g.tot * g.w).groupby(level="team").sum() / g.w.groupby(level="team").sum()
      f.attrs["team_conc"] = conc.to_dict()
    f["games"] = np.bincount(codes, weights=(L.season == season).to_numpy(float), minlength=len(ids))
    last = L.sort_values(["season", "week"]).groupby("gsis_id").tail(1).set_index("gsis_id")
    f["last_team"] = last.team
    f["last_season"] = last.season
    f["pos"] = self.info.position.reindex(f.index)
    f["tier"] = self.info.tier.reindex(f.index).fillna("UDFA")

    # Efficiency: EB-shrunk component rates + opponent-adjusted EPA per opportunity.
    for opp, (_, unit, comps) in OPP_TYPES.items():
      n = wsum(opp, "w_eff")
      f[f"n_{opp}"] = n
      grp = pos_group(opp, f.pos.fillna("WR"))
      L_adj = L[f"{opp}_epa"] - L[opp] * L.opp.map(ratings.dfn[unit]).fillna(0)
      adj_sum = pd.Series(np.bincount(codes, weights=np.nan_to_num((L_adj * L.w_eff).to_numpy(float)),
                                      minlength=len(ids)), index=ids)
      # Prior means / strengths depend only on (position group, draft tier): look each pair up once.
      pair = pd.Series(list(zip(grp, f.tier)), index=f.index)
      lam = n / (n + self.pcfg["td_blend_k"])
      for c in comps + [f"{opp}_adj"]:
        if c in TD_COMPONENTS:
          xs, ts = wsum(TD_COMPONENTS[c], "w_eff"), wsum(c, "w_eff")
          obs = xs + lam * (ts - xs)  # expected TDs blended toward actual
        elif c == f"{opp}_adj":
          obs = adj_sum
        else:
          obs = wsum(c, "w_eff")
        mu = pair.map({pt: self._mu(opp, pt[0], pt[1], c) for pt in set(pair)}).to_numpy(float)
        kk = grp.map({gp: self.prior.k.get((opp, gp, c), 100.0) for gp in set(grp)}).to_numpy(float)
        f[f"{c}_per_{opp}"] = (obs.reindex(f.index).fillna(0) + kk * mu) / (n.reindex(f.index).fillna(0) + kk)
    # Scramble rate per dropback and fumbles per touch (shrunk toward position means).
    # Prior (mean, strength) for each: fitted by method of moments on the training seasons when
    # minor_priors = "fitted", else the fixed defaults below.
    mp = self.minor_prior
    n_db = wsum("db", "w_eff")
    m, k = mp["scr_rate"]
    f["scr_rate"] = (wsum("scrambles", "w_eff") + k * m) / (n_db + k)
    # Fumbles lost per touch, where QB dropbacks count as touches (sack fumbles are most QB fumbles).
    touches = wsum("db", "w_eff") + wsum("rush", "w_eff") + wsum("reception", "w_eff")
    m, k = mp["fum_rate"]
    f["fum_rate"] = (wsum("fumble_lost", "w_eff") + k * m) / (touches + k)
    m, k = mp["adot"]
    f["adot"] = (wsum("air_yd", "w_eff") + k * m) / (wsum("tgt", "w_eff") + k)
    has_pct = L.offense_pct.notna().to_numpy(float)
    snap_num = np.bincount(codes, weights=np.nan_to_num(L.offense_pct.to_numpy(float)) * L.w_use.to_numpy(float),
                           minlength=len(ids))
    snap_den = np.bincount(codes, weights=L.w_use.to_numpy(float) * has_pct, minlength=len(ids))
    f["snap_pct"] = pd.Series(snap_num, index=ids) / pd.Series(snap_den, index=ids).replace(0, np.nan)
    tprr_den = wsum("dropbacks_on_field", "w_eff")
    m, k = mp["tprr"]
    f["tprr"] = (wsum("tgt", "w_eff") + k * m) / (tprr_den.replace(0, np.nan) + k)
    return f

  def _mu(self, opp, grp, tier, comp):
    m = self.prior.mu.get((opp, grp, tier)) or self.prior.mu_pos.get((opp, grp)) or {}
    return m.get(comp, 0.0)

  # -- meta-model training ---------------------------------------------------------------------------------------
  def training_rows(self, seasons: list[int], positions) -> pd.DataFrame:
    rows = []
    for s in seasons:
      for wk in sorted(self.ledger[self.ledger.season == s].week.unique()):
        r = self.tm.fit(s, wk)
        f = self.features(s, wk, r)
        act = self.ledger[(self.ledger.season == s) & (self.ledger.week == wk) & ~self.ledger.excluded]
        act = act[act.pos.isin(positions)]
        j = act.join(f.drop(columns=["pos", "tier"]), on="gsis_id", how="inner")
        add_rb_inputs(j, f.attrs.get("team_conc"))
        j = j.merge(self.team_ledger[["game_id", "team", "total_line", "spread_team", "qb"]],
                    on=["game_id", "team"], how="left")
        j["def_pass"] = j.opp.map(r.dfn["pass"])
        j["def_rush"] = j.opp.map(r.dfn["rush"])
        # Supporting-cast passing offense includes the quarterback who actually started that game.
        j["off_pass"] = j.team.map(r.off["pass"]) + np.array([r.qb_term(q) for q in j.qb])
        j["off_rush"] = j.team.map(r.off["rush"])
        j["implied_pts"] = j.total_line / 2 + j.spread_team / 2
        for sh in ("db_share", "carry_share", "tgt_share"):
          j[f"{sh}_x_spread"] = j[sh].fillna(0) * j.spread_team.fillna(0)
        j["spread_team"] = j.spread_team.fillna(0)
        j["wind"] = j.wind.fillna(0.0).where(~j.indoor.fillna(False).astype(bool), 0.0)
        j["wind_sq"] = j.wind ** 2
        rows.append(j)
    return pd.concat(rows, ignore_index=True)

  def fit_meta(self, train: pd.DataFrame):
    """Share calibration + per-component efficiency regressions, fit on as-of features vs realized games."""
    t = train.copy()
    self.share_models = {}
    for share, num, den, groups in (("db_share", "db", "team_db", ["QB"]),
                                    ("carry_share", "carries", "team_rush", ["QB", "RB", "WR", "TE"]),
                                    ("tgt_share", "tgt", "team_db", ["RB", "WR", "TE"])):
      t[f"y_{share}"] = t[num] / t[den].replace(0, np.nan)
      for gp in groups:
        d = t[(t.pos == gp) & t[share].notna()]
        if len(d) > 50:
          self.share_models[(share, gp)] = Linear.fit(d, f"y_{share}", SHARE_FEATURES(share, self.exp), weight=den,
                                                      name=f"{share}/{gp}")
    # Team goal-line volume (used by experiments.gl_struct): share of a team's designed rushes that come inside the
    # 10, from its implied points and run-offense rating, one row per team-game of the training seasons.
    tg = t.drop_duplicates(["game_id", "team"])
    tg = tg[tg.team_rush > 0].assign(y_gl=lambda d: d.team_rush_i10 / d.team_rush)
    self.gl_team_model = Linear.fit(tg, "y_gl", ["implied_pts", "off_rush"], weight="team_rush", name="team_gl_frac")
    self.add_gl_frac(t)
    self.eff_models = {}
    for opp, (_, unit, comps) in OPP_TYPES.items():
      d0 = t[t[opp] > 0].copy()
      d0["grp"] = pos_group(opp, d0.pos).to_numpy()
      for gp, d in d0.groupby("grp"):
        if d[opp].sum() < 500:
          continue
        for c in comps:
          d = d.assign(**{f"y_{c}": d[c] / d[opp]})
          self.eff_models[(opp, gp, c)] = Linear.fit(
            d, f"y_{c}", EFF_FEATURES(c, opp, unit, self.exp), weight=opp,
            name=f"{c}/{opp}/{gp}")
    return self

  def add_gl_frac(self, d: pd.DataFrame) -> pd.DataFrame:
    """gl_frac (in place): expected share of the player's carries inside the 10 = team's expected inside-10
    fraction x his goal-line ratio. Missing inputs fall back to league-typical values."""
    mod = getattr(self, "gl_team_model", None)
    team = pd.Series(GL_TEAM_DEFAULT, index=d.index)
    if mod is not None and {"implied_pts", "off_rush"} <= set(d.columns):
      team = pd.Series(mod.predict(d.assign(implied_pts=d.implied_pts.fillna(d.implied_pts.mean()),
                                            off_rush=d.off_rush.fillna(0.0))), index=d.index)
    team = team.fillna(GL_TEAM_DEFAULT).clip(0.0, 0.5)
    ratio = d.gl_ratio.fillna(1.0) if "gl_ratio" in d else 1.0
    d["gl_frac"] = (team * ratio).clip(0.0, 1.0)
    return d

  # -- projection ------------------------------------------------------------------------------------------------
  def project(self, f: pd.DataFrame, cands: pd.DataFrame, team_preds: pd.DataFrame, ratings,
              wind: pd.Series | None = None) -> pd.DataFrame:
    """cands: gsis_id, team, pos (players to project). team_preds: GameModel.predict output (team rows).
    Returns one row per candidate with projected opportunities, stats, and fantasy points."""
    p = cands.join(f.drop(columns=["pos"], errors="ignore"), on="gsis_id", how="left")
    tp = team_preds.set_index("team")
    p["opp"] = p.team.map(tp.opp)
    p["home"] = p.team.map(tp.home)
    p["game_id"] = p.team.map(tp.game_id)
    p["team_db"] = p.team.map(tp.dropbacks_hat)
    p["team_rush"] = p.team.map(tp.rushes_hat)
    p["def_pass"] = p.opp.map(ratings.dfn["pass"])
    p["def_rush"] = p.opp.map(ratings.dfn["rush"])
    p["off_pass"] = p.team.map(ratings.off["pass"])
    p["off_rush"] = p.team.map(ratings.off["rush"])
    implied = tp.total_line / 2 + tp.spread_team / 2
    p["implied_pts"] = p.team.map(implied.fillna(tp.points_hat))
    p["spread_team"] = p.team.map(tp.spread_team).fillna(0.0)
    p["snap_pct"] = p.snap_pct.fillna(0.0) if "snap_pct" in p else 0.0
    p["adot"] = p.adot.fillna(7.0) if "adot" in p else 7.0
    p["wind"] = p.game_id.map(wind).fillna(0.0) if wind is not None else 0.0
    p["tier"] = p.tier.fillna(pd.Series(self.info.tier.reindex(p.gsis_id).fillna("UDFA").to_numpy(),
                                        index=p.index))
    self._fill_rate_priors(p)
    add_rb_inputs(p, f.attrs.get("team_conc"))

    self.share_hats(p)
    self._qb_starters(p)
    # Pass offense = team (ex-QB) + the projected starter's QB effect; the injury module swaps in the backup.
    p["off_pass_base"] = p.off_pass
    p["qb_term"] = [ratings.qb_term(g) if pos == "QB" else np.nan for g, pos in zip(p.gsis_id, p.pos)]
    starter = p[p.pos == "QB"].sort_values("db_share_hat").groupby("team").tail(1).set_index("team").qb_term
    p["off_pass"] = p.off_pass_base + p.team.map(starter).fillna(0.0)
    p["db"] = p.db_share_hat * p.team_db
    p["carries"] = p.carry_share_hat * p.team_rush
    p["rush"] = p.carries + p.db * p.scr_rate.fillna(0.04) * (p.pos == "QB")
    p["tgt"] = p.tgt_share_hat * p.team_db
    self.add_gl_frac(p)
    return self.stats_from_volume(p, wind)

  def share_hats(self, p: pd.DataFrame) -> pd.DataFrame:
    """Calibrated next-game usage shares (in place). Players with no history in a role get 0."""
    for c in [c for c in p.columns if c.endswith(("_share", "_share_long"))] + ["snap_pct"]:
      if c in p:
        p[c] = p[c].fillna(0.0)
    # Game-script inputs (used only when experiments.spread_shares is on); no spread known = neutral script.
    if "spread_team" not in p:
      p["spread_team"] = 0.0
    for sh in ("db_share", "carry_share", "tgt_share"):
      if sh in p:
        p[f"{sh}_x_spread"] = p[sh] * p.spread_team.fillna(0.0)
    if "team_conc" not in p:  # callers that build rows themselves (injury absorption): league-typical team
      p["team_conc"] = RB_DEFAULT_CONC
    p["carry_share_x_conc"] = p.carry_share.fillna(0.0) * p.team_conc.fillna(RB_DEFAULT_CONC)
    for share, gps in (("db_share", ["QB"]), ("carry_share", ["QB", "RB", "WR", "TE"]),
                       ("tgt_share", ["RB", "WR", "TE"])):
      p[f"{share}_hat"] = 0.0
      for gp in gps:
        m = (p.pos == gp).to_numpy()
        mod = self.share_models.get((share, gp))
        if mod is not None and m.any():
          p.loc[m, f"{share}_hat"] = np.clip(mod.predict(p[m]), 0, 1)
      p.loc[p[share] <= 0, f"{share}_hat"] = 0.0
    return p

  def stats_from_volume(self, p: pd.DataFrame, wind: pd.Series | None = None, neutral: bool = False) -> pd.DataFrame:
    p = p.copy()
    windpen = 0.0
    if "wind" not in p:
      p["wind"] = 0.0
    p["wind_sq"] = p.wind.fillna(0.0) ** 2
    if wind is not None and self.exp.get("wind_mode", "fixed") == "fixed":
      w = p.game_id.map(wind).fillna(0.0)
      over = (w - self.pcfg["wind_threshold_mph"]).clip(lower=0)
      windpen = np.minimum(over * self.pcfg["wind_penalty_per_mph"], self.pcfg["wind_penalty_cap"])
    p["wind_penalty"] = windpen
    if "i10_tilt" not in p:
      p["i10_tilt"] = 0.0
    if "gl_frac" not in p:
      self.add_gl_frac(p)
    q = p.assign(def_pass=0.0, def_rush=0.0, home=0) if neutral else p
    for k in STAT_KEYS:
      p[k] = 0.0
    for opp, (_, unit, comps) in OPP_TYPES.items():
      grp = pos_group(opp, p.pos)
      for c in comps:
        rate = np.zeros(len(p))
        for gp in grp.unique():
          m = (grp == gp).to_numpy()
          mod = self.eff_models.get((opp, gp, c))
          if mod is None or not m.any():
            continue
          rate[m] = mod.predict(q[m])
        rate = np.clip(rate, 0, None)
        if unit == "pass" and c != "interception":
          rate = rate * (1 - windpen)
        p[c] = p[c] + rate * p[opp].fillna(0)
    p["fumble_lost"] = p.fum_rate.fillna(0.005) * (p.db.fillna(0) + p.rush.fillna(0) + p.reception)
    p["proj"] = self.scoring.points(p, p.pos)
    return p

  def _fill_rate_priors(self, p: pd.DataFrame):
    """Players with no history get pure prior rates (position x draft tier)."""
    for opp, (_, _, comps) in OPP_TYPES.items():
      grp = pos_group(opp, p.pos)
      for c in comps + [f"{opp}_adj"]:
        col = f"{c}_per_{opp}"
        mu = np.array([self._mu(opp, gp, t, c) for gp, t in zip(grp, p.tier)])
        p[col] = p[col].fillna(pd.Series(mu, index=p.index)) if col in p else mu
    for c, v in (("scr_rate", 0.04), ("fum_rate", 0.005), ("n_db", 0), ("n_rush", 0), ("n_tgt", 0),
                 ("games", 0)):
      p[c] = p[c].fillna(v) if c in p else v

  def _qb_starters(self, p: pd.DataFrame):
    """One starting QB per team: depth-chart QB1 (column 'depth_rank') when known, else the top share. The
    starter's dropback share is at least starter_db_share (fixed default, or measured when starter_share =
    "fitted")."""
    starter_share = getattr(self, "starter_db_share", 0.96)
    qb = p[p.pos == "QB"]
    if qb.empty:
      return
    # Vectorized: per team, lowest depth rank first (teams with no depth chart: all tied), then highest share.
    rank = qb.depth_rank if "depth_rank" in qb else pd.Series(np.nan, index=qb.index)
    team_has_rank = rank.notna().groupby(qb.team).transform("any")
    key = np.where(team_has_rank, rank.fillna(np.inf), 0.0)
    order = pd.DataFrame({"team": qb.team, "key": key, "neg": -qb.db_share_hat, "pos": np.arange(len(qb))},
                         index=qb.index).sort_values(["team", "key", "neg", "pos"], kind="stable")
    starters = order.groupby("team", sort=False).head(1).index
    is_starter = qb.index.isin(starters)
    top = np.maximum(starter_share, qb.db_share_hat.groupby(qb.team).transform("max").to_numpy())
    p.loc[qb.index, "db_share_hat"] = np.where(is_starter, top, 0.0)
    p.loc[qb.index[~is_starter], "carry_share_hat"] = 0.0


def actual_points(stats: pd.DataFrame, scoring) -> pd.DataFrame:
  """Official weekly stats -> fantasy components + points (the backtest target)."""
  s = stats.rename(columns={"player_id": "gsis_id", "passing_yards": "pass_yd", "passing_tds": "pass_td",
                            "passing_interceptions": "interception", "rushing_yards": "rush_yd",
                            "rushing_tds": "rush_td", "receptions": "reception", "receiving_yards": "rec_yd",
                            "receiving_tds": "rec_td"}).copy()
  s["fumble_lost"] = s[["sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost"]].fillna(0).sum(axis=1)
  s[STAT_KEYS] = s[STAT_KEYS].fillna(0)
  s["position"] = s.position.replace({"FB": "RB", "HB": "RB"})
  s["actual"] = scoring.points(s, s.position)
  return s
