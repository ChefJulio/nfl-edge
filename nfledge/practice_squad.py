"""(CE) practice-squad players as roster players with a chance to play (pre-registered 2026-10-21, amended before
building; docs/INSIGHTS.md). Owner: "can we just track and treat practice squad players normally?" (Jawhar Jordan,
elevated by Houston for week 6, read nothing for week 7 until Saturday's elevation).

The pool for (season, week w, team): its practice-squad QB / RB / WR / TE as the live site sees them before Saturday's
elevations: on the practice squad (DEV) at w, or elevated for w (nflverse's weekly rosters show an elevated player ACT
for his elevation week and DEV again after it: DEV at w-1, ACT / INA at w, DEV at w+1). The w+1 status only rebuilds
what the live site saw; it is never an input. Promotions to the 53 (ACT at w and w+1) aren't in the pool.

Inputs (all known before Saturday): position; elevations already used this season (the league allows 3 before a
player must be signed); elevated last week; his position room's absences this week (last week's active players at
his position listed Out / Doubtful on this week's report, or newly on a reserve list); his NFL experience (games
with an offensive snap before this week). Label: an offensive snap in game w.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SKILL = ("QB", "RB", "WR", "TE")
FEATS = ["elev_used", "elev_last", "room_out", "exp_games", "pos_QB", "pos_RB", "pos_WR", "pos_TE", "last_x_room", "room_x_exp"]


def _pos(p) -> str:
  return {"FB": "RB", "HB": "RB"}.get(str(p), str(p))


def rows(data, seasons: list[int]) -> pd.DataFrame:
  """One row per pool player-week with inputs and label (NaN where game w isn't final)."""
  ro = data.rosters[data.rosters.season.isin(seasons) & data.rosters.gsis_id.notna()].copy()
  ro = ro[ro.game_type.isin(["REG"]) if "game_type" in ro else ro.index == ro.index]
  ro["team"] = ro.team.replace({"LAR": "LA"})
  ro["pos"] = ro.position.map(_pos)
  st = {(int(s), int(w), g): (t, x) for s, w, g, t, x in zip(ro.season, ro.week, ro.gsis_id, ro.team, ro.status)}
  pos_of = ro.sort_values(["season", "week"]).drop_duplicates("gsis_id", keep="last").set_index("gsis_id").pos.to_dict()
  sn = data.snaps.dropna(subset=["gsis_id"])
  off = sn[sn.offense_snaps.fillna(0) > 0]
  played = set(zip(off.season.astype(int), off.week.astype(int), off.gsis_id))
  # career offensive games before (season, week): cumulative count per player in time order
  og = off[["season", "week", "gsis_id"]].drop_duplicates().sort_values(["season", "week"])
  og["n"] = og.groupby("gsis_id").cumcount()  # games before this one
  first_after = {}
  for g, grp in og.groupby("gsis_id"):
    first_after[g] = (grp.season.to_numpy() * 100 + grp.week.to_numpy(), grp.n.to_numpy())
  sch = data.schedules[(data.schedules.game_type == "REG") & data.schedules.season.isin(seasons)]
  final = {(int(s), int(w), t) for s, w, h, a, hs in zip(sch.season, sch.week, sch.home_team, sch.away_team, sch.home_score)
           if pd.notna(hs) for t in (h, a)}
  plays = {(int(s), int(w), t) for s, w, h, a in zip(sch.season, sch.week, sch.home_team, sch.away_team) for t in (h, a)}
  # this week's report: Out / Doubtful by (season, week, gsis)
  inj = data.injuries
  inj = inj[inj.season.isin(seasons) & (inj.game_type == "REG") & inj.report_status.isin(["Out", "Doubtful"])]
  outd = set(zip(inj.season.astype(int), inj.week.astype(int), inj.gsis_id))
  act = ro[ro.status.isin(["ACT", "INA"])]
  room = act.groupby(["season", "week", "team", "pos"]).gsis_id.apply(list).to_dict()

  def elevated(s, w, g, t) -> bool:
    a, b, c = st.get((s, w - 1, g)), st.get((s, w, g)), st.get((s, w + 1, g))
    return (a is not None and a == (t, "DEV") and b is not None and b[0] == t and b[1] in ("ACT", "INA")
            and (c is None or c[1] == "DEV"))

  out = []
  for (s, w, g), (t, x) in st.items():
    if (s, w, t) not in plays:
      continue
    ps_now = x == "DEV"
    elev_now = x in ("ACT", "INA") and elevated(s, w, g, t)
    if not (ps_now or elev_now):
      continue
    pos = pos_of.get(g)
    if pos not in SKILL:
      continue
    used = sum(1 for k in range(1, w) if elevated(s, k, g, t))
    last = float(elevated(s, w - 1, g, t))
    mates = room.get((s, w - 1, t, pos), [])
    out_n = sum(1 for m in mates if (s, w, m) in outd or (st.get((s, w, m), ("", ""))[1] == "RES"))
    keys, ns = first_after.get(g, (np.array([]), np.array([])))
    i = np.searchsorted(keys, s * 100 + w)
    exp = int(ns[i - 1] + 1) if i > 0 else 0
    left = max(len(mates) - out_n, 0)
    out.append({"season": s, "week": w, "gsis_id": g, "team": t, "pos": pos, "elev_now": elev_now, "room_left": float(min(left, 6)),
                "elev_used": float(min(used, 3)), "elev_last": last, "room_out": float(min(out_n, 3)),
                "exp_games": float(min(exp, 50)),
                "y": float((s, w, g) in played) if (s, w, t) in final else np.nan})
  x = pd.DataFrame(out)
  if len(x):
    # (CE2) his team's first practice-squad option at the position this week: most elevations used, then experience
    x["_k"] = x.elev_used * 1000 + x.exp_games
    x["first_opt"] = (x.groupby(["season", "week", "team", "pos"])._k.rank(ascending=False, method="first") == 1).astype(float)
    x = x.drop(columns="_k")
  return x


def features(x: pd.DataFrame) -> pd.DataFrame:
  f = x[["elev_used", "elev_last", "room_out", "exp_games"]].astype(float).copy()
  f["exp_games"] = np.log1p(f.exp_games)
  for p in SKILL:
    f[f"pos_{p}"] = (x.pos == p).astype(float).to_numpy()
  # where the chance jumps: elevated last week with the room short (2020-25: 72% played, n 25), and an experienced
  # player with the room short
  f["last_x_room"] = f.elev_last * f.room_out
  f["room_x_exp"] = f.room_out * f.exp_games
  if V2 and "room_left" in x.columns:  # (CE2) the room he'd join, by position, and whether he's the next man
    for p in SKILL:
      f[f"left_{p}"] = x.room_left.astype(float).to_numpy() * f[f"pos_{p}"]
    f["first_opt"] = x.first_opt.astype(float).to_numpy()
    f["first_x_short"] = f.first_opt * np.clip(3 - x.room_left.astype(float).to_numpy(), 0, None)
  return f


V2 = False  # (CE2) set by tools/ps_eval.py --v2


def fit(train: pd.DataFrame):
  from sklearn.linear_model import LogisticRegression
  t = train.dropna(subset=["y"])
  return LogisticRegression(C=1.0, max_iter=2000).fit(features(t), t.y)
