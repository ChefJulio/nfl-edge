"""NFL Edge grade: one number per offensive player (QB / RB / WR / TE) for player pages, data/grades.json.

NOTE (2026-10-17): the LIVE grade is output-based (MODEL.md "Edge grade"): fantasy points per game over this season
and the two before (SEASON_W), shrunk toward the qualified-player mean by measured pseudo-games, shown as a
percentile among qualified players. The EPA-value description below is the earlier v1 (kept for --eval).

Usage: python tools/grade_build.py [--site=site]      build the grades (CI, daily)
       python tools/grade_build.py --eval              walk-forward validation (the gate; prints the table)

What the grade means: the player's expected football value per game NEXT season, where value = EPA over
replacement per game (passing incl. scrambles, designed rushing, receiving; replacement = what that position's
backups produce per opportunity, add_value). It is learned, not hand-weighted: per
position, a ridge regression maps this player's recent per-play stats (each shrunk toward the position average by
its own sample size, method-of-moments strength) to what players with those stats produced the following season.
Shown as a percentile (0-99) among that position's regulars, with each stat's contribution.

Gate (pre-registered in docs/INSIGHTS.md): walk-forward 2021-2025, the grade's rank correlation with next-season
value must beat (a) last season's value per game and (b) last season's fantasy points per game, with the pooled
bootstrap CI of the difference excluding 0. If it fails, nothing is published.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config, load_scoring  # noqa: E402
from nfledge.player_model import actual_points, mom_prior  # noqa: E402

FIRST = 2018  # PFR advanced stats (yards after contact, broken tackles, drops) start here
SEASON_W = (1.0, 0.6, 0.3)  # the feature window: this season, last, two back (as the projection model's efficiency)
MIN_NEXT_GAMES = 4  # a target season counts only with this many games played
POS = ("QB", "RB", "WR", "TE")
ALPHAS = (0.3, 1.0, 3.0, 10.0, 30.0, 100.0)

# (feature, numerator, denominator) rates shrunk toward the position mean; per-game volumes use games as den
RATES = {
  "QB": [("epa_db", "qb_epa", "qb_db"), ("succ_db", "qb_succ", "qb_db"), ("cpoe", "cpo", "cpo_n"),
         ("sack_rate", "sacks", "qb_db"), ("int_rate", "ints", "att"), ("adot", "ay", "att"),
         ("db_pg", "qb_db", "games"), ("rush_epa_pg", "ru_epa", "games")],
  "RB": [("rush_epa", "ru_epa", "ru_n"), ("rush_succ", "ru_succ", "ru_n"), ("ypc", "ru_yd", "ru_n"),
         ("x10", "ru_x10", "ru_n"), ("yaco", "pfr_yaco", "pfr_car"), ("btk", "btk", "touch"),
         ("car_pg", "ru_n", "games"), ("tgt_pg", "tgt", "games"), ("rec_epa", "rec_epa", "tgt"),
         ("yacoe", "yco", "yco_n"), ("snap", "snap_pct", "games")],
  "WR": [("rec_epa", "rec_epa", "tgt"), ("rec_succ", "rec_succ", "tgt"), ("croe", "cro", "cro_n"),
         ("yacoe", "yco", "yco_n"), ("adot", "ay_t", "tgt"), ("tgt_share", "tgt", "team_tgt"),
         ("ay_share", "ay_t", "team_ay"), ("tgt_pg", "tgt", "games"), ("btk", "btk", "touch"),
         ("drop", "drops", "tgt"), ("snap", "snap_pct", "games")],
}
RATES["TE"] = RATES["WR"]
# v2 (ability, not situation; INSIGHTS pre-registration): context-neutral inputs only, no raw EPA / value. NGS rush yards
# over expected (tracking: blockers, box, defenders' positions) and separation; catch / YAC / completions over
# expected; PFR contact and broken tackles; role shares (coaches' own read of ability); QB sack / INT rates and depth.
RATES_V2 = {
  "QB": [("cpoe", "cpo", "cpo_n"), ("sack_rate", "sacks", "qb_db"), ("int_rate", "ints", "att"), ("adot", "ay", "att"),
         ("db_pg", "qb_db", "games"), ("rush_yd_pg", "ru_yd", "games")],
  "RB": [("ryoe", "ngs_ryoe", "ngs_ra"), ("yaco", "pfr_yaco", "pfr_car"), ("btk", "btk", "touch"), ("x10", "ru_x10", "ru_n"),
         ("yacoe", "yco", "yco_n"), ("croe", "cro", "cro_n"), ("car_pg", "ru_n", "games"), ("tgt_pg", "tgt", "games"),
         ("snap", "snap_pct", "games")],
  "WR": [("sep", "ngs_sep", "ngs_tg"), ("ngs_yacoe", "ngs_yaco", "ngs_rc"), ("yacoe", "yco", "yco_n"), ("croe", "cro", "cro_n"),
         ("tgt_share", "tgt", "team_tgt"), ("ay_share", "ay_t", "team_ay"), ("adot", "ay_t", "tgt"), ("drop", "drops", "tgt"),
         ("btk", "btk", "touch"), ("snap", "snap_pct", "games")],
}
RATES_V2["TE"] = RATES_V2["WR"]
# Lower-is-better rates are flipped into percentiles (99 = fewest); the card says once that high / green is good for
# every bar (owner 2026-10-15), so the labels stay plain.
LABEL = {"epa_db": "EPA / dropback", "succ_db": "Success rate", "cpoe": "CPOE", "sack_rate": "Sack rate",
         "int_rate": "INT rate", "adot": "Depth of target", "db_pg": "Dropbacks / game",
         "rush_epa_pg": "Rushing EPA / game", "rush_epa": "EPA / rush", "rush_succ": "Rush success rate", "ypc": "Yards / carry",
         "x10": "10+ yard run rate", "yaco": "Yards after contact per carry", "btk": "Broken tackles per touch", "car_pg": "Carries / game",
         "tgt_pg": "Targets / game", "rec_epa": "EPA / target", "yacoe": "YAC over expected", "snap": "Snap share",
         "rec_succ": "Target success rate", "croe": "Catch rate over expected", "tgt_share": "Target share",
         "ay_share": "Air-yards share", "drop": "Drop rate", "age": "Age", "draft": "Draft capital",
         "value": "EPA over replacement / game", "ryoe": "Rush yards over expected", "sep": "Separation",
         "ngs_yacoe": "YAC over expected (tracking)", "rush_yd_pg": "Rushing yards / game"}


def season_table(data, pfr: pd.DataFrame, scoring, ngs: pd.DataFrame | None = None, ftn: pd.DataFrame | None = None) -> pd.DataFrame:
  """One row per (gsis_id, season): summed opportunities and outcomes, regular season."""
  p = data.pbp[data.pbp.season_type == "REG"]
  p = p[(p.two_point_attempt == 0) & p.posteam.notna()]
  ep = p.epa.fillna(0.0)
  rows = []
  # QB: dropbacks credited to the passer (scrambles to the scrambler), as the projection ledger does
  db = p[p.is_dropback].assign(gsis_id=lambda d: d.passer_player_id.fillna(d.rusher_player_id))
  att = (db.pass_attempt == 1) & (db.sack == 0)
  cpn = att & db.cp.notna()
  rows.append(db.assign(qb_db=1, qb_epa=ep, qb_succ=(ep > 0).astype(int), sacks=db.sack, ints=db.interception,
                        att=att.astype(int), ay=db.air_yards.fillna(0).where(att, 0), cpo_n=cpn.astype(int),
                        cpo=(db.complete_pass - db.cp).where(cpn, 0.0))
              .groupby(["gsis_id", "season", "week"])[["qb_db", "qb_epa", "qb_succ", "sacks", "ints", "att", "ay", "cpo", "cpo_n"]].sum())
  ru = p[p.is_designed_rush & p.rusher_player_id.notna()]
  ry = ru.rushing_yards.fillna(0)
  rfl = ((ru.fumble_lost == 1) & (ru.fumbled_1_player_id == ru.rusher_player_id)).astype(int)
  rows.append(ru.assign(gsis_id=ru.rusher_player_id, ru_n=1, ru_epa=ep, ru_succ=(ep > 0).astype(int), ru_yd=ry,
                        ru_x10=(ry >= 10).astype(int), ru_fl=rfl)
              .groupby(["gsis_id", "season", "week"])[["ru_n", "ru_epa", "ru_succ", "ru_yd", "ru_x10", "ru_fl"]].sum())
  tg = p[(p.pass_attempt == 1) & (p.sack == 0) & p.receiver_player_id.notna()].copy()
  te = tg.epa.fillna(0.0)
  tg["team_tgt_g"] = tg.groupby(["game_id", "posteam"]).game_id.transform("size")
  tg["team_ay_g"] = tg.groupby(["game_id", "posteam"]).air_yards.transform(lambda s: s.fillna(0).clip(lower=0).sum())
  ok = (tg.complete_pass == 1) & tg.xyac_mean_yardage.notna() & tg.yards_after_catch.notna()
  # The receiver's part of a target (v1.1): catching more than the throw's completion probability says, valued at what
  # a catch is worth at that depth that season, plus YAC EPA over expected on catches. Incompletions and interceptions
  # cost him only as far as a typical receiver would have caught the ball: the throw is the quarterback's.
  tg["aybin"] = (tg.air_yards.fillna(0).clip(-10, 45) // 5).astype(int)
  ce = tg.groupby(["season", "aybin", "complete_pass"]).epa.mean().unstack()
  worth = (ce.get(1) - ce.get(0)).fillna(0.0)
  delta = pd.Series(list(zip(tg.season, tg.aybin)), index=tg.index).map(worth.to_dict()).fillna(0.0)
  catch = ((tg.complete_pass - tg.cp) * delta).where(tg.cp.notna(), 0.0)
  # Where FTN charted the ball as catchable or not (2022 on), that decides instead: a catch is measured against how
  # often THAT kind of ball (catchable or not, at that depth) is caught, so an off-target throw isn't on the receiver.
  # The completion probability alone knows depth and route, not ball placement (Bijan 2023 still paid for Ridder).
  if ftn is not None and len(ftn):
    idx = tg.index  # a left merge keeps row order but renumbers: restore so every Series above still lines up
    tg = tg.merge(ftn, on=["game_id", "play_id"], how="left")
    tg.index = idx
    known = tg.catchable.notna()
    rate = tg[known].groupby(["season", "aybin", "catchable"]).complete_pass.mean()
    pc = pd.Series(list(zip(tg.season, tg.aybin, tg.catchable)), index=tg.index).map(rate.to_dict())
    catch = catch.where(~known | pc.isna(), (tg.complete_pass - pc) * delta)
  yac = (tg.yac_epa - tg.xyac_epa).where((tg.complete_pass == 1) & tg.yac_epa.notna() & tg.xyac_epa.notna(), 0.0) \
    if "yac_epa" in tg and "xyac_epa" in tg else 0.0
  tg["rec_att_p"] = (catch + yac).fillna(0.0)
  # v1.2: plus what a target at that depth is worth on average (league, that season): credit for EARNING the target,
  # independent of this quarterback's accuracy (v1.1 without it lost target-earning and failed its guardrail).
  depth_worth = tg.groupby(["season", "aybin"]).epa.mean()
  tg["rec_att2_p"] = tg.rec_att_p + pd.Series(list(zip(tg.season, tg.aybin)), index=tg.index).map(depth_worth.to_dict()).fillna(0.0)
  rec = tg.assign(gsis_id=tg.receiver_player_id, tgt=1, rec_epa=te, rec_succ=(te > 0).astype(int), rec=tg.complete_pass,
                  ay_t=tg.air_yards.fillna(0).clip(lower=0), cro_n=tg.cp.notna().astype(int),
                  cro=(tg.complete_pass - tg.cp).where(tg.cp.notna(), 0.0), yco_n=ok.astype(int),
                  yco=(tg.yards_after_catch - tg.xyac_mean_yardage).where(ok, 0.0), rec_att=tg.rec_att_p, rec_att2=tg.rec_att2_p)
  # team targets / air yards over the games he was targeted in (traded players: each team's games)
  g = rec.groupby(["gsis_id", "season", "week"]).agg(team_tgt=("team_tgt_g", "first"), team_ay=("team_ay_g", "first"))
  rows.append(rec.groupby(["gsis_id", "season", "week"])[["tgt", "rec_epa", "rec_succ", "rec", "ay_t", "cro", "cro_n", "yco", "yco_n", "rec_att", "rec_att2"]].sum())
  rows.append(g)
  sn = data.snaps.dropna(subset=["gsis_id"])
  sn = sn[sn.offense_snaps > 0]
  rows.append(sn.groupby(["gsis_id", "season", "week"]).agg(games=("week", "nunique"), snap_pct=("offense_pct", "sum")))
  if pfr is not None and len(pfr):
    rows.append(pfr.groupby(["gsis_id", "season", "week"])[["pfr_car", "pfr_yaco", "btk", "drops"]].sum())
  if ngs is not None and len(ngs):
    rows.append(ngs.groupby(["gsis_id", "season", "week"])[["ngs_ryoe", "ngs_ra", "ngs_sep", "ngs_tg", "ngs_yaco", "ngs_rc"]].sum())
  t = pd.concat(rows, axis=1).fillna(0.0)
  t = t[t.games > 0]  # player-games (snaps > 0); per-game rows feed the shrinkage estimates (fit_priors)
  t["touch"] = t.ru_n + t.rec
  pts = actual_points(data.stats, scoring)
  t["fp"] = pts.groupby(["gsis_id", "season", "week"]).actual.sum().reindex(t.index).fillna(0.0)
  return t.reset_index()


def add_value(tg: pd.DataFrame, pos_of: pd.Series, rec_col: str = "rec_epa") -> pd.DataFrame:
  """value = EPA over replacement: each opportunity's EPA minus what that position's backups produce per
  opportunity that season (replacement = player-games under half the offensive snaps; measured, not set).
  Raw EPA per game punished volume (most runs lose EPA), so a workhorse back read worse than his backup."""
  tg = tg.copy()
  tg["pos"] = tg.gsis_id.map(pos_of)
  bk = tg[tg.snap_pct < 0.5]
  for epa, n, key in (("qb_epa", "qb_db", "rq"), ("ru_epa", "ru_n", "rr"), (rec_col, "tgt", "rt")):
    r = bk.groupby(["season", "pos"])[[epa, n]].sum()
    rate = (r[epa] / r[n].replace(0, np.nan)).fillna(0.0)
    tg[key] = pd.Series(list(zip(tg.season, tg.pos))).map(rate.to_dict()).fillna(0.0).to_numpy()
  tg["value"] = (tg.qb_epa - tg.qb_db * tg.rq) + (tg.ru_epa - tg.ru_n * tg.rr) + (tg[rec_col] - tg.tgt * tg.rt)
  return tg.drop(columns=["pos", "rq", "rr", "rt"])


def seasons_of(tg: pd.DataFrame) -> pd.DataFrame:
  """Player-game rows -> player-season sums."""
  return tg.drop(columns="week").groupby(["gsis_id", "season"]).sum().reset_index()


def window(t: pd.DataFrame, season: int) -> pd.DataFrame:
  """Weighted sums over season, season-1, season-2 (SEASON_W), for players who played in `season`."""
  cur = set(t[t.season == season].gsis_id)
  w = t[t.gsis_id.isin(cur) & t.season.between(season - 2, season)].copy()
  wt = w.season.map({season - i: x for i, x in enumerate(SEASON_W)})
  num = [c for c in w.columns if c not in ("gsis_id", "season")]
  w[num] = w[num].mul(wt, axis=0)
  out = w.groupby("gsis_id")[num].sum()
  out["games_now"] = t[t.season == season].set_index("gsis_id").games.reindex(out.index)
  out["season"] = season
  return out


def features(win: pd.DataFrame, pos: str, priors: dict, info: pd.DataFrame, rates=None) -> pd.DataFrame:
  f = pd.DataFrame(index=win.index)
  for name, num, den in (rates or RATES)[pos]:
    m, k = priors[(pos, name)]
    f[name] = (win[num] + k * m) / (win[den] + k)
  m, k = priors[(pos, "value")]
  f["value"] = (win.value + k * m) / (win.games + k)  # EPA over replacement / game, shrunk (k from game-to-game noise)
  age = (pd.Timestamp(f"{int(win.season.iloc[0])}-12-01") - info.birth.reindex(f.index)).dt.days / 365.25
  f["age"] = age.fillna(age.median() if age.notna().any() else 26.0)
  pick = info.draft_pick.reindex(f.index)
  f["draft"] = -np.log(pick.fillna(300.0).clip(1, 300))  # higher = earlier pick; undrafted = pick 300
  return f


def fit_priors(tg: pd.DataFrame, pos_of: pd.Series, seasons, rates=None) -> dict:
  """Shrinkage (mean, k) per (position, rate) from player-GAME rows in `seasons` (method of moments: game-to-game
  noise within player-seasons vs spread between players)."""
  out = {}
  tt = tg[tg.season.isin(seasons)].assign(pos=lambda d: d.gsis_id.map(pos_of))
  for pos in POS:
    d = tt[tt.pos == pos]
    for name, num, den in (rates or RATES)[pos]:
      if num not in d or den not in d:
        continue
      est = mom_prior(d, num, den) if len(d) else None
      if est is None:
        tot = d[den].sum()
        est = (float(d[num].sum() / tot) if tot else 0.0, 20.0)
      out[(pos, name)] = est
    out[(pos, "value")] = mom_prior(d, "value", "games") or (float(d.value.sum() / max(d.games.sum(), 1)), 5.0)
  return out


class Ridge:
  """Standardized weighted ridge; alpha by leave-one-season-out CV over ALPHAS."""

  def fit(self, X: pd.DataFrame, y: np.ndarray, w: np.ndarray, groups: np.ndarray):
    self.cols = list(X.columns)
    self.mu, self.sd = X.mean(), X.std().replace(0, 1.0)
    Z = ((X - self.mu) / self.sd).to_numpy(float)

    def solve(Z, y, w, a):
      ym = np.average(y, weights=w)
      W = w[:, None]
      beta = np.linalg.solve(Z.T @ (W * Z) + a * np.eye(Z.shape[1]), Z.T @ (w * (y - ym)))
      return ym, beta
    best = None
    for a in ALPHAS:
      err = 0.0
      for gq in np.unique(groups):
        tr, te = groups != gq, groups == gq
        if tr.sum() < 30 or te.sum() < 5:
          continue
        b0, b = solve(Z[tr], y[tr], w[tr], a)
        err += float(np.sum(w[te] * (y[te] - b0 - Z[te] @ b) ** 2))
      if best is None or err < best[0]:
        best = (err, a)
    self.alpha = best[1]
    self.b0, self.beta = solve(Z, y, w, self.alpha)
    return self

  def contrib(self, X: pd.DataFrame) -> pd.DataFrame:
    """Each feature's contribution (in target units) relative to the training average."""
    return ((X[self.cols] - self.mu) / self.sd) * self.beta

  def predict(self, X: pd.DataFrame) -> np.ndarray:
    return self.b0 + self.contrib(X).sum(axis=1).to_numpy()


