"""(DG) a late correction for the team with the ball tied or behind 1-3 (pre-registered 2026-10-25, docs/INSIGHTS.md).

  python tools/late_corr_eval.py export     -> scratch/calc_val/latecorr_rows.json (2006-25 late snaps)
  node tools/late_corr_eval.mjs             -> scratch/calc_val/latecorr_scored.json (wp() fit on 2006-18)
  python tools/late_corr_eval.py analyze    fit on 2006-18, test once on 2019-25 -> data/history/late_corr.json if PASS
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

OUT = ROOT / "scratch" / "calc_val"
K_GAMES = 30
TB = [0, 30, 60, 120, 180]
TB_LAB = ["0:30", "1:00", "2:00", "3:00"]


def cells(t: pd.DataFrame) -> pd.DataFrame:
  t = t.copy()
  t["tb"] = pd.cut(t.sec, TB, labels=TB_LAB, include_lowest=True).astype(str)
  t["fz"] = np.select([t.yl <= 35, t.yl <= 60], ["opp35", "mid"], "deep")
  t["mg"] = np.select([t["diff"] == 0, t["diff"].between(-3, -1)], ["tied", "b1-3"], "other")
  return t


def export():
  rows = []
  for s in range(2006, 2026):
    d = pd.read_parquet(ROOT / "cache" / f"pbp_calc_{s}.parquet")
    d = d[(d.season_type == "REG") & (d.qtr == 4) & d.down.notna() & d.posteam.notna() & d.result.notna()
          & d.play_type.isin(["run", "pass", "punt", "field_goal", "qb_kneel", "qb_spike"])]
    d = d[(d.game_seconds_remaining <= 180) & (d.score_differential.abs() <= 8) & (d.result != 0)]
    home = d.posteam == d.home_team
    for r, h in zip(d.itertuples(), home):
      rows.append({"game_id": r.game_id, "season": s, "won": int((r.result > 0) == h), "diff": float(r.score_differential),
                   "sec": float(r.game_seconds_remaining), "down": int(r.down), "togo": float(r.ydstogo),
                   "yl": float(r.yardline_100), "to": float(r.posteam_timeouts_remaining), "oppTo": float(r.defteam_timeouts_remaining),
                   "line": float(r.spread_line if h else -r.spread_line) if pd.notna(r.spread_line) else 0.0,
                   "total": float(r.total_line) if pd.notna(r.total_line) else 45.0, "home": int(h)})
  (OUT / "latecorr_rows.json").write_text(json.dumps(rows), encoding="utf-8")
  print(f"[dg] {len(rows):,} late snaps 2006-25")


def logit(p):
  p = np.clip(p, 1e-4, 1 - 1e-4)
  return np.log(p / (1 - p))


def analyze():
  t = cells(pd.DataFrame(json.loads((OUT / "latecorr_scored.json").read_text(encoding="utf-8"))))
  tr, te = t[t.season <= 2018], t[t.season >= 2019]
  corr = {}
  for (mg, tb, fz), g in tr[tr.mg != "other"].groupby(["mg", "tb", "fz"]):
    games = g.game_id.nunique()
    c = float(logit(g.won.mean()) - logit(g.p.mean()))
    corr[f"{mg}|{tb}|{fz}"] = {"c": round(c * games / (games + K_GAMES), 4), "raw": round(c, 4), "games": int(games), "n": int(len(g))}
  print("[dg] corrections fit on 2006-18 (log-odds, shrunk):")
  for k, v in corr.items():
    print(f"  {k:18s} games {v['games']:4d}  raw {v['raw']:+.3f}  shrunk {v['c']:+.3f}")
  te = te.copy()
  key = te.mg + "|" + te.tb + "|" + te.fz
  shift = key.map(lambda k: corr.get(k, {}).get("c", 0.0)).astype(float)
  te["p2"] = 1 / (1 + np.exp(-(logit(te.p.to_numpy()) + shift.to_numpy())))
  rng = np.random.default_rng(0)

  def ci(x, a, b):
    d = ((x[b] - x.won) ** 2 - (x[a] - x.won) ** 2).to_numpy()
    ug, inv = np.unique(x.game_id.to_numpy(), return_inverse=True)
    s, c = np.bincount(inv, d), np.bincount(inv)
    bs = [(w * s).sum() / (w * c).sum() for w in (np.bincount(rng.integers(0, len(ug), len(ug)), minlength=len(ug)) for _ in range(2000))]
    return d.mean(), *np.percentile(bs, [2.5, 97.5])

  tg = te[te.mg != "other"]
  m1, lo1, hi1 = ci(tg, "p", "p2")
  cg = tg.groupby(["mg", "tb", "fz"]).agg(n=("won", "size"), won=("won", "mean"), p=("p", "mean"), p2=("p2", "mean"))
  cg = cg[cg.n >= 30]
  gap0, gap1 = (cg.p - cg.won).abs().mean(), (cg.p2 - cg.won).abs().mean()
  m3, lo3, hi3 = ci(te, "p", "p2")
  g1, g2, g3 = hi1 < 0, gap1 < gap0, hi3 < 0.0005
  print(f"\n[dg] 2019-25 targeted rows ({len(tg):,}, {tg.game_id.nunique()} games): Brier {np.mean((tg.p - tg.won) ** 2):.4f} -> "
        f"{np.mean((tg.p2 - tg.won) ** 2):.4f}, {m1:+.4f} [{lo1:+.4f}, {hi1:+.4f}] -> (1) {g1}")
  print(f"[dg] targeted cells' calibration gap ({len(cg)} cells of 30+): {gap0:.4f} -> {gap1:.4f} -> (2) {g2}")
  print(f"[dg] all late rows ({len(te):,}): {m3:+.4f} [{lo3:+.4f}, {hi3:+.4f}] -> (3) {g3}")
  print(cg.assign(gap0=(cg.p - cg.won), gap1=(cg.p2 - cg.won)).round(3).to_string())
  ok = g1 and g2 and g3
  print(f"\n[dg] GATE: {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
  {"export": export, "analyze": analyze}[sys.argv[1] if len(sys.argv) > 1 else "analyze"]()
