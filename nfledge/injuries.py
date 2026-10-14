"""Injury availability and vacated-opportunity redistribution.

1. Availability. P(plays | report status, final practice status) is learned from history (injury reports joined
   to snap counts). When the target week's report is not out yet (early in the week), last week's status is
   carried forward with learned P(plays next week | status last week). IR / reserve / cut players are out.
2. Scenarios, not expected values. Availability is binary in the NFL (active players play their normal role),
   so every line is "if active" with P(plays) shown beside it. The default scenario is the likelier one:
   P(plays) < 0.5 sits. Vacated opportunity = the sitting contributor's projected target / carry share, scaled
   by (1 - absent_frac): the portion of his absence already baked into teammates' recent usage (so a player
   who has missed three straight games is not double-counted). Questionable players are assumed active, and
   their teammates get a contingent "if X sits" gain.
3. Redistribution, learned from history: when contributors missed games, how much of their vacated share each
   teammate absorbed, by (missing position -> receiving position), receiving player's depth rank, and current
   share. Non-negative least squares, no intercept. Not 1:1 to the backup.
4. QBs: when the starter sits, the next active QB on the depth chart inherits the starter's dropbacks.
   Backup efficiency comes from the empirical-Bayes prior (position x draft tier), so it is visibly uncertain.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import nnls

from .data import depth_for_week
from .player_model import RB_DEFAULT_CONC, add_rb_inputs
from .team_model import asof_weights

SHARES = {"tgt_share": ("tgt", "team_db"), "carry_share": ("carries", "team_rush")}
SIGNIFICANT = {"tgt_share": 0.08, "carry_share": 0.15}
# Which absent positions vacate each share (WR/TE carries are too rare to learn a redistribution from).
MISSING = {"tgt_share": ("RB", "WR", "TE"), "carry_share": ("RB",)}
RECV = ("RB", "WR", "TE")
RANKS = (1, 2, 3)
OUT_ROSTER = {"RES", "INA", "PUP", "NON", "SUS", "EXE", "CUT", "RET", "TRD", "TRT", "DEV"}


_SCORE = {"D": 0.0, "L": 1.0, "F": 2.0}
GAME_STATUSES = ("None", "QUESTIONABLE", "DOUBTFUL")


def practice_features(df: pd.DataFrame) -> pd.DataFrame:
  """Encode a practice week ('DDL' = DNP, DNP, Limited) + game status for the availability model."""
  days = df.days.fillna("").str.replace("?", "", regex=False)
  sc = days.map(lambda x: [_SCORE[c] for c in x])
  f = pd.DataFrame(index=df.index)
  f["n_days"] = days.str.len()
  for c in "DLF":
    f[f"n_{c}"] = days.str.count(c)
  f["last"] = sc.map(lambda x: x[-1] if x else 1.0)
  f["first"] = sc.map(lambda x: x[0] if x else 1.0)
  f["trend"] = f["last"] - f["first"]
  f["all_dnp"] = (f.n_D == f.n_days) & (f.n_days > 0)
  f["no_days"] = f.n_days == 0
  for g in GAME_STATUSES:
    f[f"gs_{g}"] = df.game_status == g
  f["skill"] = df.position.isin(["QB", "RB", "WR", "TE"])
  f["skill_q"] = f.skill & f.gs_QUESTIONABLE
  return f.astype(float)


def _practice(s) -> str:
  if not isinstance(s, str):
    return "NA"
  s = s.lower()
  return "DNP" if "did not" in s else "LP" if "limited" in s else "FP" if "full" in s else "NA"


def _report(s) -> str:
  return s if isinstance(s, str) and s else "None"


class InjuryModel:
  def __init__(self, data, pm, cfg):
    self.data, self.pm, self.cfg = data, pm, cfg
    hl = cfg["player_model"]["share_half_life_weeks"]
    self.hl = float(hl.get("default", 3.0)) if isinstance(hl, dict) else hl  # per-position setting: team-level default
    self.scale = float(cfg.get("injuries", {}).get("redistribution_scale", 1.0))

  def _gb_params(self) -> dict:
    g = self.cfg.get("injuries", {})
    return {"max_iter": int(g.get("gb_iterations", 200)), "learning_rate": float(g.get("gb_learning_rate", 0.05)),
            "max_depth": int(g.get("gb_max_depth", 3))}

  # -- fitting ---------------------------------------------------------------------------------------------------
  def fit(self, seasons: list[int]):
    self._fit_status(seasons)
    self._fit_practice(seasons)
    self._fit_scratch(seasons)
    self._fit_absorption(seasons)
    return self

  def _played_sets(self):
    """(season, week, gsis_id) for every player-game played, plus the set of players we can observe reliably
    (snap counts map to gsis ids only via rosters; unmapped players would look like they never played)."""
    sn = self.data.snaps.dropna(subset=["gsis_id"])
    any_snap = (sn.offense_snaps.fillna(0) + sn.defense_snaps.fillna(0) + sn.st_snaps.fillna(0)) > 0
    played = set(map(tuple, sn.loc[any_snap, ["season", "week", "gsis_id"]].itertuples(index=False)))
    L = self.pm.ledger
    played |= set(map(tuple, L[["season", "week", "gsis_id"]].itertuples(index=False)))
    return played, set(sn.gsis_id)

  def _fit_status(self, seasons):
    inj = self.data.injuries
    inj = inj[(inj.season.isin(seasons)) & (inj.game_type == "REG")].dropna(subset=["gsis_id"]).copy()
    played, observable = self._played_sets()
    # Calibrate on fantasy positions we can observe reliably.
    inj = inj[inj.position.isin(["QB", "RB", "WR", "TE"]) & inj.gsis_id.isin(observable)]
    inj = inj.drop_duplicates(["season", "week", "gsis_id"], keep="last")
    tl = self.pm.team_ledger
    team_games = set(map(tuple, tl[["season", "week", "team"]].itertuples(index=False)))
    inj["rep"] = inj.report_status.map(_report)
    inj["prac"] = inj.practice_status.map(_practice)
    inj = inj[[(s, w, t) in team_games for s, w, t in zip(inj.season, inj.week, inj.team)]]
    inj["played"] = [(s, w, g) in played for s, w, g in zip(inj.season, inj.week, inj.gsis_id)]
    self.p_rep = inj.groupby("rep").played.mean().to_dict()
    cnt = inj.groupby(["rep", "prac"]).played.agg(["mean", "size"])
    self.p_rep_prac = cnt[cnt["size"] >= 30]["mean"].to_dict()
    # Carry-forward: status in week w -> played in the team's next game.
    nxt = inj.copy()
    nxt["week"] = nxt.week + 1
    has_game = [(s, w, t) in team_games for s, w, t in zip(nxt.season, nxt.week, nxt.team)]
    nxt = nxt[has_game]
    nxt["played_next"] = [(s, w, g) in played for s, w, g in zip(nxt.season, nxt.week, nxt.gsis_id)]
    self.p_next = nxt.groupby("rep").played_next.mean().to_dict()
    self.p_next["None"] = self.p_next.get("None", 0.95)

  def _fit_practice(self, seasons):
    """Gradient-boosted P(plays | Wed/Thu/Fri practice sequence, game status, skill position), trained on
    labelled practice weeks from seasons before the test season. Walk-forward on 2025 (trained 2018-2024):
    Brier 0.1026 vs 0.1081 for the status x final-practice table."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    self.practice_model = None
    ah = self.data.avail_hist
    if ah is None:
      return
    d = ah[(ah.season < max(seasons) + 1) & (ah.game_status != "OUT")]
    if len(d) < 1000:
      return
    X = practice_features(d)
    self.practice_cols = list(X.columns)
    self.practice_model = HistGradientBoostingClassifier(**self._gb_params(), random_state=0).fit(X, d.played)

  def practice_prob(self, rows: pd.DataFrame) -> np.ndarray:
    X = practice_features(rows)[self.practice_cols]
    p = self.practice_model.predict_proba(X)[:, 1]
    return np.where(rows.game_status.to_numpy() == "OUT", 0.0, p)

  def prob(self, rep: str, prac: str) -> float:
    if rep == "Out":
      return 0.0
    return float(self.p_rep_prac.get((rep, prac), self.p_rep.get(rep, 1.0)))

  # -- contributors / absences -----------------------------------------------------------------------------------
  def _absent_frac(self, season: int, week: int) -> pd.DataFrame:
    """Per (player, team): weighted share of the team's recent games the player did NOT play."""
    tl = self.pm.team_ledger
    tg = tl[((tl.season == season) & (tl.week < week)) | (tl.season == season - 1)][["season", "week", "team"]]
    tg = tg.assign(w=asof_weights(tg.season, tg.week, season, week, self.cfg, self.hl))
    L = self.pm.ledger
    L = L[((L.season == season) & (L.week < week)) | (L.season == season - 1)]
    pp = L[["season", "week", "team", "gsis_id"]].drop_duplicates()
    players = pp[["team", "gsis_id"]].drop_duplicates()
    grid = players.merge(tg, on="team")
    grid = grid.merge(pp.assign(p=1), on=["season", "week", "team", "gsis_id"], how="left")
    grid["miss_w"] = grid.w * grid.p.isna()
    agg = grid.groupby(["gsis_id", "team"])[["miss_w", "w"]].sum()
    return (agg.miss_w / agg.w.replace(0, np.nan)).fillna(1.0).rename("absent_frac").reset_index()

  def contributors(self, f: pd.DataFrame, season: int, week: int) -> pd.DataFrame:
    """Recent significant contributors per team with their projected shares (as if healthy)."""
    c = f[f.pos.isin(RECV)].copy()
    c["team_conc"] = c.last_team.map(f.attrs.get("team_conc") or {}).fillna(RB_DEFAULT_CONC)
    c = self.pm.share_hats(c)
    # Only players who have suited up for the team THIS season can vacate volume: offseason departures are
    # already reflected in the new roster's current-season usage (redistributing them double-counts).
    recent = c.last_season == season
    sig = np.zeros(len(c), bool)
    min_share = self.cfg.get("injuries", {}).get("redistribute_min_share", SIGNIFICANT)
    for share, thr in min_share.items():
      sig |= (c[f"{share}_hat"] >= thr).to_numpy()
    c = c[recent & sig].reset_index().rename(columns={"last_team": "team"})
    af = self._absent_frac(season, week)
    c = c.merge(af, on=["gsis_id", "team"], how="left")
    c["absent_frac"] = c.absent_frac.fillna(0.0)
    c["full_name"] = self.pm.info.full_name.reindex(c.gsis_id).to_numpy()
    return c

  # -- absorption features ---------------------------------------------------------------------------------------
  @staticmethod
  def _design(recv: pd.DataFrame, vac: pd.DataFrame, share: str) -> np.ndarray:
    """recv: teammates (team, pos, rank, s_norm). vac: absences (team, pos, eff_vac). One column per
    (missing pos, receiving pos, rank) plus (missing pos, receiving pos, share-weighted)."""
    cols = []
    v = vac.groupby(["team", "pos"]).eff_vac.sum()
    for m in MISSING[share]:
      vm = recv.team.map(v.xs(m, level="pos") if m in v.index.get_level_values("pos") else pd.Series(dtype=float))
      vm = vm.fillna(0.0).to_numpy()
      for r in RECV:
        isr = (recv.pos == r).to_numpy()
        for k in RANKS:
          cols.append(vm * isr * (np.minimum(recv["rank"].to_numpy(), 3) == k))
        cols.append(vm * isr * recv.s_norm.to_numpy())
    return np.column_stack(cols)

  @staticmethod
  def _receivers(df: pd.DataFrame, share: str, rank_col: str | None = None) -> pd.DataFrame:
    d = df[df.pos.isin(RECV)].copy()
    hat = f"{share}_hat"
    d["share_rank"] = d.groupby(["team", "pos"])[hat].rank(ascending=False, method="first")
    if rank_col and rank_col in d:
      dr = d.groupby(["team", "pos"])[rank_col].rank(method="first")
      d["rank"] = dr.fillna(d.share_rank)
    else:
      d["rank"] = d.share_rank
    tot = d.groupby(["team", "pos"])[hat].transform("sum")
    n = d.groupby(["team", "pos"])[hat].transform("size")
    d["s_norm"] = np.where(tot > 0, d[hat] / tot.replace(0, np.nan), 1.0 / n)
    return d

  def _fit_absorption(self, seasons):
    """Teammate share change (actual - projected) regressed on vacated share. Every team-week contributes rows:
    teams with no absence estimate each position's baseline drift (players who suit up tend to beat their
    projected share slightly - a selection effect), which is removed so the weights capture only
    absence-driven shifts."""
    X, y, pos = {s: [] for s in SHARES}, {s: [] for s in SHARES}, {s: [] for s in SHARES}
    L = self.pm.ledger
    for s in seasons:
      for w in range(2, self.data.completed_weeks(s) + 1):
        r = self.pm.tm.fit(s, w)
        f = self.pm.features(s, w, r)
        cont = self.contributors(f, s, w)
        act = L[(L.season == s) & (L.week == w)]
        absent = cont[~cont.gsis_id.isin(set(act.gsis_id)) & cont.team.isin(set(act.team))]
        mates = act[act.pos.isin(RECV)][["gsis_id", "team", "pos", "tgt", "carries", "team_db", "team_rush"]]
        mates = mates.join(f.drop(columns=["pos"]), on="gsis_id")
        add_rb_inputs(mates, f.attrs.get("team_conc"))
        mates = self.pm.share_hats(mates)
        mates = mates[mates.tgt_share_hat.notna()]
        for share, (num, den) in SHARES.items():
          vac = absent.assign(eff_vac=absent[f"{share}_hat"] * (1 - absent.absent_frac))
          rv = self._receivers(mates, share)
          X[share].append(self._design(rv, vac, share))
          y[share].append((rv[num] / rv[den].replace(0, np.nan)).fillna(0).to_numpy() - rv[f"{share}_hat"].to_numpy())
          pos[share].append(rv.pos.to_numpy())
    self.coef, self.drift, self.n_obs = {}, {}, {}
    for share in SHARES:
      Xs, ys, ps = np.vstack(X[share]), np.concatenate(y[share]), np.concatenate(pos[share])
      clean = np.abs(Xs).sum(axis=1) == 0
      drift = pd.Series(ys[clean]).groupby(ps[clean]).mean()
      self.drift[share] = drift.to_dict()
      resid = ys - pd.Series(ps).map(drift).fillna(0).to_numpy()
      self.coef[share], _ = nnls(Xs[~clean], resid[~clean])
      self.n_obs[share] = int((~clean).sum())

  def absorption_table(self) -> pd.DataFrame:
    """Human-readable learned redistribution weights (fraction of a vacated share absorbed per teammate)."""
    rows = []
    for share, c in self.coef.items():
      if c is None:
        continue
      i = 0
      for m in MISSING[share]:
        for r in RECV:
          for k in RANKS:
            rows.append({"share": share, "missing": m, "receiver": r, "term": f"rank{k}", "w": c[i]})
            i += 1
          rows.append({"share": share, "missing": m, "receiver": r, "term": "x share", "w": c[i]})
          i += 1
    return pd.DataFrame(rows)

  # -- healthy scratches -----------------------------------------------------------------------------------------
  def scratch_table(self, season: int) -> pd.DataFrame:
    """One row per rostered (ACT) QB/RB/WR/TE per team game this season, including scheduled future games,
    with as-of features for P(active | not on the injury report) and the realized label for past games."""
    d = self.data
    sch = d.schedules[(d.schedules.season == season) & (d.schedules.game_type == "REG")]
    tg = pd.concat([sch[["week", "home_team", "home_score"]].rename(columns={"home_team": "team"}),
                    sch[["week", "away_team", "home_score"]].rename(columns={"away_team": "team"})])
    tg["final"] = tg.home_score.notna()
    tg = tg.drop(columns=["home_score"])
    r = d.rosters[(d.rosters.season == season) & d.rosters.gsis_id.notna()].copy()
    r["team"] = r.team.replace({"LAR": "LA"})
    r["pos"] = r.position.replace({"FB": "RB", "HB": "RB"})
    r = r[r.pos.isin(["QB", "RB", "WR", "TE"])]
    # Future weeks: carry each team's latest roster forward.
    last_wk = int(r.week.max())
    fut = tg[tg.week > last_wk]
    if len(fut):
      latest = r[r.week == r.groupby("team").week.transform("max")]
      r = pd.concat([r, fut.merge(latest.drop(columns=["week"]), on="team")], ignore_index=True)
    # ACT and INA are both the 53-man roster (INA = that week's game-day inactive list, i.e. the outcome).
    rg = r[r.status.isin(["ACT", "INA"])].merge(tg, on=["week", "team"])[["week", "team", "gsis_id", "pos", "years_exp"]]
    rg = rg.drop_duplicates(["week", "gsis_id"])
    rg = rg.merge(tg, on=["week", "team"], how="left")
    played, observable = self._played_sets()
    rg["active"] = [(season, w, g) in played for w, g in zip(rg.week, rg.gsis_id)]
    rg["observable"] = rg.gsis_id.isin(observable)
    inj = d.injuries[(d.injuries.season == season) & d.injuries.report_status.notna()]
    on_report = set(zip(inj.week, inj.gsis_id))
    rg["on_report"] = [(w, g) in on_report for w, g in zip(rg.week, rg.gsis_id)]
    od = inj[inj.report_status.isin(["Out", "Doubtful"])][["week", "team", "gsis_id"]]
    # Weeks whose report is not out yet (early in the week): carry last week's Out/Doubtful forward, as the
    # availability model does, so a backup is not scored as a scratch risk when the starter is likely out.
    reported = set(zip(d.injuries[d.injuries.season == season].week, d.injuries[d.injuries.season == season].team))
    carry = od.assign(week=od.week + 1)
    carry = carry[[(w, t) not in reported for w, t in zip(carry.week, carry.team.replace({"LAR": "LA"}))]]
    od = pd.concat([od, carry])
    out_rep = set(zip(od.week, od.gsis_id))
    L = self.pm.ledger
    snap = L[L.season == season].groupby(["week", "gsis_id"]).offense_pct.max().rename("snap").reset_index()
    rg = rg.merge(snap, on=["week", "gsis_id"], how="left")
    rg["snap"] = rg.snap.astype(float)
    rg = rg.sort_values(["gsis_id", "week"])
    # Only games with a final score count as history (a pending Monday game is not an inactive week), and only
    # once that game's participation data exists: nflverse publishes play-by-play and snap counts a day or so
    # after the final score, and until then every player of both teams would look inactive (2026-10-13: the
    # Monday BUF-LA game made Josh Allen and Matthew Stafford 21% / 40% healthy-scratch risks).
    seen = set(zip(L[L.season == season].week, L[L.season == season].team))
    sn_ = d.snaps[(d.snaps.season == season)] if "team" in d.snaps else d.snaps.iloc[0:0]
    seen |= set(zip(sn_.week, sn_.team.replace({"LAR": "LA"}))) if len(sn_) else set()
    observed = pd.Series([(w, t) in seen for w, t in zip(rg.week, rg.team)], index=rg.index)
    done = rg.final.fillna(False).astype(bool) & (rg.week <= self.data.completed_weeks(season)) & observed
    # History excludes injury-report weeks (those absences are injuries, not scratches) and unplayed weeks.
    hist = (done & ~rg.on_report).astype(int)
    act = (rg.active & (hist == 1)).astype(int)
    rg["n_prev"] = hist.groupby(rg.gsis_id).cumsum() - hist
    rg["act_prev"] = act.groupby(rg.gsis_id).cumsum() - act
    rg["act_rate"] = (rg.act_prev + 1) / (rg.n_prev + 1.2)  # light prior toward active
    lastplayed = act.where(hist == 1).groupby(rg.gsis_id).transform(lambda s: s.ffill().shift(1))
    rg["played_last"] = lastplayed.fillna(-1)
    sn = rg.snap.where(rg.active & (hist == 1))
    rg["snap_avg"] = sn.groupby(rg.gsis_id).transform(lambda s: s.expanding().mean().shift(1)).fillna(0)
    # Depth chart rank + how many players ahead of him at his position are out this week.
    ranks = []
    for w in sorted(rg.week.unique()):
      dc = depth_for_week(self.data, season, int(w))
      if len(dc):
        ranks.append(dc.assign(week=w, team=dc.team.replace({"LAR": "LA"}))[["week", "team", "gsis_id", "rank"]])
    rk = pd.concat(ranks) if ranks else pd.DataFrame(columns=["week", "team", "gsis_id", "rank"])
    rg = rg.merge(rk.drop_duplicates(["week", "gsis_id"]), on=["week", "team", "gsis_id"], how="left")
    rg["rank"] = pd.to_numeric(rg["rank"], errors="coerce").fillna(9).clip(upper=9)
    rg["is_out"] = [(w, g) in out_rep for w, g in zip(rg.week, rg.gsis_id)]
    grp = rg.groupby(["week", "team", "pos"])
    # "Ahead" = bigger recent snap share at the same position (injured players drop off the depth chart).
    out_snap = rg[rg.is_out].groupby(["week", "team", "pos"]).snap_avg.apply(list)
    rg["ahead_out"] = [sum(1 for x in out_snap.get((w, t, p), []) if x > sa + 0.05)
                       for w, t, p, sa in zip(rg.week, rg.team, rg.pos, rg.snap_avg)]
    rg["rookie"] = (pd.to_numeric(rg.years_exp, errors="coerce").fillna(1) == 0).astype(int)
    for p_ in ("QB", "RB", "WR", "TE"):
      rg[f"is_{p_}"] = (rg.pos == p_).astype(int)
    rg["season"] = season
    return rg

  SCRATCH_COLS = ["n_prev", "act_rate", "played_last", "snap_avg", "rank", "ahead_out", "rookie", "is_QB", "is_RB",
                  "is_WR", "is_TE"]

  def _fit_scratch(self, seasons):
    """Gradient-boosted P(active | not on injury report) from as-of role/history features."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    rows = []
    for s in seasons:
      t = self.scratch_table(s)
      rows.append(t[t.final & (t.week <= self.data.completed_weeks(s)) & ~t.on_report & t.observable & (t.week >= 2)])
    d = pd.concat(rows)
    self.scratch_model = HistGradientBoostingClassifier(**self._gb_params(), random_state=0).fit(
      d[self.SCRATCH_COLS], d.active)
    self._scratch_cache = {}

  def scratch_prob(self, season: int, week: int) -> pd.Series:
    if season not in self._scratch_cache:
      self._scratch_cache[season] = self.scratch_table(season)
    t = self._scratch_cache[season]
    t = t[t.week == week]
    return pd.Series(self.scratch_model.predict_proba(t[self.SCRATCH_COLS])[:, 1], index=t.gsis_id.to_numpy())

  # -- application -----------------------------------------------------------------------------------------------
  espn_bridge: dict | None = None  # gsis_id -> ESPN bucket (live week only; see espn.py / espn_calib.py)
  espn_rates: dict | None = None  # bucket -> learned P(active) (espn_calib.learned_rates); None = carry-forward rates

  def availability(self, p: pd.DataFrame, season: int, week: int) -> pd.DataFrame:
    inj = self.data.injuries
    inj = inj[(inj.season == season) & (inj.game_type == "REG")].dropna(subset=["gsis_id"])
    cur = inj[inj.week == week]
    prev = inj[inj.week == week - 1]
    published = set(cur.team)
    p = p.copy()
    p["avail"], p["status"] = 1.0, ""
    cur_map = cur.set_index("gsis_id")
    prev_map = prev.drop_duplicates("gsis_id").set_index("gsis_id")
    pr = self.data.practice
    use_days = self.practice_model is not None and pr is not None
    if use_days:
      days = pr[(pr.season == season) & (pr.week == week)].drop_duplicates("gsis_id", keep="last").set_index("gsis_id")
    scratch = self.scratch_prob(season, week)
    p["scratch_avail"] = p.gsis_id.map(scratch).fillna(1.0)
    for i, row in p.iterrows():
      p.at[i, "avail"] = p.at[i, "scratch_avail"]  # healthy-scratch risk unless the injury report says more
      if row.team in published and use_days and row.gsis_id in days.index:
        x = days.loc[[row.gsis_id]]
        p.at[i, "avail"] = float(self.practice_prob(x)[0])
        gs = x.game_status.iloc[0]
        p.at[i, "status"] = (gs.title() if gs != "None" else "") + (f" ({x.days.iloc[0]})" if x.days.iloc[0] else "")
        continue
      if row.team in published:
        if row.gsis_id in cur_map.index:
          x = cur_map.loc[[row.gsis_id]].iloc[0]
          rep, prac = _report(x.report_status), _practice(x.practice_status)
          p.at[i, "avail"] = self.prob(rep, prac)
          p.at[i, "status"] = rep if rep != "None" else ""
      elif self.espn_bridge and row.gsis_id in self.espn_bridge:
        # This week's report isn't out, but ESPN has injury news from after his last game: its bucket's P(active),
        # learned from how earlier early-week ESPN statuses turned out (espn_calib.py); before any outcomes, the
        # designation's carry-forward rate. IR: out at least 4 games.
        b = self.espn_bridge[row.gsis_id]
        rate = (self.espn_rates or {}).get(b)
        base = "Out" if b == "Out+ret" else b
        p.at[i, "avail"] = 0.0 if b == "IR" else float(rate["p"] if rate else self.p_next.get(base, 1.0))
        p.at[i, "status"] = "Out (ESPN; return date after this game)" if b == "Out+ret" else f"{b} (ESPN)"
      elif row.gsis_id in prev_map.index:
        rep = _report(prev_map.at[row.gsis_id, "report_status"])
        if rep != "None":
          p.at[i, "avail"] = float(self.p_next.get(rep, 1.0))
          p.at[i, "status"] = f"{rep} last wk"
    return p

  @staticmethod
  def build_espn_bridge(data, season: int, week: int, feed: pd.DataFrame) -> dict:
    """Early-week bridge (see espn.py): gsis_id -> ESPN bucket (espn_calib.bucket: Out / Out+ret / Doubtful / IR)
    for players with an ESPN injury status updated on or after their team's last completed game day, for teams
    whose report for `week` is not out. Empty when there is no feed, or once every report for the week is out."""
    from .espn import STATUS_MAP
    from .espn_calib import bucket
    if feed is None or feed.empty:
      return {}
    inj = data.injuries
    published = set(inj[(inj.season == season) & (inj.week == week)].team.replace({"LAR": "LA"}))
    r = data.rosters[(data.rosters.season == season) & data.rosters.espn_id.notna() & data.rosters.gsis_id.notna()]
    r = r.sort_values("week").drop_duplicates("gsis_id", keep="last")
    by_espn = {str(e).split(".")[0]: (g, t if t != "LAR" else "LA") for e, g, t in zip(r.espn_id, r.gsis_id, r.team)}
    s = data.schedules[(data.schedules.season == season) & (data.schedules.game_type == "REG")
                       & (data.schedules.week < week) & data.schedules.home_score.notna()]
    last_day = pd.concat([s[["home_team", "gameday"]].set_axis(["team", "day"], axis=1),
                          s[["away_team", "gameday"]].set_axis(["team", "day"], axis=1)]).groupby("team").day.max()
    w = data.schedules[(data.schedules.season == season) & (data.schedules.week == week)]
    game_day = {**dict(zip(w.home_team, w.gameday)), **dict(zip(w.away_team, w.gameday))}
    out = {}
    for x in feed.itertuples():
      rep = STATUS_MAP.get(str(x.status))
      hit = by_espn.get(str(x.espn_id))
      if rep is None or hit is None:
        continue
      gsis, team = hit
      if team in published or team not in last_day.index:
        continue
      upd = pd.to_datetime(x.updated, utc=True, errors="coerce")
      if pd.isna(upd) or upd.tz_convert("America/New_York").date() < pd.Timestamp(last_day[team]).date():
        continue  # news from before his last game: last week's report already covers it
      out[gsis] = bucket(x.status, getattr(x, "return_date", None), game_day.get(team)) or rep
    return out

  def report_avail(self, season: int, week: int) -> pd.Series:
    """P(active) for everyone on the injury report (any position, e.g. defenders): practice-sequence model
    when this week's report is out, else last week's status carried forward."""
    inj = self.data.injuries
    inj = inj[(inj.season == season) & (inj.game_type == "REG")].dropna(subset=["gsis_id"])
    cur = inj[inj.week == week].drop_duplicates("gsis_id", keep="last")
    out = {}
    if len(cur):
      pr = self.data.practice
      days = (pr[(pr.season == season) & (pr.week == week)].drop_duplicates("gsis_id", keep="last")
              .set_index("gsis_id") if pr is not None else None)
      for _, x in cur.iterrows():
        if self.practice_model is not None and days is not None and x.gsis_id in days.index:
          out[x.gsis_id] = float(self.practice_prob(days.loc[[x.gsis_id]])[0])
        else:
          out[x.gsis_id] = self.prob(_report(x.report_status), _practice(x.practice_status))
    else:
      for _, x in inj[inj.week == week - 1].drop_duplicates("gsis_id", keep="last").iterrows():
        rep = _report(x.report_status)
        if rep != "None":
          out[x.gsis_id] = float(self.p_next.get(rep, 1.0))
    return pd.Series(out, dtype=float)

  def apply(self, p: pd.DataFrame, season: int, week: int, wind, avail_override: dict | None = None,
            status_override: dict | None = None) -> pd.DataFrame:
    """Binary scenarios, not expected values: NFL availability is yes/no and an active player plays his normal
    role. Each player's line is his projection IF ACTIVE ('avail' = P(plays) is reported alongside, never
    multiplied in). The default team scenario is the likelier one: P(plays) < 0.5 (Out / Doubtful / IR / cut)
    sits and his volume is redistributed; Questionable players are assumed active, and their teammates carry a
    contingent 'if X sits' upside instead."""
    if avail_override is None:
      p = self.availability(p, season, week)
    else:  # lookahead weeks: P(active) from the return-timing model (no report exists that far out)
      p = p.copy()
      p["avail"] = p.gsis_id.map(avail_override).fillna(1.0)
      p["status"] = p.gsis_id.map(status_override or {}).fillna("")
      p["scratch_avail"] = 1.0
    f = self.pm.features(season, week, self.pm.tm.fit(season, week))
    cont = self.contributors(f, season, week)
    on_team = set(zip(p.gsis_id, p.team))
    cont["p_play"] = [1.0 if (g, t) in on_team else 0.0 for g, t in zip(cont.gsis_id, cont.team)]
    avail = p.set_index("gsis_id").avail
    has = cont.gsis_id.isin(avail.index) & (cont.p_play > 0)
    cont.loc[has, "p_play"] = cont.loc[has, "gsis_id"].map(avail)
    sits = cont[cont.p_play < 0.5].copy()
    sits["why"] = np.where(sits.gsis_id.isin(avail.index), "injury", "inactive")
    p["sits"] = p.avail < 0.5

    base = p.proj.copy()
    p0 = p.copy()  # pre-redistribution state for contingent scenarios
    p = self._redistribute(p, sits, wind)
    p["injury_boost"] = (p.proj - base).clip(lower=0)
    p["teammate_out"] = p.team.isin(set(sits.team))
    # Name only real contributors as the source of a boost (not low-volume healthy scratches).
    names = pd.concat([sits[["team", "full_name"]], p.loc[p.sits & (p.proj_no_inj >= 5), ["team", "full_name"]]]).dropna()
    p["boost_from"] = p.team.map(names.drop_duplicates().groupby("team").full_name.apply(", ".join)).fillna("")

    # Contingent upside: for each genuinely doubtful player (50-90% to play, assumed active), what teammates gain
    # if he sits. Recomputed from the pre-redistribution state so nothing is applied twice.
    p["if_sits_gain"], p["if_sits_name"] = 0.0, ""
    doubt = (p.avail >= 0.5) & (p.avail < 0.9)
    q = cont[(cont.p_play >= 0.5) & (cont.p_play < 0.9)]
    qbs = p[doubt & (p.pos == "QB")]
    scenarios = [(x.gsis_id, x.team, x.full_name, x.to_frame().T) for _, x in q.iterrows()]
    scenarios += [(x.gsis_id, x.team, x.full_name, None) for _, x in qbs.iterrows()]
    for gid, team, name, extra in scenarios:
      alt_p = p0.copy()
      alt_p.loc[alt_p.gsis_id == gid, "sits"] = True
      alt = self._redistribute(alt_p, sits if extra is None else pd.concat([sits, extra]), wind)
      gain = (alt.proj - p.proj).where((p.team == team) & (p.gsis_id != gid), 0.0)
      x = pd.Series({"full_name": name})
      better = gain > p.if_sits_gain
      p.loc[better, "if_sits_gain"] = gain[better]
      p.loc[better, "if_sits_name"] = x.full_name if isinstance(x.full_name, str) else ""
    self.last_absent = sits
    return p

  def _redistribute(self, p: pd.DataFrame, sits: pd.DataFrame, wind) -> pd.DataFrame:
    p = p.copy()
    p["tgt_add"], p["carry_add"] = 0.0, 0.0
    if not sits.empty:
      sits = sits.assign(team=sits.team.astype(str))
      for share in SHARES:
        if self.coef.get(share) is None:
          continue
        vac = sits.assign(eff_vac=sits[f"{share}_hat"].astype(float) * (1 - sits.absent_frac.astype(float)))
        rv = self._receivers(p[~p.sits & p.pos.isin(RECV)], share, rank_col="depth_rank")
        rv = rv[rv.team.isin(set(vac.team))]
        if rv.empty:
          continue
        add = np.clip(self._design(rv, vac, share) @ self.coef[share], 0, None) * self.scale
        p.loc[rv.index, "tgt_add" if share == "tgt_share" else "carry_add"] = add
    p["tgt"] = p.tgt + p.tgt_add * p.team_db
    p["carries"] = p.carries + p.carry_add * p.team_rush
    p["rush"] = p.rush + p.carry_add * p.team_rush
    self._qb_handoff(p)
    return self.pm.stats_from_volume(p, wind)

  @staticmethod
  def _qb_handoff(p: pd.DataFrame):
    """Starter likely sits -> next active QB on the depth chart takes the starter's dropbacks."""
    qb = p[p.pos == "QB"]
    for team, g in qb.groupby("team"):
      starter = g.db.idxmax()
      if not p.at[starter, "sits"] or len(g) < 2:
        continue
      order = g.drop(index=starter).sort_values(["depth_rank", "db_share_long"], ascending=[True, False],
                                                na_position="last").index
      backup = next((i for i in order if not p.at[i, "sits"]), None)
      if backup is None:
        continue
      p.at[backup, "db"] = p.at[backup, "db"] + p.at[starter, "db"]
      p.at[backup, "rush"] = p.at[backup, "rush"] + p.at[starter, "db"] * p.at[backup, "scr_rate"]
      # The whole passing offense (every receiver's supporting cast) now runs through the backup.
      if "qb_term" in p and pd.notna(p.at[backup, "qb_term"]):
        team_rows = p.team == team
        p.loc[team_rows, "off_pass"] = p.loc[team_rows, "off_pass_base"] + p.at[backup, "qb_term"]
