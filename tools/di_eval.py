"""(DI) the win model's home / possession skew (pre-registered 2026-10-25, docs/INSIGHTS.md). Walk-forward 2022-25 (each
season fit on 2006 through the season before), on the same rows:
  cur  the live (DH) model: FEATURES + fgp
  a    the same without `home` (exp_margin already carries home field)
  b    possession-symmetric: every row also from the defense's side (score, timeouts, line, home, second-half receiver
       flipped; y = 1 - y; ball = 0; yards to the end zone, yards to go and fgp negated so the monotone directions hold
       on both sides); the chance = (f(ball side) + 1 - f(defense side)) / 2

GATE per candidate (all): (1) pooled Brier not worse (95% interval over games, upper < +0.0005); (2) calibration
deciles within 3 points; (3) home split (ball team home / away x |line| <= 3 / > 3): worst |actual - model| lower
than current's, every group within 2 points; (4) the field goal check: tools/di_grid.mjs on the model files this
writes (scratch/di/<variant>.json, each fit through 2024, on scratch/calc_val/through_2024.json's inputs).

  python tools/di_eval.py && node tools/di_grid.mjs
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import winprob as W  # noqa: E402
from dh_eval import boot_diff, brier, cal_table, load_extra_fg, load_pbp  # noqa: E402

TESTS = [2022, 2023, 2024, 2025]
SCR = ROOT / "scratch" / "di"
FEATS_A = [f for f in W.FEATURES_FGP if f != "home"]
FEATS_B = W.FEATURES_FGP + ["ball"]


def hgb(feats, mono):
  from sklearn.ensemble import HistGradientBoostingClassifier
  return HistGradientBoostingClassifier(monotonic_cst=[mono.get(f, 0) for f in feats], **W.PARAMS)


def defense_side(r: pd.DataFrame) -> pd.DataFrame:
  """The same moments from the defense's side (y: the defense won)."""
  d = r.copy()
  d["score_diff"] = -r.score_diff
  d["own_to"], d["opp_to"] = r.opp_to, r.own_to
  d["exp_margin"] = -r.exp_margin
  d["home"] = 1 - r.home
  d["receive_2h"] = 1 - r.receive_2h
  d["y"] = 1 - r.y
  return d


def side_x(r: pd.DataFrame, ball: int) -> pd.DataFrame:
  """(b)'s inputs: rows already from that side (defense_side for ball = 0); the ball team's spot entered negated."""
  x = W.features(r, fgp=True)
  if not ball:
    x["yardline_100"], x["ydstogo"], x["fgp"] = -x.yardline_100, -x.ydstogo, -x.fgp
  x["ball"] = float(ball)
  return x[FEATS_B]


def fit_b(tr: pd.DataFrame):
  x = pd.concat([side_x(tr, 1), side_x(defense_side(tr), 0)], ignore_index=True)
  y = pd.concat([tr.y, 1 - tr.y], ignore_index=True).astype(int)
  return hgb(FEATS_B, W.MONOTONIC_FGP).fit(x, y)


def pred_b(m, te: pd.DataFrame) -> np.ndarray:
  return (m.predict_proba(side_x(te, 1))[:, 1] + 1 - m.predict_proba(side_x(defense_side(te), 0))[:, 1]) / 2


def home_split(t: pd.DataFrame, col: str) -> pd.DataFrame:
  g = t.assign(side=np.where(t.home == 1, "home", "away"), line=np.where(t.exp_margin.abs() <= 3, "|line|<=3", "|line|>3"))
  c = g.groupby(["side", "line"]).agg(n=("y", "size"), games=("game_id", "nunique"), won=("y", "mean"), model=(col, "mean"))
  c["gap"] = c.won - c.model
  return c


