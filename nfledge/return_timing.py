"""When players on injured reserve come back: a direct model of P(back by his k-th next game), k = 1..8.

Owner 2026-10-15: "pinpointing returns from IR and injuries in general is very important". The return-timing
chain (returns.py) is calibrated for injured players on the active roster but not for IR: by his 5th-8th next game
41% of IR players are back while the chain says 23-28% (it rolls one-game hazards forward and compounds errors).
This model predicts each horizon directly from what is known now, with no chain:
  the return model's state (games missed, designation, report status, injury, position, week) + k, games on IR so
  far and games still short of the season's IR minimum (forced to 0 below it: an NFL rule), whether his practice
  window is open (on the practice report) and his practice score this week, ESPN's estimated return (weeks from
  his next game) and status, and this week's practice-model P(plays) when he is on the report.
Pre-registered hybrid (docs/INSIGHTS.md section 9): this model for players on IR, the chain for everyone else.
Judged on 2021-22, seasons no earlier test or selection used: IR Brier 0.173 -> 0.158 [-0.028, -0.002], both
seasons; calibration by k within 2.4 points (chain: up to 18 points low).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from .injuries import _SCORE, practice_features
from .returns import FEATURES, ReturnModel, _gamedays  # noqa: F401 (_gamedays: tools import it from here)

H = 8
FIRST_SEASON = 2019
CAPTURES = Path(__file__).resolve().parent.parent / "data" / "history" / "espn_injury_captures.parquet"
FEATS = FEATURES + ["k", "ir_games", "shortfall", "window_now", "window", "prac_score", "espn_wk", "espn_has", "espn_out",
                    "espn_ir", "p_now"]
GB = {"max_iter": 300, "learning_rate": 0.05, "max_depth": 4}


def ir_min(season: int) -> int:
  """Games a player must spend on IR before returning: 4 since 2022, 3 in 2020-21, 8 before."""
  return 4 if season >= 2022 else 3 if season >= 2020 else 8




def enrich(data, st: pd.DataFrame, practice: pd.DataFrame, espn: pd.DataFrame) -> pd.DataFrame:
  """Adds the IR / practice-window / ESPN features to return-model states. practice: (season, week, gsis_id, days,
  game_status) rows; espn: (captured, espn_id, status, ret) rows, the latest one between his last missed game and
  the next game counts."""
  st = st.sort_values(["season", "gsis_id", "week"]).reset_index(drop=True)
  on_ir = st.desig.isin(["ir", "ir_return"])
  run = ((~on_ir) | (st.gsis_id != st.gsis_id.shift()) | (st.season != st.season.shift()) | (st.missed == 1)).cumsum()
  st["ir_games"] = np.where(on_ir, on_ir.groupby(run).cumsum(), 0).astype(float)
  st["ir_min"] = st.season.map(ir_min)
  st["shortfall"] = np.where(on_ir, np.maximum(0, st.ir_min - st.ir_games), 0).astype(float)
  pr = practice.drop_duplicates(["season", "week", "gsis_id"], keep="last").set_index(["season", "week", "gsis_id"])
  keys = list(zip(st.season, st.next_week.astype(int), st.gsis_id))

  def score(k):
    d = pr.at[k, "days"] if k in pr.index else None
    v = [_SCORE[c] for c in d if c in _SCORE] if isinstance(d, str) else []
    return float(np.mean(v)) if v else np.nan
  st["prac_score"] = [score(k) for k in keys]
  st["window_now"] = [float(k in pr.index) for k in keys]
  ep = ((st.missed == 1) | (st.gsis_id != st.gsis_id.shift()) | (st.season != st.season.shift())).cumsum()
  st["window"] = st.window_now.groupby(ep).cummax()
  gday = _gamedays(data)
  r = data.rosters.dropna(subset=["gsis_id", "espn_id"]).drop_duplicates("gsis_id")
  espn_of = {g: str(e).split(".")[0] for g, e in zip(r.gsis_id, r.espn_id)}
  e = espn.assign(espn_id=espn.espn_id.astype(str), captured=pd.to_datetime(espn.captured)).sort_values("captured")
  by_id = {k: v for k, v in e.groupby("espn_id")}
  wk, has, out_, ir_ = [], [], [], []
  for x in st.itertuples():
    rows = by_id.get(espn_of.get(x.gsis_id))
    d0, d1 = gday.get((x.season, int(x.week), x.team)), gday.get((x.season, int(x.next_week), x.team))
    row = None
    if rows is not None and d1 is not None:
      c = rows[(rows.captured < d1) & ((rows.captured > d0) if d0 is not None else True)]
      if len(c):
        row = c.iloc[-1]
    if row is None:
      wk.append(np.nan); has.append(0.0); out_.append(0.0); ir_.append(0.0)
      continue
    ret = pd.Timestamp(row.ret) if row.ret is not None and pd.notna(row.ret) else None
    wk.append((ret - d1).days / 7 if ret is not None else np.nan)
    has.append(1.0); out_.append(float(row.status == "Out")); ir_.append(float(row.status == "Injured Reserve"))
  st["espn_wk"], st["espn_has"], st["espn_out"], st["espn_ir"] = wk, has, out_, ir_
  return st


def p_now_walkforward(data, st: pd.DataFrame, gb: dict) -> np.ndarray:
  """This week's practice-model P(plays) for each state's next game, the practice model fit on seasons before."""
  from sklearn.ensemble import HistGradientBoostingClassifier
  ah = data.avail_hist
  idx_ah = ah.drop_duplicates(["season", "week", "gsis_id"], keep="last").set_index(["season", "week", "gsis_id"])
  out = np.full(len(st), np.nan)
  for s in sorted(st.season.unique()):
    d = ah[(ah.season < s) & (ah.game_status != "OUT")]
    if len(d) < 1000:
      continue
    X = practice_features(d)
    pm = HistGradientBoostingClassifier(**gb, random_state=0).fit(X, d.played)
    idx = np.where(st.season.to_numpy() == s)[0]
    keys = list(zip(st.season.iloc[idx], st.next_week.iloc[idx].astype(int), st.gsis_id.iloc[idx]))
    hit = np.array([k in idx_ah.index for k in keys])
    if hit.any():
      sub = idx_ah.loc[[k for k, h in zip(keys, hit) if h]].reset_index()
      p = pm.predict_proba(practice_features(sub)[list(X.columns)])[:, 1]
      out[idx[hit]] = np.where(sub.game_status.to_numpy() == "OUT", 0.0, p)
  return out


def expand(st: pd.DataFrame, model: ReturnModel) -> pd.DataFrame:
  """Every state x k = 1..H with its label (back by game k), where the outcome is known."""
  lab = []
  for i, x in enumerate(st.itertuples()):
    back = None
    for k in range(1, H + 1):
      a = model.active_after(x.season, x.gsis_id, x.team, int(x.week), k)
      if a is None:
        break
      back = k if (back is None and a) else back
      lab.append((i, k, float(back is not None and back <= k)))
  L = pd.DataFrame(lab, columns=["i", "k", "y"])
  xk = st.iloc[L.i.to_numpy()].reset_index(drop=True)
  xk["k"], xk["y"], xk["src"] = L.k.to_numpy(), L.y.to_numpy(), L.i.to_numpy()
  xk["impossible"] = (xk.desig.isin(["ir", "ir_return"]) & (xk.k <= xk.shortfall)).astype(float)
  return xk


def _code_key() -> str:
  here = Path(__file__).resolve().parent
  src = "".join((here / f).read_text(encoding="utf-8") for f in ("return_timing.py", "returns.py", "injuries.py"))
  return hashlib.sha1((src + str(CAPTURES.stat().st_mtime_ns if CAPTURES.exists() else "")).encode()).hexdigest()[:10]


def training_rows(data, model: ReturnModel, gb: dict, seasons: list[int], cache_dir) -> pd.DataFrame:
  """Labelled state x k rows for `seasons` (cached per code version and season list)."""
  f = Path(cache_dir) / f"return_timing_rows_{min(seasons)}_{max(seasons)}_{_code_key()}.parquet"
  if f.exists():
    return pd.read_parquet(f)
  st = model.states(sorted(data.seasons))
  st = st[st.season.isin(seasons)]
  esp = pd.read_parquet(CAPTURES) if CAPTURES.exists() else pd.DataFrame(columns=["captured", "espn_id", "status", "ret"])
  st = enrich(data, st, data.avail_hist, esp)
  st["p_now"] = p_now_walkforward(data, st, gb)
  xk = expand(st, model)
  xk.to_parquet(f, index=False)
  return xk


def fit(xk: pd.DataFrame):
  from sklearn.ensemble import HistGradientBoostingClassifier
  cols = [c for c in FEATS if xk[c].notna().any() and xk[c].nunique() > 1]  # e.g. no ESPN data before 2022
  m = HistGradientBoostingClassifier(**GB, random_state=0, categorical_features=[cols.index("inj_code"), cols.index("pos_code")])
  m.fit(xk[cols], xk.y)
  m.cols_ = cols
  return m


def predict(m, st: pd.DataFrame, horizon: int) -> np.ndarray:
  """P(back by game k), shape (len(st), horizon); 0 while still short of the IR minimum; carried flat past H."""
  out = np.zeros((len(st), horizon))
  for k in range(1, horizon + 1):
    x = st.assign(k=min(k, H))
    p = m.predict_proba(x[m.cols_])[:, 1]
    out[:, k - 1] = np.where(x.desig.isin(["ir", "ir_return"]) & (k <= x.shortfall), 0.0, p)
  return np.maximum.accumulate(out, axis=1)  # "back by k" can't fall as k grows
