"""(K) test (pre-registered 2026-10-16, docs/INSIGHTS.md): the one availability model as shipped (I2) vs the same
model + calendar, his own Questionable record, and clean depth (tuesday.add_k_feats); same rows, same calibration.

Usage: python tools/k_eval.py [--first=2021] [--last=2025] [--which=cal,own,depth]
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
from tools.week_avail_eval import ci  # noqa: E402


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  first, last = int(opt.get("first", 2021)), int(opt.get("last", 2025))
  cfg = load_config()
  d = D.load_all(cfg)
  rep, hurt = T.report_rows(d), T.hurt_notes(d, D.Cache(ROOT / cfg["data"]["cache_dir"]))
  w = T.week_rows(d, rep, hurt).dropna(subset=["y"])
  w = w[~((w.stage == 3) & (w.gs_now == "Out"))]
  which = tuple(opt.get("which", "cal,own,depth").split(","))
  wt = T.add_k_feats(d, w, w, rep, which)
  print(f"(K) inputs: {which}; rows {len(w)}", flush=True)
  out = []
  newest = int(w.season.max())
  for s in list(range(first, last + 1)) + ([newest] if newest > last else []):
    te = w[(w.season == s) & (w.stage > 0)].copy()
    if not len(te):
      continue
    te["p_ref"] = T.week_predict(T.week_model(w, s), te)
    te["p_new"] = T.week_predict(T.week_model(wt, s), wt.loc[te.index])
    out.append(te)
  r = pd.concat(out)
  r = r[(r.on_now == 1)]
  r["b_ref"], r["b_new"] = (r.p_ref - r.y) ** 2, (r.p_new - r.y) ** 2
  fresh, r = r[r.season > last], r[r.season <= last]
  ok_all = True
  for st, lab in ((1, "Wednesday"), (2, "Thursday"), (3, "final report")):
    g = r[r.stage == st]
    m, lo, hi = ci(g.b_new - g.b_ref, g.season.astype(str) + "-" + g.week.astype(str))
    dec = g.assign(dec=pd.qcut(g.p_new, 10, labels=False, duplicates="drop")).groupby("dec").agg(p=("p_new", "mean"), a=("y", "mean"))
    worst = float((dec.p - dec.a).abs().max())
    ok = (hi < 0 if st == 3 else hi < 0.002) and worst <= 0.04
    ok_all &= ok
    wins = sum(x.b_new.mean() < x.b_ref.mean() for _, x in g.groupby("season"))
    print(f"\n{lab} (n {len(g)}): Brier {g.b_ref.mean():.4f} -> {g.b_new.mean():.4f}  diff {m:+.4f} [{lo:+.4f}, {hi:+.4f}]  "
          f"better {wins}/{g.season.nunique()} seasons; worst decile {100 * worst:.1f} pts  -> {'ok' if ok else 'FAIL'}")
    if st == 3:
      for p, x in g[g.pos.isin(["QB", "RB", "WR", "TE"])].groupby("pos"):
        mp, lp, hp = ci(x.b_new - x.b_ref, x.season.astype(str) + "-" + x.week.astype(str))
        ok_all &= not lp > 0
        print(f"  {p}: {mp:+.4f} [{lp:+.4f}, {hp:+.4f}]{'  WORSE' if lp > 0 else ''}")
      q = g[g.gs_now == "Questionable"]
      print(f"  Questionable only (n {len(q)}): {q.b_ref.mean():.4f} -> {q.b_new.mean():.4f}")
  if len(fresh):
    print(f"\nuntouched check {int(fresh.season.max())}:")
    for st in (1, 2, 3):
      g = fresh[fresh.stage == st]
      dlt = g.b_new.mean() - g.b_ref.mean()
      good = bool(dlt < 0) if st == 3 else bool(dlt <= 0)
      ok_all &= good
      print(f"  stage {st} (n {len(g)}): {g.b_ref.mean():.4f} -> {g.b_new.mean():.4f}  ({dlt:+.4f})  {'ok' if good else 'FAIL'}")
  print(f"\nGATE: {'PASS' if ok_all else 'FAIL'}")


if __name__ == "__main__":
  main()
