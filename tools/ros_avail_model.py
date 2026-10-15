"""RESEARCH (not in production; gate failed 3x, INSIGHTS sec. 9). Lookahead availability for every skill player: P(he plays his team's k-th game from decision week W).

Pre-registered 2026-10-15 (docs/INSIGHTS.md section 9; owner: "if it's data backed i support it"). The lookahead
weeks (rest-of-season rankings) used the return-timing model for players out injured and 1.0 for everyone else,
but skill players who played last week and are on no report still play only ~91% of their next game, ~81% five
games out (new injuries, lost roles), and the return chain keeps climbing where real returns plateau (~71%). One
classifier learns it all from outcomes, using what is known before W's games:
  k (games ahead), position, offensive snap share over his last 3 team games, share of his team's last 4 games he
  played, games played this season, this week's P(plays) when he's on the practice report, roster designation,
  and for players out injured the return model's state (games missed) and its chained P(active) at k (step 1 =
  this week's estimate).
Label: played (any snap) his team's k-th game from W. Population: QB/RB/WR/TE with an offensive snap this season
before W, on the roster at W.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import sys
from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
from nfledge.injuries import practice_features  # noqa: E402
from nfledge.returns import DESIG, POS_GROUP, ReturnModel  # noqa: E402

SKILL = ("QB", "RB", "WR", "TE")
K_MAX = 12
FEATS = ["k", "pos_code", "snap3", "snap_season", "played4", "gp", "on_rep", "p_now", "d_ir", "d_ir_return", "d_pup", "d_res_other",
         "d_inactive", "in_state", "ret_missed", "ret_k", "week"]


def team_weeks(data, season: int) -> dict:
  s = data.schedules[(data.schedules.season == season) & (data.schedules.game_type == "REG")]
  return {t: sorted(set(s[s.home_team == t].week) | set(s[s.away_team == t].week)) for t in set(s.home_team) | set(s.away_team)}


def decision_rows(data, season: int, week: int, played: set, ret: ReturnModel | None, states: pd.DataFrame | None,
                  p_now: dict, k_max: int = K_MAX, label: bool = True, last_week: int = 18) -> pd.DataFrame:
  """One row per (relevant player, k) for decision week `week`. p_now: {gsis_id: this week's P(plays)} for players
  on this week's practice report. ret/states: a fitted return model and its states (players out injured)."""
  tw = team_weeks(data, season)
  # his latest roster row at or before W (a team on bye has none that week: v2 fix), if from the last 2 weeks
  r = data.rosters[(data.rosters.season == season) & (data.rosters.week <= week) & (data.rosters.week >= week - 2)
                   & data.rosters.gsis_id.notna()]
  r = r.sort_values("week").drop_duplicates("gsis_id", keep="last")
  r = r[r.position.map(POS_GROUP).isin(SKILL)]
  sn = data.snaps[(data.snaps.season == season) & (data.snaps.game_type == "REG") & (data.snaps.week < week)
                  & data.snaps.gsis_id.notna()]
  had = set(sn[sn.offense_snaps.fillna(0) > 0].gsis_id)
  r = r[r.gsis_id.isin(had) & r.team.isin(tw)]
  if r.empty:
    return pd.DataFrame()
  pct = sn.set_index(["gsis_id", "week"]).offense_pct
  pct = pct[~pct.index.duplicated(keep="last")]
  cur_states = {}
  if states is not None and len(states):
    st = states[(states.season == season) & (states.next_week == week)]
    st = st.drop_duplicates("gsis_id", keep="last")
    if len(st) and ret is not None:
      first = np.array([p_now.get(g, np.nan) for g in st.gsis_id], dtype=float)
      pa = ret.p_active(st.reset_index(drop=True), k_max, first=first)
      cur_states = {g: (int(m), pa[i]) for i, (g, m) in enumerate(zip(st.gsis_id, st.missed))}
  groups = {g: i for i, g in enumerate(SKILL)}
  rows = []
  for x in r.itertuples():
    t = tw[x.team]
    before = [w for w in t if w < week]
    after = [w for w in t if w >= week]
    last3, last4 = before[-3:], before[-4:]
    snap3 = float(np.mean([float(pct.get((x.gsis_id, w), 0.0)) for w in last3])) if last3 else np.nan
    snap_season = float(np.mean([float(pct.get((x.gsis_id, w), 0.0)) for w in before])) if before else np.nan
    played4 = float(np.mean([(season, w, x.gsis_id) in played for w in last4])) if last4 else np.nan
    gp = sum((season, w, x.gsis_id) in played for w in before)
    desig = DESIG.get(x.status_description_abbr, "reserve_other" if x.status == "RES" else "active")
    stt = cur_states.get(x.gsis_id)
    pn = p_now.get(x.gsis_id)
    for k in range(1, min(k_max, len(after)) + 1):
      gw = after[k - 1]
      if gw > last_week:
        break
      row = {"season": season, "week": week, "gsis_id": x.gsis_id, "team": x.team, "pos": POS_GROUP[x.position],
             "game_week": gw, "k": k, "pos_code": groups[POS_GROUP[x.position]], "snap3": snap3, "snap_season": snap_season, "played4": played4,
             "gp": gp, "on_rep": float(pn is not None), "p_now": np.nan if pn is None else float(pn),
             "d_ir": float(desig == "ir"), "d_ir_return": float(desig == "ir_return"), "d_pup": float(desig == "pup"),
             "d_res_other": float(desig == "reserve_other"), "d_inactive": float(desig == "inactive"),
             "in_state": float(stt is not None), "ret_missed": np.nan if stt is None else float(stt[0]),
             "ret_k": np.nan if stt is None else float(stt[1][k - 1])}
      if label:
        row["y"] = float((season, gw, x.gsis_id) in played)
      rows.append(row)
  return pd.DataFrame(rows)


def practice_p_now(data, season: int, week: int, pm, cols) -> dict:
  """Final-report P(plays) for everyone on the week's practice report (training / evaluation; production passes
  the live estimate instead)."""
  ah = data.avail_hist
  ah = ah[(ah.season == season) & (ah.week == week)].drop_duplicates("gsis_id", keep="last")
  if ah.empty:
    return {}
  p = pm.predict_proba(practice_features(ah)[cols])[:, 1]
  p = np.where(ah.game_status.to_numpy() == "OUT", 0.0, p)
  return dict(zip(ah.gsis_id, p))


GB = {"max_iter": 400, "learning_rate": 0.05, "max_depth": 5}  # v2 (pre-registered): room for position x role x k


def fit(rows: pd.DataFrame, gb: dict | None = None):
  from sklearn.ensemble import HistGradientBoostingClassifier
  return HistGradientBoostingClassifier(**GB, random_state=0, categorical_features=[FEATS.index("pos_code")]).fit(
    rows[FEATS], rows.y)


def baseline(rows: pd.DataFrame) -> np.ndarray:
  """Production before this model: the return chain for players out injured, everyone else 1.0."""
  return np.where(rows.in_state > 0, rows.ret_k.fillna(1.0), 1.0)


# -- training (shared by tools/ros_avail_eval.py and the live lookahead) ------------------------------------------
TRAIN_FIRST = 2022  # first decision season: post-COVID (2020-21's COVID reserve list skewed who played; v3 gate)


def _code_key() -> str:
  import hashlib
  from pathlib import Path
  here = Path(__file__).resolve().parent
  src = "".join((p).read_text(encoding="utf-8") for p in (_P(__file__), here.parent / "nfledge" / "returns.py", here.parent / "nfledge" / "injuries.py"))
  return hashlib.sha1(src.encode()).hexdigest()[:10]


def training_rows(data, gb: dict, seasons: list[int], cache_dir) -> pd.DataFrame:
  """Labelled decision rows for `seasons` (weeks 2-16), each season's inner practice and return models fit only on
  seasons before it. Finished seasons never change, so the rows are cached per season and code version."""
  from pathlib import Path
  from sklearn.ensemble import HistGradientBoostingClassifier
  from nfledge.returns import played_set
  cache_dir = Path(cache_dir)
  played = played_set(data)
  ret = ReturnModel(data, played)
  states = None
  key = _code_key()
  frames = []
  for s in seasons:
    f = cache_dir / f"ros_avail_rows_{s}_{key}.parquet"
    if f.exists():
      frames.append(pd.read_parquet(f))
      continue
    if states is None:
      states = ret.states(sorted(data.seasons))
    ret.fit_frame(states[states.season < s])
    ah = data.avail_hist
    d = ah[(ah.season < s) & (ah.game_status != "OUT")]
    X = practice_features(d)
    pm = HistGradientBoostingClassifier(**gb, random_state=0).fit(X, d.played)
    rows = pd.concat([decision_rows(data, s, w, played, ret, states, practice_p_now(data, s, w, pm, list(X.columns)))
                      for w in range(2, 17)], ignore_index=True)
    rows.to_parquet(f, index=False)
    frames.append(rows)
  return pd.concat(frames, ignore_index=True)


def predict_lookahead(data, season: int, week: int, now_report: dict, gb: dict, cache_dir) -> dict:
  """{game_week: {gsis_id: P(plays)}} for every relevant skill player, his team's games from `week` on, trained on
  every finished decision season. now_report: this week's live P(plays) for players on its practice report."""
  from nfledge.returns import played_set
  seasons = [s for s in range(TRAIN_FIRST, season) if s in set(data.seasons)]
  if not seasons:
    return {}
  m = fit(training_rows(data, gb, seasons, cache_dir), gb)
  played = played_set(data)
  ret = ReturnModel(data, played)
  st = ret.states(sorted(data.seasons))
  ret.fit_frame(st[(st.season < season) | (st.next_week < week)])
  rows = decision_rows(data, season, week, played, ret, st, now_report or {}, k_max=K_MAX + 2, label=False)
  if rows.empty:
    return {}
  rows["p"] = m.predict_proba(rows[FEATS])[:, 1]
  out = {}
  for gw, g in rows.groupby("game_week"):
    out[int(gw)] = dict(zip(g.gsis_id, g.p))
  return out
