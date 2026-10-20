"""(BD) ESPN's estimated return date in the return chain (pre-registered in docs/INSIGHTS.md 2026-10-19).

Usage: python tools/return_espn_eval.py
Today's return chain (nfledge/returns.py CHAIN_FEATURES) vs the same chain with three ESPN inputs, the IR model's own
(return_timing.enrich): espn_wk = weeks from his team's next game to ESPN's estimated return date (latest capture
between the game he just missed and that next game), espn_has, espn_out. Each chain step to his team's following game
lowers espn_wk by that gap / 7 (the date is fixed). Captures: data/history/espn_injury_captures.parquet (2022-09 to
2026-01) plus the archive branch's daily 2026 snapshots (data/espn_injuries/*.csv).
Walk-forward: each test season fit on the seasons before. Rows: every return-model state; label = played his team's
k-th game after it, k = 1..6.
GATE: (1) states with an ESPN capture, Brier over k = 1..6: lower, 95% CI (2,000 state resamples) upper < 0,
improvement >= 0.003, lower in >= 3 of 4 seasons; (2) all states, k = 1..6, CI upper < +0.0005; (3) calibration
error (k = 1, states with a capture) not above today's + 0.005; CONFIRM 2026 same direction.
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

TEST, CONFIRM, H = [2022, 2023, 2024, 2025], 2026, 6
ESPN = ["espn_wk", "espn_has", "espn_out"]
cfg = run.load_config()
data = run.load_all(cfg)
m = ReturnModel(data, played_set(data))
FEAT1 = m.feats  # production's features
FEAT2 = FEAT1 + ESPN
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
    if not n.endswith(".csv"):
      continue
    f = pd.read_csv(io.StringIO(subprocess.run(["git", "show", f"origin/archive:{n}"], capture_output=True, text=True,
                                               encoding="utf-8", cwd=ROOT).stdout))
    daily.append(pd.DataFrame({"captured": pd.Timestamp(Path(n).stem), "espn_id": f.espn_id.astype(str), "status": f.status,
                               "ret": pd.to_datetime(f.return_date, errors="coerce", utc=True).dt.tz_convert(None)}))
  return pd.concat([esp] + daily, ignore_index=True)


ST = m._calendar(m.states(sorted(data.seasons))).reset_index(drop=True)
ESP = captures()
prac = data.avail_hist[["season", "week", "gsis_id", "days", "game_status"]]
EN = RT.enrich(data, ST, prac, ESP)[["season", "gsis_id", "week"] + ESPN]
ST = ST.merge(EN.drop_duplicates(["season", "gsis_id", "week"]), on=["season", "gsis_id", "week"], how="left")
ST["espn_has"] = ST.espn_has.fillna(0.0)
ST["espn_out"] = ST.espn_out.fillna(0.0)


def chain(model, state: pd.DataFrame, feats: list[str], rule: bool = False) -> np.ndarray:
  """The chain (as returns.ReturnModel.p_active, stay = 1.0), stepping espn_wk with the calendar. rule: the reported
  arm, P = 0 while ESPN's date is 14+ days past the game and ESPN says Out (else today's hazard)."""
  s = state.copy()
  out, still = np.zeros((len(s), H)), np.ones(len(s))
  for h in range(H):
    p = model.predict_proba(s[feats])[:, 1]
    if rule:
      p = np.where((s.espn_out.to_numpy() == 1) & (s.espn_wk.fillna(-99).to_numpy() * 7 >= 14), 0.0, p)
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
    s["report"] = np.where(s.report > 0, 3, 0)  # as production: still out next week = listed Out
  return out


rows = []
for season in TEST + [CONFIRM]:
  known = ST.season < season
  base = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_depth=3, random_state=0,
                                        categorical_features=[FEAT1.index("inj_code"), FEAT1.index("pos_code")])
  base = base.fit(ST.loc[known, FEAT1], ST.loc[known, "back"])
  # columns with no data in the training seasons drop out (as return_timing.fit does): no ESPN captures before 2022-09,
  # so the 2022 test season's variant equals today's chain
  fs = [c for c in FEAT2 if ST.loc[known, c].notna().any() and ST.loc[known, c].nunique() > 1]
  var = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_depth=3, random_state=0,
                                       categorical_features=[fs.index("inj_code"), fs.index("pos_code")]).fit(ST.loc[known, fs], ST.loc[known, "back"])
  t = ST[ST.season == season].reset_index(drop=True)
  if season == CONFIRM:
    t = t[t.next_week < data.completed_weeks(season) + 1].reset_index(drop=True)
  b, v, rl = chain(base, t, FEAT1), chain(var, t, fs), chain(base, t, FEAT1, rule=True)
  for i, x in enumerate(t.itertuples()):
    for k in range(1, H + 1):
      lab = m.active_after(season, x.gsis_id, x.team, int(x.week), k)
      if lab is None:
        break
      rows.append({"season": season, "ep": f"{season}-{i}", "k": k, "y": float(lab), "base": b[i, k - 1], "var": v[i, k - 1],
                   "rule": rl[i, k - 1], "has": x.espn_has == 1, "long": bool(x.espn_out == 1 and (x.espn_wk or -99) * 7 >= 14),
                   "ir": x.desig in ("ir", "ir_return", "pup")})
  print(f"  {season}: {len(t)} states, {int(t.espn_has.sum())} with an ESPN capture", flush=True)
R = pd.DataFrame(rows)
R["sb"], R["sv"], R["sr"] = (R.base - R.y) ** 2, (R["var"] - R.y) ** 2, (R.rule - R.y) ** 2


def ci(r: pd.DataFrame, a: str = "sv") -> tuple:
  ep = r.groupby("ep").agg(sb=("sb", "sum"), sv=(a, "sum"), n=("y", "size"))
  rng = np.random.default_rng(0)
  boot = [(lambda e: (e.sv.sum() - e.sb.sum()) / e.n.sum())(ep.iloc[rng.integers(0, len(ep), len(ep))]) for _ in range(2000)]
  return r[a].mean() - r.sb.mean(), *np.percentile(boot, [2.5, 97.5])


def ece(p, y, bins=10):
  b = np.minimum((p * bins).astype(int), bins - 1)
  d = pd.DataFrame({"b": b, "p": p, "y": y}).groupby("b").agg(p=("p", "mean"), y=("y", "mean"), n=("y", "size"))
  return float((d.n * (d.p - d.y).abs()).sum() / d.n.sum())


fmt = lambda t: f"{t[0]:+.4f} [{t[1]:+.4f}, {t[2]:+.4f}]"  # noqa: E731
T = R[R.season.isin(TEST)]
H1 = T[T.has]
g1 = ci(H1)
per = H1.groupby("season")[["sb", "sv"]].mean()
better = int((per.sv < per.sb).sum())
g2 = ci(T)
k1 = H1[H1.k == 1]
eb, ev = ece(k1.base.to_numpy(), k1.y.to_numpy()), ece(k1["var"].to_numpy(), k1.y.to_numpy())
print(f"\n2022-25: {T.ep.nunique()} states ({H1.ep.nunique()} with an ESPN capture), {len(T)} state-games")
print(f"(1) states with a capture, k=1-6: Brier {H1.sb.mean():.4f} -> {H1.sv.mean():.4f}, {fmt(g1)}, seasons better {better}/4")
print(per.round(4).to_string())
print(f"(2) all states, k=1-6: Brier {T.sb.mean():.4f} -> {T.sv.mean():.4f}, {fmt(g2)}")
print(f"(3) calibration error (k=1, with a capture): {eb:.4f} -> {ev:.4f}")
L = T[T.long]
if len(L):
  print(f"\nReported: ESPN Out with a date 14+ days past the next game: {L.ep.nunique()} states; played {L.y.mean():.3f}, today {L.base.mean():.3f},"
        f" variant {L['var'].mean():.3f}, rule {L.rule.mean():.3f}; Brier today {L.sb.mean():.4f}, variant {L.sv.mean():.4f} {fmt(ci(L))},"
        f" rule {L.sr.mean():.4f} {fmt(ci(L, 'sr'))}")
for lab, sub in (("active roster", H1[~H1.ir]), ("IR / PUP", H1[H1.ir])):
  if len(sub):
    print(f"Reported: {lab} with a capture: {fmt(ci(sub))}")
C = R[(R.season == CONFIRM) & R.has]
same = len(C) and C.sv.mean() < C.sb.mean()
print(f"\nCONFIRM {CONFIRM} (states with a capture): {C.ep.nunique()} states, diff {C.sv.mean() - C.sb.mean():+.4f} ->",
      "same direction" if same else "NOT same direction")
ok = g1[2] < 0 and g1[0] <= -0.003 and better >= 3 and g2[2] < 0.0005 and ev <= eb + 0.005 and same
print("GATE:", "PASS" if ok else "FAIL")
