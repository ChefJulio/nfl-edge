"""Tuesday model test (pre-registered 2026-10-16, docs/INSIGHTS.md (G) / (G2)): P(plays this week) before the first
injury report. The model and its rows live in nfledge/tuesday.py (what the site runs); this walks it forward.

Usage: python tools/tuesday_eval.py [--first=2021] [--last=2025]

(G) players on last week's final report vs today's carry-forward (one number per last week's status); (G2) players
hurt in the last game while not on its report vs the healthy rate the site showed them. Walk-forward: the model for
season s trains on seasons before s. Gate: Brier lower with the 95% CI over season-weeks excluding 0, lower in >= 4
of 5 seasons, every predicted decile within 4 points of what happened.
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


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  first, last = int(opt.get("first", 2021)), int(opt.get("last", 2025))
  cfg = load_config()
  d = D.load_all(cfg)
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  x = T.build_rows(d, T.report_rows(d), T.hurt_notes(d, cache)).dropna(subset=["y"])
  print(f"rows {len(x)} ({x.season.min()}-{x.season.max()}); played next game {x.y.mean():.3f}", flush=True)
  # what the site shows a player who isn't on the report: the healthy rate (played next game | played this one)
  sn0 = d.snaps.dropna(subset=["gsis_id"])
  on0 = sn0[sn0[["offense_snaps", "defense_snaps", "st_snaps"]].fillna(0).sum(axis=1) > 0]
  on_set = set(zip(on0.gsis_id, on0.season.astype(int), on0.week.astype(int)))
  nx = on0.assign(s=on0.season.astype(int), w=on0.week.astype(int) + 1)
  rate = nx.assign(y=[(g, s_, w) in on_set or (g, s_, w + 1) in on_set for g, s_, w in zip(nx.gsis_id, nx.s, nx.w)]).groupby("s").y.mean()
  healthy = {s: float(rate[rate.index < s].mean()) for s in range(first, last + 1)}
  out = []
  for s in range(first, last + 1):
    tr, te = x[x.season < s], x[x.season == s].copy()
    if not len(te):
      continue
    base = tr[tr["pop"] == "A"].groupby("status").y.mean()  # today's carry-forward: one number per last week's status
    te["p_base"] = te.status.map(base).fillna(tr.y.mean()).to_numpy()
    te.loc[te["pop"] == "B", "p_base"] = healthy.get(s, 0.95)
    te["p_new"] = T.fit(tr).predict_proba(T.features(te))[:, 1]
    out.append(te)
  allr = pd.concat(out)
  allr["b_base"], allr["b_new"] = (allr.p_base - allr.y) ** 2, (allr.p_new - allr.y) ** 2
  for lab, r in (("(G) on last week's report", allr[allr["pop"] == "A"]), ("(G2) hurt last game, not on its report", allr[allr["pop"] == "B"])):
    m, lo, hi = ci(r.b_new - r.b_base, r.season.astype(str) + "-" + r.week.astype(str))
    wins = sum(g.b_new.mean() < g.b_base.mean() for _, g in r.groupby("season"))
    dec = r.assign(dec=pd.qcut(r.p_new, 10, labels=False, duplicates="drop")).groupby("dec").agg(pred=("p_new", "mean"), actual=("y", "mean"))
    worst = float((dec.pred - dec.actual).abs().max())
    ok = hi < 0 and wins >= 4 and worst <= 0.04
    print(f"\n{lab} (n {len(r)}): Brier {r.b_base.mean():.4f} -> {r.b_new.mean():.4f}  diff {m:+.4f} [{lo:+.4f}, {hi:+.4f}]; "
          f"better {wins}/{r.season.nunique()} seasons; worst decile {100 * worst:.1f} pts; predicted {100 * r.p_new.mean():.1f}% vs "
          f"played {100 * r.y.mean():.1f}%  -> {'PASS' if ok else 'FAIL'}")
    for s, g in r.groupby("season"):
      print(f"  {s}: {g.b_base.mean():.4f} -> {g.b_new.mean():.4f}")
  a = allr[allr["pop"] == "A"]
  print("\nsubgroups, on last week's report (Brier; predicted old / new vs actual):")
  for lab, mask in (("missed last game", a.played_last == 0), ("Out last week", a.status == "Out"),
                    ("Questionable last week", a.status == "Questionable"), ("in-game injury note", a.hurt_in_game == 1),
                    ("left early (20+ pts under usual)", a.left_early >= 0.2)):
    g = a[mask]
    print(f"  {lab:34s} n {len(g):5d}  {g.b_base.mean():.4f} -> {g.b_new.mean():.4f}   "
          f"{100 * g.p_base.mean():5.1f} / {100 * g.p_new.mean():5.1f} / {100 * g.y.mean():5.1f}%")


if __name__ == "__main__":
  main()
