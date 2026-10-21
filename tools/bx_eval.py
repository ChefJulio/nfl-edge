"""(BX) Questionable starting QB; defensive absences by position group (pre-registered 2026-10-20, docs/INSIGHTS.md).

Usage: python tools/bx_eval.py     (needs cache/vegas_prior_eval.parquet, cache/lineup_rows.parquet)
BASE = home + rank gap + Elo + lineup (offense, shipped). QBQ = BASE + (home starter Questionable - away's).
DEFGRP = BASE + home-minus-away defensive lineup deltas for DL / LB / CB / S (report availability, snap share).
Production's form (no intercept), walk-forward, scored 2022-25, 2026 so far.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402

TEST, CONFIRM = [2022, 2023, 2024, 2025], 2026
DEF = ["DL", "LB", "CB", "S"]


def qb_questionable() -> dict:
  """(season, week, team) -> 1 if the team's starter (most offensive snaps among QBs in its previous game) is
  Questionable on that week's report; also whether he then played."""
  pl = pd.read_parquet(ROOT / "cache" / "players_all.parquet").dropna(subset=["pfr_id", "gsis_id"])
  pid = dict(zip(pl.pfr_id, pl.gsis_id))
  sn = pd.concat([pd.read_parquet(ROOT / "cache" / f"snaps_{y}.parquet") for y in range(2020, 2027)])
  sn = sn[(sn.game_type == "REG")]
  sn["gsis_id"] = sn.pfr_player_id.map(pid)
  qb = sn[sn.position == "QB"].sort_values("offense_snaps").drop_duplicates(["season", "week", "team"], keep="last")
  games = sn[["season", "week", "team"]].drop_duplicates().sort_values(["team", "season", "week"])
  starter = qb.set_index(["season", "week", "team"]).gsis_id
  inj = pd.concat([pd.read_parquet(ROOT / "cache" / f"injuries_{y}.parquet") for y in range(2021, 2027)])
  q = set(zip(inj.season, inj.week, inj.team, inj.gsis_id, inj.report_status))
  played = set(zip(sn.season, sn.week, sn.gsis_id))
  out, rows = {}, []
  for team, g in games.groupby("team"):
    g = g.reset_index(drop=True)
    for i in range(1, len(g)):
      prev, cur = g.iloc[i - 1], g.iloc[i]
      s = starter.get((prev.season, prev.week, team))
      if s is None:
        continue
      flag = int((cur.season, cur.week, team, s, "Questionable") in q)
      out[(int(cur.season), int(cur.week), team)] = flag
      if flag:
        rows.append((cur.season, (cur.season, cur.week, s) in played))
  r = pd.DataFrame(rows, columns=["season", "played"])
  print(f"starting QB Questionable: {len(r)} team-games 2021-26, played {r.played.mean():.2f}")
  return out


def main():
  g = pd.read_parquet(ROOT / "cache" / "vegas_prior_eval.parquet")
  L = pd.read_parquet(ROOT / "cache" / "lineup_rows.parquet").set_index(["game_id", "team"])
  for c, k in [("lineup", "report_rapm_OFF")] + [(f"d_{x}", f"report_snap_{x}") for x in DEF]:
    g[c] = [L[k].get((i, h), np.nan) - L[k].get((i, a), np.nan) for i, h, a in zip(g.game_id, g.home_team, g.away_team)]
  g = g.dropna(subset=["lineup"]).copy()
  qq = qb_questionable()
  g["qbq_f"] = [qq.get((s, w, h), 0) - qq.get((s, w, a), 0) for s, w, h, a in zip(g.season, g.week, g.home_team, g.away_team)]
  ml = lambda m: np.where(m > 0, 100 / (m + 100), -m / (-m + 100))  # noqa: E731
  ph, pa = ml(g.ml_h), ml(g.ml_a)
  g["vegas"] = ph / (ph + pa)
  base = ["home", "gap", "elo", "lineup"]
  arms = {"base": base, "qbq": base + ["qbq_f"], "defgrp": base + [f"d_{x}" for x in DEF]}
  for s in TEST + [CONFIRM]:
    tr, te = g.season < s, g.season == s
    for arm, cols in arms.items():
      m = LogisticRegression(C=1e6, fit_intercept=False, max_iter=3000).fit(g.loc[tr, cols], g.loc[tr, "y"])
      g.loc[te, arm] = m.predict_proba(g.loc[te, cols])[:, 1]
  for arm in list(arms) + ["vegas"]:
    g[f"b_{arm}"] = (g[arm] - g.y) ** 2
  T = g[g.season.isin(TEST)]
  print(f"(BX) {len(T)} games 2022-25; Brier base {T.b_base.mean():.4f}, vegas {T.b_vegas.mean():.4f}; "
        f"games with a Questionable starting QB: {int((T.qbq_f != 0).sum())}")
  F = g[g.season <= 2025]
  rng = np.random.default_rng(0)
  for arm in ("qbq", "defgrp"):
    d = (T[f"b_{arm}"] - T.b_base).to_numpy()
    bt = d[rng.integers(0, len(d), (2000, len(d)))].mean(1)
    lo, hi = np.percentile(bt, [2.5, 97.5])
    per = T.groupby("season")[["b_base", f"b_{arm}"]].mean()
    better = int((per[f"b_{arm}"] < per.b_base).sum())
    C = g[g.season == CONFIRM]
    cd = (C[f"b_{arm}"] - C.b_base).mean()
    m = LogisticRegression(C=1e6, fit_intercept=False, max_iter=3000).fit(F[arms[arm]], F.y)
    ok = d.mean() <= -0.001 and hi < 0 and better >= 3 and cd < 0
    print(f"  {arm}: {d.mean():+.5f} [{lo:+.5f}, {hi:+.5f}], seasons better {better}/4, 2026 {cd:+.5f} -> {'PASS' if ok else 'FAIL'}")
    print(f"     weights (fit 2021-25, reading only): {dict(zip(arms[arm][4:], m.coef_[0][4:].round(3)))}")
  sub = T[T.qbq_f != 0]
  if len(sub):
    print(f"  games with a Questionable starter: base {sub.b_base.mean():.4f} qbq {sub.b_qbq.mean():.4f} vegas {sub.b_vegas.mean():.4f}")


if __name__ == "__main__":
  main()
