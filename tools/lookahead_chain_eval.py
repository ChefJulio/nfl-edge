"""Lookahead starts from this week's estimate (pre-registered in docs/INSIGHTS.md section 9, 2026-10-15).

Usage: python tools/lookahead_chain_eval.py
(A) players already out (return-model state) whose next game has a practice row: chain step 1 = the practice
    model's P(plays) instead of the return model's hazard.
(B) newly injured (on the report for game G after playing the previous game): production treats them as healthy
    from G+1 on (P = 1.0); variant chains: P(G) = practice model, and if he misses G a state (missed 1, active,
    his report status and injury) feeds the hazard from there.
Walk-forward 2022-25; label = played his team's k-th game, k = 2..6 (k = 1 is the current week). Gate (each):
pooled Brier lower, 95% bootstrap CI (2,000 player-episode resamples) excluding 0, lower in >= 3 of 4 seasons.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402

import run  # noqa: E402
from nfledge.injuries import practice_features  # noqa: E402
from nfledge.returns import REPORT, ReturnModel, played_set  # noqa: E402

TEST = [2022, 2023, 2024, 2025]
H = 6
cfg = run.load_config()
data = run.load_all(cfg)
gb = cfg.get("injuries", {})
GB = {"max_iter": int(gb.get("gb_iterations", 200)), "learning_rate": float(gb.get("gb_learning_rate", 0.05)),
      "max_depth": int(gb.get("gb_max_depth", 3))}
AH = data.avail_hist.copy()
m = ReturnModel(data, played_set(data))
ST = m.states(sorted(s for s in data.seasons if s <= max(TEST)))
INJ = data.injuries[(data.injuries.game_type == "REG") & data.injuries.gsis_id.notna()].drop_duplicates(
  ["season", "week", "gsis_id"], keep="last").set_index(["season", "week", "gsis_id"])


def chain(model, state: pd.DataFrame, first: np.ndarray, steps: int, start_out: np.ndarray | None = None) -> np.ndarray:
  """P(active) over `steps` games. first: P(back) at step 1 (None = hazard). start_out: P(still out) entering step 1
  (default 1: out now)."""
  s = state.copy()
  out = np.zeros((len(s), steps))
  still = np.ones(len(s)) if start_out is None else start_out.copy()
  stay = getattr(model, "stay_active", 1.0)
  for h in range(steps):
    p = first if (h == 0 and first is not None) else model.hazard(s)
    out[:, h] = (1 - still) * stay + still * p
    still = still * (1 - p)
    s["missed"] = s.missed + 1
    s["week"] = s.week + 1
    s["missed_x_ir"] = s.missed * (s.desig_ir + s.desig_pup)
    s["report"] = np.where(s.report > 0, 3, 0)
  return out


def brier_gate(R: pd.DataFrame, name: str) -> bool:
  R = R[(R.k >= 2)].copy()
  R["sb"], R["sv"] = (R.base - R.y) ** 2, (R["var"] - R.y) ** 2
  ep = R.groupby("ep").agg(sb=("sb", "sum"), sv=("sv", "sum"), n=("y", "size"))
  rng = np.random.default_rng(0)
  boot = []
  for _ in range(2000):
    e = ep.iloc[rng.integers(0, len(ep), len(ep))]
    boot.append((e.sv.sum() - e.sb.sum()) / e.n.sum())
  lo, hi = np.percentile(boot, [2.5, 97.5])
  per = R.groupby("season")[["sb", "sv"]].mean()
  d = R.sv.mean() - R.sb.mean()
  print(f"[{name}] episodes {len(ep)}, rows {len(R)}: Brier base {R.sb.mean():.4f} variant {R.sv.mean():.4f} diff {d:+.4f} "
        f"[{lo:+.4f}, {hi:+.4f}], seasons better {(per.sv < per.sb).sum()}/{len(per)}")
  print(per.round(4).to_string())
  print(R.groupby("k").agg(n=("y", "size"), actual=("y", "mean"), base=("base", "mean"), var=("var", "mean")).round(3).to_string())
  ok = hi < 0 and (per.sv < per.sb).sum() >= 3
  print(f"[{name}] GATE:", "PASS" if ok else "FAIL")
  return ok


A, B = [], []
for season in TEST:
  m.fit_frame(ST[ST.season < season])
  d = AH[(AH.season < season) & (AH.game_status != "OUT")]
  X = practice_features(d)
  pm = HistGradientBoostingClassifier(**GB, random_state=0).fit(X, d.played)
  cols = list(X.columns)
  ah = AH[AH.season == season].drop_duplicates(["week", "gsis_id"], keep="last").set_index(["week", "gsis_id"])

  def prac(rows: pd.DataFrame) -> np.ndarray:
    p = pm.predict_proba(practice_features(rows)[cols])[:, 1]
    return np.where(rows.game_status.to_numpy() == "OUT", 0.0, p)

  # (A) states with a practice row for the next game
  t = ST[ST.season == season].reset_index(drop=True)
  has = np.array([(int(w), g) in ah.index for w, g in zip(t.next_week, t.gsis_id)])
  t = t[has].reset_index(drop=True)
  first = prac(ah.loc[[(int(w), g) for w, g in zip(t.next_week, t.gsis_id)]].reset_index())
  base, var = chain(m, t, None, H), chain(m, t, first, H)
  for i, x in enumerate(t.itertuples()):
    for k in range(1, H + 1):
      lab = m.active_after(season, x.gsis_id, x.team, int(x.week), k)
      if lab is not None:
        A.append({"season": season, "ep": f"A{season}-{i}", "k": k, "y": float(lab), "base": base[i, k - 1], "var": var[i, k - 1]})

  # (B) newly injured: on the report for game G, played his team's previous game
  sch = data.schedules[(data.schedules.season == season) & (data.schedules.game_type == "REG")]
  tw = {}
  for tm in set(sch.home_team) | set(sch.away_team):
    tw[tm] = sorted(set(sch[sch.home_team == tm].week) | set(sch[sch.away_team == tm].week))
  rows = ah.reset_index()
  rows = rows[rows.team.isin(tw)]
  prev = [next((w for w in reversed(tw[tm]) if w < g), None) for tm, g in zip(rows.team, rows.week)]
  keep = [pw is not None and (season, pw, gid) in m.played and g in tw[tm]
          for pw, gid, g, tm in zip(prev, rows.gsis_id, rows.week, rows.team)]
  rows = rows[keep].reset_index(drop=True)
  if rows.empty:
    continue
  p1 = prac(rows)
  st = pd.DataFrame({"season": season, "week": rows.week.astype(int), "gsis_id": rows.gsis_id, "team": rows.team, "missed": 1,
                     "desig": "active",
                     "report": [REPORT.get(INJ.report_status.get((season, int(w), g)), 0) if (season, int(w), g) in INJ.index else 0
                                for w, g in zip(rows.week, rows.gsis_id)],
                     "injury": [INJ.report_primary_injury.get((season, int(w), g)) if (season, int(w), g) in INJ.index else None
                                for w, g in zip(rows.week, rows.gsis_id)],
                     "position": rows.position, "next_week": 0, "back": False})
  st = ReturnModel._encode(st)
  # step 1 = game G (practice model); steps 2.. chain from the state after missing G (still out = 1 - p1)
  later = chain(m, st, None, H - 1, start_out=1 - p1)
  for i, x in enumerate(rows.itertuples()):
    for k in range(2, H + 1):
      lab = m.active_after(season, x.gsis_id, x.team, int(x.week), k - 1)
      if lab is not None:
        B.append({"season": season, "ep": f"B{season}-{i}", "k": k, "y": float(lab), "base": 1.0, "var": later[i, k - 2]})

A, B = pd.DataFrame(A), pd.DataFrame(B)
A.to_parquet(ROOT / "cache" / "lookahead_chain_A.parquet", index=False)
B.to_parquet(ROOT / "cache" / "lookahead_chain_B.parquet", index=False)
okA = brier_gate(A, "A already out")
okB = brier_gate(B, "B newly injured")