def pairs(t, pos_of, info, priors, seasons, rates=None, team_of=None):
  """Training rows: features at season s, target = value per game in s+1 (>= MIN_NEXT_GAMES games)."""
  out = []
  nxt = t.set_index(["gsis_id", "season"])
  for s in seasons:
    win = window(t, s)
    for pos in POS:
      w = win[win.index.map(pos_of) == pos]
      if not len(w):
        continue
      f = features(w, pos, priors, info, rates)
      key = pd.MultiIndex.from_arrays([f.index, np.full(len(f), s + 1)])
      g1 = nxt.games.reindex(key).to_numpy()
      f = f.assign(pos=pos, s=s, games_now=w.games_now.to_numpy(),
                   y=nxt.value.reindex(key).to_numpy() / g1, g1=g1,
                   fp_next=nxt.fp.reindex(key).to_numpy() / g1,
                   fp_now=t[t.season == s].set_index("gsis_id").fp.reindex(f.index).to_numpy() / w.games_now.to_numpy(),
                   v_now=t[t.season == s].set_index("gsis_id").value.reindex(f.index).to_numpy() / w.games_now.to_numpy(),
                   tm_now=[(team_of or {}).get((g, s)) for g in f.index], tm_next=[(team_of or {}).get((g, s + 1)) for g in f.index])
      out.append(f)
  return pd.concat(out)


