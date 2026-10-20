"""The Tuesday model (owner 2026-10-16; INSIGHTS (G) / (G2), tools/tuesday_eval.py): P(plays this week) before his
team's first injury report of the week, the day fantasy managers set waiver claims.

Replaces the carry-forward (one number per last week's status) for players on their team's last final report, and
covers players hurt in the last game who weren't on it (an in-game injury note, or a snap share 20+ points under
his usual): those were shown healthy until news said otherwise. Gate passed 2021-25: on-report Brier 0.1378 ->
0.1237 (5/5 seasons), hurt-not-listed 0.2032 -> 0.1531 (5/5), every decile within 2.2 points.

A row = (player, his team's game k) -> his team's next regular-season game k+1. Features are what is known on the
Tuesday before k+1: last week's status and practice days, whether he played game k and his snap share there vs his
usual, an in-game injury note, games missed in a row, the episode so far (weeks on the report and every practice
day since the injury first appeared), the listed reason, an extra rest week (bye), position, age.

week_rows / week_features (EXPERIMENT, INSIGHTS (I)): the same "from his last game" block for any (player, game),
plus this week's report as it stands at each stage of the week (0 = Tuesday ... 3 = final report): one model for
every day.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

STATUS = ["Out", "Doubtful", "Questionable", "None"]
SCORE = {"D": 0.0, "L": 0.5, "F": 1.0}
from collections import namedtuple  # noqa: E402

Rep = namedtuple("Rep", "days game_status")  # one final report row
FEATS = ["n_D", "n_L", "n_F", "last_day", "played_last", "last_pct", "usual_pct", "left_early", "hurt_in_game",
         "missed_run", "ep_weeks", "ep_D", "ep_L", "ep_F", "bye", "age"]


def report_rows(d) -> pd.DataFrame:
  """Every final weekly report row with practice days: completed seasons (avail_hist) + this season so far (the
  practice table; team from the injury report)."""
  ah = d.avail_hist.copy() if d.avail_hist is not None else pd.DataFrame()
  parts = [ah[["season", "week", "gsis_id", "position", "game_status", "days", "team"]]] if len(ah) else []
  pr = d.practice
  if pr is not None and len(pr):
    done = set(ah.season.astype(int)) if len(ah) else set()
    cur = pr[~pr.season.astype(int).isin(done)].copy()
    if len(cur):
      inj = d.injuries.dropna(subset=["gsis_id"])
      team = {(int(s), int(w), g): t for s, w, g, t in zip(inj.season, inj.week, inj.gsis_id, inj.team)}
      cur["team"] = [team.get((int(s), int(w), g)) for s, w, g in zip(cur.season, cur.week, cur.gsis_id)]
      parts.append(cur.dropna(subset=["team"])[["season", "week", "gsis_id", "position", "game_status", "days", "team"]])
  out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
  return out.assign(season=out.season.astype(int), week=out.week.astype(int)) if len(out) else out


def hurt_notes(d, cache) -> set:
  """(gsis, season, week) with an in-game injury note (nfledge/ingame.py), for the loaded seasons."""
  import nflreadpy as nfl
  from . import ingame
  out = set()
  seasons = sorted(set(d.snaps.season.dropna().astype(int)))
  for s in seasons:
    rs = cache.get("rosters", s, lambda: nfl.load_rosters_weekly([s]), stale=False)
    n = ingame.load(cache, nfl, s, rs, stale=False) if rs is not None and len(rs) else None
    if n is not None and len(n):
      n = n[(n.season_type == "REG") & n.gsis_id.notna()]
      out |= set(zip(n.gsis_id, n.season.astype(int), n.week.astype(int)))
  return out


def _days(x) -> str:
  return str(x if isinstance(x, str) else "").replace("?", "")


def _gs(x) -> str:
  return {"OUT": "Out", "DOUBTFUL": "Doubtful", "QUESTIONABLE": "Questionable"}.get(str(x).upper(), "None")


class _Ctx:
  """Everything the per-row features look up: snaps, team schedules, reports, reasons, reserve lists, birth dates."""

  def __init__(self, d, rep_rows: pd.DataFrame, hurt: set):
    from .injuries import InjuryModel
    sn = d.snaps.dropna(subset=["gsis_id"])
    self.sn = sn
    v = np.maximum(sn.offense_pct.fillna(0).to_numpy(float), sn.defense_pct.fillna(0).to_numpy(float))
    tot = sn[["offense_snaps", "defense_snaps", "st_snaps"]].fillna(0).sum(axis=1).to_numpy(float)
    snap = pd.DataFrame({"g": sn.gsis_id.to_numpy(), "s": sn.season.astype(int).to_numpy(), "w": sn.week.astype(int).to_numpy(),
                         "pct": v, "on": tot > 0}).groupby(["g", "s", "w"]).agg(pct=("pct", "max"), on=("on", "max"))
    self.pct = snap.pct.to_dict()
    self.on = {k for k, x in snap.on.items() if x}
    self.snap_seasons = set(snap.index.get_level_values(1))
    sch = d.schedules[d.schedules.game_type == "REG"]
    tw, final = {}, set()
    for g in sch.itertuples():
      for t in (g.home_team, g.away_team):
        tw.setdefault((int(g.season), t), []).append(int(g.week))
        if pd.notna(g.home_score):
          final.add((int(g.season), int(g.week), t))
    self.tw, self.final = {k: sorted(x) for k, x in tw.items()}, final
    inj = d.injuries.dropna(subset=["gsis_id"]).drop_duplicates(["season", "week", "gsis_id"], keep="last")
    inj = inj.assign(season=inj.season.astype(int), week=inj.week.astype(int))
    pr = inj.practice_primary_injury.where(inj.practice_primary_injury.notna(), inj.report_primary_injury)
    scd = inj.practice_secondary_injury.where(inj.practice_secondary_injury.notna(), inj.report_secondary_injury)
    self.why = {(s, w, g): InjuryModel.reason_of(a, b) for s, w, g, a, b in zip(inj.season, inj.week, inj.gsis_id, pr, scd)}
    ro = d.rosters.dropna(subset=["gsis_id"])
    rr = ro[ro.status == "RES"]
    self.res = set(zip(rr.gsis_id, rr.season.astype(int), rr.week.astype(int)))
    # (BE) the list a reserve player is on: 1 designated to return (R48), 2 injured reserve (R01), 3 PUP / NFI (R04 /
    # R05), 4 any other reserve code
    code = rr.status_description_abbr.map({"R48": 1.0, "R01": 2.0, "R04": 3.0, "R05": 3.0}).fillna(4.0) \
      if "status_description_abbr" in rr else pd.Series(4.0, index=rr.index)
    self.res_code = dict(zip(zip(rr.gsis_id, rr.season.astype(int), rr.week.astype(int)), code))
    last = ro.drop_duplicates("gsis_id", keep="last").set_index("gsis_id")
    self.born = pd.to_datetime(last.birth_date, errors="coerce")
    self.pos_of = last.position.replace({"FB": "RB", "HB": "RB"}).to_dict()  # (I2) rows with no position recorded
    # plain records (pandas' row tuples can't be pickled, and the engine is cached with pickle)
    self.rep = {(r.gsis_id, r.season, r.week): Rep(r.days, r.game_status) for r in rep_rows.itertuples()}
    self.hurt = hurt

  def block(self, g, s: int, team: str, k: int | None, k1: int) -> dict:
    """The Tuesday block for game k1: what is known from his previous team game k (None: no earlier game)."""
    weeks = self.tw.get((s, team), [])
    prev = [x for x in weeks if k is not None and x <= k]
    r = self.rep.get((g, s, k)) if k is not None else None
    days = _days(r.days) if r is not None else ""
    played_k = k is not None and (g, s, k) in self.on
    run = 0
    for x in reversed(prev):
      if (g, s, x) in self.on:
        break
      run += 1
    usual = [self.pct.get((g, s, x)) for x in prev[:-1] if (g, s, x) in self.on][-3:]
    usual = float(np.mean(usual)) if usual else np.nan
    ep_w, ep_days = 0, ""
    for x in reversed(prev):
      e = self.rep.get((g, s, x))
      if e is None:
        break
      ep_w += 1
      ep_days = _days(e.days) + ep_days
    bd = self.born.get(g)
    lp = self.pct.get((g, s, k), 0.0) if played_k else 0.0
    return {"status": _gs(r.game_status) if r is not None else "None",
            "n_D": days.count("D"), "n_L": days.count("L"), "n_F": days.count("F"),
            "last_day": SCORE.get(days[-1], np.nan) if days else np.nan,
            "played_last": float(played_k) if k is not None else np.nan, "last_pct": lp, "usual_pct": usual,
            "left_early": (usual - lp) if played_k and usual == usual else np.nan,
            "hurt_in_game": float(k is not None and (g, s, k) in self.hurt), "missed_run": float(min(run, 4)),
            "ep_weeks": float(min(ep_w, 8)), "ep_D": ep_days.count("D"), "ep_L": ep_days.count("L"), "ep_F": ep_days.count("F"),
            "why": self.why.get((s, k, g), "none") if k is not None else "none", "bye": float(k is not None and k1 - k > 1),
            "age": (pd.Timestamp(f"{s}-09-01") - bd).days / 365.25 if pd.notna(bd) else np.nan}

  def reserve(self, g, s: int, team: str, k: int | None) -> dict:
    """(BE) on a reserve list at his previous team game k: the list and how many team weeks in a row (capped 17)."""
    if k is None or (g, s, k) not in self.res:
      return {"res_prev": 0.0, "res_code": 0.0, "res_weeks": 0.0}
    n = 0
    for x in reversed([x for x in self.tw.get((s, team), []) if x <= k]):
      if (g, s, x) not in self.res:
        break
      n += 1
    return {"res_prev": 1.0, "res_code": float(self.res_code.get((g, s, k), 4.0)), "res_weeks": float(min(n, 17))}

  def label(self, g, s: int, team: str, w: int) -> float:
    return float((g, s, w) in self.on) if (s, w, team) in self.final else np.nan


def _hurt_unlisted(ctx: _Ctx) -> pd.DataFrame:
  """(G2) players hurt in game k while not on its report: in-game note, or 20+ points under his usual (>= 30%)."""
  sn = ctx.sn
  snd = sn.assign(season=sn.season.astype(int), week=sn.week.astype(int)).sort_values(["gsis_id", "season", "week"])
  snd = snd.assign(v=np.maximum(snd.offense_pct.fillna(0), snd.defense_pct.fillna(0)))
  snd["usual"] = snd.groupby(["gsis_id", "season"]).v.transform(lambda z: z.shift().rolling(3, min_periods=1).mean())
  b = snd[(snd.v > 0) & ~pd.Series([(g, s_, w) in ctx.rep for g, s_, w in zip(snd.gsis_id, snd.season, snd.week)], index=snd.index)]
  b = b[np.array([(g, s_, w) in ctx.hurt for g, s_, w in zip(b.gsis_id, b.season, b.week)]) | ((b.usual >= 0.3) & (b.usual - b.v >= 0.2))]
  return pd.DataFrame({"season": b.season, "week": b.week, "gsis_id": b.gsis_id, "team": b.team, "position": b.position,
                       "game_status": "None", "days": "", "pop": "B"})


def build_rows(d, rep_rows: pd.DataFrame, hurt: set) -> pd.DataFrame:
  """Tuesday rows for every (player, game k) on a final report or hurt in game k while not on it. y = any snap in
  game k+1 (NaN when k+1 hasn't been played: the rows to predict)."""
  ctx = _Ctx(d, rep_rows, hurt)
  rows = []
  for r in pd.concat([rep_rows.assign(pop="A"), _hurt_unlisted(ctx)], ignore_index=True).itertuples():
    s, k, g, team = int(r.season), int(r.week), r.gsis_id, {"LAR": "LA"}.get(r.team, r.team)
    nxt = [x for x in ctx.tw.get((s, team), []) if x > k]
    if s not in ctx.snap_seasons or not nxt or (g, s, k) in ctx.res or (s, k, team) not in ctx.final:
      continue
    k1 = nxt[0]
    rows.append({"season": s, "week": k1, "from_week": k, "gsis_id": g, "team": team, "pos": r.position, "pop": r.pop,
                 **ctx.block(g, s, team, k, k1), "y": ctx.label(g, s, team, k1)})
  return pd.DataFrame(rows)


def features(x: pd.DataFrame) -> pd.DataFrame:
  from .injuries import InjuryModel
  f = x[FEATS].astype(float).copy()
  for st in STATUS:
    f[f"st_{st}"] = (x.status == st).astype(float)
  for p in ("QB", "RB", "WR", "TE"):
    f[f"pos_{p}"] = (x.pos == p).astype(float)
  for c in InjuryModel.REASONS + ["none"]:
    f[f"why_{c}"] = (x.why == c).astype(float)
  return f


# Gradient-boosting settings of the Tuesday model and the one-for-every-day week model (INSIGHTS (AA) tests them)
TUE_GB = dict(max_iter=300, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=40, l2_regularization=1.0)
WEEK_GB = dict(max_iter=400, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=40, l2_regularization=1.0)


def fit(rows: pd.DataFrame):
  from sklearn.ensemble import HistGradientBoostingClassifier
  t = rows.dropna(subset=["y"])
  return HistGradientBoostingClassifier(**TUE_GB, random_state=0).fit(features(t), t.y)


# ---- EXPERIMENT (I): one model for every day of the week ----------------------------------------------------------
STAGES = (0, 1, 2, 3)  # 0 = Tuesday (no report yet), 1 = Wednesday, 2 = Thursday, 3 = final report


def week_rows(d, rep_rows: pd.DataFrame, hurt: set, reserve: bool = False) -> pd.DataFrame:
  """(player, game w) for everyone on game w's final report or in the Tuesday population for game w, at each stage
  of the week: the Tuesday block (from his previous game) + this week's report as it stood at that stage.
  reserve (BE): a player on a reserve list at his previous game is a row too when his practice window is visibly open
  (stage 0: on his previous week's report; stages 1-3: on this week's), with the res_* inputs."""
  ctx = _Ctx(d, rep_rows, hurt)
  targets = {}
  for r in rep_rows.itertuples():
    targets[(r.gsis_id, int(r.season), int(r.week))] = ({"LAR": "LA"}.get(r.team, r.team), r.position)
  for r in pd.concat([rep_rows.assign(pop="A"), _hurt_unlisted(ctx)], ignore_index=True).itertuples():
    s, k, team = int(r.season), int(r.week), {"LAR": "LA"}.get(r.team, r.team)
    nxt = [x for x in ctx.tw.get((s, team), []) if x > k]
    if nxt:
      targets.setdefault((r.gsis_id, s, nxt[0]), (team, r.position))
  rows = []
  for (g, s, w), (team, pos) in targets.items():
    pos = pos if isinstance(pos, str) and pos else ctx.pos_of.get(g, "")
    if s not in ctx.snap_seasons or (s, w, team) not in ctx.final:
      continue
    prev = [x for x in ctx.tw.get((s, team), []) if x < w]
    k = prev[-1] if prev else None
    on_res = k is not None and (g, s, k) in ctx.res
    if on_res and not reserve:
      continue  # already on a reserve list: the return-timing model's job
    base = {"season": s, "week": w, "gsis_id": g, "team": team, "pos": pos, **ctx.block(g, s, team, k, w),
            "y": ctx.label(g, s, team, w), **(ctx.reserve(g, s, team, k) if reserve else {})}
    now = ctx.rep.get((g, s, w))
    if on_res and now is None and (g, s, k) not in ctx.rep:
      continue  # window not visibly open at any stage
    days_now, gs_now = (_days(now.days), _gs(now.game_status)) if now is not None else ("", "None")
    why_now = ctx.why.get((s, w, g), "none") if now is not None else "none"
    for st in STAGES:
      if 0 < st < 3 and len(days_now) < 3:
        continue  # a short report week (Thursday game) has no separate Wednesday / Thursday stage
      if on_res and (now is None if st > 0 else (g, s, k) not in ctx.rep):
        continue  # (BE) only once his window is visible at this stage
      seen = days_now if st == 3 else days_now[:st] if st else ""
      on_now = float(now is not None and st > 0)
      rows.append({**base, "stage": st, "on_now": on_now, "days_now": seen,
                   "wn_D": seen.count("D"), "wn_L": seen.count("L"), "wn_F": seen.count("F"),
                   "w_first": SCORE.get(seen[0], np.nan) if seen else np.nan,
                   "w_last": SCORE.get(seen[-1], np.nan) if seen else np.nan,
                   "gs_now": gs_now if st == 3 and on_now else "None",
                   "why_now": why_now if on_now else "none"})
  return pd.DataFrame(rows)


def add_team_q(x: pd.DataFrame, hist: pd.DataFrame, k: float = 20.0) -> pd.DataFrame:
  """EXPERIMENT (INSIGHTS (J)): team_q = share of the team's final-report Questionable players who played, over its
  games strictly before (season, week): the two seasons before + this season so far, shrunk toward the league rate
  with k pseudo-cases. hist: labelled stage-3 rows."""
  h = hist[(hist.stage == 3) & (hist.gs_now == "Questionable")].dropna(subset=["y"])
  league = float(h.y.mean()) if len(h) else 0.7
  by = {}
  for t, g in h.groupby("team"):
    g = g.assign(key=g.season * 100 + g.week).sort_values("key")
    by[t] = (g.key.to_numpy(), np.cumsum(g.y.to_numpy()), np.arange(1, len(g) + 1))
  out = []
  for t, s_, w in zip(x.team, x.season, x.week):
    e = by.get(t)
    if e is None:
      out.append(league)
      continue
    keys, cy, cn = e
    hi = np.searchsorted(keys, s_ * 100 + w, side="left")  # games before this week
    lo = np.searchsorted(keys, (s_ - 2) * 100, side="left")  # from two seasons back
    n = (cn[hi - 1] if hi else 0) - (cn[lo - 1] if lo else 0)
    yy = (cy[hi - 1] if hi else 0) - (cy[lo - 1] if lo else 0)
    out.append((yy + k * league) / (n + k))
  return x.assign(team_q=out)


def add_k_feats(d, x: pd.DataFrame, hist: pd.DataFrame, rep_rows: pd.DataFrame, which=("cal", "own", "depth")) -> pd.DataFrame:
  """EXPERIMENT (INSIGHTS (K)): calendar (week, final_week), his own record when Questionable (own_qn, own_q: shrunk
  with 3 pseudo-cases), and depth_prev (teammates at his position on the field 20%+ in the team's previous game and
  not on this week's report). Everything from before the game."""
  x = x.copy()
  sch = d.schedules[d.schedules.game_type == "REG"]
  tw = {}
  for g in sch.itertuples():
    for t in (g.home_team, g.away_team):
      tw.setdefault((int(g.season), t), []).append(int(g.week))
  if "cal" in which:
    last = {k: max(v) for k, v in tw.items()}
    x["wk"] = x.week.astype(float)
    x["final_week"] = [float(w == last.get((s_, t), -1)) for s_, w, t in zip(x.season, x.week, x.team)]
  if "own" in which:
    q = hist[(hist.stage == 3) & (hist.gs_now == "Questionable")].dropna(subset=["y"])
    league = float(q.y.mean()) if len(q) else 0.7
    by = {g: (gg.season.to_numpy() * 100 + gg.week.to_numpy(), np.cumsum(gg.y.to_numpy()))
          for g, gg in q.sort_values(["season", "week"]).groupby("gsis_id")}
    n_, r_ = [], []
    for g, s_, w in zip(x.gsis_id, x.season, x.week):
      e = by.get(g)
      i = int(np.searchsorted(e[0], s_ * 100 + w, side="left")) if e is not None else 0
      yy = float(e[1][i - 1]) if i else 0.0
      n_.append(float(min(i, 10)))
      r_.append((yy + 3 * league) / (i + 3))
    x["own_qn"], x["own_q"] = n_, r_
  if "depth" in which:
    sn = d.snaps.dropna(subset=["gsis_id"]).assign(season=lambda z: z.season.astype(int), week=lambda z: z.week.astype(int))
    sn = sn.assign(pos=sn.position.replace({"FB": "RB", "HB": "RB"}), v=np.maximum(sn.offense_pct.fillna(0), sn.defense_pct.fillna(0)))
    played = sn[sn.v >= 0.2].groupby(["team", "season", "week", "pos"]).gsis_id.apply(set).to_dict()
    onrep = {}
    for g, s_, w in zip(rep_rows.gsis_id, rep_rows.season, rep_rows.week):
      onrep.setdefault((int(s_), int(w)), set()).add(g)
    out = []
    for g, s_, w, t, ps in zip(x.gsis_id, x.season, x.week, x.team, x.pos):
      prev = [k for k in tw.get((s_, t), []) if k < w]
      if not prev:
        out.append(np.nan)
        continue
      mates = played.get((t, s_, prev[-1], ps), set()) - {g} - onrep.get((s_, w), set())
      out.append(float(min(len(mates), 4)))
    x["depth_prev"] = out
  return x


def add_stakes(x: pd.DataFrame, odds: pd.DataFrame) -> pd.DataFrame:
  """EXPERIMENT (INSIGHTS (L)): the team's playoff / division / bye odds as of the week (before its games;
  tools/playoff_odds.py --weekly) + the week number. NaN where no odds exist (2019)."""
  o = {(int(a_), int(b_), t): (p1, p2, p3) for a_, b_, t, p1, p2, p3 in zip(odds.season, odds.week, odds.team, odds.p_playoffs, odds.p_div, odds.p_bye)}
  v = [o.get((int(s_), int(w), {"LAR": "LA"}.get(t, t)), (np.nan, np.nan, np.nan)) for s_, w, t in zip(x.season, x.week, x.team)]
  # -1 = no odds (2019: an all-blank column breaks the trees' binning when a fold has only that season)
  return x.assign(st_po=[a_[0] for a_ in v], st_div=[a_[1] for a_ in v], st_bye=[a_[2] for a_ in v],
                  wk=x.week.astype(float)).fillna({"st_po": -1.0, "st_div": -1.0, "st_bye": -1.0})


def week_features(x: pd.DataFrame) -> pd.DataFrame:
  from .injuries import InjuryModel
  f = features(x)
  if "team_q" in x.columns:  # (J)
    f["team_q"] = x.team_q.astype(float).to_numpy()
  for c in ("wk", "final_week", "own_qn", "own_q", "depth_prev", "st_po", "st_div", "st_bye"):  # (K), (L)
    if c in x.columns:
      f[c] = x[c].astype(float).to_numpy()
  for c in ("on_now", "wn_D", "wn_L", "wn_F", "w_first", "w_last"):
    f[c] = x[c].astype(float).to_numpy()
  if "res_prev" in x.columns:  # (BE) reserve-list inputs (rows built with reserve=True)
    for c in ("res_prev", "res_code", "res_weeks"):
      f[c] = x[c].astype(float).to_numpy()
  f["w_trend"] = f.w_last - f.w_first
  for st in STAGES:
    f[f"stage_{st}"] = (x.stage == st).astype(float).to_numpy()
  for gsv in ("Questionable", "Doubtful"):
    f[f"gs_{gsv}"] = (x.gs_now == gsv).astype(float).to_numpy()
  for c in InjuryModel.REASONS:
    f[f"whynow_{c}"] = (x.why_now == c).astype(float).to_numpy()
  return f


def week_fit(rows: pd.DataFrame):
  from sklearn.ensemble import HistGradientBoostingClassifier
  t = rows.dropna(subset=["y"])
  return HistGradientBoostingClassifier(**WEEK_GB, random_state=0).fit(week_features(t), t.y)


def week_model(rows: pd.DataFrame, season: int):
  """(I2) the one model for `season` (trained on seasons before it) + a per-stage isotonic calibration, fit on season-1
  predictions of a model trained on seasons before season-1."""
  from sklearn.isotonic import IsotonicRegression
  m = week_fit(rows[rows.season < season])
  cal = {}
  prev, tr0 = rows[(rows.season == season - 1)].dropna(subset=["y"]), rows[rows.season < season - 1].dropna(subset=["y"])
  if len(prev) and len(tr0) > 1000:
    pp = week_fit(tr0).predict_proba(week_features(prev))[:, 1]
    iso = lambda m: IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(pp[m], prev.y.to_numpy()[m])  # noqa: E731
    res = (prev.res_prev == 1).to_numpy() if "res_prev" in prev.columns else None
    for st in STAGES:
      k = (prev.stage == st).to_numpy()
      if res is not None and (k & res).sum() >= 100:  # (BE2) reserve rows calibrated on their own
        cal[(st, 1)], cal[(st, 0)] = iso(k & res), iso(k & ~res)
      elif k.sum() >= 200:
        cal[st] = iso(k)
  return m, cal


def week_predict(model, x: pd.DataFrame) -> np.ndarray:
  m, cal = model
  p = m.predict_proba(week_features(x))[:, 1]
  for key, iso in cal.items():
    if isinstance(key, tuple):  # (BE2) (stage, reserve 1 / 0)
      k = ((x.stage == key[0]) & ((x.res_prev == 1) == bool(key[1]))).to_numpy()
    else:
      k = (x.stage == key).to_numpy()
    if k.any():
      p[k] = iso.predict(p[k])
  # isotonic steps can reach exactly 0 or 1 (every calibration-season player in that band sat / played); certainty is
  # for the game status Out rule only (Lamar, DNP Wed + Thu after missing: raw 2%, calibrated 0%; history 1.2%)
  return np.clip(p, 0.01, 0.99)


def week_now_rows(ctx: _Ctx, items: list, reserve: bool = False) -> pd.DataFrame:
  """Rows for prediction (live, or a backtest week): items = (gsis, season, week, team, pos, days so far, game status
  or "None", stage 1-3). The Tuesday block from his previous team game + this week's report as it stands."""
  rows = []
  for g, s, w, team, pos, days, gs, st in items:
    team = {"LAR": "LA"}.get(team, team)
    prev = [x for x in ctx.tw.get((s, team), []) if x < w]
    k = prev[-1] if prev else None
    seen = _days(days)
    rows.append({"season": s, "week": w, "gsis_id": g, "team": team, "pos": pos or ctx.pos_of.get(g, ""),
                 **ctx.block(g, s, team, k, w), "y": np.nan, "stage": st, "on_now": float(st > 0), "days_now": seen,
                 "wn_D": seen.count("D"), "wn_L": seen.count("L"), "wn_F": seen.count("F"),
                 "w_first": SCORE.get(seen[0], np.nan) if seen else np.nan,
                 "w_last": SCORE.get(seen[-1], np.nan) if seen else np.nan,
                 "gs_now": _gs(gs) if st == 3 else "None", "why_now": ctx.why.get((s, w, g), "none"),
                 **(ctx.reserve(g, s, team, k) if reserve else {})})
  return pd.DataFrame(rows)
