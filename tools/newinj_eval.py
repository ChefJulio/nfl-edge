"""(AH) the lookahead chain for newly injured players (pre-registered in docs/INSIGHTS.md 2026-10-17).

Usage: python tools/newinj_eval.py
Rows: walk-forward backtests (cache/experiments/adopted_*), seasons 2022-25, weeks 3-17, QB / RB / WR / TE projected
>= 3 points if active. Predicted points over his team's next 6 games (this week's included) = projection if active x
the sum of his chance to play each game. This week's chance is the backtest's (both versions). Later games:
  today    1.0 for everyone (the lookahead's healthy default; players with a return state are left at 1.0 in both
           versions here, so the paired difference comes from newly injured rows only)
  variant  newly injured (on this week's report, played his team's previous game): chance this week p; if he misses
           this week, the return model's chain from (missed 1, active, report status, injury, calendar); once back 1.0
Actual = fantasy points over those games (0 when he didn't play). GATE: MAE lower, 95% CI over season-weeks excluding
0, lower in >= 3 of 4 seasons; guard: mean weekly Spearman not lower (CI lower bound > -0.002).
"""
import glob
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import run  # noqa: E402
from nfledge.config import load_scoring  # noqa: E402
from nfledge.player_model import actual_points  # noqa: E402
from nfledge.returns import REPORT, ReturnModel, played_set  # noqa: E402

TEST, K = [2022, 2023, 2024, 2025], 6
cfg = run.load_config()
data = run.load_all(cfg)
m = ReturnModel(data, played_set(data))
ST = m.states(sorted(data.seasons))  # also builds m._tw / m._gd (team schedules, game dates)
ACT = actual_points(data.stats, load_scoring()).set_index(["season", "week", "gsis_id"]).actual
INJ = data.injuries[(data.injuries.game_type == "REG") & data.injuries.gsis_id.notna()].drop_duplicates(
  ["season", "week", "gsis_id"], keep="last").set_index(["season", "week", "gsis_id"]).report_primary_injury
BT = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(str(ROOT / "cache" / "experiments" / "adopted_*.parquet")))])
BT = BT[BT.season.isin(TEST) & BT.week.between(3, 17) & BT.pos.isin(["QB", "RB", "WR", "TE"]) & (BT.proj >= 3)].reset_index(drop=True)

out = []
for s in TEST:
  m.fit_frame(ST[ST.season < s])
  b = BT[BT.season == s].reset_index(drop=True)
  games, prev_played, newinj = [], [], []
  for x in b.itertuples():
    ws = m._tw.get((s, x.team), [])
    w = int(x.week)
    games.append([w] + [g for g in ws if g > w][:K - 1] if w in ws else [])
    pw = next((g for g in reversed(ws) if g < w), None)
    pp = pw is not None and (s, pw, x.gsis_id) in m.played
    prev_played.append(pp)
    newinj.append(pp and isinstance(x.status, str) and x.status.strip() != "")
  b["games"], b["newinj"] = games, newinj
  b = b[b.games.map(len) > 0].reset_index(drop=True)
  # chain for newly injured rows: the state after missing this week's game
  ni = b[b.newinj].reset_index(drop=True)
  chain = np.ones((len(b), K - 1))
  if len(ni):
    st = pd.DataFrame({"season": s, "week": ni.week.astype(int), "gsis_id": ni.gsis_id, "team": ni.team, "missed": 1,
                       "desig": "active",
                       "report": [REPORT.get(str(t).split(" (")[0].strip(), 0) for t in ni.status],
                       "injury": [INJ.get((s, int(w), g)) for w, g in zip(ni.week, ni.gsis_id)],
                       "position": ni.pos,
                       "next_week": [g[1] if len(g) > 1 else int(w) + 1 for g, w in zip(ni.games, ni.week)],
                       "back": False})
    st = m._calendar(ReturnModel._encode(st))
    pa = m.p_active(st, K - 1, stay=1.0)
    p0 = ni.avail.clip(0, 1).to_numpy()[:, None]
    chain[b.index[b.newinj].to_numpy()] = p0 + (1 - p0) * pa  # played this week -> back; else the chain
  for i, x in enumerate(b.itertuples()):
    g = x.games
    act = sum(float(ACT.get((s, w, x.gsis_id), 0.0)) for w in g)
    p_now = float(np.clip(x.avail, 0, 1))
    base = x.proj * (p_now + (len(g) - 1))
    var = x.proj * (p_now + chain[i, :len(g) - 1].sum())
    out.append({"season": s, "week": int(x.week), "wk": f"{s}-{x.week}", "newinj": x.newinj, "pred_b": base, "pred_v": var, "y": act})
  print(f"  {s}: {len(b)} rows, newly injured {int(b.newinj.sum())}", flush=True)

R = pd.DataFrame(out)
R["eb"], R["ev"] = (R.pred_b - R.y).abs(), (R.pred_v - R.y).abs()


def ci(diff, groups):
  g = pd.DataFrame({"d": diff, "g": groups}).groupby("g").d.agg(["sum", "size"])
  idx = np.random.default_rng(0).integers(0, len(g), size=(2000, len(g)))
  m_ = g["sum"].to_numpy()[idx].sum(1) / g["size"].to_numpy()[idx].sum(1)
  return np.percentile(m_, [2.5, 97.5])


d = (R.ev - R.eb).to_numpy()
lo, hi = ci(d, R.wk)
per = R.groupby("season")[["eb", "ev"]].mean()
better = int((per.ev < per.eb).sum())
print(f"\nnext-{K}-games points MAE, {len(R)} rows: today {R.eb.mean():.3f} variant {R.ev.mean():.3f} diff {d.mean():+.3f} [{lo:+.3f}, {hi:+.3f}], seasons better {better}/4")
print(per.round(3).to_string())
n = R[R.newinj]
print(f"newly injured rows ({len(n)}): MAE {n.eb.mean():.2f} -> {n.ev.mean():.2f}; mean predicted {n.pred_b.mean():.1f} -> {n.pred_v.mean():.1f}, actual {n.y.mean():.1f}")
sp = R.groupby("wk").apply(lambda g: pd.Series({"b": g.pred_b.corr(g.y, method="spearman"), "v": g.pred_v.corr(g.y, method="spearman")}))
sd = (sp.v - sp.b).to_numpy()
idx = np.random.default_rng(0).integers(0, len(sd), size=(2000, len(sd)))
slo, shi = np.percentile(sd[idx].mean(1), [2.5, 97.5])
print(f"weekly Spearman: today {sp.b.mean():.4f} variant {sp.v.mean():.4f} diff {sd.mean():+.4f} [{slo:+.4f}, {shi:+.4f}]")
ok = hi < 0 and better >= 3 and slo > -0.002
print("GATE:", "PASS" if ok else "FAIL")
