"""One player's projection, step by step (owner 2026-10-21: "something's wrong" with Woody Marks at 15): his usage
inputs and predicted shares, the team volume they multiply, the per-play rates, the injury redistribution on top.

Usage: python tools/explain_proj.py "Woody Marks" ["Kenneth Walker III" ...] [--week=N]
Reads the cached projection of the live build (run.py's cached_model; no retraining when the cache is current).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

from nfledge.config import load_config, load_scoring  # noqa: E402
from nfledge.data import load_all  # noqa: E402

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 60)


def main():
  names = [a for a in sys.argv[1:] if not a.startswith("--")]
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  import run
  cfg, scoring = load_config(), load_scoring()
  data = load_all(cfg, force_week=int(opt["week"]) if "week" in opt else None)
  season = data.current_season
  week = int(opt.get("week", run.display_week(data)))
  eng, proj = run.cached_model(data, cfg, scoring, season, week)
  x = proj[proj.full_name.isin(names)] if "full_name" in proj else proj[proj.gsis_id.isin(names)]
  groups = {
    "usage in": ["carry_share", "carry_share_long", "tgt_share", "tgt_share_long", "snap_pct", "games", "team_conc"],
    "shares out": ["carry_share_hat", "tgt_share_hat"],
    "team volume": ["team_rush", "team_db", "implied_pts", "spread_team", "def_rush", "def_pass", "off_rush"],
    "volume": ["carries", "tgt", "rush", "carry_add", "tgt_add"],
    "rates in": [c for c in proj.columns if c.endswith(("_ypc", "_rate", "oe", "_frac")) and not c.startswith("wind")][:14],
    "stats": ["rush_yd", "rush_td", "reception", "rec_yd", "rec_td", "fumble_lost"],
    "points": ["proj_no_inj", "proj_model", "ecr", "ecr_flex", "ecr_pts", "proj", "injury_boost", "avail", "sits"],
  }
  for _, r in x.iterrows():
    print(f"\n=== {r.get('full_name')} ({r.get('team')} {r.get('pos')}) vs {r.get('opp')}")
    for g, cols in groups.items():
      vals = {c: (round(float(r[c]), 3) if isinstance(r[c], (int, float)) and pd.notna(r[c]) else r[c]) for c in cols if c in r.index}
      print(f"  {g:<12} {vals}")


if __name__ == "__main__":
  main()
