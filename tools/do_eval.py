"""(DO) stage 1: why the calculator says "go" more than nfl4th (pre-registered 2026-10-26, docs/INSIGHTS.md (DO)).

Usage: python tools/do_eval.py [--site=scratch/site]

Each part of a 4th-down decision against what happened, on the site's graded rows (data/calc/graded_<season>.json, 2022
on; each season graded with a model fit only on earlier seasons): P(convert) on tries, P(good) on field goals, and the
win chance of each branch (converted / failed / made / missed) and of the punt, as won minus forecast with 95% intervals
by games. Overall and on the disputed region: our best call go, by 0 to 3 points (where our recommendations and
nfl4th's split). No gate: it names the parts a stage 2 fix should target.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402


def ci(err: pd.Series, games: pd.Series, n: int = 3000):
  g = pd.DataFrame({"e": err.to_numpy(), "g": games.to_numpy()}).groupby("g").e.agg(["sum", "size"])
  s_, k_ = g["sum"].to_numpy(), g["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(g), (n, len(g)))
  bt = s_[idx].sum(1) / k_[idx].sum(1)
  return err.mean(), np.percentile(bt, 2.5), np.percentile(bt, 97.5)


def line(lab, y, f, games):
  if not len(y):
    return
  m, lo, hi = ci((y - f) * 100, games)
  flag = "  <-- 2+ pts" if abs(m) >= 2 and (lo > 0 or hi < 0) else ""
  print(f"    {lab:34s} n {len(y):5d}  actual {100 * y.mean():5.1f}  forecast {100 * f.mean():5.1f}  actual - forecast {m:+5.1f} [{lo:+5.1f}, {hi:+5.1f}]{flag}")


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = Path(opt.get("site", ROOT / "scratch" / "site"))
  rows = []
  for f in sorted((site / "data" / "calc").glob("graded_20*.json")):
    rows += json.loads(f.read_text(encoding="utf-8"))["rows"]
  d = pd.DataFrame(rows)
  d["won"] = (pd.to_numeric(d.res, errors="coerce") > 0).astype(float)
  d = d[pd.to_numeric(d.res, errors="coerce").notna()].copy()
  op = pd.DataFrame(list(d.op)).reindex(columns=["go", "fg", "punt"])
  d[["w_go", "w_fg", "w_punt"]] = op.to_numpy()
  d["edge"] = d.w_go - d[["w_fg", "w_punt"]].max(axis=1)
  d["zone"] = pd.cut(d.yl, [0, 40, 60, 100], labels=["opp 40 and in", "midfield", "own side"])
  d["disputed"] = (d.b == "go") & (d.edge.between(0, 0.03))
  print(f"{len(d):,} graded 4th downs, seasons {sorted({g[:4] for g in d.g})}; disputed region {int(d.disputed.sum()):,}")
  for scope, x in (("ALL", d), ("DISPUTED (our go edge 0-3 pts)", d[d.disputed])):
    print(f"\n== {scope}")
    t = x[x.c == "go"].dropna(subset=["pc", "cv"])
    print("  (a) conversion on tries")
    line("all tries", t.cv.astype(float), t.pc, t.g)
    for lab, m in (("1 yard", t.tg == 1), ("2-3 yards", t.tg.between(2, 3)), ("4-6 yards", t.tg.between(4, 6)), ("7+ yards", t.tg >= 7)):
      line(lab, t[m].cv.astype(float), t[m].pc, t[m].g)
    for z in ("opp 40 and in", "midfield", "own side"):
      zz = t[t.zone == z]; line(z, zz.cv.astype(float), zz.pc, zz.g)
    k = x[x.c == "fg"].dropna(subset=["pf", "cv"])
    print("  (b) field goal good")
    line("all attempts", k.cv.astype(float), k.pf, k.g)
    dist = k.yl + 17
    for lab, m in (("<40 yd", dist < 40), ("40-49", dist.between(40, 49)), ("50+", dist >= 50)):
      line(lab, k[m].cv.astype(float), k[m].pf, k[m].g)
    print("  (c) win chance by branch (the team deciding)")
    line("go, converted", t[t.cv == 1].won, t[t.cv == 1].gm, t[t.cv == 1].g)
    line("go, failed", t[t.cv == 0].won, t[t.cv == 0].gf, t[t.cv == 0].g)
    line("field goal made", k[k.cv == 1].won, k[k.cv == 1].fm, k[k.cv == 1].g)
    line("field goal missed", k[k.cv == 0].won, k[k.cv == 0].ff, k[k.cv == 0].g)
    pu = x[x.c == "punt"].dropna(subset=["w_punt"])
    line("punt", pu.won, pu.w_punt, pu.g)
    print("  the option chosen, overall")
    for c in ("go", "fg", "punt"):
      y = x[x.c == c].dropna(subset=[f"w_{c}"]); line(f"chose {c}", y.won, y[f"w_{c}"], y.g)


if __name__ == "__main__":
  main()
