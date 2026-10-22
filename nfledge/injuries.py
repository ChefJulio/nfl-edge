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
GAMEDAY_ACTIVE = {"questionable": 0.974, "doubtful": 0.286}  # (AU) played rate once declared active, 2019-25 skill players


OUT_RET_PRIOR = 0.018  # ESPN Out with a return date past the game: 1.8% played early in the week (n 652, {#tags})


def filed_dates(data, season: int, week: int) -> dict:
  """team -> sorted report dates of this week whose report is in our practice data (anyone on it listed that day).
  A day not here hasn't reached us yet, even past its deadline: "not listed = practiced fully" only holds on a day
  the team's report is in. Only the live season's practice data carries dates (older caches: {})."""
  pr = data.practice
  if pr is None or "dates" not in pr:
    return {}
  x = pr[(pr.season == season) & (pr.week == week)].dropna(subset=["dates"])
  ro = data.rosters
  ro = ro[(ro.season == season) & (ro.week <= week) & ro.gsis_id.notna()].sort_values("week").drop_duplicates("gsis_id", keep="last")
  team = dict(zip(ro.gsis_id, ro.team.replace({"LAR": "LA"})))
  out = {}
  for g, ds in zip(x.gsis_id, x.dates):
    t = team.get(g)
    if t:
      out.setdefault(t, set()).update(d for d in str(ds).split(",") if d)
  return {t: sorted(v) for t, v in out.items()}


def published_teams(data, season: int, week: int) -> set:
  """Teams whose report for this week is out. The current season's injury table is built from NFL.com's report
  (data.injuries_from_nflcom, owner 2026-10-22: one source), so this, the practice lines and the filed days can't
  disagree (Tyler Shough: nflverse's copy lagged a day while NFL.com's Wednesday report showed on his card)."""
  inj = data.injuries  # the current season's table IS NFL.com's report (data.injuries_from_nflcom): one source
  return set(inj[(inj.season == season) & (inj.week == week) & (inj.game_type == "REG")].team.replace({"LAR": "LA"}))


