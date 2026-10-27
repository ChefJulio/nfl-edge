"""(DO) where coaches and nfl4th part ways with our 4th-down calls, and whether the conversion odds behind them hold up.

Usage: python tools/do_disagree.py

Rows: scratch/calc_val/graded_<season>.json (2022-25 regulation 4th downs, our walk-forward grade + nfl4th's numbers);
3rd downs from the play-by-play cache (pbp_calc) for the same seasons. Descriptive (owner 2026-10-26: "what are the
plays coaches universally disagree with us on? what trends can be found in our disagreement with nfl4th? why are we
saying go for it on 4th and 8 so much more often? ... is the probability you convert on 4th and 8 real? does the
context matter?"). No gate.
"""
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

pd.set_option("display.width", 200)


def load() -> pd.DataFrame:
  rows = []
  for f in sorted(glob.glob(str(ROOT / "scratch" / "calc_val" / "graded_20*.json"))):
    d = json.load(open(f, encoding="utf-8")); rows += (d["rows"] if isinstance(d, dict) else d)
  df = pd.DataFrame(rows)
  df = df[df.go_wp.notna() & df.best.notna()].copy()
  n4 = df[["go_wp", "fg_wp", "punt_wp"]].rename(columns={"go_wp": "go", "fg_wp": "fg", "punt_wp": "punt"})
  df["n4best"] = n4.idxmax(axis=1, skipna=True)
  df["ours_go"] = df.best == "go"; df["n4_go"] = df.n4best == "go"; df["went"] = df.choice == "go"
  df["dist"] = pd.cut(df.togo, [0, 1, 2, 3, 5, 7, 10, 99], labels=["1", "2", "3", "4-5", "6-7", "8-10", "11+"])
  df["zone"] = pd.cut(df.yl, [0, 20, 35, 45, 60, 80, 100], labels=["opp 1-20", "opp 21-35", "opp 36-45", "45-40 mid", "own 21-40", "own 1-20"])
  df["late"] = np.where((df.qtr == 4) & (df.sec <= 600), "Q4, last 10 min", "earlier")
  df["score"] = pd.cut(df["diff"], [-99, -9, -1, 0, 8, 99], labels=["down 9+", "down 1-8", "tied", "up 1-8", "up 9+"])
  return df


def rates(g: pd.DataFrame) -> pd.Series:
  return pd.Series({"n": len(g), "ours": 100 * g.ours_go.mean(), "nfl4th": 100 * g.n4_go.mean(), "coaches": 100 * g.went.mean(),
                    "conv_pred": 100 * g.p_conv.mean()})


def main():
  df = load()
  print(f"{len(df):,} 4th downs 2022-25 (share saying GO: ours / nfl4th / coaches went; our average conversion odds)\n")
  print("== by distance"); print(df.groupby("dist", observed=True).apply(rates).round(1).to_string())
  print("\n== by field zone"); print(df.groupby("zone", observed=True).apply(rates).round(1).to_string())
  print("\n== by game situation"); print(df.groupby(["late", "score"], observed=True).apply(rates).round(1).to_string())

  # where coaches universally disagree: cells with 40+ plays where we say go on 60%+ and coaches went on under 20%
  print("\n== where coaches universally disagree with us (40+ plays; we say go 60%+; coaches go under 20%)")
  cell = df.groupby(["dist", "zone", "late"], observed=True).apply(rates)
  cell = cell[(cell.n >= 40) & (cell.ours >= 60) & (cell.coaches < 20)].sort_values("n", ascending=False)
  print(cell.round(1).head(15).to_string())

  # disagreements with nfl4th: where we say go and it says kick
  dis = df[df.ours_go & ~df.n4_go]
  print(f"\n== we say GO, nfl4th says kick: {len(dis):,} plays; by distance / zone (share of all such plays)")
  print((100 * dis.dist.value_counts(normalize=True).sort_index()).round(1).to_string())
  print((100 * dis.zone.value_counts(normalize=True).sort_index()).round(1).to_string())
  print("  our go edge on them: median %+.1f pts, %.0f%% under 1.25 (toss-ups)" % (100 * dis.gap.median() if "gap" in dis else np.nan,
        100 * (dis.gap.abs() < 0.0125).mean() if "gap" in dis else np.nan))

  # 4th and 8: what drives our go
  e = df[df.togo.between(7, 9)]
  print(f"\n== 4th & 7-9: {len(e):,} plays; ours go {100 * e.ours_go.mean():.1f}%, nfl4th {100 * e.n4_go.mean():.1f}%, coaches {100 * e.went.mean():.1f}%")
  print(e.groupby(["late", "score"], observed=True).apply(rates).round(1).to_string())
  print(e.groupby("zone", observed=True).apply(rates).round(1).to_string())

  # is the conversion probability real? 4th-down tries (self-selected) and 3rd downs (every one is a try) at the distance
  print("\n== conversion odds vs reality, by distance (4th-down tries; 3rd downs from the play-by-play)")
  t = df[df.went & df.conv.notna()]
  pb = pd.concat([pd.read_parquet(ROOT / "cache" / f"pbp_calc_{s}.parquet") for s in range(2022, 2026)], ignore_index=True)
  pb = pb[(pb.season_type == "REG") & (pb.qtr <= 4) & pb.play_type.isin(["run", "pass"]) & (pb.qb_kneel != 1) & (pb.qb_spike != 1)]
  third = pb[pb.down == 3].copy()
  third["conv"] = ((third.yards_gained >= third.ydstogo) | (third.touchdown == 1)).astype(float)
  third["late"] = np.where((third.qtr == 4) & (third.game_seconds_remaining <= 600), "Q4, last 10 min", "earlier")
  out = []
  for lo, hi, lab in ((1, 1, "1"), (2, 2, "2"), (3, 3, "3"), (4, 5, "4-5"), (6, 7, "6-7"), (8, 10, "8-10"), (11, 99, "11+")):
    tt = t[t.togo.between(lo, hi)]; th = third[third.ydstogo.between(lo, hi)]
    out.append({"dist": lab, "4th tries": len(tt), "4th converted": 100 * tt.conv.mean() if len(tt) else np.nan,
                "our odds on those tries": 100 * tt.p_conv.mean() if len(tt) else np.nan,
                "our odds on all 4th downs": 100 * df[df.togo.between(lo, hi)].p_conv.mean(),
                "3rd downs": len(th), "3rd converted": 100 * th.conv.mean()})
  print(pd.DataFrame(out).round(1).to_string(index=False))
  print("\n== does context matter? conversion at 8-10 yards by situation (3rd downs, every one a try; 4th-down tries)")
  for lab, x in (("3rd & 8-10", third[third.ydstogo.between(8, 10)]),):
    x = x.copy(); x["score"] = pd.cut(x.score_differential, [-99, -9, -1, 0, 8, 99], labels=["down 9+", "down 1-8", "tied", "up 1-8", "up 9+"])
    print(f"  {lab}:"); print((x.groupby(["late", "score"], observed=True).conv.agg(["size", "mean"]).assign(mean=lambda v: (100 * v["mean"]).round(1))).to_string())
  t8 = t[t.togo.between(8, 10)]
  print(f"  4th & 8-10 tries: {len(t8)}; converted {100 * t8.conv.mean():.1f}%, our odds {100 * t8.p_conv.mean():.1f}%")
  print((t8.groupby(["late", "score"], observed=True).apply(lambda g: pd.Series({"n": len(g), "conv": 100 * g.conv.mean(), "ours": 100 * g.p_conv.mean()}))).round(1).to_string())


if __name__ == "__main__":
  main()
