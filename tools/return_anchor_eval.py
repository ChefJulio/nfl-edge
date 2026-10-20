"""(BJ) Return timing anchored on ESPN's estimated return date (pre-registered 2026-10-20, docs/INSIGHTS.md (BJ)).

Usage: python tools/return_anchor_eval.py
Base = production: the return chain (nfledge/returns.py) plus the long-date rule (ESPN Out with a date 14+ days past
his next game: no game before the date). Variant: for a state with an ESPN capture (Out / IR status, a date), each
game's hazard is the measured P(back at this game | not back yet) by days from ESPN's date to the game (before it,
0-6, 7-13, 14-20, 21-34, 35+), from earlier seasons' states, shrunk to the pooled rate with K = 20 pseudo-cases;
other states keep the chain. Rows: every return-model state 2023-25 (2022 has no earlier captures), label = played
his team's k-th game after it, k = 1..6; 2026 so far CONFIRM. Captures: return_timing.CAPTURES + the archive branch's
daily 2026 snapshots (as tools/return_espn_eval.py).
GATE: (1) states with a capture, Brier k = 1..6 lower, CI upper < 0, >= 0.003, lower in >= 2 of 3 seasons; (2) all
states CI upper < +0.0005; (3) calibration (k = 1..6, with a capture) not above today's + 0.005; CONFIRM same direction.
"""
import io
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402

import run  # noqa: E402
from nfledge import return_timing as RT  # noqa: E402
from nfledge.return_timing import _gamedays  # noqa: E402
from nfledge.returns import ReturnModel, played_set  # noqa: E402

TEST, CONFIRM, H, K = [2023, 2024, 2025], 2026, 6, 20.0
EDGES = [-1e9, 0, 7, 14, 21, 35, 1e9]  # days from ESPN's date to the game
LABELS = ["before", "0-6", "7-13", "14-20", "21-34", "35+"]
cfg = run.load_config()
data = run.load_all(cfg)
m = ReturnModel(data, played_set(data))
FEAT1 = m.feats
GD = _gamedays(data)
sch = data.schedules[data.schedules.game_type == "REG"]
TW = {}
for (s, t), g in pd.concat([sch[["season", "week", "home_team"]].set_axis(["season", "week", "team"], axis=1),
                            sch[["season", "week", "away_team"]].set_axis(["season", "week", "team"], axis=1)]).groupby(["season", "team"]):
  TW[(s, t)] = sorted(g.week.astype(int))


def day(s, w, t):
  d = GD.get((s, int(w), t)) if w is not None and w == w else None
  return d if d is not None else pd.NaT


def captures() -> pd.DataFrame:
  esp = pd.read_parquet(RT.CAPTURES)[["captured", "espn_id", "status", "ret"]]
  names = subprocess.run(["git", "ls-tree", "--name-only", "origin/archive", "data/espn_injuries/"], capture_output=True,
                         text=True, cwd=ROOT).stdout.split()
  daily = []
  for n in names:
    if n.endswith(".csv"):
      f = pd.read_csv(io.StringIO(subprocess.run(["git", "show", f"origin/archive:{n}"], capture_output=True, text=True,
                                                 encoding="utf-8", cwd=ROOT).stdout))
      daily.append(pd.DataFrame({"captured": pd.Timestamp(Path(n).stem), "espn_id": f.espn_id.astype(str), "status": f.status,
                                 "ret": pd.to_datetime(f.return_date, errors="coerce", utc=True).dt.tz_convert(None)}))
  return pd.concat([esp] + daily, ignore_index=True)


ST = m._calendar(m.states(sorted(data.seasons))).reset_index(drop=True)
EN = RT.enrich(data, ST, data.avail_hist[["season", "week", "gsis_id", "days", "game_status"]], captures())
ST = ST.merge(EN[["season", "gsis_id", "week", "espn_wk", "espn_has", "espn_out", "espn_ir"]].drop_duplicates(["season", "gsis_id", "week"]),
              on=["season", "gsis_id", "week"], how="left")
for c in ("espn_has", "espn_out", "espn_ir"):
  ST[c] = ST[c].fillna(0.0)
ST["dated"] = ST.espn_wk.notna() & ((ST.espn_out == 1) | (ST.espn_ir == 1))


def bucket(d: np.ndarray) -> np.ndarray:
  return np.digitize(d, EDGES[1:-1])


def rates(train: pd.DataFrame) -> np.ndarray:
  """P(back at the next game | not back) by bucket of days from ESPN's date to that game, shrunk to the pooled rate."""
  t = train[train.dated]
  b = bucket((-t.espn_wk * 7).to_numpy())
  pooled = float(t.back.mean()) if len(t) else 0.3
  out = np.zeros(len(LABELS))
  for i in range(len(LABELS)):
    y = t.back.to_numpy()[b == i]
    out[i] = (y.sum() + K * pooled) / (len(y) + K)
  return out


