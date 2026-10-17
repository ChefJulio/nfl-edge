"""(AD) calendar days in the return chain (pre-registered in docs/INSIGHTS.md 2026-10-17; owner: "do we account for
likelihood of coming back after a bye? ... total calendar dates to return ... thursday game return likelihood").

Usage: python tools/return_days_eval.py
Today's return model (nfledge/returns.py FEATURES: games missed, designation, report, injury, position, week) vs the
same model plus two calendar features:
  gap       days from the game he just missed to his team's next game (Thursday game ~4, normal 7, after a bye 14)
  days_out  days from the last game he played to that next game (calendar time since he got hurt)
The variant's chain steps them along his team's real schedule; today's chain steps a game at a time (week + 1).
Walk-forward: each test season fit on the seasons before. Rows: every return-model state (injured, missed his team's
last game); label = played his team's k-th game after it, k = 1..6.
GATE: (1) k = 1 Brier pooled 2022-25 lower, 95% CI over 2,000 state resamples excluding 0, lower in >= 3 of 4 seasons;
(2) k = 2..6 not worse (CI upper < +0.002); (3) calibration error (10 bins, k = 1) not above today's + 0.005; CONFIRM
2026 so far, same direction. Reported apart: states on injured reserve / PUP (the live site rates those with
return_timing.py, which shares the features).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402

import run  # noqa: E402
from nfledge.return_timing import _gamedays  # noqa: E402
from nfledge.returns import FEATURES, ReturnModel, played_set  # noqa: E402

TEST, CONFIRM, H = [2022, 2023, 2024, 2025], 2026, 6
FEAT2 = FEATURES + ["gap", "days_out"]
cfg = run.load_config()
data = run.load_all(cfg)
m = ReturnModel(data, played_set(data))
ST = m.states(sorted(data.seasons)).reset_index(drop=True)
GD = _gamedays(data)
sch = data.schedules[data.schedules.game_type == "REG"]
TW = {}  # (season, team) -> sorted game weeks
for (s, t), g in pd.concat([sch[["season", "week", "home_team"]].set_axis(["season", "week", "team"], axis=1),
                            sch[["season", "week", "away_team"]].set_axis(["season", "week", "team"], axis=1)]).groupby(["season", "team"]):
  TW[(s, t)] = sorted(g.week.astype(int))


def day(s, w, t):
  d = GD.get((s, int(w), t))
  return d if d is not None else pd.NaT


def add_days(st: pd.DataFrame) -> pd.DataFrame:
  st = st.copy()
  gap, out, last = [], [], []
  for x in st.itertuples():
    ws = TW.get((x.season, x.team), [])
    i = ws.index(int(x.week)) if int(x.week) in ws else None
    lp = ws[i - int(x.missed)] if i is not None and i - int(x.missed) >= 0 else None  # last game he played (or none)
    d1 = day(x.season, x.next_week, x.team)
    gap.append((d1 - day(x.season, x.week, x.team)).days if pd.notna(d1) else np.nan)
    out.append((d1 - day(x.season, lp, x.team)).days if lp is not None and pd.notna(d1) else np.nan)
    last.append(lp)
  st["gap"], st["days_out"], st["last_played"] = gap, out, last
  return st


ST = add_days(ST)
mk = lambda: HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_depth=3, random_state=0,  # noqa: E731
                                            categorical_features=[FEAT2.index("inj_code"), FEAT2.index("pos_code")])


def chain_base(state: pd.DataFrame) -> np.ndarray:
  return m.p_active(state, H, stay=1.0)


def chain_days(model, state: pd.DataFrame) -> np.ndarray:
  """The variant's chain: each step moves to his team's next game, with that game's gap and days out."""
  s = state.copy()
  out, still = np.zeros((len(s), H)), np.ones(len(s))
  for h in range(H):
    p = model.predict_proba(s[FEAT2])[:, 1]
    out[:, h] = (1 - still) + still * p
    still = still * (1 - p)
    nw, gap, dout = [], [], []
    for x in s.itertuples():  # he missed next_week: the state moves there
      ws = TW.get((x.season, x.team), [])
      cur = int(x.next_week)
      nxt = next((w for w in ws if w > cur), None)
      d1 = day(x.season, nxt, x.team) if nxt is not None else pd.NaT
      nw.append(nxt if nxt is not None else cur + 1)
      gap.append((d1 - day(x.season, cur, x.team)).days if pd.notna(d1) else np.nan)
      dout.append((d1 - day(x.season, x.last_played, x.team)).days if pd.notna(d1) and x.last_played is not None and x.last_played == x.last_played else np.nan)
    s["week"], s["next_week"], s["gap"], s["days_out"] = s.next_week, nw, gap, dout
    s["missed"] = s.missed + 1
    s["missed_x_ir"] = s.missed * (s.desig_ir + s.desig_pup)
    s["report"] = np.where(s.report > 0, 3, 0)
  return out


