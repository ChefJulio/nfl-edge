"""(BO) Lineup value in the Matchups win chance (pre-registered 2026-10-20, docs/INSIGHTS.md (BO)).

Usage: python tools/lineup_eval.py        (needs cache/vegas_prior_eval.parquet and cache/lineup_rows.parquet)
BASE = home + rank gap + Elo (as of the game's week); LINEUP = BASE + OFF + DEF (home minus away, report / cap).
Logistic fit walk-forward on earlier seasons, scored 2022-25, 2026 CONFIRM.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402

TEST, CONFIRM = [2022, 2023, 2024, 2025], 2026
BASE = ["home", "gap", "elo"]
GROUPS = ["OL", "WR", "TE", "RB", "DL", "LB", "CB", "S"]


def main():
  g = pd.read_parquet(ROOT / "cache" / "vegas_prior_eval.parquet")
  L = pd.read_parquet(ROOT / "cache" / "lineup_rows.parquet")
  feats = [c for c in L.columns if c.split("_")[0] in ("report", "inactives", "actual")]
  h = L.rename(columns={c: f"h_{c}" for c in feats})[["game_id", "team"] + [f"h_{c}" for c in feats]]
  a = L.rename(columns={c: f"a_{c}" for c in feats})[["game_id", "team"] + [f"a_{c}" for c in feats]]
  df = g.merge(h, left_on=["game_id", "home_team"], right_on=["game_id", "team"], how="left").drop(columns="team")
  df = df.merge(a, left_on=["game_id", "away_team"], right_on=["game_id", "team"], how="left").drop(columns="team")
  miss = df[f"h_{feats[0]}"].isna() | df[f"a_{feats[0]}"].isna()
  print(f"{len(df)} games, {int(miss.sum())} without lineup rows (dropped)")
  df = df[~miss].copy()
  for c in feats:
    df[c] = df[f"h_{c}"] - df[f"a_{c}"]
  ml = lambda m: np.where(m > 0, 100 / (m + 100), -m / (-m + 100))  # noqa: E731
  ph, pa = ml(df.ml_h), ml(df.ml_a)
  df["vegas"] = ph / (ph + pa)
  arms = {"base": BASE, "lineup": BASE + ["report_cap_OFF", "report_cap_DEF"], "snap": BASE + ["report_snap_OFF", "report_snap_DEF"],
          "inactives": BASE + ["inactives_cap_OFF", "inactives_cap_DEF"], "actual": BASE + ["actual_cap_OFF", "actual_cap_DEF"],
          "groups": BASE + [f"report_cap_{x}" for x in GROUPS]}
  for s in TEST + [CONFIRM]:
    tr, te = df.season < s, df.season == s
    for arm, cols in arms.items():
      m = LogisticRegression(C=1e6, max_iter=3000).fit(df.loc[tr, cols], df.loc[tr, "y"])
      df.loc[te, arm] = m.predict_proba(df.loc[te, cols])[:, 1]
  for arm in list(arms) + ["vegas"]:
    df[f"b_{arm}"] = (df[arm] - df.y) ** 2
  T = df[df.season.isin(TEST)]
  rng = np.random.default_rng(0)

  def ci(x):
    d = (T[f"b_{x}"] - T.b_base).to_numpy()
    bt = d[rng.integers(0, len(d), (2000, len(d)))].mean(1)
    return d.mean(), *np.percentile(bt, [2.5, 97.5])

  print(f"(BO) {len(T)} games 2022-25; Brier: " + "  ".join(f"{a} {T[f'b_{a}'].mean():.4f}" for a in list(arms) + ["vegas"]))
  for arm in arms:
    if arm != "base":
      m, lo, hi = ci(arm)
      print(f"  {arm:10s} - base {m:+.5f} [{lo:+.5f}, {hi:+.5f}]{'   <- gate' if arm == 'lineup' else ''}")
  per = T.groupby("season")[["b_base", "b_lineup", "b_inactives", "b_actual"]].mean()
  print(per.round(4).to_string())
  T = T.assign(band=pd.cut(T.week, [0, 4, 12, 18], labels=["wk 1-4", "wk 5-12", "wk 13-18"]))
  print(T.groupby("band", observed=True)[["b_base", "b_lineup", "b_inactives", "b_actual", "b_vegas"]].mean().round(4).to_string())
  F = df[df.season.between(2021, 2025)]
  for arm in ("lineup", "inactives", "actual", "groups"):
    m = LogisticRegression(C=1e6, max_iter=3000).fit(F[arms[arm]], F.y)
    print(f"  weights {arm} (fit 2021-25, reading only):", dict(zip(arms[arm][3:], m.coef_[0][3:].round(3))), " rank gap", round(m.coef_[0][1], 4))
  C = df[df.season == CONFIRM]
  cd = (C.b_lineup - C.b_base).mean()
  m, lo, hi = ci("lineup")
  better = int((per.b_lineup < per.b_base).sum())
  print(f"CONFIRM {CONFIRM}: {len(C)} games, lineup - base {cd:+.5f}")
  print(f"seasons better {better}/4; GATE:", "PASS" if m <= -0.002 and hi < 0 and better >= 3 and cd < 0 else "FAIL")


if __name__ == "__main__":
  main()
