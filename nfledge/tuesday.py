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
"""
from __future__ import annotations

import numpy as np
import pandas as pd

STATUS = ["Out", "Doubtful", "Questionable", "None"]
SCORE = {"D": 0.0, "L": 0.5, "F": 1.0}
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


def build_rows(d, rep_rows: pd.DataFrame, hurt: set) -> pd.DataFrame:
  """Tuesday rows for every (player, game k) on a final report or hurt in game k while not on it. y = any snap in
  game k+1 (NaN when k+1 hasn't been played: the rows to predict)."""
  from .injuries import InjuryModel
  sn = d.snaps.dropna(subset=["gsis_id"])
  v = np.maximum(sn.offense_pct.fillna(0).to_numpy(float), sn.defense_pct.fillna(0).to_numpy(float))
  tot = sn[["offense_snaps", "defense_snaps", "st_snaps"]].fillna(0).sum(axis=1).to_numpy(float)
  snap = pd.DataFrame({"g": sn.gsis_id.to_numpy(), "s": sn.season.astype(int).to_numpy(), "w": sn.week.astype(int).to_numpy(),
                       "pct": v, "on": tot > 0}).groupby(["g", "s", "w"]).agg(pct=("pct", "max"), on=("on", "max"))
  pct = snap.pct.to_dict()
  on = {k for k, x in snap.on.items() if x}
  snap_seasons = set(snap.index.get_level_values(1))
  sch = d.schedules[d.schedules.game_type == "REG"]
  tw, final = {}, set()
  for g in sch.itertuples():
    for t in (g.home_team, g.away_team):
      tw.setdefault((int(g.season), t), []).append(int(g.week))
      if pd.notna(g.home_score):
        final.add((int(g.season), int(g.week), t))
  tw = {k: sorted(x) for k, x in tw.items()}
  inj = d.injuries.dropna(subset=["gsis_id"]).drop_duplicates(["season", "week", "gsis_id"], keep="last")
  inj = inj.assign(season=inj.season.astype(int), week=inj.week.astype(int))
  pr = inj.practice_primary_injury.where(inj.practice_primary_injury.notna(), inj.report_primary_injury)
  scd = inj.practice_secondary_injury.where(inj.practice_secondary_injury.notna(), inj.report_secondary_injury)
  why = {(s, w, g): InjuryModel.reason_of(a, b) for s, w, g, a, b in zip(inj.season, inj.week, inj.gsis_id, pr, scd)}
  ro = d.rosters.dropna(subset=["gsis_id"])
  res = set(zip(ro[ro.status == "RES"].gsis_id, ro[ro.status == "RES"].season.astype(int), ro[ro.status == "RES"].week.astype(int)))
  born = pd.to_datetime(ro.drop_duplicates("gsis_id", keep="last").set_index("gsis_id").birth_date, errors="coerce")
  rep = {(r.gsis_id, r.season, r.week): r for r in rep_rows.itertuples()}
  # (G2) hurt in game k while not on its report: in-game note, or 20+ points under his usual share (usual >= 30%)
  snd = sn.assign(season=sn.season.astype(int), week=sn.week.astype(int)).sort_values(["gsis_id", "season", "week"])
  snd = snd.assign(v=np.maximum(snd.offense_pct.fillna(0), snd.defense_pct.fillna(0)))
  snd["usual"] = snd.groupby(["gsis_id", "season"]).v.transform(lambda z: z.shift().rolling(3, min_periods=1).mean())
  b = snd[(snd.v > 0) & ~pd.Series([(g, s_, w) in rep for g, s_, w in zip(snd.gsis_id, snd.season, snd.week)], index=snd.index)]
  b = b[np.array([(g, s_, w) in hurt for g, s_, w in zip(b.gsis_id, b.season, b.week)]) | ((b.usual >= 0.3) & (b.usual - b.v >= 0.2))]
  extra = pd.DataFrame({"season": b.season, "week": b.week, "gsis_id": b.gsis_id, "team": b.team, "position": b.position,
                        "game_status": "None", "days": "", "pop": "B"})
  rows = []
  for r in pd.concat([rep_rows.assign(pop="A"), extra], ignore_index=True).itertuples():
    s, k, g, team = int(r.season), int(r.week), r.gsis_id, {"LAR": "LA"}.get(r.team, r.team)
    weeks = tw.get((s, team), [])
    nxt = [x for x in weeks if x > k]
    if s not in snap_seasons or not nxt or (g, s, k) in res or (s, k, team) not in final:
      continue
    k1 = nxt[0]
    prev = [x for x in weeks if x <= k]
    played_k = (g, s, k) in on
    run = 0
    for x in reversed(prev):
      if (g, s, x) in on:
        break
      run += 1
    usual = [pct.get((g, s, x)) for x in prev[:-1] if (g, s, x) in on][-3:]
    usual = float(np.mean(usual)) if usual else np.nan
    ep_w, ep_days = 0, ""
    for x in reversed(prev):
      e = rep.get((g, s, x))
      if e is None:
        break
      ep_w += 1
      ep_days = str(e.days if isinstance(e.days, str) else "").replace("?", "") + ep_days
    days = str(r.days if isinstance(r.days, str) else "").replace("?", "")
    gs = {"OUT": "Out", "DOUBTFUL": "Doubtful", "QUESTIONABLE": "Questionable"}.get(str(r.game_status).upper(), "None")
    bd = born.get(g)
    rows.append({"season": s, "week": k1, "from_week": k, "gsis_id": g, "team": team, "pos": r.position, "status": gs, "pop": r.pop,
                 "n_D": days.count("D"), "n_L": days.count("L"), "n_F": days.count("F"),
                 "last_day": SCORE.get(days[-1], np.nan) if days else np.nan,
                 "played_last": float(played_k), "last_pct": pct.get((g, s, k), 0.0) if played_k else 0.0, "usual_pct": usual,
                 "left_early": (usual - pct.get((g, s, k), 0.0)) if played_k and usual == usual else np.nan,
                 "hurt_in_game": float((g, s, k) in hurt), "missed_run": float(min(run, 4)),
                 "ep_weeks": float(min(ep_w, 8)), "ep_D": ep_days.count("D"), "ep_L": ep_days.count("L"), "ep_F": ep_days.count("F"),
                 "why": why.get((s, k, g), "none"), "bye": float(k1 - k > 1),
                 "age": (pd.Timestamp(f"{s}-09-01") - bd).days / 365.25 if pd.notna(bd) else np.nan,
                 "y": float((g, s, k1) in on) if (s, k1, team) in final else np.nan})
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
