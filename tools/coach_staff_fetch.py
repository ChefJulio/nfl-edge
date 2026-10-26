"""Past coaching staffs (Wikipedia season articles) -> data/history/coach_staff.json, committed: past seasons never
change, so the site build reads this file and fetches only the current staffs (tools/coaches_build.py).

Usage: python tools/coach_staff_fetch.py [--seasons=1999-2025] [--missing-only]
Shape: {"src": ..., "fetched": "YYYY-MM-DD", "staff": {"<season>": {"<TEAM>": {"hc", "oc", "dc", "st"}}}}
"""
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nfledge import coaches as C  # noqa: E402

OUT = ROOT / "data" / "history" / "coach_staff.json"


def main() -> None:
  args = dict(a.lstrip("-").split("=", 1) if "=" in a else (a.lstrip("-"), "1") for a in sys.argv[1:])
  lo, hi = (int(x) for x in args.get("seasons", f"1999-{date.today().year - 1}").split("-"))
  doc = json.loads(OUT.read_text()) if OUT.exists() else {"staff": {}}
  doc["src"] = "Wikipedia season articles (CC BY-SA), '<season> <Team> season'"
  got = doc["staff"]
  for s in range(lo, hi + 1):
    row = got.setdefault(str(s), {})
    for t in C.NAME:
      if "missing-only" in args and row.get(t): continue
      try: v = C.season_staff(t, s)
      except Exception as e:
        print(f"[staff] {s} {t}: {e}"); continue
      if v: row[t] = v
      time.sleep(0.15)  # polite to Wikipedia
    gaps = [f"{t}:{''.join(r for r in C.ROLES if r not in row.get(t, {}))}" for t in C.NAME if C.name_in(t, s) and len(row.get(t, {})) < 4]
    print(f"[staff] {s}: {len(row)} teams; gaps {' '.join(gaps) or 'none'}", flush=True)
  doc["fetched"] = date.today().isoformat()
  OUT.write_text(json.dumps(doc, separators=(",", ":"), sort_keys=True))
  print(f"[staff] wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
  main()