def listed_now(data, season: int, week: int) -> set:
  """gsis ids on this week's report in either source (see published_teams)."""
  inj = data.injuries
  return set(inj[(inj.season == season) & (inj.week == week) & (inj.game_type == "REG")].gsis_id.dropna())


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
    # a number, or per receiving position ({RB = .., default = ..}; INSIGHTS (V))
    sc = cfg.get("injuries", {}).get("redistribution_scale", 1.0)
    self.scale = {k: float(v) for k, v in sc.items()} if isinstance(sc, dict) else float(sc)
    # EXPERIMENT (injuries.absorb_snap; INSIGHTS (U)): the receiver's share of his position group's recent snap share
    # as one more absorption column per (missing, receiving position)
    self.absorb_snap = bool(cfg.get("injuries", {}).get("absorb_snap", False))
    self.conserve = bool(cfg.get("injuries", {}).get("redistribute_conserve", False))

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
    X = self._with_rest(self._with_role(practice_features(d), d), d)
    self.practice_cols = list(X.columns)
    self.practice_model = HistGradientBoostingClassifier(**self._gb_params(), random_state=0).fit(X, d.played)
    # Midweek (owner-approved test 2026-10-15, INSIGHTS sec. 9; tools/partial_week_eval.py): the full-week model
    # reads "no game status yet" as "cleared" (1 day published: 86% predicted vs 65% played). One model per k = 1, 2
    # published days, trained on 3-day report weeks cut to their first k days, every outcome: walk-forward 2021-25
    # Brier 0.203 -> 0.160 (5/5 seasons), calibrated within 1.2 points. Used until the team's final report is out.
    self.partial_models = {}
    full3 = ah[(ah.season < max(seasons) + 1) & (ah.days.fillna("").str.len() == 3)]
    for k in (1, 2):
      t = full3.assign(days=full3.days.str[:k], game_status="None")
      self.partial_models[k] = HistGradientBoostingClassifier(**self._gb_params(), random_state=0).fit(
        self._with_rest(self._with_role(practice_features(t), t), t)[self.practice_cols], t.played)

  def _with_role(self, X: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    """EXPERIMENT (injuries.practice_role; pre-registered 2026-10-15): add his recent role, the mean snap share
    (offense or defense, whichever is larger) over his last 3 games before that week, any season; 0 if none. Without
    it the practice models treat a starter listed with full practice like the backups on the report, who often
    don't take a snap (Drake Maye 6.5-11% inactive while practicing fully)."""
    pr = self.cfg.get("injuries", {}).get("practice_role")
    if not pr:
      return X
    use_pos = set(pr) if isinstance(pr, (list, tuple)) else None  # a list: only those positions get the role
    if not hasattr(self, "_role_idx"):
      sn = self.data.snaps.dropna(subset=["gsis_id"])
      v = np.maximum(sn.offense_pct.fillna(0).to_numpy(float), sn.defense_pct.fillna(0).to_numpy(float))
      t = pd.DataFrame({"g": sn.gsis_id.to_numpy(), "k": (sn.season * 100 + sn.week).to_numpy(), "v": v})
      t = t[t.v > 0].groupby(["g", "k"]).v.max().reset_index().sort_values(["g", "k"])
      self._role_idx = {g: (x.k.to_numpy(), x.v.to_numpy()) for g, x in t.groupby("g")}
    gid = rows.gsis_id if "gsis_id" in rows else pd.Series(rows.index, index=rows.index)
    out = []
    for g, s_, w in zip(gid, rows.season, rows.week):
      e = self._role_idx.get(g)
      n = int(np.searchsorted(e[0], int(s_) * 100 + int(w))) if e is not None else 0
      out.append(float(e[1][max(0, n - 3):n].mean()) if n else 0.0)
    if use_pos is not None and "position" in rows:
      out = [v if ps in use_pos else -1.0 for v, ps in zip(out, rows.position)]
    return X.assign(role=out)

  REASONS = ["hamstring", "neck", "concussion", "leg_soft", "ankle", "knee", "foot", "upper", "core", "illness",
             "personal", "rest", "other"]

  @staticmethod
  def reason_of(primary: str, secondary: str) -> str:
    """The week's listed reason as one category (INSIGHTS (E)): a real injury wins over a rest note listed with it."""
    def cat(t: str):
      t = t.lower()
      if not t or t in ("nan", "none"):
        return None
      for key, words in (("hamstring", ["hamstring"]), ("neck", ["neck"]), ("concussion", ["concussion", "head"]),
                         ("leg_soft", ["groin", "quad", "thigh", "calf", "achilles", "adductor"]), ("ankle", ["ankle"]),
                         ("knee", ["knee", "acl", "mcl"]), ("foot", ["foot", "toe", "heel"]),
                         ("upper", ["shoulder", "elbow", "hand", "wrist", "finger", "thumb", "arm", "pectoral", "bicep", "tricep"]),
                         ("core", ["back", "hip", "rib", "chest", "abdom", "oblique", "pelvis"]), ("illness", ["illness"]),
                         ("personal", ["personal"]), ("rest", ["rest", "not injury related"])):
        if any(w in t for w in words):
          return key
      return "other"
    a, b = cat(str(primary)), cat(str(secondary))
    if a in ("rest", "personal") and b not in (None, "rest", "personal"):
      return b  # "resting player" with a groin listed second: the groin is what could keep him out
    return a or b or "none"

  def _tues_inputs(self):
    """(final report rows, in-game injury notes), built once per model object (nfledge/tuesday.py)."""
    if not hasattr(self, "_tues_in"):
      from pathlib import Path
      from . import data as D
      from . import tuesday as T
      cache = D.Cache(Path(__file__).resolve().parent.parent / self.cfg["data"]["cache_dir"])
      self._tues_in = (T.report_rows(self.data), T.hurt_notes(self.data, cache))
    return self._tues_in

  def _tues_table(self):
    """The Tuesday model's rows (nfledge/tuesday.py), built once per model object."""
    if not hasattr(self, "_tues_rows"):
      from . import tuesday as T
      self._tues_rows = T.build_rows(self.data, *self._tues_inputs())
    return self._tues_rows

  def week_prob(self, items: list) -> np.ndarray:
    """(INSIGHTS (I2), injuries.week_model) the one availability model for Wednesday on: items as
    tuesday.week_now_rows. Trained on seasons before this one, calibrated per stage on the season before."""
    from . import tuesday as T
    if not hasattr(self, "_week_ctx"):
      rep_rows, hurt = self._tues_inputs()
      self._week_ctx = T._Ctx(self.data, rep_rows, hurt)
      # (BE2, owner 2026-10-20) reserve-list players with an open practice window are rows too, with the reserve
      # inputs and their own calibration (tuesday.week_rows reserve=True)
      self._week_res = bool(self.cfg.get("injuries", {}).get("reserve_rows"))
      w = T.week_rows(self.data, rep_rows, hurt, reserve=self._week_res).dropna(subset=["y"])
      self._week_all = w[~((w.stage == 3) & (w.gs_now == "Out"))]
      self._week_models = {}
    x = T.week_now_rows(self._week_ctx, items, reserve=self._week_res)
    out = np.full(len(x), np.nan)
    for s_ in sorted(set(x.season)):
      if s_ not in self._week_models:
        self._week_models[s_] = T.week_model(self._week_all, s_) if (self._week_all.season < s_).sum() > 5000 else None
      m = self._week_models[s_]
      k = (x.season == s_).to_numpy()
      if m is not None:
        out[k] = T.week_predict(m, x[k])
    return out

  def _with_tprior(self, X: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    """EXPERIMENT (injuries.tuesday_prior; pre-registered 2026-10-16, INSIGHTS (H)): the Tuesday model's P(plays) for
    that week as an input, so the practice models build on it instead of starting over. Strictly walk-forward: the
    number for any row of season s comes from a Tuesday model trained on seasons before s."""
    if not self.cfg.get("injuries", {}).get("tuesday_prior"):
      return X
    if not hasattr(self, "_tprior_idx"):
      from . import tuesday as T
      r = self._tues_table()
      idx = {}
      for s_ in sorted(set(r.season)):
        tr, te = r[(r.season < s_) & r.y.notna()], r[r.season == s_]
        if len(tr) < 1000 or not len(te):
          continue
        pv = T.fit(tr).predict_proba(T.features(te))[:, 1]
        idx.update({(int(a), int(b), g): float(v) for a, b, g, v in zip(te.season, te.week, te.gsis_id, pv)})
      self._tprior_idx = idx
    gid = rows.gsis_id if "gsis_id" in rows else pd.Series(rows.index, index=rows.index)
    return X.assign(tues_p=[self._tprior_idx.get((int(s_), int(w), g), np.nan) for g, s_, w in zip(gid, rows.season, rows.week)])

  def _with_prev(self, X: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    """EXPERIMENT (injuries.practice_prev; pre-registered 2026-10-16): did he miss his team's previous game (no snap
    in it), and how many in a row (cap 4). Limited Wed + Thu: played 89% after playing last week, 59% after missing
    it (owner: Ladd McConkey). His team that week: the injury report's, else his latest roster row. NaN where snap
    counts don't cover the season (2018)."""
    if not self.cfg.get("injuries", {}).get("practice_prev"):
      return X
    if not hasattr(self, "_prev_idx"):
      sn = self.data.snaps.dropna(subset=["gsis_id"])
      tot = sn[["offense_snaps", "defense_snaps", "st_snaps"]].fillna(0).sum(axis=1)
      self._on_field = set(zip(sn.gsis_id[tot > 0], sn.season[tot > 0].astype(int), sn.week[tot > 0].astype(int)))
      self._snap_seasons = set(sn.season.astype(int))
      sch = self.data.schedules[self.data.schedules.game_type == "REG"]
      tw = {}
      for g in sch.itertuples():
        for t in (g.home_team, g.away_team):
          tw.setdefault((int(g.season), t), []).append(int(g.week))
      self._team_weeks = {k: sorted(v) for k, v in tw.items()}
      inj = self.data.injuries.dropna(subset=["gsis_id"])
      self._team_of = {(int(s_), int(w), g): t for s_, w, g, t in zip(inj.season, inj.week, inj.gsis_id, inj.team)}
      ro = self.data.rosters.dropna(subset=["gsis_id"]).sort_values(["season", "week"])
      self._ros_team = ro.drop_duplicates("gsis_id", keep="last").set_index("gsis_id").team.to_dict()
      self._prev_idx = True
    gid = rows.gsis_id if "gsis_id" in rows else pd.Series(rows.index, index=rows.index)
    teams = rows.team if "team" in rows else pd.Series([None] * len(rows), index=rows.index)
    miss, streak = [], []
    for g, s_, w, t in zip(gid, rows.season, rows.week, teams):
      s_, w = int(s_), int(w)
      t = t if isinstance(t, str) else self._team_of.get((s_, w, g)) or self._ros_team.get(g)
      t = {"LAR": "LA"}.get(t, t)
      prev = [k for k in self._team_weeks.get((s_, t), []) if k < w]
      if s_ not in self._snap_seasons or not prev:
        miss.append(np.nan); streak.append(np.nan)
        continue
      n = 0
      for k in reversed(prev):
        if (g, s_, k) in self._on_field:
          break
        n += 1
      miss.append(float(n > 0)); streak.append(float(min(n, 4)))
    return X.assign(missed_prev=miss, missed_run=streak)

  def _with_reason(self, X: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    """EXPERIMENT (injuries.practice_reason; pre-registered 2026-10-16): one flag per listed-reason category."""
    if not self.cfg.get("injuries", {}).get("practice_reason"):
      return X
    if not hasattr(self, "_reason_idx"):
      inj = self.data.injuries.dropna(subset=["gsis_id"]).drop_duplicates(["season", "week", "gsis_id"], keep="last")
      pr = inj.practice_primary_injury.where(inj.practice_primary_injury.notna(), inj.report_primary_injury)
      sc = inj.practice_secondary_injury.where(inj.practice_secondary_injury.notna(), inj.report_secondary_injury)
      self._reason_idx = {(int(s_), int(w), g): self.reason_of(a, b)
                          for s_, w, g, a, b in zip(inj.season, inj.week, inj.gsis_id, pr, sc)}
    gid = rows.gsis_id if "gsis_id" in rows else pd.Series(rows.index, index=rows.index)
    cats = [self._reason_idx.get((int(s_), int(w), g), "none") for g, s_, w in zip(gid, rows.season, rows.week)]
    return X.assign(**{f"why_{c}": [float(x == c) for x in cats] for c in self.REASONS})

  def _with_rest(self, X: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    """EXPERIMENT (injuries.practice_rest; pre-registered 2026-10-16): veteran rest days. 'rest' = 1 when any of the
    week's report / practice injury fields says the player was resting ("Not injury related - resting player"), so a
    rest DNP stops reading like an injury DNP (owner: Keenan Allen, 34). practice_rest = "age" also adds his age at the
    start of the season (rosters' birth date; NaN when unknown, which the trees handle)."""
    X = self._with_tprior(self._with_prev(self._with_reason(X, rows), rows), rows)
    mode = self.cfg.get("injuries", {}).get("practice_rest")
    if not mode:
      return X
    if not hasattr(self, "_rest_idx"):
      inj = self.data.injuries.dropna(subset=["gsis_id"])
      txt = inj[["report_primary_injury", "report_secondary_injury", "practice_primary_injury",
                 "practice_secondary_injury"]].fillna("").astype(str).agg(" ".join, axis=1).str.lower()
      r = inj[txt.str.contains("resting")]
      self._rest_idx = set(zip(r.season.astype(int), r.week.astype(int), r.gsis_id))
      ro = self.data.rosters.dropna(subset=["gsis_id", "birth_date"])
      self._born = pd.to_datetime(ro.drop_duplicates("gsis_id", keep="last").set_index("gsis_id").birth_date, errors="coerce")
    gid = rows.gsis_id if "gsis_id" in rows else pd.Series(rows.index, index=rows.index)
    X = X.assign(rest=[float((int(s_), int(w), g) in self._rest_idx) for g, s_, w in zip(gid, rows.season, rows.week)])
    if mode == "age":
      b = gid.map(self._born)
      start = pd.to_datetime(rows.season.astype(int).astype(str) + "-09-01")
      X = X.assign(age=((start - pd.to_datetime(b.values)).dt.days / 365.25).to_numpy(float))
    return X

  def practice_prob(self, rows: pd.DataFrame, final: bool = True) -> np.ndarray:
    """P(plays) from the practice sequence. final=False (his team's final report isn't out): 1-2 published days
    use the partial-week model for that many days."""
    X = self._with_rest(self._with_role(practice_features(rows), rows), rows)[self.practice_cols]
    p = self.practice_model.predict_proba(X)[:, 1]
    if not final and getattr(self, "partial_models", None):
      n = rows.days.fillna("").str.replace("?", "", regex=False).str.len().to_numpy()
      for k, m in self.partial_models.items():
        if (n == k).any():
          p = np.where(n == k, m.predict_proba(X)[:, 1], p)
    return np.where(rows.game_status.to_numpy() == "OUT", 0.0, p)

  def final_report_teams(self, days: pd.DataFrame, season: int, week: int) -> set:
    """Teams whose final report for the week is out: someone on it has a game status, or it has 3 practice days.
    days: this week's practice rows indexed by gsis_id."""
    r = self.data.rosters
    r = r[(r.season == season) & (r.week <= week)].sort_values("week").drop_duplicates("gsis_id", keep="last")
    team = days.index.map(dict(zip(r.gsis_id, r.team)))
    has_gs = days.game_status.fillna("None").astype(str).isin(["None", "nan", ""]).__invert__()
    long = days.days.fillna("").str.len() >= 3
    t = pd.DataFrame({"team": team, "fin": (has_gs | long).to_numpy()}).dropna(subset=["team"])
    fin = set(t[t.fin].team)
    # (AP, {#calendar-stage}) the week clock: a team's final report is out once its third report day's 4 p.m. ET
    # deadline has passed (nfledge/week_clock.py, per team; Thursday / Monday / Saturday games included). The rule
    # above was sometimes late (nobody listed all week), never early: Brier 0.173 -> 0.108 on those rows, 2021-25.
    from .week_clock import Clock
    fin |= Clock(self.data.schedules).final_report_teams(season, week)
    return fin

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
  def _design(recv: pd.DataFrame, vac: pd.DataFrame, share: str, snap: bool = False) -> np.ndarray:
    """recv: teammates (team, pos, rank, s_norm). vac: absences (team, pos, eff_vac). One column per
    (missing pos, receiving pos, rank) plus (missing pos, receiving pos, share-weighted); with snap, one more per
    (missing pos, receiving pos), snap-weighted, after all of those (absorption_table reads the first ones)."""
    cols, extra = [], []
    v = vac.groupby(["team", "pos"]).eff_vac.sum()
    for m in MISSING[share]:
      vm = recv.team.map(v.xs(m, level="pos") if m in v.index.get_level_values("pos") else pd.Series(dtype=float))
      vm = vm.fillna(0.0).to_numpy()
      for r in RECV:
        isr = (recv.pos == r).to_numpy()
        for k in RANKS:
          cols.append(vm * isr * (np.minimum(recv["rank"].to_numpy(), 3) == k))
        cols.append(vm * isr * recv.s_norm.to_numpy())
        if snap:
          extra.append(vm * isr * recv.snap_norm.to_numpy())
    return np.column_stack(cols + extra)

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
    if "snap_pct" in d:
      sp = d.snap_pct.astype(float).fillna(0.0)
      st = sp.groupby([d.team, d.pos]).transform("sum")
      d["snap_norm"] = np.where(st > 0, sp / st.replace(0, np.nan), 1.0 / n)
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
          X[share].append(self._design(rv, vac, share, self.absorb_snap))
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
    rg = r[r.status.isin(["ACT", "INA"])].merge(tg, on=["week", "team"])[["week", "team", "gsis_id", "pos", "years_exp", "status"]]
    rg = rg.drop_duplicates(["week", "gsis_id"])
    rg = rg.merge(tg, on=["week", "team"], how="left")
    played, observable = self._played_sets()
    # (AY3, owner 2026-10-18: "0 snaps has never meant injured ... lots of players are active and don't play"; "it
    # shouldn't conflate availability with healthy scratches at all"): scratch_label = "dressed" makes the label the
    # game-day active list (ACT vs INA on the weekly roster, 2019 on), not "took a snap", and the history features
    # dressed weeks; a dressed backup who never plays is no longer a scratch.
    dressed_label = self.cfg.get("injuries", {}).get("scratch_label") == "dressed"
    if dressed_label:
      rg["active"] = (rg.status == "ACT").to_numpy()
      ina_teams = set(zip(r[r.status == "INA"].week, r[r.status == "INA"].team))  # weeks whose inactives are posted
      rg["observable"] = [(w, t) in ina_teams for w, t in zip(rg.week, rg.team)]
    else:
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
    if dressed_label:
      observed = rg.observable.astype(bool)  # the week's game-day inactive list is published
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
    rg["hist_w"], rg["act_w"] = hist.to_numpy(), act.to_numpy()  # this week's own history counts (next season's seed)
    # EXPERIMENT (injuries.scratch_carry; pre-registered 2026-10-15): a player with no games yet this season starts
    # from last season's totals, so week 1 isn't "no history" for everyone (every starting QB got 70% active).
    carry = self.cfg.get("injuries", {}).get("scratch_carry")
    if carry and (season - 1) in self.data.seasons:
      tabs = self.__dict__.setdefault("_scratch_tables", {})  # previous seasons' tables, built once
      prev = tabs.get(season - 1)
      if prev is None:
        prev = tabs[season - 1] = self.scratch_table(season - 1)
      pv = prev.sort_values("week")
      pv_hist = pv[pv.hist_w == 1]
      agg = pd.DataFrame({
        "n": pv.groupby("gsis_id").hist_w.sum(), "a": pv.groupby("gsis_id").act_w.sum(),
        "snap": pv_hist[pv_hist.act_w == 1].groupby("gsis_id").snap.mean(),
        "last": pv_hist.groupby("gsis_id").act_w.last()})
      seed = rg.n_prev == 0
      if carry == "week1":  # v2: only each team's first game of the season; training unchanged
        seed &= rg.week == rg.groupby("team").week.transform("min")
      m = rg.gsis_id.map(agg.n).fillna(0)
      use = seed & (m > 0)
      rg.loc[use, "n_prev"] = m[use]
      rg.loc[use, "act_prev"] = rg.gsis_id.map(agg.a)[use]
      rg.loc[use, "act_rate"] = (rg.act_prev[use] + 1) / (rg.n_prev[use] + 1.2)
      rg.loc[use, "snap_avg"] = rg.gsis_id.map(agg.snap)[use].fillna(0)
      rg.loc[use, "played_last"] = rg.gsis_id.map(agg["last"])[use].fillna(-1)
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
    if self.cfg.get("injuries", {}).get("ahead_reserve"):
      # (AV) starters out this week who are no longer on the ACT / INA rows (moved to a reserve list: IR, PUP, NFI), or
      # on the report but off the roster rows: they still stand ahead of their backups (Jalen Hurts on IR, 2026 wk 6).
      # Their snap share = the last one known from earlier weeks.
      res = r[(r.status == "RES") & r.week.isin(rg.week.unique())][["week", "team", "gsis_id", "pos"]]
      inrows = set(zip(rg.week, rg.gsis_id))
      gone = pd.concat([res, rg.iloc[0:0][["week", "team", "gsis_id", "pos"]]])
      rep_out = pd.DataFrame(list(out_rep), columns=["week", "gsis_id"])
      tp = r.drop_duplicates(["gsis_id"], keep="last").set_index("gsis_id")[["team", "pos"]]
      rep_out = rep_out[rep_out.gsis_id.isin(tp.index)].assign(team=lambda z: z.gsis_id.map(tp.team), pos=lambda z: z.gsis_id.map(tp.pos))
      gone = pd.concat([gone, rep_out]).drop_duplicates(["week", "gsis_id"])
      gone = gone[[(w, g) not in inrows for w, g in zip(gone.week, gone.gsis_id)]]
      hist_sa = rg[rg.snap_avg > 0][["week", "gsis_id", "snap_avg"]].sort_values("week")
      by_g = {g: list(zip(x.week, x.snap_avg)) for g, x in hist_sa.groupby("gsis_id")}
      def last_sa(g, w):
        v = [sa for ww, sa in by_g.get(g, []) if ww <= w]
        return v[-1] if v else None
      extra = [(w, t, p_, last_sa(g, w)) for w, t, p_, g in zip(gone.week, gone.team, gone.pos, gone.gsis_id)]
      extra = pd.DataFrame([e for e in extra if e[3] is not None], columns=["week", "team", "pos", "snap_avg"])
      if len(extra):
        add = extra.groupby(["week", "team", "pos"]).snap_avg.apply(list)
        out_snap = pd.concat([out_snap, add]).groupby(level=[0, 1, 2]).sum()
    rg["ahead_out"] = [sum(1 for x in out_snap.get((w, t, p), []) if x > sa + 0.05)
                       for w, t, p, sa in zip(rg.week, rg.team, rg.pos, rg.snap_avg)]
    rg["qb_pick"] = self._qb_picks(rg)
    rg["rookie"] = (pd.to_numeric(rg.years_exp, errors="coerce").fillna(1) == 0).astype(int)
    for p_ in ("QB", "RB", "WR", "TE"):
      rg[f"is_{p_}"] = (rg.pos == p_).astype(int)
    rg["season"] = season
    if self.cfg.get("injuries", {}).get("job_security"):
      self._job_security(rg, season)
    if self.cfg.get("injuries", {}).get("stakes_scratch"):
      # EXPERIMENT (INSIGHTS (L2)): the team's playoff / division / bye odds as of the week + the week number, so
      # rested healthy starters (a clinched seed in week 18) stop looking like any other week
      from pathlib import Path
      from .tuesday import add_stakes
      f = Path(__file__).resolve().parent.parent / self.cfg["data"]["cache_dir"] / "playoff_odds_weekly.parquet"
      odds = pd.read_parquet(f) if f.exists() else pd.DataFrame(columns=["season", "week", "team", "p_playoffs", "p_div", "p_bye"])
      rg = add_stakes(rg, odds)
    return rg

  JOB_COLS = ["incumbent", "perf_pct", "r1_behind", "win_pct", "cap_pct", "last_week"]

  def _job_security(self, rg: pd.DataFrame, season: int):
    """EXPERIMENT (injuries.job_security; pre-registered 2026-10-16, tools/job_security.py): in place, what makes a
    healthy starter lose the job: incumbent (started his team's first game: QB 70%+ snaps, others led the position
    group), season-to-date EPA per opportunity percentile at his position, a first-round rookie at his position on
    the roster, team win % before the week, his contract's APY share of the cap, the team's last regular-season week."""
    from .config import ROOT
    d, L = self.data, self.pm.ledger
    Ls = L[L.season == season]
    # incumbent
    first = Ls.groupby("team").week.transform("min") == Ls.week
    f0 = Ls[first].assign(pos=Ls[first].gsis_id.map(self.pm.info.position).replace({"FB": "RB", "HB": "RB"}))
    lead = f0.groupby(["team", "pos"]).offense_pct.transform("max")
    inc = f0[((f0.pos == "QB") & (f0.offense_pct >= 0.7)) | ((f0.pos != "QB") & (f0.offense_pct >= 0.5) & (f0.offense_pct >= lead - 1e-9))]
    rg["incumbent"] = rg.gsis_id.isin(set(inc.gsis_id)).astype(float)
    # season-to-date EPA per opportunity, as of the week (games before it)
    e = Ls.assign(epa=Ls.db_epa.fillna(0) + Ls.rush_epa.fillna(0) + Ls.tgt_epa.fillna(0),
                  opp=Ls.db.fillna(0) + Ls.carries.fillna(0) + Ls.tgt.fillna(0)).groupby(["gsis_id", "week"])[["epa", "opp"]].sum()
    e = e.reset_index().sort_values(["gsis_id", "week"])
    e["ce"], e["co"] = e.groupby("gsis_id").epa.cumsum(), e.groupby("gsis_id").opp.cumsum()
    look = {}
    for g, x in e.groupby("gsis_id"):
      look[g] = (x.week.to_numpy(), x.ce.to_numpy(), x.co.to_numpy())
    perf = []
    for g, w in zip(rg.gsis_id, rg.week):
      z = look.get(g)
      n = int(np.searchsorted(z[0], w)) if z is not None else 0  # games before this week
      perf.append(z[1][n - 1] / max(z[2][n - 1], 1.0) if n and z[2][n - 1] >= 10 else np.nan)
    rg["perf"] = perf
    rg["perf_pct"] = rg.groupby(["week", "pos"]).perf.rank(pct=True).fillna(0.5)
    rg.drop(columns=["perf"], inplace=True)
    # a first-round rookie at his position on the roster that week (not him)
    r = d.rosters[(d.rosters.season == season) & d.rosters.gsis_id.notna()]
    r = r[(pd.to_numeric(r.years_exp, errors="coerce") == 0) & (pd.to_numeric(r.draft_number, errors="coerce") <= 32)]
    r = r.assign(team=r.team.replace({"LAR": "LA"}), pos=r.position.replace({"FB": "RB", "HB": "RB"}))
    rk = r.groupby(["week", "team", "pos"]).gsis_id.apply(set).to_dict()
    last_r = int(r.week.max()) if len(r) else 0
    rg["r1_behind"] = [float(bool(rk.get((min(w, last_r), t_, p_), set()) - {g})) for w, t_, p_, g in zip(rg.week, rg.team, rg.pos, rg.gsis_id)]
    # team win % before the week
    sch = d.schedules[(d.schedules.season == season) & (d.schedules.game_type == "REG") & d.schedules.home_score.notna()]
    res = pd.concat([pd.DataFrame({"week": sch.week, "team": sch.home_team, "w": (sch.home_score > sch.away_score) + 0.5 * (sch.home_score == sch.away_score)}),
                     pd.DataFrame({"week": sch.week, "team": sch.away_team, "w": (sch.away_score > sch.home_score) + 0.5 * (sch.home_score == sch.away_score)})])
    res["team"] = res.team.replace({"LAR": "LA"})
    wins = {(t_, w): float(x[x.week < w].w.mean()) if (x.week < w).any() else 0.5 for t_, x in res.groupby("team") for w in range(1, 23)}
    rg["win_pct"] = [wins.get((t_, w), 0.5) for t_, w in zip(rg.team, rg.week)]
    # contract: APY share of the cap for the deal in force this season (cached by tools/player_logs.py)
    cp = getattr(self, "_contracts", None)
    if cp is None:
      try:
        cp = pd.read_parquet(ROOT / self.cfg["data"]["cache_dir"] / "contracts_all.parquet")
      except Exception:
        cp = pd.DataFrame(columns=["gsis_id", "year_signed", "last_year", "apy_cap_pct"])
      self._contracts = cp
    c = cp.dropna(subset=["gsis_id", "year_signed"])
    c = c[(c.year_signed <= season) & (c.last_year.fillna(c.year_signed) >= season)].sort_values("year_signed")
    cap = c.drop_duplicates("gsis_id", keep="last").set_index("gsis_id").apy_cap_pct
    rg["cap_pct"] = rg.gsis_id.map(cap).fillna(0.0).astype(float)
    # last regular-season week (rest games)
    last_wk = int(d.schedules[(d.schedules.season == season) & (d.schedules.game_type == "REG")].week.max())
    rg["last_week"] = (rg.week == last_wk).astype(float)

  @property
  def scratch_cols(self):
    g = self.cfg.get("injuries", {})
    return (self.SCRATCH_COLS + (self.JOB_COLS if g.get("job_security") else [])
            + (["st_po", "st_div", "st_bye", "wk"] if g.get("stakes_scratch") else []))

  SCRATCH_COLS = ["n_prev", "act_rate", "played_last", "snap_avg", "rank", "ahead_out", "rookie", "is_QB", "is_RB",
                  "is_WR", "is_TE"]

  def _fit_scratch(self, seasons):
    """Gradient-boosted P(active | not on injury report) from as-of role/history features."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    rows = []
    for s in seasons:
      t = self.scratch_table(s)
      first = 1 if self.cfg.get("injuries", {}).get("scratch_carry") is True else 2  # v1 trained on week 1 too
      rows.append(t[t.final & (t.week <= self.data.completed_weeks(s)) & ~t.on_report & t.observable & (t.week >= first)])
    d = pd.concat(rows)
    self.scratch_model = HistGradientBoostingClassifier(**self._gb_params(), random_state=0).fit(
      d[self.scratch_cols], d.active)
    self._scratch_cache = {}

  def scratch_prob(self, season: int, week: int) -> pd.Series:
    if season not in self._scratch_cache:
      self._scratch_cache[season] = self.scratch_table(season)
    t = self._scratch_cache[season]
    t = t[t.week == week]
    p = pd.Series(self.scratch_model.predict_proba(t[self.scratch_cols])[:, 1], index=t.gsis_id.to_numpy())
    rate = self.cfg.get("injuries", {}).get("nextup_qb")
    if rate is not None:  # (AY4, {#nextup-qb2}) the promoted backup QB (dressed as the backup, starter out): the measured inactive rate
      m = self.nextup_rows(t).to_numpy()
      p[m] = 1.0 - float(rate)
    return p

  @staticmethod
  def _qb_picks(rg: pd.DataFrame) -> list:
    """(AY4) each team-week's starting QB from what was known before the game (owner 2026-10-18: backups' snaps say
    nothing; who dressed does): last game's starter (the most snaps, 30%+) if he is healthy this week ("starter"); else
    the healthy QBs who dressed as his backups last game (game-day active), best depth rank first ("promoted").
    Healthy = not out and not on the injury report. Rows: "starter" / "promoted" for the pick, "" otherwise."""
    q = rg[rg.is_QB == 1] if "is_QB" in rg else rg[rg.pos == "QB"]
    pick = {}
    for team, g in q.groupby("team"):
      wks = sorted(g.week.unique())
      for i in range(1, len(wks)):
        prev, cur = g[g.week == wks[i - 1]], g[g.week == wks[i]]
        healthy = set(cur[~cur.is_out & ~cur.on_report].gsis_id)
        top = prev.sort_values("snap", ascending=False)
        starter = top.gsis_id.iloc[0] if len(top) and top.snap.fillna(0).iloc[0] > 0.3 else None
        if starter in healthy:
          pick[(wks[i], team)] = (starter, "starter")
          continue
        dressed = set(prev[prev.status == "ACT"].gsis_id) - {starter}
        cand = cur[cur.gsis_id.isin(dressed & healthy)].sort_values("rank")
        if len(cand):
          pick[(wks[i], team)] = (cand.gsis_id.iloc[0], "promoted")
    return [pick[(w, t)][1] if pick.get((w, t), (None,))[0] == g else ""
            for w, t, g in zip(rg.week, rg.team, rg.gsis_id)]

  @staticmethod
  def nextup_rows(t: pd.DataFrame) -> pd.Series:
    """(AY4) the promoted backup QB: his team's starter is out and he dressed as the backup last game (_qb_picks)."""
    return t.get("qb_pick", pd.Series("", index=t.index)) == "promoted"

  # -- application -----------------------------------------------------------------------------------------------
  espn_bridge: dict | None = None  # gsis_id -> ESPN bucket (live week only; see espn.py / espn_calib.py)
  espn_rates: dict | None = None  # bucket -> learned P(active) (espn_calib.learned_rates); None = carry-forward rates
  espn_midweek: dict | None = None  # gsis_id -> ESPN bucket ruled after his team's report started (build_espn_bridge)
  espn_questionable: dict | None = None  # gsis_id -> "Questionable": fresh ESPN Q, display only (availability)
  espn_gameday: dict | None = None  # (AU) gsis_id -> ("INA" | "ACT", time): game-day rulings (espn.gameday_rulings)

  def midweek_ruling(self, gsis_id: str, game_status) -> tuple[float, str] | None:
    """A fresh ESPN Out / IR for a player on this week's practice report, before his final game status: its measured
    play rate (espn_calib.MIDWEEK) and label, or None. The final report's status (Friday) takes over again."""
    from .espn_calib import MIDWEEK
    b = (self.espn_midweek or {}).get(gsis_id)
    if b is None or b not in MIDWEEK or str(game_status) not in ("None", "", "nan"):
      return None
    return float(MIDWEEK[b]["p"]), {"IR": "IR (ESPN)", "Doubtful": "Doubtful (ESPN)"}.get(b, "Out (ESPN)")

  def tuesday_probs(self, season: int, week: int) -> dict:
    """gsis -> (P(plays), status label, plain-English why) from the Tuesday model, for players whose team's game this
    week is next after one he was listed for or hurt in (nfledge/tuesday.py). Built once, trained on every row whose
    outcome is known before this week."""
    from . import tuesday as T
    r = self._tues_table()
    if not len(r):
      return {}
    train = r[r.y.notna() & ((r.season < season) | ((r.season == season) & (r.week < week)))]
    now = r[(r.season == season) & (r.week == week) & r.y.isna()]
    if "aug" in now.columns:
      now = now[now.aug == 0]  # (CN) the 2-week rows only train
    if len(train) < 1000 or not len(now):
      return {}
    pr_ = T.fit(train).predict_proba(T.features(now))[:, 1]
    words = {"D": "DNP", "L": "limited", "F": "full"}
    out = {}
    for x, v in zip(now.itertuples(), pr_):
      if x.pop == "A":
        lab = f"{x.status} last wk" if x.status != "None" else "On report last wk"
      else:
        lab = "Hurt last game" if x.hurt_in_game else "Left last game early"
      bits = []
      if x.pop == "A":
        bits.append(f"{x.status if x.status != 'None' else 'no game status'} last week"
                    + (f" (practice {', '.join(words[c] for c in 'DLF' for _ in range(int(getattr(x, 'n_' + c))))})" if x.n_D + x.n_L + x.n_F else ""))
      if x.played_last:
        sh = f"played last game, {round(100 * x.last_pct)}% of snaps" + (f" vs his usual {round(100 * x.usual_pct)}%" if x.usual_pct == x.usual_pct else "")
        bits.append(sh + ((", injured during it, then returned" if getattr(x, "hurt_back", 0) == 1 else ", injury noted during it")
                          if x.hurt_in_game else ""))
      else:
        bits.append(f"missed his last {int(x.missed_run)} game{'s' if x.missed_run > 1 else ''}" if x.missed_run else "did not play last game")
      out[x.gsis_id] = (float(v), lab, "Before this week's first injury report: " + "; ".join(bits)
                        + ". How players in that spot played the next game (Tuesday model)")
    return out

  def availability(self, p: pd.DataFrame, season: int, week: int) -> pd.DataFrame:
    inj = self.data.injuries
    inj = inj[(inj.season == season) & (inj.game_type == "REG")].dropna(subset=["gsis_id"])
    cur = inj[inj.week == week]
    prev = inj[inj.week == week - 1]
    published = published_teams(self.data, season, week)
    p = p.copy()
    p["avail"], p["status"], p["partial_week"], p["on_report"] = 1.0, "", False, False
    p["tuesday"] = ""  # report.inactive_why: why the Tuesday model says what it says
    tues = None
    # (BE2) reserve-list players whose practice window is open (returns.window_open): rated by the week model, which
    # was tested on them; the midweek ESPN IR rate (built for active players newly placed on IR) doesn't override it
    wo = set()
    if self.cfg.get("injuries", {}).get("reserve_rows") and self.cfg.get("injuries", {}).get("week_model"):
      from .returns import window_open
      wo = set(window_open(self.data, week).gsis_id)
    cur_map = cur.set_index("gsis_id")
    prev_map = prev.drop_duplicates("gsis_id").set_index("gsis_id")
    pr = self.data.practice
    use_days = self.practice_model is not None and pr is not None
    if use_days:
      days = pr[(pr.season == season) & (pr.week == week)].drop_duplicates("gsis_id", keep="last").set_index("gsis_id")
      final = self.final_report_teams(days, season, week)
    scratch = self.scratch_prob(season, week)
    p["scratch_avail"] = p.gsis_id.map(scratch).fillna(1.0)
    # display only (owner 2026-10-18: Tyler Warren showed one "LP" labelled Wednesday): each team's report days from the
    # calendar (practice_calendar: fixed by game day, plus any extra day it filed), so a player first listed Friday reads
    # "FFL" (off the report before then = practiced fully); days not reached yet are left off. The model reads x.days.
    team_dates, filed = {}, {}
    if use_days and "dates" in days:
      from .practice_calendar import team_report_days
      filed = {t: set(v) for t, v in self.filed_dates(season, week).items()}
      cal = team_report_days(self.data.schedules, season, week, filed)
      # a day counts once HIS TEAM's report for it is in our data (2026-10-21, Tyler Warren: any team's report used to
      # count, so Indianapolis' Wednesday read "full" for everyone before it arrived; he had not practiced)
      team_dates = {t: [d for d in ds if d in filed.get(t, set())] for t, ds in cal.items()}

    def shown(x, team) -> str:
      dd, ds = str(x.days.iloc[0] or "").replace("?", ""), [d for d in str(x.dates.iloc[0] or "").split(",") if d] if "dates" in x else []
      allds = list(team_dates.get(team, []))
      if not dd or len(ds) != len(dd) or not allds:
        return dd
      on = dict(zip(ds, dd))
      # a report day he isn't listed on = full participation (owner 2026-10-18: "full participation if they're healthy
      # that day and not listed"), before his first listing and after he drops off alike
      return "".join(on.get(d, "F") for d in allds)
    for i, row in p.iterrows():
      p.at[i, "avail"] = p.at[i, "scratch_avail"]  # healthy-scratch risk unless the injury report says more
      if row.team in published and use_days and row.gsis_id in days.index:
        x = days.loc[[row.gsis_id]]
        p.at[i, "avail"] = float(self.practice_prob(x, final=row.team in final)[0])
        if self.cfg.get("injuries", {}).get("week_model") and x.game_status.iloc[0] != "OUT":
          # (I2) the one model: the Tuesday picture + this week's practice so far (stage 1-2) or the final report (3)
          dd = str(x.days.iloc[0] or "").replace("?", "")
          st = 3 if row.team in final else max(1, min(2, len(dd)))
          from . import tuesday as T
          tdays = sorted(filed.get(row.team, set())) if T.STAGE_FROM == "calendar" else []
          ds = [d for d in str(x.dates.iloc[0] or "").split(",") if d] if "dates" in x else []
          if tdays and len(ds) == len(dd):
            # (AS, owner's design call 2026-10-22: "we need to use dates") his line over his team's report days so far,
            # "X" on a day he wasn't listed; stage = how many of the team's report days are in (tuesday.calendar_view)
            on = dict(zip(ds, dd))
            dd = "".join(on.get(d, "X") for d in tdays)
            st = 3 if row.team in final else max(1, min(2, len(tdays)))
          v = self.week_prob([(row.gsis_id, season, week, row.team, row.pos, dd, x.game_status.iloc[0], st)])[0]
          if v == v:
            p.at[i, "avail"] = float(v)
        p.at[i, "partial_week"] = row.team not in final  # report.inactive_why: "practice so far"
        p.at[i, "on_report"] = True  # returns.lookahead_availability starts its chain from this week's chance
        gs = x.game_status.iloc[0]
        label = gs.title() if gs != "None" else ""
        ruled = self.midweek_ruling(row.gsis_id, gs)
        if ruled and not (row.gsis_id in wo and ruled[1].startswith("IR")):
          p.at[i, "avail"], label = ruled
        sd = shown(x, row.team)
        p.at[i, "status"] = label + (f" ({sd})" if sd else "")
        continue
      if row.team in published:
        if row.gsis_id in cur_map.index:
          x = cur_map.loc[[row.gsis_id]].iloc[0]
          rep, prac = _report(x.report_status), _practice(x.practice_status)
          p.at[i, "avail"] = self.prob(rep, prac)
          p.at[i, "status"] = rep if rep != "None" else ""
      elif row.gsis_id in wo:
        # (BE2) window open, before his team's first report of the week: the week model at stage 0
        v = self.week_prob([(row.gsis_id, season, week, row.team, row.pos, "", "None", 0)])[0]
        if v == v:
          p.at[i, "avail"], p.at[i, "status"] = float(v), "IR (practice window open)"
      elif self.espn_bridge and row.gsis_id in self.espn_bridge:
        # This week's report isn't out, but ESPN has injury news from after his last game: its bucket's P(active),
        # learned from how earlier early-week ESPN statuses turned out (espn_calib.py); before any outcomes, the
        # designation's carry-forward rate. IR: out at least 4 games.
        b = self.espn_bridge[row.gsis_id]
        rate = (self.espn_rates or {}).get(b)
        base = "Out" if b == "Out+ret" else b
        # Out with a return date past this game: its own measured rate when there are no learned outcomes yet (1.8%,
        # n 652, {#tags}); the plain-Out carry-forward (~33%) contradicted the O tag this bucket gets (2026-10-22,
        # tools/scenario_audit.py S15)
        fallback = OUT_RET_PRIOR if b == "Out+ret" else self.p_next.get(base, 1.0)
        p.at[i, "avail"] = 0.0 if b == "IR" else float(rate["p"] if rate else fallback)
        p.at[i, "status"] = "Out (ESPN; return date after this game)" if b == "Out+ret" else f"{b} (ESPN)"
      elif self.cfg.get("injuries", {}).get("tuesday") and row.gsis_id in (tues if tues is not None else (tues := self.tuesday_probs(season, week))):
        # Before his team's first report: the Tuesday model (nfledge/tuesday.py; INSIGHTS (G) / (G2))
        pr_, lab, why_ = tues[row.gsis_id]
        p.at[i, "avail"], p.at[i, "status"], p.at[i, "tuesday"] = pr_, lab, why_
      elif row.gsis_id in prev_map.index:
        rep = _report(prev_map.at[row.gsis_id, "report_status"])
        if rep != "None":
          p.at[i, "avail"] = float(self.p_next.get(rep, 1.0))
          p.at[i, "status"] = f"{rep} last wk"
    # (AU, {#gameday}) game-day actives / inactives, once a team's are posted (espn.gameday_rulings, week clock): a
    # declared inactive doesn't play (0 of 3,000+ skill players 2019-25); a Questionable player who dresses played 97.4%
    # (n 1,992), a Doubtful one 28.6% (n 14). Measured rates, nothing fitted. pre_gameday keeps the model's chance for
    # the prospective audit (tools/gameday_audit.py).
    gd = self.espn_gameday or {}
    if gd:
      p["pre_gameday"] = np.nan
      for i, row in p.iterrows():
        r_ = gd.get(row.gsis_id)
        if not r_:
          continue
        st = str(p.at[i, "status"] or "")
        des = st.split("(")[0].strip().lower()
        if r_[0] == "INA":
          p.at[i, "pre_gameday"], p.at[i, "avail"] = p.at[i, "avail"], 0.0
          p.at[i, "status"] = "Inactive" + (f" ({st.split('(', 1)[1]}" if "(" in st else "")
        elif r_[0] == "ACT" and des in ("questionable", "doubtful"):
          p.at[i, "pre_gameday"], p.at[i, "avail"] = p.at[i, "avail"], GAMEDAY_ACTIVE[des]
          p.at[i, "status"] = "Active" + (f" ({st.split('(', 1)[1]}" if "(" in st else "")
    # ESPN's Questionable, shown but not used (owner 2026-10-15: rows showed ESPN's O / D but never its Q): only where
    # there's no designation yet ("" or practice days only) or just last week's; the chance to play is unchanged
    for i, row in p.iterrows():
      st = p.at[i, "status"]
      if row.gsis_id in (self.espn_questionable or {}) and (st == "" or st.startswith(" (") or st.endswith("last wk")):
        p.at[i, "status"] = "Questionable (ESPN)" + (st if st.startswith(" (") else "")
    p["tag"] = self.designations(p, season, week)
    return p

  def filed_dates(self, season: int, week: int) -> dict:
    return filed_dates(self.data, season, week)

  def tag_map(self, season: int, week: int, board: pd.DataFrame | None = None) -> dict:
    """gsis -> designation for every QB / RB / WR / TE / K on a roster (active, game-day inactive or a reserve list),
    bye teams included; the board's own tags (availability) win for its players. Non-empty tags only."""
    ro = self.data.rosters
    ro = ro[(ro.season == season) & (ro.week <= week) & ro.gsis_id.notna()].sort_values("week").drop_duplicates("gsis_id", keep="last")
    ro = ro[ro.position.isin(["QB", "RB", "FB", "WR", "TE", "K"]) & ro.status.isin(["ACT", "INA", "RES"])]
    rows = pd.DataFrame({"gsis_id": ro.gsis_id.to_numpy(), "team": ro.team.replace({"LAR": "LA"}).to_numpy()})
    out = {g: t for g, t in zip(rows.gsis_id, self.designations(rows, season, week)) if t}
    if board is not None and "tag" in board:
      for g, t in zip(board.gsis_id, board.tag):
        if t:
          out[g] = t
        else:
          out.pop(g, None)
    return out

  RESERVE_TAG = {"R01": "IR", "R48": "IR", "R04": "PUP", "R05": "NFI", "R40": "SSPD"}

  def designations(self, p: pd.DataFrame, season: int, week: int) -> list:
    """The injury tag a row shows (owner 2026-10-21: "we should use the official tags"), apart from our chance to play:
      - a reserve list (IR, PUP, NFI, SSPD): its code;
      - game day, once his team's actives / inactives are out (90 min before kickoff): inactive -> O, active -> none;
      - his team's final report: its designation (Q / D / O; listed without one, or not listed -> none);
      - before it (Tuesday -> the final report): Q if he missed his last game hurt (on its report, no snap; not when
        its listed reason was rest or personal) or was hurt in it and not back (the play-by-play's injury note with no
        "has returned to the game" after it; ingame.not_back); once his team's practice reports start, that Q holds
        only while he's on them;
      - O before the final report only when we're confident he sits: ESPN's Out with a return date past this game
        (1.8% played early in the week, n 652; 0 of 43 midweek). A plain ESPN Out (34% played) or Doubtful isn't O.
    Hurt during a game being played now: the page marks him Q live from ESPN's play text (gamecast.js).
    Byes (owner 2026-10-21): "his last game" is his team's last game, wherever the bye fell, and a bye week files no
    report, so a Tuesday Q holds through the bye until his team's first report of the week it plays again.
    p: rows with gsis_id and team."""
    out = [""] * len(p)
    published = published_teams(self.data, season, week)
    pr, days, final = self.data.practice, None, set()
    if pr is not None:
      days = pr[(pr.season == season) & (pr.week == week)].drop_duplicates("gsis_id", keep="last").set_index("gsis_id")
      final = self.final_report_teams(days, season, week)
    ro = self.data.rosters
    ro = ro[(ro.season == season) & (ro.week <= week) & ro.gsis_id.notna()].sort_values("week").drop_duplicates("gsis_id", keep="last")
    res = {g: self.RESERVE_TAG.get(a) for g, st, a in zip(ro.gsis_id, ro.status, ro.get("status_description_abbr", pd.Series("", index=ro.index)))
           if st == "RES" and self.RESERVE_TAG.get(a)}
    gd = self.espn_gameday or {}
    ctx = None
    if hasattr(self, "_week_ctx"):
      ctx = self._week_ctx
    else:
      try:
        from . import tuesday as T
        ctx = self._week_ctx = T._Ctx(self.data, *self._tues_inputs())
      except Exception:  # no Tuesday inputs (offline backtests): the official report alone
        ctx = None

    nb = []

    def not_back() -> set:
      if not nb:
        try:
          from pathlib import Path
          from . import data as D
          from . import tuesday as T
          cache = D.Cache(Path(__file__).resolve().parent.parent / self.cfg["data"]["cache_dir"])
          nb.append(T.hurt_not_back(self.data, cache, season))
        except Exception:  # offline: no in-game rule
          nb.append(set())
      return nb[0]

    def tuesday_q(g, team) -> bool:
      if ctx is None:
        return False
      prev = [x for x in ctx.tw.get((season, team), []) if x < week]
      if not prev:
        return False
      k = prev[-1]
      if (g, season, k) not in ctx.on:  # missed it while on its injury report, for an injury
        return (g, season, k) in ctx.rep and ctx.why.get((season, k, g), "none") not in ("rest", "personal")
      return (g, season, k) in not_back()  # hurt in it and not back

    for j, (i, row) in enumerate(p.iterrows()):
      g, team = row.gsis_id, row.team
      if g in res:
        out[j] = res[g]
        continue
      r_ = gd.get(g)
      if r_:
        out[j] = "O" if r_[0] == "INA" else ""
        continue
      listed = days is not None and team in published and g in days.index
      if team in final:
        gs = str(days.game_status.loc[g]).upper() if listed else "NONE"
        out[j] = {"OUT": "O", "DOUBTFUL": "D", "QUESTIONABLE": "Q"}.get(gs, "")
        continue
      bucket = (self.espn_midweek or {}).get(g) if team in published else (self.espn_bridge or {}).get(g)
      if bucket == "Out+ret":
        out[j] = "O"
        continue
      if team in published and not listed:
        continue  # practice reports out and he isn't on them: practicing fully
      out[j] = "Q" if tuesday_q(g, team) else ""
    return out

  @staticmethod
  def build_espn_bridge(data, season: int, week: int, feed: pd.DataFrame, midweek: bool = False,
                        questionable: bool = False) -> dict:
    """Early-week bridge (see espn.py): gsis_id -> ESPN bucket (espn_calib.bucket: Out / Out+ret / Doubtful / IR)
    for players with an ESPN injury status updated on or after their team's last completed game day, for teams
    whose report for `week` is not out. Empty when there is no feed, or once every report for the week is out.
    midweek=True: the same, for teams whose report IS out, Out / Out+ret / IR only (espn_calib.MIDWEEK): a ruling
    made after practice started, applied to players on the report until their final game status (availability).
    questionable=True: ESPN Questionable, any team, same freshness filter: DISPLAY only (espn_questionable), since
    it adds nothing to the practice days (INSIGHTS sec. 9: played 63%, practice model 58%)."""
    from .espn import STATUS_MAP
    from .espn_calib import MIDWEEK_BUCKETS, bucket
    if feed is None or feed.empty:
      return {}
    inj = data.injuries
    published = published_teams(data, season, week)
    r = data.rosters[(data.rosters.season == season) & data.rosters.espn_id.notna() & data.rosters.gsis_id.notna()]
    r = r.sort_values("week").drop_duplicates("gsis_id", keep="last")
    by_espn = {str(e).split(".")[0]: (g, t if t != "LAR" else "LA") for e, g, t in zip(r.espn_id, r.gsis_id, r.team)}
    s = data.schedules[(data.schedules.season == season) & (data.schedules.game_type == "REG")
                       & (data.schedules.week < week) & data.schedules.home_score.notna()]
    last_day = pd.concat([s[["home_team", "gameday"]].set_axis(["team", "day"], axis=1),
                          s[["away_team", "gameday"]].set_axis(["team", "day"], axis=1)]).groupby("team").day.max()
    w = data.schedules[(data.schedules.season == season) & (data.schedules.week == week)]
    game_day = {**dict(zip(w.home_team, w.gameday)), **dict(zip(w.away_team, w.gameday))}
    from .week_clock import kickoff
    kick = {t: kickoff(d, tm) for t, d, tm in [*zip(w.home_team, w.gameday, w.gametime), *zip(w.away_team, w.gameday, w.gametime)]}
    out = {}
    for x in feed.itertuples():
      rep = ("Questionable" if str(x.status) == "Questionable" else None) if questionable else STATUS_MAP.get(str(x.status))
      hit = by_espn.get(str(x.espn_id))
      if rep is None or hit is None:
        continue
      gsis, team = hit
      if (not questionable and (team in published) != midweek) or team not in last_day.index:
        continue
      upd = pd.to_datetime(x.updated, utc=True, errors="coerce")
      if pd.isna(upd) or upd.tz_convert("America/New_York").date() < pd.Timestamp(last_day[team]).date():
        continue  # news from before his last game: last week's report already covers it
      if kick.get(team) is not None and upd >= kick[team]:
        continue  # posted after this week's kickoff: about his next game (Terry McLaurin, hurt in 2026 week 6's MNF)
      if questionable:
        out[gsis] = rep
        continue
      b = bucket(x.status, getattr(x, "return_date", None), game_day.get(team)) or rep
      if midweek and b not in MIDWEEK_BUCKETS:
        continue
      out[gsis] = b
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
      final = self.final_report_teams(days, season, week) if days is not None else set()
      for _, x in cur.iterrows():
        if self.practice_model is not None and days is not None and x.gsis_id in days.index:
          d = days.loc[[x.gsis_id]]
          ruled = self.midweek_ruling(x.gsis_id, d.game_status.iloc[0])
          out[x.gsis_id] = ruled[0] if ruled else float(self.practice_prob(d, final=x.team in final)[0])
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
    # The backup QB plays when the starter sits (pre-registered 2026-10-16; owner watch list Huntley / Daniels): QB2 (depth
    # 2, not on the injury report) = P(QB1 sits) + P(QB1 plays) x r, r = how often a healthy QB2 plays anyway (relief,
    # blowouts; 0.232 measured 2021-23). Tested 2024-25 on QB2s whose starter had a chance to sit: Brier 0.2283 -> 0.1957
    # (-0.0326 [-0.0562, -0.0093]). The healthy-scratch model scored him as a generic backup unless QB1 was Out / D.
    # (AY3) injury availability apart from the healthy-scratch risk (owner 2026-10-18: "it shouldn't conflate
    # availability with healthy scratches at all"): where only the scratch model spoke (avail is its number), he is
    # healthy (inj_avail 1) with that scratch risk; else the injury models' number, no scratch part. avail itself
    # stays "takes the field" (injury x scratch, the backup-QB rule below): sits, redistribution, starter picks.
    only_scratch = np.isclose(p.avail.astype(float), p.scratch_avail.astype(float)) & ~p.status.fillna("").astype(str).str.startswith("Inactive")
    p["inj_avail"] = np.where(only_scratch, 1.0, p.avail.astype(float))
    p["scratch"] = np.where(only_scratch, 1.0 - p.scratch_avail.astype(float), 0.0)
    r2 = self.cfg.get("injuries", {}).get("qb2_play_rate")
    p["qb2_of"] = ""
    if r2 is not None:
      qb = p[p.pos == "QB"]
      rk = pd.to_numeric(qb.get("depth_rank", pd.Series(np.nan, index=qb.index)), errors="coerce")
      for team, g in qb.groupby("team"):
        q1, q2 = g[rk[g.index] == 1], g[(rk[g.index] == 2) & (g.status.fillna("") == "")]
        if len(q1) == 1 and len(q2):
          a1 = float(q1.avail.iloc[0])
          for i in q2.index:
            p.at[i, "avail"] = (1 - a1) + a1 * float(r2)
            p.at[i, "qb2_of"] = q1.full_name.iloc[0] if "full_name" in q1 else ""
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

    # Two numbers instead of one (owner 2026-10-15: "it's binary, not a spectrum"): for every teammate of a genuinely
    # uncertain player (15-85% to sit), his projection in both worlds, that player plays / sits; each player keeps
    # the pairing that moves him most. The default scenario (his `proj`) is one of the two; nothing is averaged.
    # Up to two pairings per player, biggest swing first (owner 2026-10-16: Coleman showed only "if Palmer sits" while
    # his projection already assumed DJ Moore, 6% to play, sits - the bigger story). Uncertain = 5-95% to play, so a
    # likely-out teammate's "if he plays" world is shown too.
    for k in ("cond", "cond2"):
      p[f"{k}_name"], p[f"{k}_pid"], p[f"{k}_p_sit"], p[f"{k}_plays"], p[f"{k}_sits"] = "", "", np.nan, np.nan, np.nan
    unsure = [(u, False) for _, u in cont[(cont.p_play >= 0.05) & (cont.p_play <= 0.95) & cont.gsis_id.isin(set(p.gsis_id))].iterrows()]
    # (owner 2026-10-20: Lamar Jackson / Tyler Huntley) injured quarterbacks too: their swap runs on the "sits" flag
    # (the backup inherits the dropbacks), not the contributor list; a backup whose chance is the backup-QB rule isn't one
    uq = p0[(p0.pos == "QB") & (p0.qb2_of.fillna("") == "") & p0.inj_avail.between(0.05, 0.95)]
    unsure += [(pd.Series({"gsis_id": x.gsis_id, "team": x.team, "full_name": x.full_name, "p_play": float(x.avail)}), True)
               for x in uq.itertuples()]
    cands = {}  # row -> [(|swing|, name, pid, p_sit, plays, sits)], swings under 0.3 points ignored
    for u, is_qb in unsure:
      alt_p = p0.copy()
      if u.p_play < 0.5:  # benched in the default scenario: the other world is him playing
        alt_p.loc[alt_p.gsis_id == u.gsis_id, "sits"] = False
        alt = self._redistribute(alt_p, sits[sits.gsis_id != u.gsis_id], wind)
        plays, sat = alt.proj, p.proj
      else:  # playing in the default scenario: the other world is him sitting
        alt_p.loc[alt_p.gsis_id == u.gsis_id, "sits"] = True
        alt = self._redistribute(alt_p, sits if is_qb else pd.concat([sits, u.to_frame().T]), wind)
        plays, sat = p.proj, alt.proj
      d = (sat - plays).where((p.team == u.team) & (p.gsis_id != u.gsis_id), 0.0)
      for i in d.index[d.abs() > 0.3]:
        cands.setdefault(i, []).append((abs(float(d[i])), u.full_name, u.gsis_id, 1 - float(u.p_play),
                                        float(plays[i]), float(sat[i])))
    for i, cs in cands.items():
      for k, c in zip(("cond", "cond2"), sorted(cs, key=lambda c: -c[0])):
        p.loc[i, [f"{k}_name", f"{k}_pid", f"{k}_p_sit", f"{k}_plays", f"{k}_sits"]] = list(c[1:])
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
        scale = (rv.pos.map(self.scale).fillna(self.scale.get("default", 1.0)).to_numpy(float)
                 if isinstance(self.scale, dict) else self.scale)
        add = np.clip(self._design(rv, vac, share, self.absorb_snap) @ self.coef[share], 0, None) * scale
        if self.conserve:  # EXPERIMENT (injuries.redistribute_conserve): hand out all of the vacated share
          need = vac.groupby("team").eff_vac.sum()
          got = pd.Series(add, index=rv.index).groupby(rv.team).transform("sum")
          k = rv.team.map(need).fillna(0).to_numpy() / np.where(got.to_numpy() > 0, got.to_numpy(), np.inf)
          add = np.where(got.to_numpy() > 0, add * k, add)
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
