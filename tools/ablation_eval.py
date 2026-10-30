"""(DS) ablation of the shipped Matchups win chance; (DT) where the gap to Vegas sits (pre-registered 2026-10-29,
docs/INSIGHTS.md).

Usage: python tools/ablation_eval.py   (needs cache/vegas_prior_eval.parquet, cache/lineup_rows.parquet,
                                        cache/playoff_odds_weekly.parquet, cache/snaps_<y>.parquet)
FULL = production's form: logistic, no intercept, of home + rank gap + Elo + lineup (offense), walk-forward, plus the
fixed final-week settled offset (config [report.win_model] final_week_settled, week 18). Each arm drops one piece.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402

from nfledge.config import load_config  # noqa: E402

TEST, CONFIRM = [2022, 2023, 2024, 2025], 2026
PIECES = ["home", "gap", "elo", "lineup"]


def qb_changed() -> dict:
  """(season, week, team) -> 1 when the team's starting QB (most offensive snaps among its QBs) differs from its
  previous game's."""
  pl = pd.read_parquet(ROOT / "cache" / "players_all.parquet").dropna(subset=["pfr_id", "gsis_id"])
  pid = dict(zip(pl.pfr_id, pl.gsis_id))
  sn = pd.concat([pd.read_parquet(ROOT / "cache" / f"snaps_{y}.parquet") for y in range(2020, 2027)])
  sn = sn[sn.game_type == "REG"]
  sn["gsis_id"] = sn.pfr_player_id.map(pid).fillna(sn.player)
  qb = sn[sn.position == "QB"].sort_values("offense_snaps").drop_duplicates(["season", "week", "team"], keep="last")
  qb = qb.sort_values(["team", "season", "week"])
  out = {}
  for team, g in qb.groupby("team"):
    prev = None
    for r in g.itertuples():
      out[(r.season, r.week, team)] = int(prev is not None and r.gsis_id != prev)
      prev = r.gsis_id
  return out


