"""(DM3) the practice model calibrated per position group (pre-registered 2026-10-26, docs/INSIGHTS.md).

Usage: python tools/dm3_eval.py [--first=2021] [--last=2025]

(DM)'s A1 (the lineman-fixed history, the position group in place of the skill flag) failed only on calibration (DL /
LB too low, QB too high). A1c = A1 plus a per-group isotonic map fit on out-of-fold predictions of the training seasons
(each training season predicted by A1 fit on the other training seasons); groups under 300 training rows share one
pooled map. Season s uses only seasons before s. A0 = today's model (production history, skill flag).
GATE (as (DM)): (1) fantasy positions (QB RB WR TE K) Brier A1c - A0 upper 95% < +0.001; (2) each group with 300+ test
rows: mean predicted within 3 points of the share who played, each predicted decile within 5; (3) the rest: A1c beats
A0 (upper < 0); plus the untouched check, 2026 so far: fantasy Brier A1c no worse than A0.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402
from sklearn.isotonic import IsotonicRegression  # noqa: E402

from dm_eval import FANTASY, GROUPS, GRP, ci  # noqa: E402
from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.injuries import InjuryModel, practice_features  # noqa: E402

MIN_GROUP = 300


def main():
  import nflreadpy as nfl
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  first, last = int(opt.get("first", 2021)), int(opt.get("last", 2025))
  cfg = load_config()
  d = D.load_all(cfg)
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  players = cache.get("players", "all", lambda: nfl.load_players(), stale=False)
  start = int(cfg["data"].get("practice_history_start", 2018))
  cur = max(d.seasons)
  fixed = pd.concat([cache.get("availhist_all", s, lambda s=s: D.availability_history(nfl, s, players), stale=(s == cur))
                     for s in range(start, cur + 1)], ignore_index=True)
  fixed["grp"] = fixed.position.map(GRP).fillna("other")
  prod = d.avail_hist
  im = InjuryModel.__new__(InjuryModel)
  im.data, im.cfg = d, cfg
  gbp = im._gb_params()
  X0 = lambda f: im._with_rest(im._with_role(practice_features(f), f), f)  # noqa: E731

  def X1(f):
    x = X0(f).drop(columns=["skill", "skill_q"])
    g = f.position.map(GRP).fillna("other").to_numpy()
    for k in GROUPS:
      x[f"g_{k}"] = (g == k).astype(float)
    return x

  def fit(tr, X):
    xt = X(tr)
    return HistGradientBoostingClassifier(**gbp, random_state=0).fit(xt, tr.played), list(xt.columns)

  def calibrated(train_seasons):
    """A1 on every training season + per-group isotonic maps from out-of-fold predictions."""
    tr = fixed[fixed.season.isin(train_seasons) & (fixed.game_status != "OUT")]
    oof = []
    for t in train_seasons:
      a, b = tr[tr.season != t], tr[tr.season == t]
      if not len(a) or not len(b):
        continue
      mm, cols = fit(a, X1)
      oof.append(pd.DataFrame({"p": mm.predict_proba(X1(b)[cols])[:, 1], "y": b.played.astype(float).to_numpy(), "grp": b.grp.to_numpy()}))
    o = pd.concat(oof, ignore_index=True)
    maps = {"__all": IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip").fit(o.p, o.y)}
    for k, x in o.groupby("grp"):
      if len(x) >= MIN_GROUP:
        maps[k] = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip").fit(x.p, x.y)
    model, cols = fit(tr, X1)
    return model, cols, maps

  out = []
  for s in list(range(first, last + 1)) + [cur]:
    te = fixed[(fixed.season == s) & (fixed.game_status != "OUT")].copy()
    if not len(te):
      continue
    m0, c0 = fit(prod[(prod.season < s) & (prod.game_status != "OUT")], X0)
    te["A0"] = m0.predict_proba(X0(te)[c0])[:, 1]
    model, cols, maps = calibrated(list(range(start, s)))
    raw = model.predict_proba(X1(te)[cols])[:, 1]
    te["A1"] = raw
    te["A1c"] = [maps.get(g, maps["__all"]).predict([p])[0] for g, p in zip(te.grp, raw)]
    out.append(te)
    print(f"  {s}: {len(te)} rows", flush=True)
  r = pd.concat(out, ignore_index=True)
  r["y"] = r.played.astype(float)
  r["cl"] = r.season.astype(str) + "-" + r.week.astype(str)
  for a in ("A0", "A1", "A1c"):
    r[f"b_{a}"] = (r[a] - r.y) ** 2
  fresh, r = r[r.season == cur], r[r.season <= last]
  fan, non = r[r.position.isin(FANTASY)], r[~r.position.isin(FANTASY)]
  g1, g3 = ci(fan.b_A1c - fan.b_A0, fan.cl), ci(non.b_A1c - non.b_A0, non.cl)
  print(f"\nBrier fantasy / rest: A0 {fan.b_A0.mean():.4f} / {non.b_A0.mean():.4f}  A1 {fan.b_A1.mean():.4f} / {non.b_A1.mean():.4f}"
        f"  A1c {fan.b_A1c.mean():.4f} / {non.b_A1c.mean():.4f}")
  print(f"(1) fantasy A1c - A0 {g1[0]:+.4f} [{g1[1]:+.4f}, {g1[2]:+.4f}]  (3) rest {g3[0]:+.4f} [{g3[1]:+.4f}, {g3[2]:+.4f}]")
  ok2, passing = True, []
  print("(2) calibration by group (A1c; A0 shown for the fantasy groups):")
  for k, x in r.groupby("grp"):
    if k == "other":
      continue
    dec = x.assign(q=pd.qcut(x.A1c, 10, labels=False, duplicates="drop")).groupby("q").agg(p=("A1c", "mean"), y=("y", "mean"))
    worst = float((dec.p - dec.y).abs().max())
    good = abs(x.A1c.mean() - x.y.mean()) <= 0.03 and worst <= 0.05
    if len(x) >= MIN_GROUP:
      ok2 &= good
      if good:
        passing.append(k)
    print(f"  {k:3s} n {len(x):5d}  played {x.y.mean():.3f}  A1c {x.A1c.mean():.3f} (worst decile {worst:.3f})  A0 {x.A0.mean():.3f}"
          f"  {'' if len(x) < MIN_GROUP else 'ok' if good else 'FAIL'}")
  fz = fresh[fresh.position.isin(FANTASY)]
  fresh_ok = bool(len(fz)) and fz.b_A1c.mean() <= fz.b_A0.mean()
  if len(fresh):
    print(f"\nuntouched {cur} weeks {int(fresh.week.min())}-{int(fresh.week.max())}: fantasy Brier A0 {fz.b_A0.mean():.4f} A1c {fz.b_A1c.mean():.4f}"
          f" ({'ok' if fresh_ok else 'FAIL'}); all groups A0 {fresh.b_A0.mean():.4f} A1c {fresh.b_A1c.mean():.4f}")
  ok = g1[2] < 0.001 and g3[2] < 0 and ok2 and fresh_ok
  print(f"\n(DM3) GATE: {'PASS' if ok else 'FAIL'}  (groups calibrated: {', '.join(passing)})")


if __name__ == "__main__":
  main()