def load(cfg):
  import nflreadpy as nfl
  c = json.loads(json.dumps(cfg))
  cur = int(nfl.get_current_season())
  c["data"]["history_seasons"] = cur - FIRST
  data = D.load_all(c)
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  players = cache.get("players", "all", lambda: nfl.load_players(), stale=False)
  ppid = players.dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates("pfr_id").set_index("pfr_id").gsis_id
  fr = []
  for s in range(FIRST, cur + 1):
    st = lambda: nfl.load_pfr_advstats([s], stat_type="rush", summary_level="week")  # noqa: E731
    r = cache.get("pfrrush", s, st, stale=s == cur and cache.age_hours("pfrrush", s) > 12)
    st2 = lambda: nfl.load_pfr_advstats([s], stat_type="rec", summary_level="week")  # noqa: E731
    q = cache.get("pfrrec", s, st2, stale=s == cur and cache.age_hours("pfrrec", s) > 12)
    if r is not None and len(r):
      r = r[r.game_type == "REG"]
      fr.append(pd.DataFrame({"pfr": r.pfr_player_id, "season": r.season, "week": r.week, "pfr_car": r.carries.fillna(0),
                              "pfr_yaco": r.rushing_yards_after_contact.fillna(0),
                              "btk": r.rushing_broken_tackles.fillna(0), "drops": 0.0}))
    if q is not None and len(q):
      q = q[q.game_type == "REG"]
      fr.append(pd.DataFrame({"pfr": q.pfr_player_id, "season": q.season, "week": q.week, "pfr_car": 0.0, "pfr_yaco": 0.0,
                              "btk": q.receiving_broken_tackles.fillna(0), "drops": q.receiving_drop.fillna(0)}))
  ng = []
  for s in range(2016, cur + 1):
    for st, name in (("rushing", "ngsrush"), ("receiving", "ngsrec")):
      f = cache.get(name, s, lambda: nfl.load_nextgen_stats(seasons=[s], stat_type=st),
                    stale=s == cur and cache.age_hours(name, s) > 12)
      if f is None or not len(f):
        continue
      f = f[(f.week > 0) & (f.season_type == "REG")]
      if st == "rushing":
        ok = f.rush_yards_over_expected.notna()
        ng.append(pd.DataFrame({"gsis_id": f.player_gsis_id, "season": f.season, "week": f.week,
                                "ngs_ryoe": f.rush_yards_over_expected.fillna(0), "ngs_ra": f.rush_attempts.where(ok, 0)}))
      else:
        ng.append(pd.DataFrame({"gsis_id": f.player_gsis_id, "season": f.season, "week": f.week,
                                "ngs_sep": (f.avg_separation * f.targets).fillna(0), "ngs_tg": f.targets.where(f.avg_separation.notna(), 0),
                                "ngs_yaco": (f.avg_yac_above_expectation * f.receptions).fillna(0),
                                "ngs_rc": f.receptions.where(f.avg_yac_above_expectation.notna(), 0)}))
  ngs = pd.concat(ng, ignore_index=True).fillna(0.0) if ng else None
  # season-level rush yards over expected (NGS week 0 = the season; its own qualifying minimum, close to ours)
  ys = []
  for s in range(2018, cur + 1):
    f = cache.get("ngsrush", s, lambda: None, stale=False)
    if f is not None and len(f):
      f = f[(f.week == 0) & f.rush_yards_over_expected.notna()]
      ys.append(pd.DataFrame({"gsis_id": f.player_gsis_id, "season": f.season, "ryoe_s": f.rush_yards_over_expected,
                              "ryoe_att": f.rush_attempts}))
  ryoe = pd.concat(ys, ignore_index=True).groupby(["gsis_id", "season"]).sum() if ys else None
  pfr = pd.concat(fr, ignore_index=True)
  pfr["gsis_id"] = pfr.pfr.map(ppid)
  pfr = pfr.dropna(subset=["gsis_id"])
  pl = players.dropna(subset=["gsis_id"]).drop_duplicates("gsis_id").set_index("gsis_id")
  info = pd.DataFrame({"birth": pd.to_datetime(pl.get("birth_date"), errors="coerce"),
                       "draft_pick": pd.to_numeric(pl.get("draft_pick"), errors="coerce"),
                       "name": pl.get("display_name")})
  ro = data.rosters.dropna(subset=["gsis_id"]).sort_values(["season", "week"])
  pos_of = ro.drop_duplicates("gsis_id", keep="last").set_index("gsis_id").position.replace({"FB": "RB", "HB": "RB"})
  sn = data.snaps.dropna(subset=["gsis_id"])
  sn = sn[sn.offense_snaps > 0]
  main = sn.groupby(["gsis_id", "season"]).team.agg(lambda x: x.value_counts().index[0])
  team_of = {k: D.RELOCATED.get(v, v) for k, v in main.items()}
  # league rushing context per season: EPA per rushing yard (slope over designed runs) and a lost fumble's EPA
  pb = data.pbp[(data.pbp.season_type == "REG") & data.pbp.is_designed_rush & data.pbp.epa.notna()]
  rush_ctx = {}
  for s, g in pb.groupby("season"):
    yd = g.rushing_yards.fillna(0)
    slope = float(np.cov(yd, g.epa)[0, 1] / max(yd.var(), 1e-9))
    fl = g[g.fumble_lost == 1]
    rush_ctx[int(s)] = (slope, float(fl.epa.mean()) if len(fl) else -4.0, float(len(fl) / len(g)))
  data.ryoe, data.rush_ctx = ryoe, rush_ctx
  # FTN charting (2022 on): was each target catchable
  fl = []
  for s in range(2022, cur + 1):
    f = cache.get("ftn", s, lambda: nfl.load_ftn_charting([s]), stale=s == cur and cache.age_hours("ftn", s) > 12)
    if f is not None and len(f):
      fl.append(pd.DataFrame({"game_id": f.nflverse_game_id, "play_id": pd.to_numeric(f.nflverse_play_id, errors="coerce"),
                              "catchable": f.is_catchable_ball.astype(float)}))
  data.ftn = pd.concat(fl, ignore_index=True).dropna(subset=["play_id"]).drop_duplicates(["game_id", "play_id"]) if fl else None
  return data, pfr, info, pos_of, cur, ngs, team_of


def evaluate(tg, pos_of, info, cur):
  """Walk-forward: for target season T, priors + model use only seasons before T."""
  res = []
  t = seasons_of(tg)
  for T in range(2021, cur):
    pri = fit_priors(tg, pos_of, range(FIRST, T))
    tr = pairs(t, pos_of, info, pri, range(FIRST + 1, T - 1))
    te = pairs(t, pos_of, info, pri, [T - 1])
    for pos in POS:
      a, b = tr[(tr.pos == pos) & (tr.g1 >= MIN_NEXT_GAMES)], te[(te.pos == pos) & (te.g1 >= MIN_NEXT_GAMES) & (te.games_now >= 6)]
      cols = [n for n, _, _ in RATES[pos]] + ["value", "age", "draft"]
      m = Ridge().fit(a[cols], a.y.to_numpy(), np.minimum(a.g1, 17).to_numpy(float), a.s.to_numpy())
      res.append(b.assign(grade=m.predict(b[cols]), T=T))
  return pd.concat(res)


