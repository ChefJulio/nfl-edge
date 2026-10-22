"""(AS) the week model's stage from the calendar (pre-registered 2026-10-22, amended before running; docs/INSIGHTS.md).
Walk-forward 2021-25 + 2026 to date. Rows: players on the report by calendar day k of their team's report week
(k = 1, 2, final), QB / RB / WR / TE, final-report Out excluded. Each arm is fed what it would see live by that day:
  own      - today's construction: his listed days so far (no fill), stage = his own day count; model trained on
             week_rows with STAGE_FROM="own"
  calendar - the team's report days, a day he isn't listed marked "X" (off the report), stage = calendar day; model
             trained on week_rows with STAGE_FROM="calendar"
GATE: pooled Brier lower with the 95% season-week CI excluding 0 on 2021-25, not worse on 2026.

  python tools/stage_cal_eval.py
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


def ci(diff: pd.Series, cl: pd.Series):
  gr = pd.DataFrame({"d": diff.to_numpy(), "c": cl.to_numpy()}).groupby("c").d.agg(["sum", "size"])
  s_, n_ = gr["sum"].to_numpy(), gr["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(gr), (4000, len(gr)))
  bt = s_[idx].sum(1) / n_[idx].sum(1)
  return diff.mean(), np.percentile(bt, 2.5), np.percentile(bt, 97.5)


def rows(d, rep, hurt, mode):
  T.STAGE_FROM = mode
  w = T.week_rows(d, rep, hurt).dropna(subset=["y"])
  return w[~((w.stage == 3) & (w.gs_now == "Out"))]


def own_view(te: pd.DataFrame) -> pd.DataFrame:
  """The calendar rows as today's construction would see them live by that day."""
  x = te.copy()
  seen = x.own_seen.where(x.own_seen.notna(), x.days_now.str.replace("X", "")).astype(str)
  x["days_now"] = seen
  x["wn_D"], x["wn_L"], x["wn_F"] = seen.str.count("D"), seen.str.count("L"), seen.str.count("F")
  x["w_first"] = seen.str[:1].map(T.SCORE)
  x["w_last"] = seen.str[-1:].map(T.SCORE)
  x["stage"] = np.where(x.stage == 3, 3, np.clip(seen.str.len(), 1, 2))
  return x.drop(columns=["wn_X"], errors="ignore")


def main():
  cfg = load_config()
  d = D.load_all(cfg)
  rep, hurt = T.report_rows(d), T.hurt_notes(d, D.Cache(ROOT / cfg["data"]["cache_dir"]))
  w_own, w_cal = rows(d, rep, hurt, "own"), rows(d, rep, hurt, "calendar")
  print(f"rows own {len(w_own)}, calendar {len(w_cal)}; calendar rows built from dates {w_cal.own_seen.notna().mean():.1%}",
        flush=True)
  out = []
  for s in sorted(set(range(2021, 2026)) | {int(w_cal.season.max())}):
    te = w_cal[(w_cal.season == s) & (w_cal.stage > 0) & (w_cal.on_now == 1)].copy()
    T.STAGE_FROM = "calendar"
    te["p_cal"] = T.week_predict(T.week_model(w_cal, s), te)
    T.STAGE_FROM = "own"
    te["p_own"] = T.week_predict(T.week_model(w_own, s), own_view(te))
    out.append(te)
    print(f"[stage cal] {s}", flush=True)
  r = pd.concat(out, ignore_index=True)
  r = r[r.pos.isin(["QB", "RB", "WR", "TE"])]
  r["cl"] = r.season.astype(str) + "-" + r.week.astype(str)
  bo, bc = (r.p_own - r.y) ** 2, (r.p_cal - r.y) ** 2
  dlt = bc - bo
  hist, now = r.season <= 2025, r.season > 2025
  m, lo, hi = ci(dlt[hist], r.cl[hist])
  print(f"\ncalendar vs own, 2021-25 (n {int(hist.sum())}): Brier {bo[hist].mean():.4f} -> {bc[hist].mean():.4f}: "
        f"{m:+.4f} [{lo:+.4f}, {hi:+.4f}]; 2026 (n {int(now.sum())}): {dlt[now].mean():+.4f}")
  late = r.days_now.str.contains("X", na=False)
  for st in (1, 2, 3):
    k = hist & (r.stage == st)
    kl = k & late
    print(f"  stage {st}: {dlt[k].mean():+.4f} (n {int(k.sum())}); with a day off the report: {dlt[kl].mean():+.4f} "
          f"(n {int(kl.sum())}, played {r.y[kl].mean():.3f}, own {r.p_own[kl].mean():.3f}, calendar {r.p_cal[kl].mean():.3f})")
  for s in sorted(r.season.unique()):
    print(f"  {s}: {dlt[r.season == s].mean():+.4f}")
  f = r[hist & (r.stage == 3)]
  print("\nspots (final report): played / own / calendar")
  for lab, g in (("Q, no practice all week", f[(f.gs_now == "Questionable") & (f.days_now == "DDD")]), ("Doubtful", f[f.gs_now == "Doubtful"])):
    print(f"  {lab:<26} n {len(g):>4}  {g.y.mean():.3f} / {g.p_own.mean():.3f} / {g.p_cal.mean():.3f}")
  gate = hi < 0 and dlt[now].mean() <= 0
  print(f"\nGATE: {'PASS' if gate else 'FAIL'}")


if __name__ == "__main__":
  main()
