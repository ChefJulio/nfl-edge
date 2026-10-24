"""Prospective audit of the late-downgrade rule (pre-registered 2026-10-24, docs/INSIGHTS.md {#late-downgrade}).

Usage: python tools/espn_late_audit.py [--site=site]
Reads every data/live_inputs/espnlate_<season>_<week>.json (written by run.py: each player ESPN listed Out / Doubtful
after his team's final report, with the chance before the override and the rate it set) and scores them against who
played (snap counts, nfledge.returns.played_set) for weeks whose snaps are out. GATE once 30+ player-weeks are in: no
more than 1 in 30 Out overrides played (else the rule comes out), and the overrides' Brier below the pre-override
chances' on the same players.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.returns import played_set  # noqa: E402

MIN_N = 30


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  files = sorted((Path(opt.get("site", "site")) / "data" / "live_inputs").glob("espnlate_*.json"))
  if not files:
    print("[audit] no late-downgrade overrides archived yet")
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
    rows += [(v, (season, week, g) in played) for g, v in json.loads(f.read_text(encoding="utf-8")).items()]
  if not rows:
    return
  outs = [(v, p) for v, p in rows if v.get("ruling") == "Out"]
  b_post = sum((v["post"] - p) ** 2 for v, p in rows) / len(rows)
  b_pre = sum((v["pre"] - p) ** 2 for v, p in rows) / len(rows)
  print(f"[audit] {len(rows)} overrides ({len(outs)} Out): Out played {sum(p for _, p in outs)}; "
        f"Brier rule {b_post:.4f} vs before it {b_pre:.4f}")
  for v, p in rows:
    if p:
      print(f"  played anyway: {v['name']} ({v['team']}) ruling {v.get('ruling')} rule {v['post']:.2f} model {v['pre']:.2f}")
  if len(rows) < MIN_N:
    print(f"[audit] gate: not yet ({len(rows)} of {MIN_N})")
  else:
    ok = sum(p for _, p in outs) <= max(1, len(outs) // 30) and b_post < b_pre
    print(f"[audit] gate: {'PASS (keep)' if ok else 'FAIL (take the rule out)'}")


if __name__ == "__main__":
  main()
