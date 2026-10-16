"""Watch a few owner-chosen players across this week and the lookahead weeks (projection, inactive %, why).

Usage: python tools/watch_players.py [--site=scratch/site] [NAME ...]
Default list (owner 2026-10-16): starter / backup pairs whose numbers should flip when the starter is healthy:
Lamar Jackson / Tyler Huntley (BAL), Baker Mayfield / Jalon Daniels (TB). Reads index.json and <season>/week-NN.json
lookahead pages of a built site.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ["Lamar Jackson", "Tyler Huntley", "Baker Mayfield", "Jalon Daniels"]


def main():
  sys.stdout.reconfigure(encoding="utf-8")
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  names = [a for a in sys.argv[1:] if not a.startswith("--")] or DEFAULT
  site = ROOT / opt.get("site", "scratch/site")
  cur = json.loads((site / "index.json").read_text(encoding="utf-8"))
  pages = [("now", cur)]
  for w in range(int(cur["week"]) + 1, int(cur["week"]) + 5):
    f = site / str(cur["season"]) / f"week-{w:02d}.json"
    if f.exists():
      pages.append((f"wk{w}", json.loads(f.read_text(encoding="utf-8"))))
  for nm in names:
    print(nm)
    for lab, d in pages:
      p = next((x for x in d["players"].values() if x.get("name") == nm), None)
      if p is None:
        print(f"  {lab:5s} wk{d['week']:<2}  not listed")
        continue
      boost = f" +{p['boost']:.1f} from {p['boost_from']}" if p.get("boost", 0) >= 1 else ""
      print(f"  {lab:5s} wk{d['week']:<2}  proj {p['proj']:5.1f}  inactive {100 * p['inactive']:5.1f}%  {p.get('status') or ''}{boost}  | {str(p.get('inactive_why', ''))[:90]}")


if __name__ == "__main__":
  main()
