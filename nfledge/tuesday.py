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


def fit(rows: pd.DataFrame):
  from sklearn.ensemble import HistGradientBoostingClassifier
  t = rows.dropna(subset=["y"])
  return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=40,
                                        l2_regularization=1.0, random_state=0).fit(features(t), t.y)


# ---- EXPERIMENT (I): one model for every day of the week ----------------------------------------------------------
STAGES = (0, 1, 2, 3)  # 0 = Tuesday (no report yet), 1 = Wednesday, 2 = Thursday, 3 = final report


def week_rows(d, rep_rows: pd.DataFrame, hurt: set) -> pd.DataFrame:
  """(player, game w) for everyone on game w's final report or in the Tuesday population for game w, at each stage
  of the week: the Tuesday block (from his previous game) + this week's report as it stood at that stage."""
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
    if k is not None and (g, s, k) in ctx.res:
      continue  # already on a reserve list: the return-timing model's job
    base = {"season": s, "week": w, "gsis_id": g, "team": team, "pos": pos, **ctx.block(g, s, team, k, w),
            "y": ctx.label(g, s, team, w)}
    now = ctx.rep.get((g, s, w))
    days_now, gs_now = (_days(now.days), _gs(now.game_status)) if now is not None else ("", "None")
    why_now = ctx.why.get((s, w, g), "none") if now is not None else "none"
    for st in STAGES:
      if 0 < st < 3 and len(days_now) < 3:
        continue  # a short report week (Thursday game) has no separate Wednesday / Thursday stage
      seen = days_now if st == 3 else days_now[:st] if st else ""
      on_now = float(now is not None and st > 0)
      rows.append({**base, "stage": st, "on_now": on_now, "days_now": seen,
                   "wn_D": seen.count("D"), "wn_L": seen.count("L"), "wn_F": seen.count("F"),
                   "w_first": SCORE.get(seen[0], np.nan) if seen else np.nan,
                   "w_last": SCORE.get(seen[-1], np.nan) if seen else np.nan,
                   "gs_now": gs_now if st == 3 and on_now else "None",
                   "why_now": why_now if on_now else "none"})
  return pd.DataFrame(rows)


def week_features(x: pd.DataFrame) -> pd.DataFrame:
  from .injuries import InjuryModel
  f = features(x)
  for c in ("on_now", "wn_D", "wn_L", "wn_F", "w_first", "w_last"):
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
  return HistGradientBoostingClassifier(max_iter=400, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=40,
                                        l2_regularization=1.0, random_state=0).fit(week_features(t), t.y)


def week_model(rows: pd.DataFrame, season: int):
  """(I2) the one model for `season` (trained on seasons before it) + a per-stage isotonic calibration, fit on season-1
  predictions of a model trained on seasons before season-1."""
  from sklearn.isotonic import IsotonicRegression
  m = week_fit(rows[rows.season < season])
  cal = {}
  prev, tr0 = rows[(rows.season == season - 1)].dropna(subset=["y"]), rows[rows.season < season - 1].dropna(subset=["y"])
  if len(prev) and len(tr0) > 1000:
    pp = week_fit(tr0).predict_proba(week_features(prev))[:, 1]
    for st in STAGES:
      k = (prev.stage == st).to_numpy()
      if k.sum() >= 200:
        cal[st] = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(pp[k], prev.y.to_numpy()[k])
  return m, cal


def week_predict(model, x: pd.DataFrame) -> np.ndarray:
  m, cal = model
  p = m.predict_proba(week_features(x))[:, 1]
  for st, iso in cal.items():
    k = (x.stage == st).to_numpy()
    if k.any():
      p[k] = iso.predict(p[k])
  # isotonic steps can reach exactly 0 or 1 (every calibration-season player in that band sat / played); certainty is
  # for the game status Out rule only (Lamar, DNP Wed + Thu after missing: raw 2%, calibrated 0%; history 1.2%)
  return np.clip(p, 0.01, 0.99)


def week_now_rows(ctx: _Ctx, items: list) -> pd.DataFrame:
  """Rows for prediction (live, or a backtest week): items = (gsis, season, week, team, pos, days so far, game status
  or "None", stage 1-3). The Tuesday block from his previous team game + this week's report as it stands."""
  rows = []
  for g, s, w, team, pos, days, gs, st in items:
    team = {"LAR": "LA"}.get(team, team)
    prev = [x for x in ctx.tw.get((s, team), []) if x < w]
    k = prev[-1] if prev else None
    seen = _days(days)
    rows.append({"season": s, "week": w, "gsis_id": g, "team": team, "pos": pos or ctx.pos_of.get(g, ""),
                 **ctx.block(g, s, team, k, w), "y": np.nan, "stage": st, "on_now": 1.0, "days_now": seen,
                 "wn_D": seen.count("D"), "wn_L": seen.count("L"), "wn_F": seen.count("F"),
                 "w_first": SCORE.get(seen[0], np.nan) if seen else np.nan,
                 "w_last": SCORE.get(seen[-1], np.nan) if seen else np.nan,
                 "gs_now": _gs(gs) if st == 3 else "None", "why_now": ctx.why.get((s, w, g), "none")})
  return pd.DataFrame(rows)
