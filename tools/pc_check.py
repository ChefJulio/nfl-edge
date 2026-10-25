"""(PC) grading accept / decline calls (pre-registered 2026-10-25, docs/INSIGHTS.md): the inputs for the gate.
Writes scratch/pc/snaps_<season>.json (every real snap 2022-25 as an engine state + whether its team won: gate (1),
the trust cells) and scratch/pc/choices_<season>.json (nfledge/penalties.choice_rows), then runs tools/pc_check.mjs,
which grades with the browser engine and each season's walk-forward model (scratch/site/data/calc/wf/).

  python tools/pc_check.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

from nfledge import penalties as P  # noqa: E402
from nfledge import winprob as W  # noqa: E402

SEASONS = [2022, 2023, 2024, 2025]
OUT = ROOT / "scratch" / "pc"


def main():
  OUT.mkdir(parents=True, exist_ok=True)
  for s in SEASONS:
    d = pd.read_parquet(ROOT / "cache" / f"pbp_calc_{s}.parquet")
    d = d[d.result.notna()]
    r = W.rows(d[d.season_type == "REG"])
    r = r[r.down.notna()]
    snaps = [[float(v) for v in row] for row in r[["score_diff", "game_sec", "down", "ydstogo", "yardline_100", "own_to",
                                                   "opp_to", "exp_margin", "home", "receive_2h", "y"]].to_numpy()]
    (OUT / f"snaps_{s}.json").write_text(json.dumps(snaps, separators=(",", ":")), encoding="utf-8")
    c = P.choice_rows(d)
    (OUT / f"choices_{s}.json").write_text(c.to_json(orient="records"), encoding="utf-8")
    print(f"[pc] {s}: {len(snaps):,} snaps, {len(c):,} choices ({(c.choice == 'decline').sum():,} declined)", flush=True)
  subprocess.run(["node", str(ROOT / "tools" / "pc_check.mjs")], check=True)


if __name__ == "__main__":
  main()
