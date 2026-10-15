"""Return timing v3, direct horizons (pre-registered in docs/INSIGHTS.md section 9, 2026-10-15; last attempt).

Usage: python tools/return_v3_eval.py
One classifier: P(back by his k-th next game | state now, k), k = 1..8, no chain (v2 rolled today-only
information forward and compounded errors). Same information as v2 plus this week's practice-model P(plays).
Forced 0 when an IR player is still short of the minimum at that game. Gate as v2.

v2 notes follow:

Usage: python tools/return_v2_eval.py [--only=ir|window|espn]
Adds to the return-timing model (nfledge/returns.py): (1) IR rule: games spent on IR so far, hazard 0 below the
season's minimum; (2) practice window: on the practice report for the next game + his practice score, the flag
carried forward once opened; (3) ESPN's estimated return: weeks from the next game to ESPN's return date at the
latest Wayback capture before it, + ESPN status, counted down one week per game. Walk-forward test seasons 2023-25.
Scored: skill players, every return-model state, P(back by his k-th next game), k = 1..8. Baseline and variant both
use production's step 1 (practice estimate when on the report) and stay = 1.
Gate: (i) Brier lower, 95% bootstrap CI by episode excluding 0, >= 2 of 3 seasons; (ii) each designation (n >= 150)
x k-bucket (1-2 / 3-4 / 5-8) within 5 points; (iii) rule-impossible IR rows predicted <= 1%.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402

import run  # noqa: E402
from nfledge.injuries import _SCORE, practice_features  # noqa: E402
from nfledge.returns import FEATURES, POS_GROUP, ReturnModel, played_set  # noqa: E402

ONLY = None
TEST = [2023, 2024, 2025]
H = 8
IR_MIN = lambda season: 4 if season >= 2022 else 3 if season >= 2020 else 8  # noqa: E731
ADD = {"ir": ["ir_games", "ir_short"], "window": ["window", "prac_score"], "espn": ["espn_wk", "espn_has", "espn_out", "espn_ir"]}
USE = ADD[ONLY] if ONLY else sum(ADD.values(), [])
FEATS2 = FEATURES + USE

cfg = run.load_config()
data = run.load_all(cfg)
g = cfg.get("injuries", {})
GB = {"max_iter": int(g.get("gb_iterations", 200)), "learning_rate": float(g.get("gb_learning_rate", 0.05)),
      "max_depth": int(g.get("gb_max_depth", 3))}
played = played_set(data)
base_m = ReturnModel(data, played)
ST = base_m.states(sorted(data.seasons)).reset_index(drop=True)
AH = data.avail_hist

# ---- enrich states ------------------------------------------------------------------------------------------------
sched = data.schedules[data.schedules.game_type == "REG"]
gday = {}
for x in sched.itertuples():
  gday[(x.season, x.week, x.home_team)] = gday[(x.season, x.week, x.away_team)] = pd.Timestamp(x.gameday)
ST = ST.sort_values(["season", "gsis_id", "week"]).reset_index(drop=True)
on_ir = ST.desig.isin(["ir", "ir_return"])
run_id = ((~on_ir) | (ST.gsis_id != ST.gsis_id.shift()) | (ST.season != ST.season.shift()) | (ST.missed == 1)).cumsum()
ST["ir_games"] = np.where(on_ir, on_ir.groupby(run_id).cumsum(), 0).astype(float)
ST["ir_min"] = ST.season.map(IR_MIN)
ST["ir_short"] = (on_ir & (ST.ir_games < ST.ir_min)).astype(float)
ah = AH.drop_duplicates(["season", "week", "gsis_id"], keep="last").set_index(["season", "week", "gsis_id"])
ST["prac_score"] = [np.mean([_SCORE[c] for c in ah.at[k, "days"] if c in _SCORE]) if k in ah.index and isinstance(ah.at[k, "days"], str)
                    and any(c in _SCORE for c in ah.at[k, "days"]) else np.nan
                    for k in zip(ST.season, ST.next_week.astype(int), ST.gsis_id)]
ST["window_now"] = [float(k in ah.index) for k in zip(ST.season, ST.next_week.astype(int), ST.gsis_id)]
ep = ((ST.missed == 1) | (ST.gsis_id != ST.gsis_id.shift()) | (ST.season != ST.season.shift())).cumsum()
ST["window"] = ST.window_now.groupby(ep).cummax()
# ESPN: latest capture between his last missed game and the next one
caps = [pd.read_parquet(ROOT / "cache" / f) for f in ("espn_injury_history.parquet", "espn_injury_midweek.parquet", "espn_injury_2025.parquet")
        if (ROOT / "cache" / f).exists()]
E = pd.concat(caps, ignore_index=True).drop_duplicates(["ts", "espn_id"])
players = data.rosters.dropna(subset=["gsis_id", "espn_id"]).drop_duplicates("gsis_id")
espn_of = {g_: str(e).split(".")[0] for g_, e in zip(players.gsis_id, players.espn_id)}
E["captured"] = pd.to_datetime(E.captured)
E = E.sort_values("captured")
by_id = {k: v for k, v in E.groupby("espn_id")}
wk, has, out_, ir_ = [], [], [], []
for x in ST.itertuples():
  e = by_id.get(espn_of.get(x.gsis_id))
  d0, d1 = gday.get((x.season, int(x.week), x.team)), gday.get((x.season, int(x.next_week), x.team))
  row = None
  if e is not None and d0 is not None and d1 is not None:
    c = e[(e.captured > d0) & (e.captured < d1)]
    if len(c):
      row = c.iloc[-1]
  if row is None:
    wk.append(np.nan); has.append(0.0); out_.append(0.0); ir_.append(0.0)
    continue
  r = pd.Timestamp(row.ret) if row.ret is not None and pd.notna(row.ret) else None
  wk.append((r - d1).days / 7 if r is not None else np.nan)
  has.append(1.0); out_.append(float(row.status == "Out")); ir_.append(float(row.status == "Injured Reserve"))
ST["espn_wk"], ST["espn_has"], ST["espn_out"], ST["espn_ir"] = wk, has, out_, ir_
print(f"[ret-v2] states {len(ST)}; ESPN coverage 2022-25: {ST[ST.season >= 2022].espn_has.mean():.0%}; "
      f"window opened {ST.window.mean():.1%}; ir rows {on_ir.mean():.1%}", flush=True)



# ---- v3: direct horizons ----------------------------------------------------------------------------------------
ST["shortfall"] = np.where(on_ir, np.maximum(0, ST.ir_min - ST.ir_games), 0).astype(float)
pnow = np.full(len(ST), np.nan)
for s_ in sorted(ST.season.unique()):  # this week's practice-model P(plays), walk-forward per season
  d = AH[(AH.season < s_) & (AH.game_status != "OUT")]
  if len(d) < 1000:
    continue
  X = practice_features(d)
  pm = HistGradientBoostingClassifier(**GB, random_state=0).fit(X, d.played)
  idx = np.where(ST.season == s_)[0]
  keys = list(zip(ST.season.iloc[idx], ST.next_week.iloc[idx].astype(int), ST.gsis_id.iloc[idx]))
  hit = [k in ah.index for k in keys]
  if any(hit):
    sub = ah.loc[[k for k, h_ in zip(keys, hit) if h_]].reset_index()
    p = pm.predict_proba(practice_features(sub)[list(X.columns)])[:, 1]
    pnow[idx[np.array(hit)]] = np.where(sub.game_status.to_numpy() == "OUT", 0.0, p)
ST["p_now"] = pnow
F3 = FEATURES + ["k", "ir_games", "shortfall", "window_now", "window", "prac_score", "espn_wk", "espn_has", "espn_out",
                 "espn_ir", "p_now"]
# expand every state to k = 1..8 with its label (back by game k), where known
lab = []
for i, x in enumerate(ST.itertuples()):
  back = None
  for k in range(1, H + 1):
    a = base_m.active_after(x.season, x.gsis_id, x.team, int(x.week), k)
    if a is None:
      break
    back = k if (back is None and a) else back
    lab.append((i, k, float(back is not None and back <= k)))
L = pd.DataFrame(lab, columns=["i", "k", "y"])
XK = ST.iloc[L.i.to_numpy()].reset_index(drop=True)
XK["k"], XK["y"] = L.k.to_numpy(), L.y.to_numpy()
XK["impossible"] = (XK.desig.isin(["ir", "ir_return"]) & (XK.k <= XK.shortfall)).astype(float)
print(f"[ret-v3] {len(XK)} state x k rows", flush=True)

rows = []
for season in TEST:
  tr = XK[XK.season < season]
  m3 = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_depth=4, random_state=0,
                                      categorical_features=[F3.index("inj_code"), F3.index("pos_code")]).fit(tr[F3], tr.y)
  b = ReturnModel(data, played); b._nxt = base_m._nxt; b.fit_frame(ST[ST.season < season])
  t = ST[(ST.season == season) & ST.position.map(POS_GROUP).isin(["QB", "RB", "WR", "TE"])]
  first = t.p_now.to_numpy()
  pb = b.p_active(t.reset_index(drop=True), H, first=first, stay=1.0)
  pos_of = {ix: j for j, ix in enumerate(t.index)}
  te = XK[(XK.season == season) & XK.position.map(POS_GROUP).isin(["QB", "RB", "WR", "TE"])].copy()
  # the state row each test row came from
  src_i = L.i.to_numpy()[te.index.to_numpy()]
  te["base"] = [pb[pos_of[s_], k - 1] for s_, k in zip(src_i, te.k)]
  v = m3.predict_proba(te[F3])[:, 1]
  te["var"] = np.where(te.impossible > 0, 0.0, v)
  te["ep"] = te.season.astype(str) + "-" + te.gsis_id + "-" + (te.week - te.missed).astype(int).astype(str)
  rows.append(te[["season", "ep", "desig", "k", "y", "base", "var", "impossible"]])
R = pd.concat(rows, ignore_index=True)
R["sb"], R["sv"] = (R.base - R.y) ** 2, (R["var"] - R.y) ** 2
e = R.groupby("ep").agg(sb=("sb", "sum"), sv=("sv", "sum"), n=("y", "size"))
rng = np.random.default_rng(0)
boot = [(lambda z: (z.sv.sum() - z.sb.sum()) / z.n.sum())(e.iloc[rng.integers(0, len(e), len(e))]) for _ in range(2000)]
lo, hi = np.percentile(boot, [2.5, 97.5])
per = R.groupby("season")[["sb", "sv"]].mean()
print(f"[ret-v3] rows {len(R)}, episodes {len(e)}: Brier base {R.sb.mean():.4f} variant {R.sv.mean():.4f} diff {R.sv.mean() - R.sb.mean():+.4f} "
      f"[{lo:+.4f}, {hi:+.4f}] seasons better {(per.sv < per.sb).sum()}/{len(per)}")
print(per.round(4).to_string())
R["kb"] = pd.cut(R.k, [0, 2, 4, 8], labels=["1-2", "3-4", "5-8"])
cell = R.groupby(["desig", "kb"], observed=True).agg(n=("y", "size"), actual=("y", "mean"), base=("base", "mean"), var=("var", "mean"))
dn = R.groupby("desig").size()
cell = cell[cell.index.get_level_values(0).isin(dn[dn >= 150].index)]
cell["gap"] = 100 * (cell["var"] - cell.actual)
print(cell.round(3).to_string())
imp = R[R.impossible > 0]
print(f"[ret-v3] rule-impossible IR rows n {len(imp)}: actual {imp.y.mean():.3f} variant {imp['var'].mean():.3f} base {imp.base.mean():.3f}")
ok = hi < 0 and (per.sv < per.sb).sum() >= 2 and (cell.gap.abs() <= 5).all() and (len(imp) == 0 or imp["var"].mean() <= 0.01)
print("[ret-v3] GATE:", "PASS" if ok else "FAIL")
R.to_parquet(ROOT / "cache" / "return_v3_eval.parquet", index=False)
