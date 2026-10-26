"""(DM) chance to play for every position, by position group (pre-registered 2026-10-26, docs/INSIGHTS.md).

Usage: python tools/dm_eval.py [--first=2021] [--last=2025]

The game-week half of (DM): the full-week practice model (InjuryModel._fit_practice: practice days, game status, role,
rest) on every final-report row of every position. History with the lineman fix (data.availability_history with the
players-table id map; cached as availhist_all_<season>, production's availhist_<season> untouched).
Arms, walk-forward (season s trains on 2018 .. s-1), game status Out excluded (0% by rule) as in production:
  A0  today's model as is: production's history (no linemen), the skill yes/no input
  A0f the same inputs on the fixed history (what the lineman rows alone do)
  A1  the skill input replaced by the position group (QB RB WR TE OL DL LB DB ST)
  A2  A1 plus group x Questionable / Doubtful
GATE (pre-registered): (1) fantasy positions (QB RB WR TE K): adopted arm's Brier - A0's, upper 95% < +0.001;
(2) each group with 300+ test rows: mean predicted within 3 points of the share who played, each predicted decile
within 5 points; (3) A1 or A2 beats A0 on the non-fantasy groups pooled (upper < 0). The simplest passing arm.
Intervals: bootstrap over season-weeks.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.injuries import InjuryModel, practice_features  # noqa: E402
from nfledge.returns import POS_GROUP  # noqa: E402

GROUPS = ["QB", "RB", "WR", "TE", "OL", "DL", "LB", "DB", "ST"]
FANTASY = {"QB", "RB", "FB", "WR", "TE", "K"}
GRP = dict(POS_GROUP, OT="OL", OG="OL", HB="RB", PK="ST")


def ci(diff: pd.Series, cl: pd.Series):
  gr = pd.DataFrame({"d": diff.to_numpy(), "c": cl.to_numpy()}).groupby("c").d.agg(["sum", "size"])
  s_, n_ = gr["sum"].to_numpy(), gr["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(gr), (4000, len(gr)))
  bt = s_[idx].sum(1) / n_[idx].sum(1)
  return diff.mean(), np.percentile(bt, 2.5), np.percentile(bt, 97.5)


def main():
  from sklearn.ensemble import HistGradientBoostingClassifier
  import nflreadpy as nfl
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  first, last = int(opt.get("first", 2021)), int(opt.get("last", 2025))
  cfg = load_config()
  d = D.load_all(cfg)
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  players = cache.get("players", "all", lambda: nfl.load_players(), stale=False)
  start = int(cfg["data"].get("practice_history_start", 2018))
  fixed = pd.concat([cache.get("availhist_all", s, lambda s=s: D.availability_history(nfl, s, players), stale=False)
                     for s in range(start, last + 1)], ignore_index=True)
  prod = d.avail_hist
  for x in (fixed, prod):
    x["grp"] = x.position.map(GRP).fillna("other")
  print("rows by group (production -> fixed history):")
  print(pd.concat([prod.groupby("grp").size().rename("prod"), fixed.groupby("grp").size().rename("fixed")], axis=1).fillna(0).astype(int).T.to_string())

  im = InjuryModel.__new__(InjuryModel)
  im.data, im.cfg = d, cfg
  gb = im._gb_params()
  X0 = lambda f: im._with_rest(im._with_role(practice_features(f), f), f)  # noqa: E731  production's inputs

  def X1(f, inter=False):
    x = X0(f).drop(columns=["skill", "skill_q"])
    g = f.position.map(GRP).fillna("other").to_numpy()
    for k in GROUPS:
      x[f"g_{k}"] = (g == k).astype(float)
      if inter:
        x[f"g_{k}_q"] = x[f"g_{k}"] * x["gs_QUESTIONABLE"]
        x[f"g_{k}_d"] = x[f"g_{k}"] * x["gs_DOUBTFUL"]
    return x

  arms = {"A0": (prod, X0), "A0f": (fixed, X0), "A1": (fixed, X1), "A2": (fixed, lambda f: X1(f, True))}
  out = []
  for s in range(first, last + 1):
    te = fixed[(fixed.season == s) & (fixed.game_status != "OUT")].copy()
    for name, (hist, X) in arms.items():
      tr = hist[(hist.season < s) & (hist.game_status != "OUT")]
      xt = X(tr)
      m = HistGradientBoostingClassifier(**gb, random_state=0).fit(xt, tr.played)
      te[name] = m.predict_proba(X(te)[list(xt.columns)])[:, 1]
    out.append(te)
    print(f"  {s}: {len(te)} test rows", flush=True)
  r = pd.concat(out, ignore_index=True)
  r["y"] = r.played.astype(float)
  r["cl"] = r.season.astype(str) + "-" + r.week.astype(str)
  for a in arms:
    r[f"b_{a}"] = (r[a] - r.y) ** 2
  fan = r[r.position.isin(FANTASY)]
  non = r[~r.position.isin(FANTASY)]

  print("\nBrier by arm (fantasy positions / the rest / all):")
  for a in arms:
    print(f"  {a:4s} {fan[f'b_{a}'].mean():.4f} / {non[f'b_{a}'].mean():.4f} / {r[f'b_{a}'].mean():.4f}")
  res = {}
  for a in ("A0f", "A1", "A2"):
    g1 = ci(fan[f"b_{a}"] - fan.b_A0, fan.cl)
    g3 = ci(non[f"b_{a}"] - non.b_A0, non.cl)
    cal_ok, lines = True, []
    for k, x in r.groupby("grp"):
      if len(x) < 300 or k == "other":
        continue
      bias = x[a].mean() - x.y.mean()
      dec = x.assign(q=pd.qcut(x[a], 10, labels=False, duplicates="drop")).groupby("q").agg(p=(a, "mean"), y=("y", "mean"))
      worst = float((dec.p - dec.y).abs().max())
      ok = abs(bias) <= 0.03 and worst <= 0.05
      cal_ok &= ok
      lines.append(f"    {k:3s} n {len(x):5d}  played {x.y.mean():.3f}  predicted {x[a].mean():.3f}  worst decile {worst:.3f}  {'ok' if ok else 'FAIL'}")
    res[a] = (g1[2] < 0.001, cal_ok, g3[2] < 0)
    print(f"\n{a}: (1) fantasy vs A0 {g1[0]:+.4f} [{g1[1]:+.4f}, {g1[2]:+.4f}] {'ok' if res[a][0] else 'FAIL'};"
          f" (3) rest vs A0 {g3[0]:+.4f} [{g3[1]:+.4f}, {g3[2]:+.4f}] {'ok' if res[a][2] else 'FAIL'}; (2) calibration by group:")
    print("\n".join(lines))
  print("\nby group, Brier (A0 / A0f / A1 / A2) and played share when Questionable:")
  for k, x in r.groupby("grp"):
    q = x[x.game_status == "QUESTIONABLE"]
    print(f"  {k:5s} n {len(x):5d}  " + " / ".join(f"{x[f'b_{a}'].mean():.4f}" for a in arms)
          + f"   Q n {len(q)} played {q.y.mean():.3f}" if len(q) else "")
  passing = [a for a in ("A1", "A2") if all(res[a])]
  print(f"\n(DM) GAME-WEEK GATE: {'PASS, adopt ' + passing[0] if passing else 'FAIL'}"
        f"  (A0f, the lineman rows alone: {'passes' if all(res['A0f']) else 'does not pass'})")


if __name__ == "__main__":
  main()