def main():
  wm = load_config()["report"]["win_model"]
  settled_w = float(wm.get("final_week_settled", 0))
  g = pd.read_parquet(ROOT / "cache" / "vegas_prior_eval.parquet")
  L = pd.read_parquet(ROOT / "cache" / "lineup_rows.parquet").set_index(["game_id", "team"]).report_rapm_OFF
  g["lineup"] = [L.get((i, h), np.nan) - L.get((i, a), np.nan) for i, h, a in zip(g.game_id, g.home_team, g.away_team)]
  g = g.dropna(subset=["lineup"]).copy()
  o = pd.read_parquet(ROOT / "cache" / "playoff_odds_weekly.parquet").set_index(["season", "week", "team"])
  settled = ((o.p_playoffs >= 0.99) & ((o.p_bye >= 0.99) | (o.p_bye <= 0.01))).astype(float)
  sh = np.array([settled.get((s, w, t), 0.0) for s, w, t in zip(g.season, g.week, g.home_team)])
  sa = np.array([settled.get((s, w, t), 0.0) for s, w, t in zip(g.season, g.week, g.away_team)])
  g["settled"] = np.where(g.week == 18, sh - sa, 0.0)
  ml = lambda m: np.where(m > 0, 100 / (m + 100), -m / (-m + 100))  # noqa: E731
  ph, pa = ml(g.ml_h), ml(g.ml_a)
  g["vegas"] = ph / (ph + pa)

  arms = {"FULL": (PIECES, True)}
  arms.update({f"- {p}": ([x for x in PIECES if x != p], True) for p in PIECES})
  arms["- settled offset"] = (PIECES, False)
  for s in TEST + [CONFIRM]:
    tr, te = g.season < s, g.season == s
    for arm, (cols, use_settled) in arms.items():
      m = LogisticRegression(C=1e6, fit_intercept=False, max_iter=3000).fit(g.loc[tr, cols], g.loc[tr, "y"])
      z = g.loc[te, cols].to_numpy(float) @ m.coef_[0] + (settled_w * g.loc[te, "settled"].to_numpy() if use_settled else 0)
      g.loc[te, arm] = 1 / (1 + np.exp(-z))
  for arm in list(arms) + ["vegas"]:
    g[f"b_{arm}"] = (g[arm] - g.y) ** 2
  T, C = g[g.season.isin(TEST)], g[g.season == CONFIRM]
  rng = np.random.default_rng(0)
  idx = rng.integers(0, len(T), (2000, len(T)))
  print(f"(DS) ablation, {len(T)} games 2022-25 ({len(C)} in 2026 so far). Brier FULL {T.b_FULL.mean():.4f}, "
        f"Vegas {T.b_vegas.mean():.4f}; settled offset {settled_w} on {int((T.settled != 0).sum())} week-18 games")
  print(f"{'arm':18s} {'Brier':>7s} {'vs FULL':>9s}  95% CI                better than FULL (seasons)  2026")
  for arm in arms:
    if arm == "FULL":
      continue
    d = (T[f"b_{arm}"] - T.b_FULL).to_numpy()
    bt = d[idx].mean(1)
    lo, hi = np.percentile(bt, [2.5, 97.5])
    per = T.groupby("season")[["b_FULL", f"b_{arm}"]].mean()
    better = int((per[f"b_{arm}"] < per.b_FULL).sum())
    cd = (C[f"b_{arm}"] - C.b_FULL).mean()
    if arm == "- settled offset":
      w18 = T[T.week == 18]
      d18 = (w18[f"b_{arm}"] - w18.b_FULL).to_numpy()
      note = f"   (week 18 only: {d18.mean():+.4f} on {len(d18)} games)"
    else:
      note = ""
    verdict = "CUT candidate" if d.mean() < 0 and hi < 0 and better >= 3 else ("carries nothing measurable" if abs(d.mean()) < 0.0005 and lo < 0 < hi else "")
    print(f"{arm:18s} {T[f'b_{arm}'].mean():7.4f} {d.mean():+9.5f}  [{lo:+.5f}, {hi:+.5f}]  {better}/4 {cd:+20.5f}  {verdict}{note}")

  # (DT) where the gap sits: Brier(FULL) - Brier(Vegas) by slice
  qc = qb_changed()
  T = T.copy()
  T["qbchg"] = [max(qc.get((s, w, h), 0), qc.get((s, w, a), 0)) for s, w, h, a in zip(T.season, T.week, T.home_team, T.away_team)]
  T["gap_b"] = T.b_FULL - T.b_vegas
  fav = np.maximum(T.vegas, 1 - T.vegas)
  dis = (T.FULL - T.vegas).abs()
  slices = {
    "week": pd.cut(T.week, [0, 4, 8, 12, 17, 18], labels=["1-4", "5-8", "9-12", "13-17", "18"]),
    "Vegas favorite": pd.cut(fav, [0, .6, .7, .8, 1.01], labels=["<60%", "60-70%", "70-80%", "80%+"]),
    "our vs Vegas": pd.cut(dis, [-.01, .05, .10, 1.01], labels=["<5 pts", "5-10", "10+"]),
    "QB change": T.qbchg.map({0: "no", 1: "yes (either team)"}),
  }
  total = T.gap_b.sum()
  print(f"\n(DT) the gap to Vegas, {len(T)} games 2022-25: Brier {T.b_FULL.mean():.4f} vs {T.b_vegas.mean():.4f} "
        f"(gap {T.gap_b.mean():+.4f})")
  for name, key in slices.items():
    print(f"  by {name}:")
    for lab, sub in T.groupby(key, observed=True):
      se = sub.gap_b.std() / np.sqrt(len(sub))
      print(f"    {str(lab):18s} {len(sub):5d} games ({len(sub) / len(T):5.1%})  gap {sub.gap_b.mean():+.4f} +- {1.96 * se:.4f}"
            f"   share of the total gap {sub.gap_b.sum() / total:6.1%}")


if __name__ == "__main__":
  main()