def write_file(name: str, wp: dict) -> None:
  """A calculator model file for the engine check: the DH through-2024 file with this variant's trees."""
  base = json.loads((ROOT / "scratch" / "calc_val" / "through_2024.json").read_text(encoding="utf-8"))
  base["wp"] = wp
  base.pop("check", None)  # the self-check rows are the live model's
  SCR.mkdir(parents=True, exist_ok=True)
  (SCR / f"{name}.json").write_text(json.dumps(base, separators=(",", ":"), allow_nan=False), encoding="utf-8")


def main():
  pbp = load_pbp()
  fg = pd.concat([W.fg_attempts(load_extra_fg()), W.fg_attempts(pbp)], ignore_index=True)
  r, _ = W.add_fgp(W.rows(pbp), fg)
  print(f"[di] {len(r):,} regulation rows 2006-{max(TESTS)}", flush=True)
  preds = []
  for s in TESTS:
    tr, te = r[r.season < s], r[r.season == s].copy()
    mc = W.fit(tr, fgp=True)
    te["pc"] = mc.predict_proba(W.features(te, True))[:, 1]
    ma = hgb(FEATS_A, W.MONOTONIC_FGP).fit(W.features(tr, True)[FEATS_A], tr.y.astype(int))
    te["pa"] = ma.predict_proba(W.features(te, True)[FEATS_A])[:, 1]
    mb = fit_b(tr)
    te["pb"] = pred_b(mb, te)
    preds.append(te)
    print(f"  {s}: n {len(te):,}  Brier cur {brier(te.pc, te.y):.5f}  a {brier(te.pa, te.y):.5f}  b {brier(te.pb, te.y):.5f}",
          flush=True)
    if s == 2025:  # fit through 2024: the engine check's files
      write_file("cur", W.export(mc, W.FEATURES_FGP))
      write_file("a", W.export(ma, FEATS_A))
      wb = W.export(mb, FEATS_B)
      wb["sym"] = 1
      write_file("b", wb)
      smp = te.sample(300, random_state=0)
      for nm, wp, x, p in [("a", W.export(ma, FEATS_A), W.features(smp, True)[FEATS_A], ma.predict_proba(W.features(smp, True)[FEATS_A])[:, 1]),
                           ("b", wb, side_x(smp, 1), mb.predict_proba(side_x(smp, 1))[:, 1])]:
        diff = np.abs(W.predict_exported(wp, x) - p).max()
        print(f"  export check {nm}: max diff {diff:.2e}", flush=True)
  t = pd.concat(preds)
  rng = np.random.default_rng(0)
  hc = home_split(t, "pc")
  print(f"\n[di] {len(t):,} rows, {t.game_id.nunique():,} games")
  print("current, home split:\n" + hc.round(4).to_string())
  res = {}
  for v, col in [("a", "pa"), ("b", "pb")]:
    m1, lo1, hi1 = boot_diff(t, "pc", col, rng)
    g1 = hi1 < 0.0005
    c = cal_table(t, col)
    g2 = bool((c.gap.abs() <= 0.03).all())
    h = home_split(t, col)
    g3 = h.gap.abs().max() < hc.gap.abs().max() and bool((h.gap.abs() <= 0.02).all())
    res[v] = (g1, g2, g3)
    print(f"\n[di] ({v}) (1) Brier {brier(t.pc, t.y):.5f} -> {brier(t[col], t.y):.5f}, {m1:+.5f} [{lo1:+.5f}, {hi1:+.5f}] -> {g1}")
    print(f"[di] ({v}) (2) worst decile {c.gap.abs().max():.4f} (current {cal_table(t, 'pc').gap.abs().max():.4f}) -> {g2}")
    print(f"[di] ({v}) (3) home split worst |gap| {hc.gap.abs().max():.4f} -> {h.gap.abs().max():.4f} -> {g3}")
    print(h.round(4).to_string())
  print("\n[di] gates (1)-(3): " + "  ".join(f"({v}) {' '.join(str(g) for g in gs)}" for v, gs in res.items())
        + "   (4): node tools/di_grid.mjs")


if __name__ == "__main__":
  main()