def evaluate_v2(tg, pos_of, info, cur, team_of):
  """Walk-forward v2 (RATES_V2 ridge) vs v1 (shrunk value / game, the live grade) on the same rows."""
  res = []
  t = seasons_of(tg)
  both = {p: RATES[p] + [x for x in RATES_V2[p] if x[0] not in {n for n, _, _ in RATES[p]}] for p in POS}
  for T in range(2021, cur):
    pri = fit_priors(tg, pos_of, range(FIRST, T), both)
    tr = pairs(t, pos_of, info, pri, range(FIRST + 1, T - 1), RATES_V2, team_of)
    te = pairs(t, pos_of, info, pri, [T - 1], RATES_V2, team_of)
    for pos in POS:
      a = tr[(tr.pos == pos) & (tr.g1 >= MIN_NEXT_GAMES)]
      b = te[(te.pos == pos) & (te.g1 >= MIN_NEXT_GAMES) & (te.games_now >= 6)]
      cols = [n for n, _, _ in RATES_V2[pos]] + ["age", "draft"]
      m = Ridge().fit(a[cols], a.y.to_numpy(), np.minimum(a.g1, 17).to_numpy(float), a.s.to_numpy())
      res.append(b.assign(v2=m.predict(b[cols]), v1=b.value, T=T, alpha=m.alpha))
  return pd.concat(res)


def report_v2(r, label):
  rng = np.random.default_rng(11)
  groups = {k: g for k, g in r.groupby(["T", "pos"]) if len(g) >= 5}
  def mean_corr(col, tgt, gs):
    return float(np.mean([spearmanr(g[col], g[tgt])[0] for g in gs.values()]))
  print(f"\n{label}: n={len(r)}  (rank corr., mean over season x position)")
  for tgt, name in (("y", "next-season value/g"), ("fp_next", "next-season fantasy pts/g")):
    c1, c2 = mean_corr("v1", tgt, groups), mean_corr("v2", tgt, groups)
    boots = []
    for _ in range(1000):
      d = []
      for g in groups.values():
        x = g.iloc[rng.integers(0, len(g), len(g))]
        d.append(spearmanr(x.v2, x[tgt])[0] - spearmanr(x.v1, x[tgt])[0])
      boots.append(np.nanmean(d))
    lo, hi = np.percentile(boots, [2.5, 97.5])
    print(f"  {name:28s} v1 {c1:.3f}  v2 {c2:.3f}  v2 - v1 {c2 - c1:+.3f} [{lo:+.3f}, {hi:+.3f}]")
  for pos in POS:
    gp = {k: g for k, g in groups.items() if k[1] == pos}
    if gp:
      print(f"    {pos}: n={sum(len(g) for g in gp.values())}  value/g v1 {mean_corr('v1', 'y', gp):.3f} v2 {mean_corr('v2', 'y', gp):.3f}")


def evaluate_v11(tg, pos_of, info, cur, opt_col="rec_att2"):
  out = []
  for col, tag in (("rec_epa", "v1"), (opt_col, "v11")):
    tv = add_value(tg, pos_of, col)
    t = seasons_of(tv)
    for T in range(2021, cur):
      pri = fit_priors(tv, pos_of, range(FIRST, T))
      te = pairs(t, pos_of, info, pri, [T - 1])
      te = te[(te.g1 >= MIN_NEXT_GAMES) & (te.games_now >= 6)]
      out.append(te[["pos", "value", "fp_next"]].assign(T=T, tag=tag).reset_index(names="gsis_id"))
  r = pd.concat(out).pivot_table(index=["gsis_id", "T", "pos", "fp_next"], columns="tag", values="value").reset_index()
  return r.rename(columns={"v1": "v1", "v11": "v2"}).assign(y=r.fp_next)


def report(r):
  rng = np.random.default_rng(7)
  print(f"{'pos':4s} {'n':>5s}  rank corr. with next-season EPA/game:  grade   last EPA/g   last FP/g    "
        f"grade - last EPA/g [95% CI]   grade - last FP/g [95% CI]   | vs next FP/g: grade  last FP/g")
  out = {}
  for pos in list(POS) + ["ALL"]:
    d = r if pos == "ALL" else r[r.pos == pos]
    def stat(x):
      by = [spearmanr(g.grade, g.y)[0] - spearmanr(g[x], g.y)[0] for _, g in x_groups(d)]
      return by
    def corr(d, col, tgt="y"):
      vals = [spearmanr(g[col], g[tgt])[0] for _, g in x_groups(d)]
      return float(np.mean(vals))
    def x_groups(d):
      return d.groupby(["T", "pos"])
    cg, cv, cf = corr(d, "grade"), corr(d, "v_now"), corr(d, "fp_now")
    boots = []
    keys = list(x_groups(d).groups)
    groups = {k: g for k, g in x_groups(d)}
    for _ in range(400):
      dv, df = [], []
      for k in keys:
        g = groups[k]
        s = g.iloc[rng.integers(0, len(g), len(g))]
        dv.append(spearmanr(s.grade, s.y)[0] - spearmanr(s.v_now, s.y)[0])
        df.append(spearmanr(s.grade, s.y)[0] - spearmanr(s.fp_now, s.y)[0])
      boots.append((np.mean(dv), np.mean(df)))
    b = np.array(boots)
    lo1, hi1 = np.percentile(b[:, 0], [2.5, 97.5])
    lo2, hi2 = np.percentile(b[:, 1], [2.5, 97.5])
    gf, ff = corr(d, "grade", "fp_next"), corr(d, "fp_now", "fp_next")
    print(f"{pos:4s} {len(d):5d}  {'':38s}{cg:.3f}   {cv:.3f}        {cf:.3f}        {cg - cv:+.3f} [{lo1:+.3f}, {hi1:+.3f}]"
          f"       {cg - cf:+.3f} [{lo2:+.3f}, {hi2:+.3f}]     |              {gf:.3f}  {ff:.3f}")
    out[pos] = (lo1 > 0 and lo2 > 0)
  return out


LOWER_BETTER = {"sack_rate", "int_rate", "drop"}
# Unqualified players with a real role (owner 2026-10-14: spot starters like Tyler Huntley, but no garbage-time
# fringe): at least SUB_GAMES games that season with SUB_SNAP of the offensive snaps or more. Graded on those games only,
# against the qualified pool (not joining it), shown with an asterisk.
SUB_GAMES, SUB_SNAP = 2, 0.5


def pct_vs(ref: pd.Series, x: pd.Series) -> pd.Series:
  """0-99 percentile of each x within the reference distribution (x not part of it; ties count half)."""
  r = np.sort(ref.dropna().to_numpy())
  if not len(r):
    return pd.Series(50, index=x.index)
  lo, hi = np.searchsorted(r, x.to_numpy(), "left"), np.searchsorted(r, x.to_numpy(), "right")
  return pd.Series(np.clip(np.round(100 * (lo + hi) / 2 / len(r)), 0, 99).astype(int), index=x.index)


def pct(v: pd.Series, w: pd.Series | None = None) -> pd.Series:
  """0-99 percentile within the group, weighted by games played when w is given: the share of the position's games
  played by players below him. Unweighted, the many shrunk 1-3 game backups pile up at the position average and any
  above-average player leaps past them (Allgeier 2024 graded 91 as a backup)."""
  if w is None:
    return (100 * (v.rank(method="average") - 0.5) / len(v)).clip(0, 99).round().astype(int)
  w = w.reindex(v.index).fillna(0).clip(lower=0)
  order = v.sort_values(kind="stable").index
  cw = w[order].cumsum() - w[order] / 2
  tot = w.sum() or 1.0
  return (100 * cw / tot).reindex(v.index).clip(0, 99).round().astype(int)


# Who gets a grade (owner 2026-10-14: compare only players with real involvement): the NFL's own qualifying minimums
# for its stat titles, per team game so they work mid-season. RBs qualify on carries or catches.
QUALIFY = {"QB": [("att", 14.0)], "RB": [("ru_n", 6.25), ("rec", 1.875)], "WR": [("rec", 1.875)], "TE": [("rec", 1.875)]}


def team_games(sched: pd.DataFrame) -> dict:
  """(team, season) -> regular-season games played (final scores)."""
  g = sched[(sched.game_type == "REG") & sched.home_score.notna()]
  out = {}
  for r in g.itertuples():
    for tm in (r.home_team, r.away_team):
      k = (D.RELOCATED.get(tm, tm), int(r.season))
      out[k] = out.get(k, 0) + 1
  return out


