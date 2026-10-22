"""(CK) the week model's calibration step (pre-registered 2026-10-22, docs/INSIGHTS.md). Walk-forward like
tools/avail_track.py (players on this week's report, stages 1-3, QB / RB / WR / TE, final-report Out excluded):
T.WEEK_CALIB "prev" (shipped) vs "none" vs "oof", 2021-25, plus the untouched 2026 weeks so far.
GATE: pooled Brier lower than "prev" with the 95% season-week CI excluding 0 on 2021-25 and not worse on 2026;
"oof" over "none" only if it beats "none" with the CI excluding 0.

  python tools/week_calib_eval.py
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

VARIANTS = ("prev", "none", "oof")


def ci(diff: pd.Series, cl: pd.Series):
  gr = pd.DataFrame({"d": diff.to_numpy(), "c": cl.to_numpy()}).groupby("c").d.agg(["sum", "size"])
  s_, n_ = gr["sum"].to_numpy(), gr["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(gr), (4000, len(gr)))
  bt = s_[idx].sum(1) / n_[idx].sum(1)
  return diff.mean(), np.percentile(bt, 2.5), np.percentile(bt, 97.5)


def main():
  cfg = load_config()
  d = D.load_all(cfg)
  rep, hurt = T.report_rows(d), T.hurt_notes(d, D.Cache(ROOT / cfg["data"]["cache_dir"]))
  w = T.week_rows(d, rep, hurt).dropna(subset=["y"])
  w = w[~((w.stage == 3) & (w.gs_now == "Out"))]
  out = []
  for s in sorted(set(range(2021, 2026)) | {int(w.season.max())}):
    te = w[(w.season == s) & (w.stage > 0) & (w.on_now == 1)].copy()
    for v in VARIANTS:
      T.WEEK_CALIB = v
      te[f"p_{v}"] = T.week_predict(T.week_model(w, s), te)
    out.append(te)
    print(f"[week calib] {s}", flush=True)
  T.WEEK_CALIB = "prev"
  r = pd.concat(out, ignore_index=True)
  r = r[r.pos.isin(["QB", "RB", "WR", "TE"])]
  r["cl"] = r.season.astype(str) + "-" + r.week.astype(str)
  br = {v: (r[f"p_{v}"] - r.y) ** 2 for v in VARIANTS}
  hist, now = r.season <= 2025, r.season > 2025
  res = {}
  for v in ("none", "oof"):
    m, lo, hi = ci((br[v] - br["prev"])[hist], r.cl[hist])
    res[v] = (m, hi, (br[v] - br["prev"])[now].mean())
    print(f"\n{v} vs prev, 2021-25 (n {int(hist.sum())}): {m:+.4f} [{lo:+.4f}, {hi:+.4f}]; 2026 (n {int(now.sum())}): {res[v][2]:+.4f}")
    for st in (1, 2, 3):
      k = hist & (r.stage == st)
      print(f"  stage {st}: {(br[v] - br['prev'])[k].mean():+.4f}  (prev {br['prev'][k].mean():.4f})")
    for s in sorted(r.season.unique()):
      k = r.season == s
      print(f"  {s}: {(br[v] - br['prev'])[k].mean():+.4f}")
  m, lo, hi = ci((br["oof"] - br["none"])[hist], r.cl[hist])
  print(f"\noof vs none, 2021-25: {m:+.4f} [{lo:+.4f}, {hi:+.4f}]")
  f = r[(r.stage == 3) & hist]
  spots = {"Q, no practice all week": f[(f.gs_now == "Questionable") & (f.days_now == "DDD")], "Doubtful": f[f.gs_now == "Doubtful"],
           "Wed DNP, missed last game": r[hist & (r.stage == 1) & (r.days_now == "D") & (r.played_last == 0)],
           "Final report, all": f}
  print("\nspots: played / prev / none / oof")
  for k, g in spots.items():
    print(f"  {k:<28} n {len(g):>5}  {g.y.mean():.3f} / " + " / ".join(f"{g[f'p_{v}'].mean():.3f}" for v in VARIANTS))
  ok = {v: res[v][1] < 0 and res[v][2] <= 0 for v in ("none", "oof")}
  pick = "oof" if ok["oof"] and hi < 0 else "none" if ok["none"] else ("oof" if ok["oof"] else None)
  print(f"\nGATE: {'PASS -> ' + pick if pick else 'FAIL (keep prev)'}  (none {'pass' if ok['none'] else 'fail'}, oof {'pass' if ok['oof'] else 'fail'})")


if __name__ == "__main__":
  main()
