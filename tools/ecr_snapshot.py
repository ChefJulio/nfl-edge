"""Expert consensus (FantasyPros weekly ECR) snapshots through the week, for a forward test (owner 2026-10-15).

Usage: python tools/ecr_snapshot.py [--out=site/data/ecr_snapshots]   (CI step; failures never fail the build)

Why: the model's expert blend reads nflverse's weekly ECR history, which keeps ONE snapshot per week (Fridays), so
projections Tuesday-Thursday run without it. DynastyProcess re-scrapes FantasyPros' weekly ranks twice a day
(nflreadpy load_ff_rankings(type="week")), but nobody archives those, so whether early-week ranks help can't be
backtested. Each CI run saves the current scrape (once per scrape_date); after a few weeks, the pre-registered test in
docs/INSIGHTS.md section 9 decides whether early-week ECR joins the blend.
Writes <out>/<season>_<scrape_date>.json: {"scrape_date", "season", "week", "p": {fantasypros_id: [pos, ecr, sd]}}.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  out = Path(opt.get("out", str(ROOT / "site" / "data" / "ecr_snapshots")))
  import nflreadpy as nfl
  w = nfl.load_ff_rankings(type="week")
  w = w.to_pandas() if hasattr(w, "to_pandas") else w
  w = w[w.pos.isin(["QB", "RB", "WR", "TE", "K", "DST"])]
  if w.empty:
    print("[ecr-snapshot] nothing to save")
    return
  sd = str(w.scrape_date.max())
  season = int(nfl.get_current_season())
  f = out / f"{season}_{sd}.json"
  if f.exists():
    print(f"[ecr-snapshot] {f.name} already saved")
    return
  wk = None
  try:
    import urllib.request
    with urllib.request.urlopen(urllib.request.Request("https://api.sleeper.app/v1/state/nfl",
                                                       headers={"User-Agent": "nfl-edge-site/1.0"}), timeout=20) as r:
      wk = int(json.load(r)["week"])
  except Exception:
    pass
  p = {str(i): [pos, round(float(e), 2), round(float(s), 2) if s == s else None]
       for i, pos, e, s in zip(w.fantasypros_id, w.pos, w.ecr, w.sd)}
  out.mkdir(parents=True, exist_ok=True)
  f.write_text(json.dumps({"scrape_date": sd, "season": season, "week": wk, "p": p}, separators=(",", ":")), encoding="utf-8")
  print(f"[ecr-snapshot] {season} wk {wk} scraped {sd}: {len(p)} players -> {f.name} ({f.stat().st_size // 1024} KB)")


if __name__ == "__main__":
  main()
