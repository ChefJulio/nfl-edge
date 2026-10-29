"""The training-data lock (owner 2026-10-24: "shouldn't they always match exact?"). The engine trains on cached history
tables (practice weeks, injury reports, practice reports, snap counts of past seasons) that are cached per season
and never refetched; on 2026-10-24 the live build's copies differed from a fresh local cache (practice dates) and it
trained a different injury model (Saquon Barkley 33% live vs 65% local) for two days unnoticed. Every build (run.py)
now compares the history's fingerprint with data/history/training_fingerprint.json and stops on any difference.

  python tools/training_lock.py           show this cache's fingerprint vs the locked one
  python tools/training_lock.py --bless   lock this cache's fingerprint (after checking WHY the history changed:
                                          a new season joining it, nflverse revising old data, a deliberate refetch)
  python tools/training_lock.py --bless --refresh-ids
                                          ...and take nflverse's current player-id matches for past seasons' snap
                                          counts (data/history/snap_ids.json) instead of the frozen ones

Past seasons' snap counts carry PFR ids, matched to ours through tables nflverse refreshes (2026-10-29: the weekly
player-table refresh re-attributed old rows and stopped every build for a morning). The matches are frozen in
data/history/snap_ids.json (nfledge/data.py freeze_snap_ids); --bless adds ids it hasn't seen (a season newly past)
and keeps the rest.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
  import run
  from nfledge.config import load_config
  from nfledge import data as D
  refresh = "--bless" in sys.argv and "--refresh-ids" in sys.argv
  frozen = json.loads(D.SNAP_IDS.read_text(encoding="utf-8")) if D.SNAP_IDS.exists() else None
  if refresh and frozen is not None:
    D.SNAP_IDS.unlink()  # load with the live matches; rewritten below
  try:
    d = D.load_all(load_config())
  except BaseException:
    if refresh and frozen is not None:
      D.SNAP_IDS.write_text(json.dumps(frozen, separators=(",", ":")) + "\n", encoding="utf-8")
    raise
  if "--bless" in sys.argv:
    through = int(d.current_season) - 1
    keep = None if refresh or frozen is None else frozen.get("ids", {})
    ids = D.snap_id_map(d.snaps, through, keep)
    D.SNAP_IDS.write_text(json.dumps({"through": through, "ids": ids}, separators=(",", ":")) + "\n", encoding="utf-8")
    # (d.snaps already reads this way: the frozen ids as frozen, the new ones as just matched)
    print(f"[lock] wrote {D.SNAP_IDS.relative_to(ROOT)}: {len(ids)} ids through {through} ({len(ids) - len(keep or {})} new)")
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
