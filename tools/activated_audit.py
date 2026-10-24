"""Prospective audit of the activation rule (pre-registered 2026-10-24, docs/INSIGHTS.md {#activated}).

Usage: python tools/activated_audit.py [--site=site]
Reads every data/live_inputs/activated_<season>_<week>.json (written by run.py: each player activated off a reserve
list, ESPN Active after his last game, with his team's final report out: the model's chance before the override and
the measured rate it set) and checks them against who played (snap counts, nfledge.returns.played_set) for weeks whose
snaps are out. GATE (once 30+ player-weeks are in): the played rate's 95% Wilson interval includes the mean of the
rates the rule set, AND the Brier of the rule's chances is lower than the model's chances before it on the same
players. Fail -> the chance part of the rule comes out (the tag part stays).
"""
import json
import sys
from math import sqrt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.returns import played_set  # noqa: E402

MIN_N = 30


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = Path(opt.get("site", "site"))
  files = sorted((site / "data" / "live_inputs").glob("activated_*.json"))
  if not files:
    print("[audit] no activation overrides archived yet")
    return
  d = D.load_all(load_config())
  played = played_set(d)
  snap_weeks = {(int(s), int(w)) for s, w in zip(d.snaps.season, d.snaps.week)}
  rows = []
  for f in files:
    season, week = map(int, f.stem.split("_")[1:3])
    if (season, week) not in snap_weeks:
      print(f"[audit] {f.name}: week {week} snap counts not out yet")
      continue
    for g, v in json.loads(f.read_text(encoding="utf-8")).items():
      rows.append((v, (season, week, g) in played))
  if not rows:
    return
  n, k = len(rows), sum(p for _, p in rows)
  rate = sum(v["post"] for v, _ in rows) / n
  z, ph = 1.96, k / n
  c = (ph + z * z / (2 * n)) / (1 + z * z / n)
  h = z * sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / (1 + z * z / n)
  b_post = sum((v["post"] - p) ** 2 for v, p in rows) / n
  b_pre = sum((v["pre"] - p) ** 2 for v, p in rows) / n
  print(f"[audit] {n} player-weeks: played {k} ({ph:.1%}, 95% {c - h:.1%}-{c + h:.1%}); rule's mean {rate:.1%}; "
        f"Brier rule {b_post:.4f} vs model before it {b_pre:.4f}")
  for v, p in rows:
    if not p:
      print(f"  did not play: {v['name']} ({v['team']}, {v.get('days')}) rule {v['post']:.2f}, model {v['pre']:.2f}")
  if n < MIN_N:
    print(f"[audit] gate: not yet ({n} of {MIN_N} player-weeks)")
  else:
    ok = c - h <= rate <= c + h and b_post < b_pre
    print(f"[audit] gate: {'PASS (keep)' if ok else 'FAIL (take the rule out)'}")


if __name__ == "__main__":
  main()
