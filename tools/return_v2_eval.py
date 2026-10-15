"""Return timing v2 (pre-registered in docs/INSIGHTS.md section 9, 2026-10-15).

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

opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
ONLY = opt.get("only")
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


class V2(ReturnModel):
  def fit_frame(self, d):
    self.model = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_depth=3, random_state=0,
                                                categorical_features=[FEATS2.index("inj_code"), FEATS2.index("pos_code")]).fit(d[FEATS2], d.back)
    return self

  def hazard(self, d):
    p = self.model.predict_proba(d[FEATS2])[:, 1]
    if "ir_games" in FEATS2:
      p = np.where(d.ir_short.to_numpy() > 0, 0.0, p)  # IR minimum: can't return yet
    return p

  def p_active(self, state, horizon, first=None, stay=1.0):
    s = state.copy()
    out = np.zeros((len(s), horizon))
    still = np.ones(len(s))
    for h in range(horizon):
      p = self.hazard(s)
      if h == 0 and first is not None:
        p = np.where(np.isnan(first), p, first)
      out[:, h] = (1 - still) * stay + still * p
      still = still * (1 - p)
      ir = s.desig_ir + s.desig_ir_return > 0
      s["missed"] = s.missed + 1
      s["week"] = s.week + 1
      s["missed_x_ir"] = s.missed * (s.desig_ir + s.desig_pup)
      s["report"] = np.where(s.report > 0, 3, 0)
      s["ir_games"] = np.where(ir, s.ir_games + 1, s.ir_games)
      s["ir_short"] = (ir & (s.ir_games < s.ir_min)).astype(float)
      s["prac_score"] = np.nan
      s["espn_wk"] = s.espn_wk - 1
    return out


rows = []
for season in TEST:
  tr = ST[ST.season < season]
  b = ReturnModel(data, played); b._nxt = base_m._nxt; b.fit_frame(tr)
  v = V2(data, played); v._nxt = base_m._nxt; v.fit_frame(tr)
  d = AH[(AH.season < season) & (AH.game_status != "OUT")]
  X = practice_features(d)
  pm = HistGradientBoostingClassifier(**GB, random_state=0).fit(X, d.played)
  t = ST[(ST.season == season) & ST.position.map(POS_GROUP).isin(["QB", "RB", "WR", "TE"])].reset_index(drop=True)
  first = np.full(len(t), np.nan)
  keys = list(zip(t.season, t.next_week.astype(int), t.gsis_id))
  hit = [k in ah.index for k in keys]
  if any(hit):
    sub = ah.loc[[k for k, h_ in zip(keys, hit) if h_]].reset_index()
    p = pm.predict_proba(practice_features(sub)[list(X.columns)])[:, 1]
    first[np.array(hit)] = np.where(sub.game_status.to_numpy() == "OUT", 0.0, p)
  pb, pv = b.p_active(t, H, first=first, stay=1.0), v.p_active(t, H, first=first, stay=1.0)
  for i, x in enumerate(t.itertuples()):
    back = None
    for k in range(1, H + 1):
      lab = base_m.active_after(season, x.gsis_id, x.team, int(x.week), k)
      if lab is None:
        break
      back = k if (back is None and lab) else back
      rows.append({"season": season, "ep": f"{season}-{x.gsis_id}-{int(x.week) - int(x.missed)}", "desig": x.desig, "k": k,
                   "y": float(back is not None and back <= k), "base": pb[i, k - 1], "var": pv[i, k - 1],
                   "impossible": float(x.desig in ("ir", "ir_return") and x.ir_games + k - 1 < x.ir_min)})
R = pd.DataFrame(rows)
R["sb"], R["sv"] = (R.base - R.y) ** 2, (R["var"] - R.y) ** 2
e = R.groupby("ep").agg(sb=("sb", "sum"), sv=("sv", "sum"), n=("y", "size"))
rng = np.random.default_rng(0)
boot = [(lambda z: (z.sv.sum() - z.sb.sum()) / z.n.sum())(e.iloc[rng.integers(0, len(e), len(e))]) for _ in range(2000)]
lo, hi = np.percentile(boot, [2.5, 97.5])
per = R.groupby("season")[["sb", "sv"]].mean()
tag = f"[ret-v2{':' + ONLY if ONLY else ''}]"
print(f"{tag} rows {len(R)}, episodes {len(e)}: Brier base {R.sb.mean():.4f} variant {R.sv.mean():.4f} diff {R.sv.mean() - R.sb.mean():+.4f} "
      f"[{lo:+.4f}, {hi:+.4f}] seasons better {(per.sv < per.sb).sum()}/{len(per)}")
print(per.round(4).to_string())
R["kb"] = pd.cut(R.k, [0, 2, 4, 8], labels=["1-2", "3-4", "5-8"])
cell = R.groupby(["desig", "kb"], observed=True).agg(n=("y", "size"), actual=("y", "mean"), base=("base", "mean"), var=("var", "mean"))
dn = R.groupby("desig").size()
cell = cell[cell.index.get_level_values(0).isin(dn[dn >= 150].index)]
cell["gap"] = 100 * (cell["var"] - cell.actual)
print(cell.round(3).to_string())
imp = R[R.impossible > 0]
print(f"{tag} rule-impossible IR rows n {len(imp)}: actual {imp.y.mean():.3f} variant {imp['var'].mean():.3f} base {imp.base.mean():.3f}")
ok = hi < 0 and (per.sv < per.sb).sum() >= 2 and (cell.gap.abs() <= 5).all() and (len(imp) == 0 or imp["var"].mean() <= 0.01)
print(f"{tag} GATE:", "PASS" if ok else "FAIL")
