"""(CN2) days as inputs alone (pre-registered 2026-10-22, docs/INSIGHTS.md). Walk-forward, test 2021-25 + 2026 to date.
  (a) Tuesday model: + gap_days (days from his last team game to the game predicted); no extra training rows.
  (b) week model: + onset_days (days from the start of this injury to game day, as known at each stage).
GATE each: Brier lower with the 95% season-week CI excluding 0 (a: all Tuesday rows; b: stages 1-3 on-report rows),
not worse on 2026.

  python tools/days_eval.py
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

SEASONS = list(range(2021, 2026))


def ci(diff: pd.Series, cl: pd.Series):
  gr = pd.DataFrame({"d": diff.to_numpy(), "c": cl.to_numpy()}).groupby("c").d.agg(["sum", "size"])
  s_, n_ = gr["sum"].to_numpy(), gr["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(gr), (4000, len(gr)))
  bt = s_[idx].sum(1) / n_[idx].sum(1)
  return diff.mean(), np.percentile(bt, 2.5), np.percentile(bt, 97.5)


def verdict(name: str, r: pd.DataFrame, by: str | None = None) -> bool:
  r = r.assign(cl=r.season.astype(str) + "-" + r.week.astype(str))
  dlt = (r.p1 - r.y) ** 2 - (r.p0 - r.y) ** 2
  hist = r.season <= 2025
  m, lo, hi = ci(dlt[hist], r.cl[hist])
  now = dlt[~hist].mean() if (~hist).any() else 0.0
  print(f"\n{name}: 2021-25 (n {int(hist.sum())}) Brier {((r.p0 - r.y) ** 2)[hist].mean():.4f} -> {((r.p1 - r.y) ** 2)[hist].mean():.4f}: "
        f"{m:+.4f} [{lo:+.4f}, {hi:+.4f}]; 2026 {now:+.4f} (n {int((~hist).sum())})")
  for s in sorted(r.season.unique()):
    print(f"  {s}: {dlt[r.season == s].mean():+.4f}")
  if by:
    t = r[hist].assign(d=dlt[hist]).groupby(by, observed=True).agg(n=("y", "size"), played=("y", "mean"), base=("p0", "mean"),
                                                                     new=("p1", "mean"), d=("d", "mean"))
    print(t.round(4).to_string())
  ok = hi < 0 and now <= 0
  print(f"  GATE: {'PASS' if ok else 'FAIL'}")
  return ok


def main():
  cfg = load_config()
  d = D.load_all(cfg)
  rep, hurt = T.report_rows(d), T.hurt_notes(d, D.Cache(ROOT / cfg["data"]["cache_dir"]))
  # (a) Tuesday model
  T.TIME_ROWS = False
  x = T.build_rows(d, rep, hurt).dropna(subset=["y"])
  out = []
  for s in SEASONS + [int(x.season.max())]:
    te, tr = x[x.season == s].copy(), x[x.season < s]
    T.TUE_DAYS = False
    te["p0"] = T.fit(tr).predict_proba(T.features(te))[:, 1]
    T.TUE_DAYS = True
    te["p1"] = T.fit(tr).predict_proba(T.features(te))[:, 1]
    out.append(te)
  T.TUE_DAYS = False
  ra = pd.concat(out, ignore_index=True)
  ra["gap"] = pd.cut(ra.gap_days, [0, 5, 8, 11, 30], labels=["short (<=5)", "normal (6-8)", "long (9-11)", "bye (12+)"])
  verdict("(a) Tuesday model + gap_days", ra, "gap")
  # (b) week model
  T.ONSET_DAYS = True
  w = T.week_rows(d, rep, hurt).dropna(subset=["y"])
  w = w[~((w.stage == 3) & (w.gs_now == "Out"))]
  out = []
  for s in SEASONS + [int(w.season.max())]:
    te = w[(w.season == s) & (w.stage > 0) & (w.on_now == 1)].copy()
    T.ONSET_DAYS = False
    te["p0"] = T.week_predict(T.week_model(w, s), te)
    T.ONSET_DAYS = True
    te["p1"] = T.week_predict(T.week_model(w, s), te)
    out.append(te)
  T.ONSET_DAYS = False
  rb = pd.concat(out, ignore_index=True)
  rb = rb[rb.pos.isin(["QB", "RB", "WR", "TE"])]
  rb["onset"] = pd.cut(rb.onset_days, [-1, 4, 8, 15, 29, 400], labels=["0-4", "5-8", "9-15", "16-29", "30+"])
  verdict("(b) week model + onset_days", rb, "onset")


if __name__ == "__main__":
  main()