def rb_value(t: pd.DataFrame, pos_of: pd.Series, ryoe, rush_ctx: dict) -> pd.DataFrame:
  """RB rows of the season table re-valued (owner 2026-10-14: EPA per carry graded Saquon 2022 an 18 and backup
  Allgeier above Bijan; rushing EPA is mostly the line and play-calling). Rushing = NGS rush yards over expected
  (tracking: blockers, box, defenders) x the league's EPA per rushing yard that season, plus lost fumbles vs the
  league rate x a lost fumble's EPA; receiving = the receiver's part of each target vs the RB average. Seasons
  without an NGS row (under its minimum) keep rushing EPA vs the RB average."""
  t = t.copy()
  rb = (t.gsis_id.map(pos_of) == "RB").to_numpy()
  if ryoe is None or not rb.any():
    return t
  key = pd.MultiIndex.from_frame(t[["gsis_id", "season"]])
  ry = ryoe.ryoe_s.reindex(key).to_numpy()
  ctx = pd.DataFrame([rush_ctx.get(int(s), (0.065, -4.0, 0.006)) for s in t.season], columns=["epy", "fcost", "frate"])
  rbt = t[rb]
  avg_rush = (rbt.groupby("season").ru_epa.sum() / rbt.groupby("season").ru_n.sum()).reindex(t.season).to_numpy()
  avg_rec = (rbt.groupby("season").rec_att2.sum() / rbt.groupby("season").tgt.sum().replace(0, np.nan)).reindex(t.season).fillna(0).to_numpy()
  fum = (t.ru_fl.to_numpy() - t.ru_n.to_numpy() * ctx.frate.to_numpy()) * ctx.fcost.to_numpy()
  # no NGS row: rushing EPA vs the RB average (it already contains his fumbles); NGS row: RYOE value + fumble cost
  rush = np.where(np.isnan(ry), t.ru_epa.to_numpy() - t.ru_n.to_numpy() * avg_rush, ry * ctx.epy.to_numpy() + fum)
  rec = t.rec_att2.to_numpy() - t.tgt.to_numpy() * avg_rec
  t.loc[rb, "value"] = (rush + rec)[rb]
  return t


def build(tg, pos_of, info, cur, out: Path, sched: pd.DataFrame, team_of: dict, ryoe=None, rush_ctx=None):
  """data/grades/<season>.json for 2018..current + index.json. Grades are PER OPPORTUNITY (dropbacks + designed
  carries + targets; owner 2026-10-14: per-opportunity is fair, totals aren't) and only for players who met the NFL's
  qualifying minimum that season (QUALIFY), as percentiles among the qualified at the position:
    [0] current form: value per opportunity over that season and the two before (SEASON_W);
    [6] that season only (the by-season history: a season's grade never borrows earlier seasons).
  Both shrunk toward the position average by k pseudo-opportunities, measured (method of moments)."""
  out.mkdir(parents=True, exist_ok=True)
  tg = tg.assign(opps=tg.qb_db + tg.ru_n + tg.tgt)
  t = rb_value(seasons_of(tg), pos_of, ryoe, rush_ctx or {})
  t_sub = seasons_of(tg[tg.snap_pct >= SUB_SNAP])  # only the games where he played half the snaps or more
  pri = fit_priors(tg, pos_of, range(FIRST, cur + 1))
  tgames = team_games(sched)
  # who qualified, per season (the NFL's minimums per team game)
  qual = set()
  for s in range(FIRST, cur + 1):
    one = t[t.season == s].set_index("gsis_id")
    tgm = pd.Series([tgames.get((team_of.get((g, s)), s), np.nan) for g in one.index], index=one.index)
    pos_s = one.index.map(pos_of)
    for pos in POS:
      ok = np.zeros(len(one), bool)
      for col, rate in QUALIFY[pos]:
        ok |= (one[col] >= rate * tgm).fillna(False).to_numpy()
      qual |= {(g, s) for g in one.index[(pos_s == pos) & ok]}
  # THE RATING = OUTPUT (owner 2026-10-14: "correlate with output, not advanced-metric skill"): fantasy points per game
  # in the site's scoring (yards, TDs, catches, turnovers), shrunk toward the QUALIFIED players' average at the
  # position by k pseudo-games measured from game-to-game noise (method of moments on qualified player-games).
  qg = tg[[(g, s) in qual for g, s in zip(tg.gsis_id, tg.season)]]
  fpri = {}
  for pos in POS:
    d = qg[qg.gsis_id.map(pos_of) == pos]
    fpri[pos] = mom_prior(d, "fp", "games") or (float(d.fp.sum() / max(d.games.sum(), 1)), 3.0)
  seasons = []
  for s in range(FIRST, cur + 1):
    one = t[t.season == s].set_index("gsis_id")
    if not len(one):
      continue
    pos_s = one.index.map(pos_of)
    win = window(t, s)
    players, stats, qual_n = {}, {}, {}
    for pos in POS:
      ids = [g for g in one.index[pos_s == pos] if (g, s) in qual and g in win.index]
      if len(ids) < 5:
        continue
      qual_n[pos] = len(ids)
      w, o = win.loc[ids], one.loc[ids]
      f = features(w, pos, pri, info)
      m, k = fpri[pos]
      cur_v = (w.fp + k * m) / (w.games + k)  # current form: this season + the two before (SEASON_W)
      sea_v = (o.fp + k * m) / (o.games + k)  # that season only
      raw = o.fp / o.games
      names = [n for n, _, _ in RATES[pos]]
      stats[pos] = [LABEL[n] for n in names]
      g, sg = pct(cur_v), pct(sea_v)
      ps = {n: (99 - pct(f[n])) if n in LOWER_BETTER else pct(f[n]) for n in names}
      for gid in ids:
        players[gid] = [int(g[gid]), pos, int(w.games_now[gid]), int(round(w.games[gid])), round(float(cur_v[gid]), 1),
                        [int(ps[n][gid]) for n in names], int(sg[gid]), round(float(raw[gid]), 1), int(o.games[gid])]
      # unqualified with a real role: graded on their half-the-snaps games, against the qualified pool ([9] = 1)
      sub = t_sub[(t_sub.season == s) & (t_sub.games >= SUB_GAMES)].set_index("gsis_id")
      uq = [x for x in sub.index if pos_of.get(x) == pos and x not in players]
      if uq:
        wsub = window(t_sub, s)
        uq = [x for x in uq if x in wsub.index]
        u, uo = wsub.loc[uq], sub.loc[uq]
        fu = features(u, pos, pri, info)
        ucur = (u.fp + k * m) / (u.games + k)
        usea = (uo.fp + k * m) / (uo.games + k)
        ug, usg = pct_vs(cur_v, ucur), pct_vs(sea_v, usea)
        ups = {n: (99 - pct_vs(f[n], fu[n])) if n in LOWER_BETTER else pct_vs(f[n], fu[n]) for n in names}
        for gid in uq:
          players[gid] = [int(ug[gid]), pos, int(u.games_now[gid]), int(round(u.games[gid])), round(float(ucur[gid]), 1),
                          [int(ups[n][gid]) for n in names], int(usg[gid]), round(float(uo.fp[gid] / uo.games[gid]), 1),
                          int(uo.games[gid]), 1]
    (out / f"{s}.json").write_text(json.dumps({"season": s, "stats": stats, "qualified": qual_n, "players": players},
                                              separators=(",", ":")), encoding="utf-8")
    seasons.append(s)
    print(f"[grades] {s}: {len(players)} qualified players {qual_n}", flush=True)
  (out / "index.json").write_text(json.dumps({"seasons": seasons, "current": cur}), encoding="utf-8")



# ---- Seasons before 2018 (owner 2026-10-15: "a more crude calculation to give grades to players before 2018") ----
# The OVR is the same thing it is from 2018 on: fantasy points per game in the site's scoring, shrunk toward the
# qualified players' average at the position (method of moments, these seasons' own player-games), as a percentile
# among that season's qualified players (QUALIFY). Only the stat bars change: box-score rates from nflverse weekly
# player stats instead of play-by-play / tracking / charting. Targets are missing in nflverse 2003-2008, so those
# seasons' receiving bars use catches instead. Finished seasons never change: built once, kept in the cache.
HIST_FIRST, HIST_V = 1999, 2  # v2: spot starters (role games) graded too
HIST_RATES = {
  "QB": [("ypa", "pass_yd", "att", "Yards / attempt"), ("cmp", "cmp", "att", "Completion %"),
         ("ptd", "pass_td", "att", "TD rate"), ("int_rate", "ints", "att", "INT rate"),
         ("sack_rate", "sacks", "db", "Sack rate"), ("att_pg", "att", "games", "Attempts / game"),
         ("ryd_pg", "ru_yd", "games", "Rushing yards / game")],
  "RB": [("ypc", "ru_yd", "ru_n", "Yards / carry"), ("rtd", "ru_td", "ru_n", "Rushing TD rate"),
         ("car_pg", "ru_n", "games", "Carries / game"), ("rec_pg", "rec", "games", "Catches / game"),
         ("ypr", "rec_yd", "rec", "Yards / catch")],
  "WR": [("ypt", "rec_yd", "tgt", "Yards / target"), ("catch", "rec", "tgt", "Catch rate"),
         ("ypr", "rec_yd", "rec", "Yards / catch"), ("tgt_pg", "tgt", "games", "Targets / game"),
         ("ryd_pg", "rec_yd", "games", "Receiving yards / game"), ("rtd", "rec_td", "rec", "TD per catch")],
}
HIST_RATES["TE"] = HIST_RATES["WR"]
HIST_NO_TGT = {"ypt", "catch", "tgt_pg"}  # dropped in seasons without targets (2003-2008)
HIST_LOWER = {"int_rate", "sack_rate"}


