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
  if exp.get("implied_total"):
    cols.append("implied_pts")
  if exp.get("air_yards") and comp == "rec_yd":
    cols.append("adot")
  return cols


def SHARE_FEATURES(share: str, exp: dict | None = None) -> list[str]:
  exp = exp or {}
  cols = [share, f"{share}_long"]
  if exp.get("air_yards") and share == "tgt_share":
    cols += ["ay_share", "ay_share_long"]
  if exp.get("snap_input"):
    cols.append("snap_pct")
  return cols


def pos_group(opp: str, pos: pd.Series) -> pd.Series:
  """Which efficiency-model group a player falls into for an opportunity type."""
  if opp == "db":
    return pd.Series("QB", index=pos.index)
  if opp == "rush":
    return pos.where(pos == "QB", "RB")
  return pos.where(pos != "QB", "WR")  # QB targets (trick plays) are negligible; lump with WR


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
                 rush_td=ru.rush_touchdown, rush_xtd=xtd.rush_xtd(ru))
  b = ru.groupby(base + ["gsis_id"])[["rush", "carries", "scrambles", "rush_epa", "rush_yd", "rush_td",
                                      "rush_xtd"]].sum()

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
    info["tier"] = info.get("draft_round", pd.Series(np.nan, index=info.index)).map(draft_tier)
    return info

  # -- setup -----------------------------------------------------------------------------------------------------
  def prepare(self, train_seasons: list[int]):
    """Fit xTD + build the player-game ledger. xTD is fit on train seasons only (no test leakage)."""
    pbp = self.data.pbp
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
    return self.prior

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
    L = self.ledger
    L = L[(L.season < season) | (L.week < week)]
    L = L[(L.season >= season - 2) & ~L.excluded]
    # Usage weights: recency within season + decaying prior season (as team model, but share half-life).
    w_use = asof_weights(L.season, L.week, season, week, self.cfg, self.pcfg["share_half_life_weeks"])
    # Efficiency weights: flat by season age.
    w_eff = np.select([L.season == season, L.season == season - 1, L.season == season - 2],
                      list(EFF_SEASON_WEIGHTS), 0.0)
    L = L.assign(w_use=w_use, w_eff=w_eff)
    g = L.groupby("gsis_id")
    f = pd.DataFrame(index=pd.Index(L.gsis_id.unique(), name="gsis_id"))

    def wsum(col, wcol):
      return (L[col] * L[wcol]).groupby(L.gsis_id).sum()

    # Usage shares (games played only; exclusions removed).
    for name, num, den in (("db_share", "db", "team_db"), ("carry_share", "carries", "team_rush"),
                           ("tgt_share", "tgt", "team_db"), ("route_share", "dropbacks_on_field", "team_db"),
                           ("ay_share", "air_yd", "team_ay")):
      f[name] = wsum(num, "w_use") / wsum(den, "w_use").replace(0, np.nan)
      f[name + "_long"] = wsum(num, "w_eff") / wsum(den, "w_eff").replace(0, np.nan)
    cur = L[L.season == season]
    f["games"] = cur.groupby("gsis_id").size()
    f["games"] = f.games.fillna(0)
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
      adj_sum = (L_adj * L.w_eff).groupby(L.gsis_id).sum()
      lam = n / (n + self.pcfg["td_blend_k"])
      for c in comps + [f"{opp}_adj"]:
        if c in TD_COMPONENTS:
          xs, ts = wsum(TD_COMPONENTS[c], "w_eff"), wsum(c, "w_eff")
          obs = xs + lam * (ts - xs)  # expected TDs blended toward actual
        elif c == f"{opp}_adj":
          obs = adj_sum
        else:
          obs = wsum(c, "w_eff")
        mu = np.array([self._mu(opp, gp, t, c) for gp, t in zip(grp, f.tier)])
        kk = np.array([self.prior.k.get((opp, gp, c), 100.0) for gp in grp])
        f[f"{c}_per_{opp}"] = (obs.reindex(f.index).fillna(0) + kk * mu) / (n.reindex(f.index).fillna(0) + kk)
    # Scramble rate per dropback and fumbles per touch (shrunk toward position means).
    n_db = wsum("db", "w_eff")
    f["scr_rate"] = (wsum("scrambles", "w_eff") + 40 * 0.04) / (n_db + 40)
    # Fumbles lost per touch, where QB dropbacks count as touches (sack fumbles are most QB fumbles).
    touches = wsum("db", "w_eff") + wsum("rush", "w_eff") + wsum("reception", "w_eff")
    f["fum_rate"] = (wsum("fumble_lost", "w_eff") + 150 * 0.005) / (touches + 150)
    f["adot"] = (wsum("air_yd", "w_eff") + 30 * 7.0) / (wsum("tgt", "w_eff") + 30)
    has_pct = L.offense_pct.notna()
    f["snap_pct"] = ((L.offense_pct.fillna(0) * L.w_use).groupby(L.gsis_id).sum()
                     / (L.w_use * has_pct).groupby(L.gsis_id).sum().replace(0, np.nan))
    tprr_den = wsum("dropbacks_on_field", "w_eff")
    f["tprr"] = (wsum("tgt", "w_eff") + 60 * 0.17) / (tprr_den.replace(0, np.nan) + 60)
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
        j = j.merge(self.team_ledger[["game_id", "team", "total_line", "spread_team", "qb"]],
                    on=["game_id", "team"], how="left")
        j["def_pass"] = j.opp.map(r.dfn["pass"])
        j["def_rush"] = j.opp.map(r.dfn["rush"])
        # Supporting-cast passing offense includes the quarterback who actually started that game.
        j["off_pass"] = j.team.map(r.off["pass"]) + np.array([r.qb_term(q) for q in j.qb])
        j["off_rush"] = j.team.map(r.off["rush"])
        j["implied_pts"] = j.total_line / 2 + j.spread_team / 2
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
    p["snap_pct"] = p.snap_pct.fillna(0.0) if "snap_pct" in p else 0.0
    p["adot"] = p.adot.fillna(7.0) if "adot" in p else 7.0
    p["tier"] = p.tier.fillna(pd.Series(self.info.tier.reindex(p.gsis_id).fillna("UDFA").to_numpy(),
                                        index=p.index))
    self._fill_rate_priors(p)

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
    return self.stats_from_volume(p, wind)

  def share_hats(self, p: pd.DataFrame) -> pd.DataFrame:
    """Calibrated next-game usage shares (in place). Players with no history in a role get 0."""
    for c in [c for c in p.columns if c.endswith(("_share", "_share_long"))] + ["snap_pct"]:
      if c in p:
        p[c] = p[c].fillna(0.0)
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
    if wind is not None:
      w = p.game_id.map(wind).fillna(0.0)
      over = (w - self.pcfg["wind_threshold_mph"]).clip(lower=0)
      windpen = np.minimum(over * self.pcfg["wind_penalty_per_mph"], self.pcfg["wind_penalty_cap"])
    p["wind_penalty"] = windpen
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

  @staticmethod
  def _qb_starters(p: pd.DataFrame):
    """One starting QB per team: depth-chart QB1 (column 'depth_rank') when known, else the top share."""
    qb = p[p.pos == "QB"]
    for team, g in qb.groupby("team"):
      if "depth_rank" in g and g.depth_rank.notna().any():
        starter = g.sort_values(["depth_rank", "db_share_hat"], ascending=[True, False]).index[0]
      else:
        starter = g.db_share_hat.idxmax()
      p.loc[g.index, "db_share_hat"] = np.where(g.index == starter, max(0.96, g.db_share_hat.max()), 0.0)
      p.loc[g.index[g.index != starter], "carry_share_hat"] = 0.0


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
