"""The expected Friday tag (owner 2026-10-23: "the tag is just an aesthetic for our purposes anyway i just want it to be
realistic, in line with how ESPN might list them"): for a player on this week's practice report before the final one,
the official designation he most likely gets, from what's known so far: did he miss his team's last game while on its
report, and his practice days so far (D / L / F). From every 3-day report week 2018 on (cache/availhist_<season>).

  python tools/tag_odds_build.py      -> data/history/tag_odds.json

Read by InjuryModel.designations (nfledge/injuries.py).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

MIN_N = 50
TAG = {"none": "", "QUESTIONABLE": "Q", "DOUBTFUL": "D", "OUT": "O"}


def main():
  fr = [pd.read_parquet(p) for p in sorted((ROOT / "cache").glob("availhist_*.parquet"))]
  a = pd.concat(fr, ignore_index=True).sort_values(["gsis_id", "season", "week"])
  a["gs"] = a.game_status.fillna("").str.upper().replace({"NONE": ""}).replace({"": "none"})
  prev = a.groupby(["gsis_id", "season"]).shift(1)
  a["missed"] = ((a.week - prev.week) <= 2) & (prev.played == False)  # noqa: E712 (NaN-safe)
  a = a[a.days.str.len() == 3]
  out = {"built": pd.Timestamp.now().strftime("%Y-%m-%d"), "seasons": [int(a.season.min()), int(a.season.max())], "odds": {}}
  for k in (1, 2):
    for (m, seq), g in a.assign(seq=a.days.str[:k]).groupby(["missed", "seq"]):
      if len(g) < MIN_N or "?" in seq:
        continue
      share = g.gs.value_counts(normalize=True)
      top = share.idxmax()
      # the likeliest tag when one is at least an even bet; otherwise the honest middle, Q
      tag = TAG.get(top, "") if share.max() >= 0.5 else "Q"
      out["odds"][f"{'missed' if m else 'played'}:{seq}"] = {
        "tag": tag, "n": int(len(g)), "played": round(float(g.played.mean()), 3),
        "share": {TAG.get(s, s) or "none": round(float(v), 3) for s, v in share.items()}}
  # (owner 2026-10-23, "can we fix it") the play rate of a player with NO designation on the final report, by the
  # same keys: what ESPN's "Active" before the report stands for (InjuryModel: espn_active, cleared_rate)
  out["cleared"] = {}
  c = a[a.gs == "none"]
  for k in (0, 1, 2):
    for (m, seq), g in c.assign(seq=c.days.str[:k]).groupby(["missed", "seq"]):
      if len(g) >= MIN_N and "?" not in seq:
        out["cleared"][f"{'missed' if m else 'played'}:{seq}"] = {"n": int(len(g)), "played": round(float(g.played.mean()), 4)}
  dst = ROOT / "data" / "history" / "tag_odds.json"
  dst.write_text(json.dumps(out, indent=1), encoding="utf-8")
  for key, v in out["odds"].items():
    print(f"  {key:10s} n {v['n']:5d}  tag {v['tag'] or '-':2s} played {v['played']:.2f}  {v['share']}")
  for key, v in out["cleared"].items():
    print(f"  cleared {key:10s} n {v['n']:5d}  played {v['played']:.3f}")
  print(f"[tags] wrote {dst.relative_to(ROOT)}")


if __name__ == "__main__":
  main()