def chain(base, state: pd.DataFrame, rate: np.ndarray | None) -> np.ndarray:
  """Production's chain + long-date rule (rate None), or the date-anchored hazard for dated states (rate given)."""
  s = state.copy()
  long0 = ((s.espn_out == 1) & (s.espn_wk.fillna(-99) * 7 >= 14)).to_numpy()  # the rule, decided at the state
  out, still = np.zeros((len(s), H)), np.ones(len(s))
  for h in range(H):
    p = base.predict_proba(s[FEAT1])[:, 1]
    before = (s.espn_wk.fillna(-99) > 0).to_numpy()  # this game is before ESPN's date
    if rate is None:
      p = np.where(long0 & before, 0.0, p)
    else:
      dated = s.dated.to_numpy()
      p = np.where(dated, rate[bucket((-s.espn_wk.fillna(0) * 7).to_numpy())], p)
    out[:, h] = (1 - still) + still * p
    still = still * (1 - p)
    nw, gap, dout = [], [], []
    for x in s.itertuples():
      ws = TW.get((x.season, x.team), [])
      cur = int(x.next_week)
      nxt = next((w for w in ws if w > cur), None)
      d1 = day(x.season, nxt, x.team) if nxt is not None else pd.NaT
      nw.append(nxt if nxt is not None else cur + 1)
      gap.append((d1 - day(x.season, cur, x.team)).days if pd.notna(d1) else np.nan)
      dout.append((d1 - day(x.season, x.last_played, x.team)).days if pd.notna(d1) and x.last_played is not None and x.last_played == x.last_played else np.nan)
    s["espn_wk"] = s.espn_wk - pd.Series(gap, index=s.index).fillna(7) / 7
    s["week"], s["next_week"], s["gap"], s["days_out"] = s.next_week, nw, gap, dout
    s["missed"] = s.missed + 1
    s["missed_x_ir"] = s.missed * (s.desig_ir + s.desig_pup)
    s["report"] = np.where(s.report > 0, 3, 0)
  return out


rows, shown = [], None
for season in TEST + [CONFIRM]:
  known = ST.season < season
  base = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_depth=3, random_state=0,
                                        categorical_features=[FEAT1.index("inj_code"), FEAT1.index("pos_code")]).fit(ST.loc[known, FEAT1], ST.loc[known, "back"])
  rt = rates(ST[known])
  if season == TEST[-1]:
    shown = rt
  t = ST[ST.season == season].reset_index(drop=True)
  if season == CONFIRM:
    t = t[t.next_week < data.completed_weeks(season) + 1].reset_index(drop=True)
  b, v = chain(base, t, None), chain(base, t, rt)
  for i, x in enumerate(t.itertuples()):
    for k in range(1, H + 1):
      lab = m.active_after(season, x.gsis_id, x.team, int(x.week), k)
      if lab is None:
        break
      rows.append({"season": season, "ep": f"{season}-{i}", "k": k, "y": float(lab), "base": b[i, k - 1], "var": v[i, k - 1], "dated": bool(x.dated)})
  print(f"  {season}: {len(t)} states, {int(t.dated.sum())} with a dated ESPN capture", flush=True)
R = pd.DataFrame(rows)
R["sb"], R["sv"] = (R.base - R.y) ** 2, (R["var"] - R.y) ** 2


def ci(r: pd.DataFrame) -> tuple:
  ep = r.groupby("ep").agg(sb=("sb", "sum"), sv=("sv", "sum"), n=("y", "size"))
  rng = np.random.default_rng(0)
  boot = [(lambda e: (e.sv.sum() - e.sb.sum()) / e.n.sum())(ep.iloc[rng.integers(0, len(ep), len(ep))]) for _ in range(2000)]
  return r.sv.mean() - r.sb.mean(), *np.percentile(boot, [2.5, 97.5])


def ece(p, y, bins=10):
  b = np.minimum((p * bins).astype(int), bins - 1)
  d = pd.DataFrame({"b": b, "p": p, "y": y}).groupby("b").agg(p=("p", "mean"), y=("y", "mean"), n=("y", "size"))
  return float((d.n * (d.p - d.y).abs()).sum() / d.n.sum())


fmt = lambda t: f"{t[0]:+.4f} [{t[1]:+.4f}, {t[2]:+.4f}]"  # noqa: E731
T = R[R.season.isin(TEST)]
D = T[T.dated]
g1, g2 = ci(D), ci(T)
per = D.groupby("season")[["sb", "sv"]].mean()
better = int((per.sv < per.sb).sum())
eb, ev = ece(D.base.to_numpy(), D.y.to_numpy()), ece(D["var"].to_numpy(), D.y.to_numpy())
print(f"\nmeasured rates (fit for {TEST[-1]}): " + ", ".join(f"{l} {v:.2f}" for l, v in zip(LABELS, shown)))
print(f"2023-25: {T.ep.nunique()} states ({D.ep.nunique()} dated)")
print(f"(1) dated states, k=1-6: Brier {D.sb.mean():.4f} -> {D.sv.mean():.4f}, {fmt(g1)}, seasons better {better}/3")
print(per.round(4).to_string())
print(f"(2) all states: {fmt(g2)}")
print(f"(3) calibration (dated, k=1-6): {eb:.4f} -> {ev:.4f}")
print("    played vs predicted by k (dated): " + "; ".join(f"k{k} {D[D.k == k].y.mean():.2f} / base {D[D.k == k].base.mean():.2f} / var {D[D.k == k]['var'].mean():.2f}" for k in range(1, H + 1)))
C = R[(R.season == CONFIRM) & R.dated]
same = len(C) and C.sv.mean() < C.sb.mean()
print(f"CONFIRM {CONFIRM} dated: {C.ep.nunique()} states, {C.sv.mean() - C.sb.mean() if len(C) else float('nan'):+.4f}:", "same direction" if same else "NOT same direction")
ok = g1[2] < 0 and g1[0] <= -0.003 and better >= 2 and g2[2] < 0.0005 and ev <= eb + 0.005 and same
print("GATE:", "PASS" if ok else "FAIL")
