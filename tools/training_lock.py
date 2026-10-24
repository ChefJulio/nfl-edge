"""The training-data lock (owner 2026-10-24: "shouldn't they always match exact?"). The engine trains on cached history
tables (practice weeks, injury reports, practice reports, snap counts of past seasons) that are cached per season
and never refetched; on 2026-10-24 the live build's copies differed from a fresh local cache (practice dates) and it
trained a different injury model (Saquon Barkley 33% live vs 65% local) for two days unnoticed. Every build (run.py)
now compares the history's fingerprint with data/history/training_fingerprint.json and stops on any difference.

  python tools/training_lock.py           show this cache's fingerprint vs the locked one
  python tools/training_lock.py --bless   lock this cache's fingerprint (after checking WHY the history changed:
                                          a new season joining it, nflverse revising old data, a deliberate refetch)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
  import run
  from nfledge.config import load_config
  from nfledge.data import load_all
  d = load_all(load_config())
  now = {k: f"{v:x}" for k, v in run.training_data(d).items()}
  path = run.LOCK
  old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
  for k, v in now.items():
    print(f"  {k:10s} this cache {v:16s} locked {old.get('tables', {}).get(k, '-'):16s} {'' if old.get('tables', {}).get(k) == v else 'DIFFERENT'}")
  if "--bless" in sys.argv:
    path.write_text(json.dumps({"tables": now, "season": int(d.current_season)}, indent=1) + "\n", encoding="utf-8")
    print(f"[lock] wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
  main()
