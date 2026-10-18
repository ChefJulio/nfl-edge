"""(AU) prospective audit of the game-day rulings (pre-registered 2026-10-18, docs/INSIGHTS.md {#gameday}).

Usage: python tools/gameday_audit.py [--site=site] [--week=2026_06]
Reads data/live_inputs/gameday_<season>_<week>.json (written by run.py: each override, its time, the model's chance
before it) and checks it against who played (snap counts, nfledge.returns.played_set) once the week's snaps are out.
GATE to keep the rule: no INACTIVE override played; the ACTIVE-Questionable played rate's 95% CI includes 0.974;
Brier of the overridden chances below the pre-ruling chances on the same players.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.returns import played_set  # noqa: E402


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = Path(opt.get("site", "site"))
  files = sorted((site / "data" / "live_inputs").glob(f"gameday_{opt.get('week', '*')}.json"))
  d = D.load_all(load_config())
  played = played_set(d)
  snap_weeks = {(int(s), int(w)) for s, w in zip(d.snaps.season, d.snaps.week)}
  for f in files:
    season, week = map(int, f.stem.split("_")[1:3])
    if (season, week) not in snap_weeks:
      print(f"[audit] {f.name}: week {week} snap counts not out yet")
      continue
    log = json.loads(f.read_text(encoding="utf-8"))
    rows = [(g, v, (season, week, g) in played) for g, v in log.items()]
    ina = [r for r in rows if r[1]["ruling"] == "INA"]
    act = [r for r in rows if r[1]["ruling"] == "ACT"]
    bad = [r[1]["name"] for r in ina if r[2]]
    print(f"[audit] {f.name}: {len(ina)} inactive overrides, played: {len(bad)} {bad}")
    if act:
      y = np.array([float(r[2]) for r in act]); n = len(y); p = y.mean()
      lo, hi = p - 1.96 * np.sqrt(max(p * (1 - p), 1e-9) / n), p + 1.96 * np.sqrt(max(p * (1 - p), 1e-9) / n)
      print(f"[audit]   {n} active overrides played {p:.1%} [{lo:.1%}, {hi:.1%}]")
    y = np.array([float(r[2]) for r in rows]); pre = np.array([r[1]["pre"] for r in rows]); post = np.array([r[1]["post"] for r in rows])
    print(f"[audit]   Brier pre-ruling {np.mean((pre - y) ** 2):.4f} -> with rulings {np.mean((post - y) ** 2):.4f} (n {len(y)})")


if __name__ == "__main__":
  main()
