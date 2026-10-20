"""(BE) Roster designation as an input, not a gate (pre-registered 2026-10-20, docs/INSIGHTS.md (BE)).

Usage: python tools/reserve_avail_eval.py
Rows: tools/week_avail_eval.py's (nfledge/tuesday.py week_rows; game status Out at stage 3 excluded, 0 by rule).
Today: reserve-list players are not rows (and off the live board: 0). Variant: week_rows(reserve=True) adds a
reserve-list player once his practice window is visible (stage 0: on his previous week's report; stages 1-3: on this
week's) with res_prev / res_code / res_weeks. Walk-forward (tuesday.week_model: season s trained on seasons before,
calibrated per stage on s-1), 2021-25, 2026 so far as CONFIRM.
GATE: (1) reserve-window rows, Brier vs 0: lower, CI upper < 0, improvement >= 0.01; (2) other rows, variant vs today's
model: CI upper < +0.0005; (3) reserve-window rows at stages 1 and 3: mean predicted within 3 points of the played
rate; CONFIRM 2026 (1) same direction.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge import tuesday as T  # noqa: E402
from nfledge.config import load_config  # noqa: E402

KEY = ["season", "week", "gsis_id", "stage"]
CODE = {1.0: "designated to return", 2.0: "injured reserve", 3.0: "PUP / NFI", 4.0: "other"}


def ci(diff: np.ndarray, cl: np.ndarray):
  gr = pd.DataFrame({"d": diff, "c": cl}).groupby("c").d.agg(["sum", "size"])
  s_, n_ = gr["sum"].to_numpy(), gr["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(gr), (4000, len(gr)))
  bt = s_[idx].sum(1) / n_[idx].sum(1)
  return float(diff.mean()), float(np.percentile(bt, 2.5)), float(np.percentile(bt, 97.5))


def main():
  cfg = load_config()
  d = D.load_all(cfg)
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  rep, hurt = T.report_rows(d), T.hurt_notes(d, cache)
  drop = lambda w: w[~((w.stage == 3) & (w.gs_now == "Out"))].dropna(subset=["y"]).reset_index(drop=True)  # noqa: E731
  base, var = drop(T.week_rows(d, rep, hurt)), drop(T.week_rows(d, rep, hurt, reserve=True))
  print(f"rows: today {len(base)}, variant {len(var)} ({int(var.res_prev.sum())} reserve-window rows)", flush=True)
  out = []
  for s in list(range(2021, 2026)) + [2026]:
    tb, tv = base[base.season == s], var[var.season == s]
    if not len(tv):
      continue
    mb, mv = T.week_model(base, s), T.week_model(var, s)
    pb = pd.Series(T.week_predict(mb, tb), index=pd.MultiIndex.from_frame(tb[KEY]))
    pv = T.week_predict(mv, tv)
    o = tv[KEY + ["y", "res_prev", "res_code", "gs_now", "days_now"]].copy()
    o["p_var"] = pv
    o["p_base"] = pb.reindex(pd.MultiIndex.from_frame(tv[KEY])).to_numpy()
    o.loc[o.res_prev == 1, "p_base"] = 0.0  # today: off the board
    out.append(o)
    print(f"  {s}: {len(tv)} rows, {int(tv.res_prev.sum())} reserve-window", flush=True)
  r = pd.concat(out, ignore_index=True)
  r["sb"], r["sv"] = (r.p_base - r.y) ** 2, (r.p_var - r.y) ** 2
  r["cl"] = r.season.astype(str) + "-" + r.week.astype(str)
  fmt = lambda t: f"{t[0]:+.4f} [{t[1]:+.4f}, {t[2]:+.4f}]"  # noqa: E731
  T5 = r[r.season <= 2025]
  R, O = T5[T5.res_prev == 1], T5[T5.res_prev == 0].dropna(subset=["p_base"])
  g1 = ci((R.sv - R.sb).to_numpy(), R.cl.to_numpy())
  g2 = ci((O.sv - O.sb).to_numpy(), O.cl.to_numpy())
  print(f"\n2021-25 reserve-window rows {len(R)} (players {R.gsis_id.nunique()}), played {R.y.mean():.3f}")
  print(f"(1) reserve-window Brier vs 0: {R.sb.mean():.4f} -> {R.sv.mean():.4f}, {fmt(g1)}")
  print(f"(2) other rows: {O.sb.mean():.4f} -> {O.sv.mean():.4f}, {fmt(g2)}")
  ok3 = True
  for st in (0, 1, 2, 3):
    k = R[R.stage == st]
    if len(k):
      gap = abs(k.p_var.mean() - k.y.mean())
      if st in (1, 3):
        ok3 = ok3 and gap <= 0.03
      print(f"(3) stage {st}: {len(k)} rows, predicted {k.p_var.mean():.3f}, played {k.y.mean():.3f}{'  (gated)' if st in (1, 3) else ''}")
  f3 = R[R.stage == 3].assign(code=lambda x: x.res_code.map(CODE))
  print("\nStage 3 (final report) by list x final status:")
  print(f3.groupby(["code", "gs_now"]).agg(n=("y", "size"), played=("y", "mean"), predicted=("p_var", "mean")).round(3).to_string())
  full = f3[(f3.gs_now == "None") & f3.days_now.str.contains("F") & ~f3.days_now.str.contains("D")]
  print(f"\nWindow open, no final status, practiced (no DNP): {len(full)} rows, played {full.y.mean():.3f}, predicted {full.p_var.mean():.3f}")
  C = r[(r.season == 2026) & (r.res_prev == 1)]
  same = len(C) and C.sv.mean() < C.sb.mean()
  print(f"\nCONFIRM 2026 reserve-window: {len(C)} rows, {C.sb.mean() if len(C) else float('nan'):.4f} -> {C.sv.mean() if len(C) else float('nan'):.4f}:",
        "same direction" if same else "NOT same direction")
  ok = g1[2] < 0 and g1[0] <= -0.01 and g2[2] < 0.0005 and ok3 and same
  print("GATE:", "PASS" if ok else "FAIL")


if __name__ == "__main__":
  main()
