"""(CJ) validating the calculator's decisions (docs/INSIGHTS.md; owner 2026-10-23: "how confident are we that this is an
accurate model? what data shows we're right?").

  python tools/calc_validate.py export --nfl4th=<pre_computed_go_boost.rds>   every regulation 4th down 2022-25 (state,
                                                                             choice, result, nfl4th's numbers) -> scratch/calc_val/rows_<season>.json
  node tools/calc_validate.mjs                                               grades them with each season's walk-forward model
  python tools/calc_validate.py analyze                                      (1) calibration of the chosen option, (3) agreement with nfl4th
  python tools/calc_validate.py boot                                         (2) the noise band from the bootstrap refits
Model files: tools/calc_build.py --through=<season before> --out=scratch/calc_val/through_<y>.json (and --boot=<seed>).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

OUT = ROOT / "scratch" / "calc_val"
TESTS = [2022, 2023, 2024, 2025]
ROOF = {"outdoors": "outdoors", "open": "outdoors", "dome": "dome", "closed": "retractable"}


def export(nfl4th_path: str):
  import pyreadr
  n4 = list(pyreadr.read_r(nfl4th_path).values())[0]
  n4["play_id"] = n4.play_id.astype(float)
  for s in TESTS:
    d = pd.read_parquet(ROOT / "cache" / f"pbp_calc_{s}.parquet")
    d = d[d.season_type == "REG"]
    ko = d[(d.kickoff_attempt == 1) & (d.qtr == 1) & d.posteam.notna()].sort_values(["game_id", "play_id"])
    first_rec = ko.drop_duplicates("game_id").set_index("game_id").posteam
    x = d[(d.down == 4) & (d.qtr <= 4) & d.play_type.isin(["run", "pass", "punt", "field_goal"]) & d.result.notna()
          & d.ydstogo.notna() & d.yardline_100.notna() & (d.qb_kneel != 1) & (d.qb_spike != 1)]
    x = x[x.result != 0]
    home = x.posteam == x.home_team
    rows = pd.DataFrame({
      "game_id": x.game_id, "play_id": x.play_id.astype(float), "qtr": x.qtr, "desc": x.desc.str.slice(0, 140),
      "diff": x.score_differential.fillna(0), "sec": x.game_seconds_remaining, "togo": x.ydstogo, "yl": x.yardline_100,
      "to": x.posteam_timeouts_remaining.fillna(3), "oppTo": x.defteam_timeouts_remaining.fillna(3),
      "line": np.where(home, x.spread_line, -x.spread_line), "total": x.total_line.fillna(45), "home": home.astype(int),
      "rec2h": (x.game_id.map(first_rec) != x.posteam).astype(int), "roof": x.roof.map(ROOF).fillna("outdoors"),
      "wind": x.wind, "choice": x.play_type.map({"run": "go", "pass": "go", "punt": "punt", "field_goal": "fg"}),
      "won": np.where(home, x.result > 0, x.result < 0).astype(int), "team": x.posteam})
    rows = rows.merge(n4, on=["game_id", "play_id"], how="left")
    rows = rows.replace({np.nan: None})
    (OUT / f"rows_{s}.json").write_text(json.dumps(rows.to_dict("records")), encoding="utf-8")
    print(f"[val] {s}: {len(rows):,} 4th downs ({rows.go_wp.notna().sum():,} with nfl4th numbers)", flush=True)


def _load(name: str) -> pd.DataFrame:
  return pd.concat([pd.DataFrame(json.loads((OUT / f"{name}_{s}.json").read_text(encoding="utf-8"))) for s in TESTS
                    if (OUT / f"{name}_{s}.json").exists()], ignore_index=True)


def analyze():
  g = _load("graded")
  print(f"[val] {len(g):,} graded 4th downs, 2022-25")
  # (1) the chosen option's win chance as a forecast
  g["n4_chosen"] = np.select([g.choice == "go", g.choice == "fg", g.choice == "punt"], [g.go_wp, g.fg_wp, g.punt_wp], np.nan).astype(float)
  ok = True
  print("\n(1) the chosen option's forecast vs the share of games won")
  for c in ("go", "fg", "punt", "all"):
    x = g if c == "all" else g[g.choice == c]
    gap = x.won.mean() - x.f_chosen.mean()
    y = x[x.n4_chosen.notna()]
    gate = c != "all"
    if gate:
      ok &= abs(gap) <= 0.03
    print(f"  {('ok ' if abs(gap) <= 0.03 else 'BAD') if gate else '   '} {c:5s} n {len(x):5d}  ours {x.f_chosen.mean():.3f}  won {x.won.mean():.3f}  ({gap:+.3f})"
          f"   | nfl4th on {len(y):5d}: {y.n4_chosen.mean():.3f} vs won {y.won.mean():.3f} ({y.won.mean() - y.n4_chosen.mean():+.3f})"
          f"   Brier ours {np.mean((x.f_chosen - x.won) ** 2):.4f} nfl4th {np.mean((y.n4_chosen - y.won) ** 2):.4f} (ours on its rows {np.mean((y.f_chosen - y.won) ** 2):.4f})")
  g["dec"] = np.minimum((g.f_chosen * 10).astype(int), 9)
  cal = g.groupby(["choice", "dec"]).agg(n=("won", "size"), forecast=("f_chosen", "mean"), won=("won", "mean"))
  cal["gap"] = cal.won - cal.forecast
  bad = cal[(cal.n >= 50) & (cal.gap.abs() > 0.06)]
  ok &= bad.empty
  print(cal.round(3).to_string())
  print(f"  deciles of 50+ off by more than 6 points: {len(bad)}")
  print(f"[val] (1) gate: {'PASS' if ok else 'FAIL'}")
  # (3) agreement with nfl4th
  y = g[g.go_wp.notna()].copy()
  ours = y[["w_go", "w_fg", "w_punt"]].rename(columns=lambda c: c[2:])
  theirs = y[["go_wp", "fg_wp", "punt_wp"]].rename(columns=lambda c: c[:-3])
  avail = ours.notna() & theirs.notna()
  ours, theirs = ours.where(avail), theirs.where(avail)
  y["best_ours"], y["best_n4"] = ours.idxmax(axis=1), theirs.idxmax(axis=1)
  # the gap between going and the best kick, both models
  y["gap_ours"] = ours.go - ours[["fg", "punt"]].max(axis=1)
  y["gap_n4"] = theirs.go - theirs[["fg", "punt"]].max(axis=1)
  agree = (y.best_ours == y.best_n4).mean()
  r = y[["gap_ours", "gap_n4"]].dropna().corr().iloc[0, 1]
  print(f"\n(3) vs nfl4th on {len(y):,} plays: same recommendation {agree:.1%}; correlation of the go-vs-best-kick gap {r:.3f}")
  print("  recommendation table (rows ours, columns nfl4th):")
  print(pd.crosstab(y.best_ours, y.best_n4).to_string())
  y["dis"] = (y.gap_ours - y.gap_n4).abs()
  top = y.sort_values("dis", ascending=False).head(25)
  print("\n  the 25 biggest disagreements (go minus best kick, points of win chance):")
  for t in top.itertuples():
    print(f"  {t.game_id} Q{t.qtr} {int(t.sec)}s diff {int(t.diff):+d} 4th&{int(t.togo)} at {int(t.yl)}: ours {100 * t.gap_ours:+.1f} nfl4th {100 * t.gap_n4:+.1f}"
          f" | chose {t.choice} | {t.desc[:70]}")
  # how the teams decided, by each model's sign
  print("\n  teams going for it when each model says go by 3+ points:",
        f"ours {y[y.gap_ours > 0.03].choice.eq('go').mean():.1%} (n {int((y.gap_ours > 0.03).sum())}),",
        f"nfl4th {y[y.gap_n4 > 0.03].choice.eq('go').mean():.1%} (n {int((y.gap_n4 > 0.03).sum())})")


def boot():
  b = _load("bootgraded")
  if b.empty:
    print("[val] no bootstrap grades yet"); return
  # one row per play x replicate: options' win chances; the base model's best and gap
  piv = b.groupby("key")
  rows = []
  for k, x in piv:
    gaps = x.gap.to_numpy()
    rows.append({"key": k, "base_gap": float(x.base_gap.iloc[0]), "sd": float(gaps.std(ddof=1)),
                 "flip": float((x.best != x.base_best.iloc[0]).mean()), "n": len(x)})
  r = pd.DataFrame(rows)
  print(f"[val] (2) {len(r):,} plays x {int(r.n.median())} refits: sd of the best-minus-second gap median {100 * r.sd.median():.2f} points"
        f" (90th pct {100 * r.sd.quantile(.9):.2f})")
  r["band"] = pd.cut(r.base_gap, [0, 0.005, 0.01, 0.015, 0.02, 0.03, 0.05, 1.0])
  t = r.groupby("band", observed=True).agg(n=("flip", "size"), flips=("flip", "mean"), flip_over_20pct=("flip", lambda f: (f > 0.2).mean()))
  print(t.round(3).to_string())
  # the toss-up band: the gap below which a recommendation flips in more than 1 refit in 5 (on average)
  for cut in np.arange(0.0025, 0.06, 0.0025):
    if r[(r.base_gap >= cut) & (r.base_gap < cut + 0.0025)].flip.mean() <= 0.2:
      print(f"[val] (2) toss-up band: gaps under {100 * cut:.2f} points flip in more than 1 refit in 5")
      break


if __name__ == "__main__":
  cmd = sys.argv[1] if len(sys.argv) > 1 else "analyze"
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  OUT.mkdir(parents=True, exist_ok=True)
  {"export": lambda: export(opt["nfl4th"]), "analyze": analyze, "boot": boot}[cmd]()