def build_historic(out: Path, cur_first: int, sched: pd.DataFrame, scoring, cache_dir: Path) -> list[int]:
  """data/grades/<season>.json for HIST_FIRST..cur_first-1 (same record layout as build(); "basis": "box")."""
  import shutil
  import nflreadpy as nfl
  kept = cache_dir / "grades_site" / f"hist_v{HIST_V}"
  kept.mkdir(parents=True, exist_ok=True)
  seasons = list(range(HIST_FIRST, cur_first))
  todo = [x for x in seasons if not (kept / f"{x}.json").exists()]
  if todo:
    wk = nfl.load_player_stats(list(range(max(HIST_FIRST, min(todo) - 2), cur_first)), summary_level="week").to_pandas()
    wk = wk[(wk.season_type == "REG") & wk.position.isin(["QB", "RB", "FB", "HB", "WR", "TE"])]
    pts = actual_points(wk, scoring)
    g = pd.DataFrame({"gsis_id": wk.player_id, "season": wk.season, "team": wk.team.map(lambda x: D.RELOCATED.get(x, x)),
                      "pos": pts.position, "fp": pts.actual,
                      "att": wk.attempts.fillna(0), "cmp": wk.completions.fillna(0), "pass_yd": wk.passing_yards.fillna(0),
                      "pass_td": wk.passing_tds.fillna(0), "ints": wk.passing_interceptions.fillna(0),
                      "sacks": wk.sacks_suffered.fillna(0), "ru_n": wk.carries.fillna(0), "ru_yd": wk.rushing_yards.fillna(0),
                      "ru_td": wk.rushing_tds.fillna(0), "rec": wk.receptions.fillna(0), "tgt": wk.targets.fillna(0),
                      "rec_yd": wk.receiving_yards.fillna(0), "rec_td": wk.receiving_tds.fillna(0), "games": 1.0})
    g["db"] = g.att + g.sacks
    mode1 = lambda x: (lambda m: m.iloc[0] if len(m) else None)(x.dropna().mode())  # noqa: E731  (most common, if any)
    pos_of = g.groupby("gsis_id").pos.agg(mode1)  # one position per player (his usual one)
    g["pos"] = g.gsis_id.map(pos_of)
    num = ["fp", "att", "cmp", "pass_yd", "pass_td", "ints", "sacks", "db", "ru_n", "ru_yd", "ru_td", "rec", "tgt", "rec_yd",
           "rec_td", "games"]
    t = g.groupby(["gsis_id", "season"]).agg({**{c: "sum" for c in num}, "pos": "first",
                                              "team": mode1}).reset_index()
    # games with a real role (owner 2026-10-15: "2017 just missing is jarring"): the 2018+ grades use half the snaps;
    # this source has no snaps, so workload stands in: QB 10+ attempts, RB 8+ carries + catches/targets, WR / TE 3+
    # targets or 2+ catches
    role = np.select([g.pos == "QB", g.pos == "RB"], [g.att >= 10, (g.ru_n + np.maximum(g.tgt, g.rec)) >= 8],
                     (g.tgt >= 3) | (g.rec >= 2))
    tr = g[role].groupby(["gsis_id", "season"]).agg({**{c: "sum" for c in num}, "pos": "first"}).reset_index()
    tgames = team_games(sched)
    qual = set()
    for s_ in seasons:
      one = t[t.season == s_]
      tgm = pd.Series([tgames.get((tm, s_), np.nan) for tm in one.team], index=one.index)
      for pos in POS:
        ok = np.zeros(len(one), bool)
        for col, rate in QUALIFY[pos]:
          col = {"ru_n": "ru_n", "rec": "rec", "att": "att"}[col]
          ok |= (one[col] >= rate * tgm).fillna(False).to_numpy()
        qual |= {(a, s_) for a, ok_ in zip(one.gsis_id[one.pos == pos], ok[(one.pos == pos).to_numpy()]) if ok_}
    # shrinkage prior on qualified player-games (every season here, so early seasons have a stable k)
    qg = g[[(a, b) in qual for a, b in zip(g.gsis_id, g.season)]]
    fpri = {pos: mom_prior(qg[qg.pos == pos], "fp", "games") or (float(qg[qg.pos == pos].fp.mean()), 3.0) for pos in POS}
    for s_ in todo:
      one = t[t.season == s_].set_index("gsis_id")
      has_tgt = float(one.tgt.sum()) > 0
      players, stats, qual_n = {}, {}, {}
      for pos in POS:
        ids = [x for x in one.index[one.pos == pos] if (x, s_) in qual]
        if len(ids) < 5:
          continue
        qual_n[pos] = len(ids)
        o = one.loc[ids]
        # current form: this season and the two before, weighted SEASON_W (games and points alike)
        wf, wg = pd.Series(0.0, index=ids), pd.Series(0.0, index=ids)
        for lag, w in enumerate(SEASON_W):
          prev = t[t.season == s_ - lag].set_index("gsis_id").reindex(ids)
          wf, wg = wf + w * prev.fp.fillna(0), wg + w * prev.games.fillna(0)
        m, k = fpri[pos]
        cur_v, sea_v = (wf + k * m) / (wg + k), (o.fp + k * m) / (o.games + k)
        rates = [r for r in HIST_RATES[pos] if has_tgt or r[0] not in HIST_NO_TGT]
        stats[pos] = [r[3] for r in rates]
        bars = {}
        for key, nu, de, _ in rates:
          v = o[nu] / o[de].replace(0, np.nan)
          v = v.replace([np.inf, -np.inf], np.nan)
          v = v.fillna(v.median()).fillna(0.0)
          bars[key] = (99 - pct(v)) if key in HIST_LOWER else pct(v)
        gp, sg = pct(cur_v), pct(sea_v)
        for x in ids:
          players[x] = [int(gp[x]), pos, int(o.games[x]), int(round(wg[x])), round(float(cur_v[x]), 1),
                        [int(bars[r[0]][x]) for r in rates], int(sg[x]), round(float(o.fp[x] / o.games[x]), 1), int(o.games[x])]
        # under the minimum with SUB_GAMES+ role games: graded on those games against the qualified pool ([9] = 1)
        sub = tr[(tr.season == s_) & (tr.pos == pos) & (tr.games >= SUB_GAMES)].set_index("gsis_id")
        uq = [x for x in sub.index if x not in players]
        if uq:
          u = sub.loc[uq]
          uwf, uwg = pd.Series(0.0, index=uq), pd.Series(0.0, index=uq)
          for lag, w in enumerate(SEASON_W):
            prev = tr[tr.season == s_ - lag].set_index("gsis_id").reindex(uq)
            uwf, uwg = uwf + w * prev.fp.fillna(0), uwg + w * prev.games.fillna(0)
          ucur, usea = (uwf + k * m) / (uwg + k), (u.fp + k * m) / (u.games + k)
          ug, usg = pct_vs(cur_v, ucur), pct_vs(sea_v, usea)
          ub = {}
          for key, nu, de, _ in rates:
            ref = (o[nu] / o[de].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
            v = (u[nu] / u[de].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(ref.median()).fillna(0.0)
            ref = ref.fillna(ref.median()).fillna(0.0)
            ub[key] = (99 - pct_vs(ref, v)) if key in HIST_LOWER else pct_vs(ref, v)
          for x in uq:
            players[x] = [int(ug[x]), pos, int(u.games[x]), int(round(uwg[x])), round(float(ucur[x]), 1),
                          [int(ub[r[0]][x]) for r in rates], int(usg[x]), round(float(u.fp[x] / u.games[x]), 1), int(u.games[x]), 1]
      doc = {"season": s_, "basis": "box", "stats": stats, "qualified": qual_n, "players": players}
      (kept / f"{s_}.json").write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
      print(f"[grades] {s_} (box score): {len(players)} qualified players {qual_n}", flush=True)
  out.mkdir(parents=True, exist_ok=True)
  done = []
  for s_ in seasons:
    if (kept / f"{s_}.json").exists():
      shutil.copyfile(kept / f"{s_}.json", out / f"{s_}.json")
      done.append(s_)
  return done


# ---- Defenders (owner 2026-10-18: "individual defense players in our system too ... 50-99 grades") ----------------
# The same OVR as the skill grades: fantasy points per game, here IDP points under Sleeper's default IDP123
# (nfledge/report.py), shrunk toward the qualified players' average at the position (method of moments on qualified
# player-games), current form over this season and the two before (SEASON_W), as a percentile among the qualified.
# Groups: DL (DE DT NT DL), LB (LB ILB OLB MLB), DB (CB S SS FS SAF DB) by his listed position that season.
# Who qualifies: 2012 on, an average defensive snap share of DEF_QUAL or more over his team's games (the snap counts);
# before 2012 (no snap counts) games with a real role (DEF_ROLE: 2+ tackles, or a sack, interception or pass
# defended) in at least half his team's games. Spot starters (SUB_GAMES+ games at SUB_SNAP of the snaps, or role
# games before 2012) are graded on those games against the qualified pool, flagged like the skill players.
# Stat bars: box-score rates every season; pressures, coverage allowed and missed tackles from PFR (2018 on).
DEF_GROUP = {**{p: "DL" for p in "DE DT NT DL".split()}, **{p: "LB" for p in "LB ILB OLB MLB".split()},
             **{p: "DB" for p in "CB S SS FS SAF DB".split()}}
DEF_POS = ["DL", "LB", "DB"]
DEF_QUAL, DEF_SNAP_FIRST, DEF_PFR_FIRST = 0.40, 2012, 2018
DEF_BARS = {  # key, numerator, denominator, label, lower is better, needs PFR
  "DL": [("sk_pg", "sk", "games", "Sacks / game", 0, 0), ("prs_pg", "prs", "games", "Pressures / game", 0, 1),
         ("tfl_pg", "tfl", "games", "Tackles for loss / game", 0, 0), ("tk_pg", "tk_all", "games", "Tackles / game", 0, 0),
         ("mt_pct", "mt", "tk_try", "Missed tackle %", 1, 1)],
  "LB": [("tk_pg", "tk_all", "games", "Tackles / game", 0, 0), ("tfl_pg", "tfl", "games", "Tackles for loss / game", 0, 0),
         ("prs_pg", "prs", "games", "Pressures / game", 0, 1), ("ypt", "cyd", "ctgt", "Yards / target allowed", 1, 1),
         ("mt_pct", "mt", "tk_try", "Missed tackle %", 1, 1)],
  "DB": [("ypt", "cyd", "ctgt", "Yards / target allowed", 1, 1), ("rtg", "rtg_n", "ctgt", "Passer rating allowed", 1, 1),
         ("bp_pg", "bp", "games", "INT + passes defended / game", 0, 0), ("tk_pg", "tk_all", "games", "Tackles / game", 0, 0),
         ("mt_pct", "mt", "tk_try", "Missed tackle %", 1, 1)],
}


def _rating(c, a, y, t, i):
  """NFL passer rating (each part capped 0-2.375); NaN without attempts."""
  a = np.where(a > 0, a, np.nan)
  cl = lambda v: np.clip(v, 0, 2.375)  # noqa: E731
  return (cl((c / a - 0.3) * 5) + cl((y / a - 3) * 0.25) + cl(t / a * 20) + cl(2.375 - i / a * 25)) / 6 * 100


def defense_games(cache, cur: int) -> pd.DataFrame:
  """One row per defender-game (regular season, 1999 on): IDP points, box stats, his snap share (2012 on) and PFR's
  advanced defense (2018 on)."""
  import nflreadpy as nfl
  import player_logs as PL
  from nfledge.report import IDP123
  players = cache.get("players", "all", lambda: nfl.load_players(), stale=False)
  p2g = players.dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates("pfr_id").set_index("pfr_id").gsis_id
  out = []
  for s in range(HIST_FIRST, cur + 1):
    x = cache.get("stats_full", s, lambda: nfl.load_player_stats([s]).select(PL.FULL_COLS).to_pandas(),
                  stale=(s == cur and cache.age_hours("stats_full", s) > 6) or cache.lacks("stats_full", s, PL.FULL_COLS))
    if x is None or not len(x):
      continue
    x = x[(x.season_type == "REG") & x.position.isin(DEF_GROUP)].copy()
    num = [c for _, c in PL.KIND_STATS["def"] if c != "def_blocks"] + PL.BLOCKS
    for c in num:
      x[c] = pd.to_numeric(x[c], errors="coerce").fillna(0)
    g = pd.DataFrame({"gsis_id": x.player_id, "season": s, "week": x.week.astype(int), "pos": x.position.map(DEF_GROUP),
                      "team": x.team.map(lambda t: D.RELOCATED.get(t, t)),
                      "tk": x.def_tackles_solo, "ast": x.def_tackle_assists, "tfl": x.def_tackles_for_loss, "sk": x.def_sacks,
                      "qbh": x.def_qb_hits, "int": x.def_interceptions, "pd": x.def_pass_defended, "ff": x.def_fumbles_forced,
                      "fr": x.fumble_recovery_opp, "td": x.def_tds, "sf": x.def_safeties, "blk": x[PL.BLOCKS].sum(axis=1)})
    w = IDP123
    g["fp"] = (g.tk * w["idp_tkl_solo"] + g.ast * w["idp_tkl_ast"] + g.tfl * w["idp_tkl_loss"] + g.sk * w["idp_sack"]
               + g.qbh * w["idp_qb_hit"] + g.int * w["idp_int"] + g.pd * w["idp_pass_def"] + g.ff * w["idp_ff"]
               + g.fr * w["idp_fum_rec"] + g.td * w["idp_def_td"] + g.sf * w["idp_safe"] + g.blk * w["idp_blk_kick"])
    g["snap"] = np.nan
    if s >= DEF_SNAP_FIRST:
      sn = cache.get("snaps", s, lambda: nfl.load_snap_counts([s]), stale=False)
      if sn is not None and len(sn):
        sn = sn[sn.game_type == "REG"] if "game_type" in sn else sn
        sn = sn.assign(g=sn.pfr_player_id.map(p2g)).dropna(subset=["g"])
        sp = dict(zip(zip(sn.g, sn.week.astype(int)), pd.to_numeric(sn.defense_pct, errors="coerce")))
        g["snap"] = [sp.get((a, b), np.nan) for a, b in zip(g.gsis_id, g.week)]
    for c in ("prs", "ctgt", "ccmp", "cyd", "ctd", "cint", "mt", "tkc"):
      g[c] = np.nan
    if s >= DEF_PFR_FIRST:
      a = cache.get("pfrdef", s, lambda: nfl.load_pfr_advstats([s], stat_type="def", summary_level="week"),
                    stale=s == cur and cache.age_hours("pfrdef", s) > 6)
      if a is not None and len(a):
        a = a[a.game_type == "REG"].assign(g=lambda d: d.pfr_player_id.map(p2g)).dropna(subset=["g"])
        cols = {"prs": "def_pressures", "ctgt": "def_targets", "ccmp": "def_completions_allowed", "cyd": "def_yards_allowed",
                "ctd": "def_receiving_td_allowed", "cint": "def_ints", "mt": "def_missed_tackles", "tkc": "def_tackles_combined"}
        idx = {k: dict(zip(zip(a.g, a.week.astype(int)), pd.to_numeric(a[v], errors="coerce").fillna(0))) for k, v in cols.items()}
        for k in cols:
          g[k] = [idx[k].get((p, wk), 0.0) for p, wk in zip(g.gsis_id, g.week)]
    out.append(g)
  return pd.concat(out, ignore_index=True)


def defense_table(cache, cur: int, sched: pd.DataFrame):
  """(player-games, player-seasons, spot-starter seasons, qualified {(gsis, season)}): the one place defenders'
  qualification lives; build_defense grades seasons from it, tools/player_logs.py grades single games against the
  qualified players' games."""
  g = defense_games(cache, cur)
  g["games"] = 1.0
  g["tk_all"] = g.tk + g.ast
  g["bp"] = g.int + g.pd
  g["tk_try"] = g.tkc + g.mt
  g["rtg_n"] = 0.0  # filled per season below (a rating isn't a sum)
  g["role"] = ((g.tk_all >= 2) | (g.sk > 0) | (g.int > 0) | (g.pd > 0)) if True else None
  mode1 = lambda x: (lambda m: m.iloc[0] if len(m) else None)(x.dropna().mode())  # noqa: E731
  num = ["fp", "games", "tk", "ast", "tk_all", "tfl", "sk", "qbh", "int", "pd", "bp", "ff", "fr", "td", "prs", "ctgt", "ccmp",
         "cyd", "ctd", "cint", "mt", "tkc", "tk_try"]
  agg = {**{c: "sum" for c in num}, "pos": mode1, "team": mode1}
  t = g.groupby(["gsis_id", "season"]).agg(agg).reset_index()
  t["snap_sum"] = g.groupby(["gsis_id", "season"]).snap.sum(min_count=1).to_numpy()
  t["role_g"] = g.groupby(["gsis_id", "season"]).role.sum().to_numpy()
  t["rtg_n"] = _rating(t.ccmp, t.ctgt, t.cyd, t.ctd, t.cint) * t.ctgt  # rating x targets: rate = rtg_n / ctgt
  tgames = team_games(sched)
  t["tgm"] = [tgames.get((tm, s), np.nan) for tm, s in zip(t.team, t.season)]
  snap_era = t.season >= DEF_SNAP_FIRST
  t["qual"] = np.where(snap_era, t.snap_sum.fillna(0) >= DEF_QUAL * t.tgm, t.role_g >= 0.5 * t.tgm)
  # spot starters' games: half the snaps (2012 on) or a role game (before)
  sub_g = g[np.where(g.season >= DEF_SNAP_FIRST, g.snap >= SUB_SNAP, g.role)]
  tsub = sub_g.groupby(["gsis_id", "season"]).agg(agg).reset_index()
  tsub["rtg_n"] = _rating(tsub.ccmp, tsub.ctgt, tsub.cyd, tsub.ctd, tsub.cint) * tsub.ctgt
  qual = set(zip(t.gsis_id[t.qual], t.season[t.qual]))
  return g, t, tsub, qual


def defense_game_pools(g: pd.DataFrame, qual: set) -> dict:
  """(season, group) -> sorted IDP points of every game by a qualified defender; the current season padded with last
  season's games from the weeks not played yet (as the skill players' pools, tools/player_logs.py)."""
  q = g[[(a, b) in qual for a, b in zip(g.gsis_id, g.season)]]
  pools = {(int(s), p): np.sort(x.fp.to_numpy(float)) for (s, p), x in q.groupby(["season", "pos"])}
  cur_s = int(g.season.max())
  done = int(g[g.season == cur_s].week.max()) if (g.season == cur_s).any() else 0
  for p in DEF_POS:
    prev = q[(q.season == cur_s - 1) & (q.pos == p) & (q.week > done)].fp.to_numpy(float)
    if len(prev):
      pools[(cur_s, p)] = np.sort(np.concatenate([pools.get((cur_s, p), np.array([])), prev]))
  return pools


def build_defense(out: Path, cur: int, sched: pd.DataFrame, cache) -> None:
  """Adds DL / LB / DB records (the skill records' layout) to data/grades/<season>.json, 1999..cur."""
  g, t, tsub, qual = defense_table(cache, cur, sched)
  qg = g[[(a, b) in qual for a, b in zip(g.gsis_id, g.season)]]
  fpri = {pos: mom_prior(qg[qg.pos == pos].assign(games=1.0), "fp", "games") or (float(qg[qg.pos == pos].fp.mean()), 3.0)
          for pos in DEF_POS}

  def form(tab, s, ids):
    wf, wg = pd.Series(0.0, index=ids), pd.Series(0.0, index=ids)
    for lag, w in enumerate(SEASON_W):
      prev = tab[tab.season == s - lag].drop_duplicates("gsis_id").set_index("gsis_id").reindex(ids)
      wf, wg = wf + w * prev.fp.fillna(0), wg + w * prev.games.fillna(0)
    return wf, wg

  def rate(o, nu, de):
    return (o[nu] / o[de].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)

  n_all = 0
  for s in sorted(t.season.unique()):
    f = out / f"{int(s)}.json"
    doc = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"season": int(s), "stats": {}, "qualified": {}, "players": {}}
    one = t[t.season == s].drop_duplicates("gsis_id").set_index("gsis_id")
    for pos in DEF_POS:
      ids = [x for x in one.index[(one.pos == pos) & one.qual]]
      if len(ids) < 5:
        continue
      o = one.loc[ids]
      m, k = fpri[pos]
      wf, wg = form(t, s, ids)
      cur_v, sea_v = (wf + k * m) / (wg + k), (o.fp + k * m) / (o.games + k)
      bars = [b for b in DEF_BARS[pos] if s >= DEF_PFR_FIRST or not b[5]]
      bp = {}
      for key, nu, de, _, low, _p in bars:
        v = rate(o, nu, de)
        v = v.fillna(v.median()).fillna(0.0)
        bp[key] = (99 - pct(v)) if low else pct(v)
      gp, sg = pct(cur_v), pct(sea_v)
      doc["stats"][pos] = [b[3] for b in bars]
      doc["qualified"][pos] = len(ids)
      for x in ids:
        doc["players"][x] = [int(gp[x]), pos, int(o.games[x]), int(round(wg[x])), round(float(cur_v[x]), 1),
                             [int(bp[b[0]][x]) for b in bars], int(sg[x]), round(float(o.fp[x] / o.games[x]), 1), int(o.games[x])]
      # spot starters: graded on their role games against the qualified pool ([9] = 1)
      sub = tsub[(tsub.season == s) & (tsub.pos == pos) & (tsub.games >= SUB_GAMES)].drop_duplicates("gsis_id").set_index("gsis_id")
      uq = [x for x in sub.index if x not in doc["players"]]
      if uq:
        u = sub.loc[uq]
        uwf, uwg = form(tsub, s, uq)
        ucur, usea = (uwf + k * m) / (uwg + k), (u.fp + k * m) / (u.games + k)
        ug, usg = pct_vs(cur_v, ucur), pct_vs(sea_v, usea)
        ub = {}
        for key, nu, de, _, low, _p in bars:
          ref = rate(o, nu, de)
          v = rate(u, nu, de).fillna(ref.median()).fillna(0.0)
          ref = ref.fillna(ref.median()).fillna(0.0)
          ub[key] = (99 - pct_vs(ref, v)) if low else pct_vs(ref, v)
        for x in uq:
          doc["players"][x] = [int(ug[x]), pos, int(u.games[x]), int(round(uwg[x])), round(float(ucur[x]), 1),
                               [int(ub[b[0]][x]) for b in bars], int(usg[x]), round(float(u.fp[x] / u.games[x]), 1), int(u.games[x]), 1]
      n_all += len(ids) + len(uq)
    f.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
  print(f"[grades] defenders: {n_all} graded player-seasons, {int(t.season.min())}-{int(t.season.max())}", flush=True)


def main():
  opt = dict(a[2:].split("=", 1) if "=" in a else (a[2:], "1") for a in sys.argv[1:] if a.startswith("--"))
  cfg = load_config()
  data, pfr, info, pos_of, cur, ngs, team_of = load(cfg)
  st = season_table(data, pfr, load_scoring(), ngs, getattr(data, "ftn", None))
  # the live grade credits receivers with their part of a target only (v1.2; INSIGHTS): the throw is the QB's
  tg = add_value(st, pos_of, "rec_att2")
  if "eval11" in opt:
    r = evaluate_v11(st, pos_of, info, cur)
    print("\nv1.1 guardrail (v2 column = v1.1): rank corr. with next-season fantasy pts/g")
    report_v2(r, "All players")
    return
  if "eval2" in opt:
    r = evaluate_v2(tg, pos_of, info, cur, team_of)
    r.to_parquet(ROOT / "cache" / "grade_eval_v2.parquet")
    mv = r[r.tm_now.notna() & r.tm_next.notna() & (r.tm_now != r.tm_next)]
    report_v2(mv, "GATE: players who changed teams")
    report_v2(r, "All players (reported, not gating)")
    return
  if "eval" in opt:
    r = evaluate(tg, pos_of, info, cur)
    r.to_parquet(ROOT / "cache" / "grade_eval.parquet")
    print(report(r))
    return
  out = Path(opt.get("site", "site")) / "data" / "grades"
  build(tg, pos_of, info, cur, out, data.schedules, team_of, getattr(data, "ryoe", None), getattr(data, "rush_ctx", None))
  # seasons before FIRST: box-score grades (same OVR), built once and cached; listed ahead of the rest in index.json
  sched = D.Cache(ROOT / cfg["data"]["cache_dir"]).get("schedules", "since1999", None, stale=False)
  old = build_historic(out, FIRST, sched if sched is not None else data.schedules, load_scoring(), ROOT / cfg["data"]["cache_dir"])
  build_defense(out, cur, sched if sched is not None else data.schedules, D.Cache(ROOT / cfg["data"]["cache_dir"]))
  ix = json.loads((out / "index.json").read_text(encoding="utf-8"))
  ix["seasons"] = sorted(set(old) | set(ix["seasons"]))
  ix["box_before"] = FIRST
  (out / "index.json").write_text(json.dumps(ix), encoding="utf-8")
  # per-player history for the Grade tab (one small file instead of every season's: 28 files, ~700 KB):
  # data/grades/players/<last 2 digits of gsis>.json = {gsis: [[season, basis, record, [bar labels], qualified n], ...]}
  shards = {}
  for sf in sorted(out.glob("[12][0-9][0-9][0-9].json")):
    d = json.loads(sf.read_text(encoding="utf-8"))
    for pid, rec in d["players"].items():
      pos = rec[1]
      shards.setdefault(pid[-2:], {}).setdefault(pid, []).append(
        [d["season"], d.get("basis", "pbp"), rec, d["stats"].get(pos, []), (d.get("qualified") or {}).get(pos)])
  # seasons he played but wasn't graded (too few games / role): listed so the history has no silent gaps (owner
  # 2026-10-15). Weekly stats per season, finished seasons cached.
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  import nflreadpy as nfl
  graded = {(pid, r[0]) for sh in shards.values() for pid, rows in sh.items() for r in rows}
  for yr in range(HIST_FIRST, cur + 1):
    wk = cache.get("pstats_week", yr, lambda: nfl.load_player_stats([yr], summary_level="week").to_pandas(),
                   stale=yr == cur and cache.age_hours("pstats_week", yr) > 6)
    if wk is None or not len(wk):
      continue
    wk = wk[(wk.season_type == "REG") & wk.position.isin(["QB", "RB", "FB", "HB", "WR", "TE"])]
    pts = actual_points(wk, load_scoring())
    agg = pd.DataFrame({"gsis_id": wk.player_id, "pos": pts.position, "fp": pts.actual}).groupby("gsis_id").agg(
      fp=("fp", "sum"), games=("fp", "size"), pos=("pos", lambda x: x.mode().iloc[0] if len(x.mode()) else None))
    for pid, r in agg.iterrows():
      if not isinstance(pid, str) or (pid, yr) in graded or r.pos not in POS:
        continue
      shards.setdefault(pid[-2:], {}).setdefault(pid, []).append(
        [yr, "none", [None, r.pos, int(r.games), None, None, [], None, round(float(r.fp / r.games), 1), int(r.games)], [], None])
  for sh in shards.values():
    for rows in sh.values():
      rows.sort(key=lambda r: r[0])
  (out / "players").mkdir(exist_ok=True)
  for k, v in shards.items():
    (out / "players" / f"{k}.json").write_text(json.dumps(v, separators=(",", ":")), encoding="utf-8")
  print(f"[grades] player histories: {sum(len(v) for v in shards.values())} players in {len(shards)} shards", flush=True)


if __name__ == "__main__":
  main()
