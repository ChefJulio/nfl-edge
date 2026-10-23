"""(CO2) why the calculator's "if it works" and "missed field goal" branches read high ((CO) in docs/INSIGHTS.md).
For each 2022-25 converted 4th-down try and missed field goal, the next snap's real state (clock, spot, score,
timeouts) is exported; tools/branch_eval.mjs scores it with the engine's wp() beside the branch the engine assumed.
If the real next state is called right and the branch is not, the assumed state is wrong; if both read high, it is
the win model.

  python tools/branch_eval.py export    -> scratch/calc_val/next_<season>.json
  node tools/branch_eval.mjs            -> scratch/calc_val/nextgraded.json
  python tools/branch_eval.py analyze
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


def export():
  for s in TESTS:
    d = pd.read_parquet(ROOT / "cache" / f"pbp_calc_{s}.parquet")
    d = d[d.season_type == "REG"].sort_values(["game_id", "play_id"]).reset_index(drop=True)
    g = json.loads((OUT / f"graded_{s}.json").read_text(encoding="utf-8"))
    g = pd.DataFrame([r for r in g if (r["choice"] == "go" and r["conv"] == 1) or (r["choice"] == "fg" and r["fgm"] == 0)])
    snaps = d[d.down.notna() & d.posteam.notna() & d.play_type.isin(["run", "pass", "punt", "field_goal", "qb_kneel", "qb_spike", "no_play"])]
    snaps = snaps[snaps.down == 1]
    by_game = {k: v for k, v in snaps.groupby("game_id")}
    out = []
    for r in g.itertuples():
      n = by_game.get(r.game_id)
      if n is None:
        continue
      n = n[n.play_id > r.play_id]
      if n.empty:
        continue
      x = n.iloc[0]
      same = x.posteam == r.team
      # the branch's next snap: ours after a conversion, theirs after a miss; a score or another change in between = out
      if (r.choice == "go") != bool(same) or x.qtr != r.qtr:
        continue
      home = x.posteam == x.home_team
      out.append({"game_id": r.game_id, "play_id": r.play_id, "choice": r.choice, "won": r.won, "f_branch": r.f_made if r.choice == "go" else r.f_missed,
                  "sec0": r.sec, "diff0": r.diff, "yl0": r.yl, "togo0": r.togo, "qtr": int(r.qtr),
                  "diff": float(x.score_differential), "sec": float(x.game_seconds_remaining), "down": 1, "togo": float(x.ydstogo),
                  "yl": float(x.yardline_100), "to": float(x.posteam_timeouts_remaining), "oppTo": float(x.defteam_timeouts_remaining),
                  "line": r.line if same else -r.line, "total": r.total, "home": int(home), "rec2h": r.rec2h if same else 1 - r.rec2h,
                  "roof": r.roof, "wind": None if pd.isna(r.wind) else r.wind})
    (OUT / f"next_{s}.json").write_text(json.dumps(out), encoding="utf-8")
    print(f"[co2] {s}: {len(out)} next snaps", flush=True)


def analyze():
  t = pd.DataFrame(json.loads((OUT / "nextgraded.json").read_text(encoding="utf-8")))
  rng = np.random.default_rng(0)

  def gap(x, col):
    d = (x.won - x[col]).to_numpy(); gm = x.game_id.to_numpy(); ug = np.unique(gm)
    idx = {k: np.where(gm == k)[0] for k in ug}
    b = [d[np.concatenate([idx[k] for k in rng.choice(ug, len(ug))])].mean() for _ in range(1000)]
    lo, hi = np.percentile(b, [2.5, 97.5])
    return f"{100 * d.mean():+5.1f} [{100 * lo:+5.1f}, {100 * hi:+5.1f}]"

  for ch, lab in (("go", "converted"), ("fg", "missed field goal")):
    x = t[t.choice == ch]
    print(f"\n[co2] {lab}: {len(x)} plays; won minus forecast (95% by games)")
    for sub, y in (("all", x), ("branch 40-80%", x[x.f_branch.between(.4, .8)]), ("branch 20-70%", x[x.f_branch.between(.2, .7)]),
                   ("4th quarter", x[x.qtr == 4]), ("1st half", x[x.qtr <= 2])):
      print(f"  {sub:14s} n {len(y):4d}  branch {gap(y, 'f_branch')}   real next state {gap(y, 'f_next')}"
            + (f"   branch, clock run {gap(y, 'f_run')}" if ch == "go" else ""))
    print(f"  assumed vs real: seconds used, median {x.sec0.sub(x.sec).median():.0f}"
          f"; spot {'gained' if ch == 'go' else 'theirs'} median {(x.yl0 - x.yl).median() if ch == 'go' else (100 - x.yl).median():.0f} yards")


if __name__ == "__main__":
  {"export": export, "analyze": analyze}[sys.argv[1] if len(sys.argv) > 1 else "analyze"]()
