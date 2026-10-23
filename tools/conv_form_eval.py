"""(CM) 4th-down conversion questions (docs/INSIGHTS.md): (a) why long tries read high, (b) how often teams go by distance,
(c) does the offense's form (this game, this season) predict conversion beyond the model? Uses the cached play-by-play.

  python tools/conv_form_eval.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import calc_inputs as C  # noqa: E402


def main():
  d = pd.concat([pd.read_parquet(ROOT / "cache" / f"pbp_calc_{s}.parquet") for s in range(2014, 2026)], ignore_index=True)
  d = d[d.season_type == "REG"].sort_values(["game_id", "play_id"]).reset_index(drop=True)
  # ---- (c) form: the offense's yards per play in this game before the snap, and this season before this game
  sc = d[d.play_type.isin(["run", "pass"]) & (d.qb_kneel != 1) & (d.qb_spike != 1) & d.posteam.notna()].copy()
  sc["yg"] = sc.yards_gained.fillna(0).clip(-20, 99)
  g = sc.groupby(["game_id", "posteam"])
  sc["g_yds"], sc["g_n"] = g.yg.cumsum() - sc.yg, g.cumcount()
  gm = sc.groupby(["season", "posteam", "week"]).agg(y=("yg", "sum"), n=("yg", "size")).reset_index().sort_values(["season", "posteam", "week"])
  gs = gm.groupby(["season", "posteam"])
  gm["s_yds"], gm["s_n"] = gs.y.cumsum() - gm.y, gs.n.cumsum() - gm.n
  sc = sc.merge(gm[["season", "posteam", "week", "s_yds", "s_n"]], on=["season", "posteam", "week"], how="left")
  lg = sc.yg.mean()
  sc["form_game"] = (sc.g_yds + 20 * lg) / (sc.g_n + 20) - lg      # shrunk by 20 plays
  sc["form_season"] = (sc.s_yds + 200 * lg) / (sc.s_n + 200) - lg  # shrunk by 200 plays
  key = sc.set_index(["game_id", "play_id"])[["form_game", "form_season"]]

  rows = []
  for s in range(2018, 2026):
    tr = d[d.season < s] if s <= 2023 else d[d.season < 2024]
    if s in (2018, 2024):  # one conversion model per period (2018-23 fit before 2018 is too thin: use through 2017 / 2023)
      m = C.conversion_gb(tr)
    x = C._gain_rows(d[d.season == s]).join(d[["game_id", "play_id"]], how="left")
    x = x.join(key, on=["game_id", "play_id"])
    v = x.assign(down=3)  # the model as the page asks it
    x["p"] = m.predict_proba(C.conv_features(v))[:, 1]
    x["p4"] = m.predict_proba(C.conv_features(x))[:, 1]
    xd = d.loc[x.index]
    x["late_behind"] = ((xd.qtr == 4) & (xd.game_seconds_remaining <= 300) & (xd.score_differential < 0)).to_numpy()
    rows.append(x)
  r = pd.concat(rows)
  f4 = r[(r.down == 4) & (r.season >= 2022)]
  t3 = r[(r.down == 3) & (r.season >= 2022)]
  print("(a) conversion by distance, 2022-25: 3rd downs actual | 4th-down tries actual, model at down 3, model at down 4")
  for lo, hi in [(1, 2), (3, 5), (6, 7), (8, 10), (11, 99)]:
    a, b = t3[t3.ydstogo.between(lo, hi)], f4[f4.ydstogo.between(lo, hi)]
    print(f"  {lo}-{hi}: 3rd {a.y.mean():.3f} (n {len(a)}) | 4th {b.y.mean():.3f} (n {len(b)})  model@3 {b.p.mean():.3f}  model@4 {b.p4.mean():.3f}")
  for lab, b in (("4th & 6+, desperation (Q4, last 5:00, behind)", f4[(f4.ydstogo >= 6) & f4.late_behind]),
                 ("4th & 6+, the rest", f4[(f4.ydstogo >= 6) & ~f4.late_behind])):
    print(f"  {lab}: n {len(b)}  actual {b.y.mean():.3f}  model@3 {b.p.mean():.3f}")
  # ---- (b) how often teams go, by distance
  q = d[(d.down == 4) & (d.season >= 2022) & (d.qtr <= 4) & d.play_type.isin(["run", "pass", "punt", "field_goal"])
        & ~((d.qtr == 4) & (d.game_seconds_remaining <= 300)) & ~((d.qtr == 2) & (d.half_seconds_remaining <= 120))]
  q = q.assign(go=q.play_type.isin(["run", "pass"]))
  print("\n(b) share of 4th downs where teams went for it, 2022-25 (not the last 5:00 / the 1st half's last 2:00):")
  for t in range(1, 13):
    b = q[q.ydstogo == t] if t < 12 else q[q.ydstogo >= 12]
    print(f"  4th & {t}{'+' if t == 12 else ''}: {b.go.mean():.1%} of {len(b)}   (own half {b[b.yardline_100 > 50].go.mean():.1%}, opponent's {b[b.yardline_100 <= 50].go.mean():.1%})")
  # ---- (c) the gate
  from sklearn.linear_model import LogisticRegression
  rr = r.dropna(subset=["form_game", "form_season"])
  lo_ = lambda p: np.log(np.clip(p, 1e-4, 1 - 1e-4) / (1 - np.clip(p, 1e-4, 1 - 1e-4)))  # noqa: E731
  rr = rr.assign(lp=lo_(rr.p4))
  trn, tst = rr[rr.season <= 2023], rr[rr.season >= 2024]
  base = LogisticRegression(C=1e6, max_iter=1000).fit(trn[["lp"]], trn.y)
  full = LogisticRegression(C=1e6, max_iter=1000).fit(trn[["lp", "form_game", "form_season"]], trn.y)
  pb, pf = base.predict_proba(tst[["lp"]])[:, 1], full.predict_proba(tst[["lp", "form_game", "form_season"]])[:, 1]
  print(f"\n(c) form terms (per yard per play above the league): game {full.coef_[0][1]:+.3f}, season {full.coef_[0][2]:+.3f}")
  diff = ((pf - tst.y) ** 2 - (pb - tst.y) ** 2).to_numpy()
  games = tst.game_id.to_numpy()
  ug = np.unique(games)
  idx = {gg: np.where(games == gg)[0] for gg in ug}
  rng = np.random.default_rng(0)
  boots = []
  for _ in range(1000):
    pick = rng.choice(ug, len(ug))
    ii = np.concatenate([idx[gg] for gg in pick])
    boots.append(diff[ii].mean())
  lo, hi = np.percentile(boots, [2.5, 97.5])
  print(f"(c) 2024-25, {len(tst):,} 3rd / 4th downs: Brier model {np.mean((pb - tst.y) ** 2):.4f}, + form {np.mean((pf - tst.y) ** 2):.4f}, "
        f"change {diff.mean():+.5f} [{lo:+.5f}, {hi:+.5f}] -> {'PASS' if hi < 0 else 'FAIL'}")
  # the size of the effect where it matters: 4th downs, form in the top vs bottom fifth
  t4 = tst[tst.down == 4].assign(pf=pf[(tst.down == 4).to_numpy()])
  qg = pd.qcut(t4.form_game, 5, labels=False)
  print("  4th downs 2024-25 by this game's form (fifths): actual / model / model + form:",
        [f"{t4.y[qg == k].mean():.2f}/{t4.p4[qg == k].mean():.2f}/{t4.pf[qg == k].mean():.2f}" for k in range(5)])


if __name__ == "__main__":
  main()