rows = []
for season in TEST + [CONFIRM]:
  known = (ST.season < season)
  m.fit_frame(ST[known])
  var = mk().fit(ST.loc[known, FEAT2], ST.loc[known, "back"])
  t = ST[ST.season == season].reset_index(drop=True)
  if season == CONFIRM:
    t = t[t.next_week < data.completed_weeks(season) + 1].reset_index(drop=True)
  b, v = chain_base(t), chain_days(var, t)
  for i, x in enumerate(t.itertuples()):
    for k in range(1, H + 1):
      lab = m.active_after(season, x.gsis_id, x.team, int(x.week), k)
      if lab is None:
        break
      rows.append({"season": season, "ep": f"{season}-{i}", "k": k, "y": float(lab), "base": b[i, k - 1], "var": v[i, k - 1],
                   "ir": x.desig in ("ir", "ir_return", "pup"), "gap": x.gap})
  print(f"  {season}: {len(t)} states", flush=True)
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


def report(r: pd.DataFrame, name: str):
  k1, kl = r[r.k == 1], r[r.k >= 2]
  d1, lo1, hi1 = ci(k1)
  per = k1.groupby("season")[["sb", "sv"]].mean()
  better = int((per.sv < per.sb).sum())
  dl, lol, hil = ci(kl) if len(kl) else (np.nan, np.nan, np.nan)
  eb, ev = ece(k1.base.to_numpy(), k1.y.to_numpy()), ece(k1["var"].to_numpy(), k1.y.to_numpy())
  print(f"\n[{name}] k=1: {len(k1)} states, Brier {k1.sb.mean():.4f} -> {k1.sv.mean():.4f} diff {d1:+.4f} [{lo1:+.4f}, {hi1:+.4f}],"
        f" seasons better {better}/{len(per)}; calibration error {eb:.4f} -> {ev:.4f}")
  print(f"[{name}] k=2-6: {len(kl)} rows, diff {dl:+.4f} [{lol:+.4f}, {hil:+.4f}]")
  print(per.round(4).to_string())
  return hi1 < 0 and better >= 3 and hil < 0.002 and ev <= eb + 0.005


T = R[R.season.isin(TEST)]
ok = report(T, "2022-25 all states")
report(T[~T.ir], "2022-25 active roster")
report(T[T.ir], "2022-25 injured reserve / PUP")
k1 = T[T.k == 1].assign(g=pd.cut(T[T.k == 1].gap, [0, 5, 8, 12, 99], labels=["<=5d", "6-8d", "9-12d", "13d+"]))
print("\nk=1 by days to the next game (actual, today, variant):")
print(k1.groupby("g", observed=True).agg(n=("y", "size"), actual=("y", "mean"), base=("base", "mean"), var=("var", "mean")).round(3).to_string())
C = R[R.season == CONFIRM]
c1 = C[C.k == 1]
print(f"\nCONFIRM {CONFIRM} so far: k=1 {len(c1)} states, diff {c1.sv.mean() - c1.sb.mean():+.4f} ->",
      "same direction" if c1.sv.mean() < c1.sb.mean() else "NOT same direction")
print("\nGATE:", "PASS" if ok and c1.sv.mean() < c1.sb.mean() else "FAIL")
