"""(DH) the field goal's make chance from the spot as a win model input (pre-registered 2026-10-25, docs/INSIGHTS.md).
Walk-forward 2022-25 (each season fit on 2006 through the season before), the current (CG) model vs + fgp on the same
rows. fgp = P(make) from a logistic curve in distance (yards to the end zone + 17) fit on the three seasons before
the row's season (nfledge/winprob.py fg_curve / add_fgp).

GATE (all): (1) pooled Brier not worse (95% interval over games, upper < +0.0005); (2) late-and-close (4th quarter,
within 8) Brier lower; (3) calibration deciles within 3 points; (4) last 3:00 of the 4th, team with the ball tied or
behind 1-3: mean calibration gap over (CH)'s cells (time x field zone x margin, cells of 30+) lower, and the 55-64 yd
band's gap smaller.

  python tools/dh_eval.py        (2003-05 field goal attempts, for the 2006-08 curves, are fetched once into
                                  scratch/dh/fg_<season>.parquet; the cache is only read)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import winprob as W  # noqa: E402

FIRST, TESTS = 2006, [2022, 2023, 2024, 2025]
EXTRA_FG = [2003, 2004, 2005]  # not in cache/pbp_calc_*: only their field goal attempts are needed
SCR = ROOT / "scratch" / "dh"
FG_COLS = ["season", "season_type", "field_goal_attempt", "kick_distance", "field_goal_result"]


def load_pbp() -> pd.DataFrame:
  return pd.concat([pd.read_parquet(ROOT / "cache" / f"pbp_calc_{s}.parquet", columns=W.PBP_COLS)
                    for s in range(FIRST, max(TESTS) + 1)], ignore_index=True)


def load_extra_fg() -> pd.DataFrame:
  SCR.mkdir(parents=True, exist_ok=True)
  fr = []
  for s in EXTRA_FG:
    f = SCR / f"fg_{s}.parquet"
    if not f.exists():
      import nflreadpy as nfl
      d = nfl.load_pbp([s]).select(FG_COLS).to_pandas()
      d[d.field_goal_attempt == 1].to_parquet(f)
    fr.append(pd.read_parquet(f))
  return pd.concat(fr, ignore_index=True)


def brier(p, y):
  return float(np.mean((p - y) ** 2))


def boot_diff(t: pd.DataFrame, a: str, b: str, rng, reps: int = 2000):
  """Mean of (b's squared error - a's), with a 95% bootstrap interval over games."""
  d = ((t[b] - t.y) ** 2 - (t[a] - t.y) ** 2).to_numpy()
  ug, inv = np.unique(t.game_id.to_numpy(), return_inverse=True)
  s, c = np.bincount(inv, d), np.bincount(inv)
  bs = []
  for _ in range(reps):
    w = np.bincount(rng.integers(0, len(ug), len(ug)), minlength=len(ug))
    bs.append((w * s).sum() / (w * c).sum())
  return float(d.mean()), *np.percentile(bs, [2.5, 97.5])


def cal_table(t: pd.DataFrame, col: str) -> pd.DataFrame:
  dec = np.minimum((t[col] * 10).astype(int), 9)
  c = t.groupby(dec).agg(pred=(col, "mean"), act=("y", "mean"), n=("y", "size"))
  c["gap"] = c.act - c.pred
  return c


def late_cells(t: pd.DataFrame) -> pd.DataFrame:
  t = t.copy()
  t["tb"] = pd.cut(t.game_sec, [0, 30, 60, 120, 180], labels=["0:30", "1:00", "2:00", "3:00"], include_lowest=True).astype(str)
  t["fz"] = np.select([t.yardline_100 <= 35, t.yardline_100 <= 60], ["inside opp 35", "to own 40"], "deeper")
  t["mg"] = np.where(t.score_diff == 0, "tied", "behind 1-3")
  return t


def main():
  pbp = load_pbp()
  fg = pd.concat([W.fg_attempts(load_extra_fg()), W.fg_attempts(pbp)], ignore_index=True)
  r = W.rows(pbp)
  r, curves = W.add_fgp(r, fg)
  print(f"[dh] {len(r):,} regulation rows {FIRST}-{max(TESTS)}; {len(fg):,} field goal attempts {fg.season.min()}-{fg.season.max()}")
  print("[dh] make curves (fit on the 3 seasons before): P(make) at 40 / 50 / 55 / 60 yd")
  for s in [2006, 2010, 2014, 2018, 2022, 2023, 2024, 2025]:
    c = curves[s]
    pm = W.fg_make(c, np.array([40, 50, 55, 60]) - W.FG_SNAP)
    print(f"  {s} (fit {c['seasons'][0]}-{c['seasons'][1]}, n {c['n']:,}): a {c['a']:+.4f} b {c['b']:+.5f}  "
          + " / ".join(f"{x:.3f}" for x in pm))
  live = W.fg_curve(fg, 2026)
  print(f"  2026 live curve (fit {live['seasons'][0]}-{live['seasons'][1]}): a {live['a']:+.4f} b {live['b']:+.5f}")

  preds = []
  for s in TESTS:
    tr, te = r[r.season < s], r[r.season == s].copy()
    te["p0"] = W.fit(tr).predict_proba(W.features(te))[:, 1]
    te["p1"] = W.fit(tr, fgp=True).predict_proba(W.features(te, fgp=True))[:, 1]
    preds.append(te)
    print(f"  {s}: n {len(te):,}  Brier current {brier(te.p0, te.y):.5f}  + fgp {brier(te.p1, te.y):.5f}", flush=True)
  t = pd.concat(preds)
  rng = np.random.default_rng(0)

  # (1) pooled Brier
  m1, lo1, hi1 = boot_diff(t, "p0", "p1", rng)
  g1 = hi1 < 0.0005
  print(f"\n[dh] (1) pooled ({len(t):,} rows, {t.game_id.nunique():,} games): Brier {brier(t.p0, t.y):.5f} -> "
        f"{brier(t.p1, t.y):.5f}, {m1:+.5f} [{lo1:+.5f}, {hi1:+.5f}] -> {g1}")
  # (2) late-and-close
  lc = t[(t.qtr == 4) & (t.score_diff.abs() <= 8)]
  b0, b1 = brier(lc.p0, lc.y), brier(lc.p1, lc.y)
  m2, lo2, hi2 = boot_diff(lc, "p0", "p1", rng)
  g2 = b1 < b0
  print(f"[dh] (2) late-and-close ({len(lc):,}): Brier {b0:.5f} -> {b1:.5f} ({m2:+.5f} [{lo2:+.5f}, {hi2:+.5f}]) -> {g2}")
  # (3) calibration deciles
  c0, c1 = cal_table(t, "p0"), cal_table(t, "p1")
  g3 = bool((c1.gap.abs() <= 0.03).all())
  print(f"[dh] (3) calibration deciles: worst |gap| current {c0.gap.abs().max():.4f}, + fgp {c1.gap.abs().max():.4f} -> {g3}")
  print(pd.concat({"current": c0, "+fgp": c1}, axis=1).round(3).to_string())
  # (4) late tied / behind 1-3 with the ball
  lt = late_cells(t[(t.qtr == 4) & (t.game_sec <= 180) & t.score_diff.between(-3, 0) & t.down.notna()])
  cg = lt.groupby(["mg", "tb", "fz"]).agg(n=("y", "size"), won=("y", "mean"), p0=("p0", "mean"), p1=("p1", "mean"))
  cg = cg[cg.n >= 30]
  cg["gap0"], cg["gap1"] = cg.won - cg.p0, cg.won - cg.p1
  gap0, gap1 = cg.gap0.abs().mean(), cg.gap1.abs().mean()
  band = lt[(lt.yardline_100 + W.FG_SNAP >= 55) & (lt.yardline_100 + W.FG_SNAP < 65)]
  bg0, bg1 = band.y.mean() - band.p0.mean(), band.y.mean() - band.p1.mean()
  g4 = gap1 < gap0 and abs(bg1) < abs(bg0)
  print(f"\n[dh] (4) last 3:00, ball, tied or behind 1-3 ({len(lt):,} snaps, {lt.game_id.nunique():,} games): mean |gap| over "
        f"{len(cg)} cells of 30+ {gap0:.4f} -> {gap1:.4f}; 55-64 yd band (n {len(band):,}) actual minus model "
        f"{bg0:+.4f} -> {bg1:+.4f} -> {g4}")
  for mg, g in cg.groupby(level="mg"):
    print(f"  {mg}: {len(g)} cells, mean |gap| {g.gap0.abs().mean():.4f} -> {g.gap1.abs().mean():.4f}")
  print(cg.round(3).to_string())
  lt["fgd"] = pd.cut(lt.yardline_100 + W.FG_SNAP, [0, 35, 45, 55, 65, 200], right=False,
                     labels=["<35", "35-44", "45-54", "55-64", "65+"])
  fb = lt.groupby("fgd", observed=True).agg(n=("y", "size"), won=("y", "mean"), p0=("p0", "mean"), p1=("p1", "mean"))
  fb["gap0"], fb["gap1"] = fb.won - fb.p0, fb.won - fb.p1
  print("  by field goal distance from the spot:")
  print(fb.round(3).to_string())
  ok = g1 and g2 and g3 and g4
  print(f"\n[dh] GATE: (1) {g1}  (2) {g2}  (3) {g3}  (4) {g4}  -> {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
  main()
