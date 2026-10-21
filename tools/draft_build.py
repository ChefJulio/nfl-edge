"""Draft data for Teams > Draft: data/draft/<year>.json (every pick 1980 on, with career outcomes) + index.json.

Usage: python tools/draft_build.py [--site=site]   (CI runs it; ~2 s)
Source: nflverse load_draft_picks (Pro Football Reference): round, pick, team, player, position, college, age, and
career outcomes (last season, games, seasons as a starter, Pro Bowls, All-Pro, Hall of Fame, weighted career
approximate value, value to the drafting team, career passing / rushing / receiving / defense totals). Team codes are
PFR's: mapped to today's franchise for logos (the code of the time is kept for display).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402

V = 1
FRANCHISE = {"GNB": "GB", "KAN": "KC", "LVR": "LV", "OAK": "LV", "RAI": "LV", "NOR": "NO", "NWE": "NE", "SDG": "LAC",
             "SFO": "SF", "TAM": "TB", "STL": "LA", "RAM": "LA", "LAR": "LA", "PHO": "ARI"}
COLS = ["round", "pick", "team", "gsis_id", "pfr_player_name", "position", "category", "side", "college", "age", "to",
        "allpro", "probowls", "seasons_started", "w_av", "dr_av", "games", "hof", "pass_yards", "pass_tds", "rush_yards",
        "rush_tds", "receptions", "rec_yards", "rec_tds", "def_solo_tackles", "def_ints", "def_sacks"]


def clean(v):
  if v is None or (isinstance(v, float) and not np.isfinite(v)):
    return None
  if isinstance(v, (np.bool_, bool)):
    return 1 if v else 0
  if isinstance(v, (np.integer,)):
    return int(v)
  if isinstance(v, (float, np.floating)):
    return int(v) if float(v).is_integer() else round(float(v), 1)
  return v


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = Path(opt.get("site", "site"))
  import nflreadpy as nfl
  cfg = load_config()
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  draft = cache.get("draft", "all", lambda: nfl.load_draft_picks(), stale=cache.age_hours("draft", "all") > 24)
  teams = cache.get("teams", "all", lambda: nfl.load_teams(), stale=False)
  cache.save_meta()
  t = teams.drop_duplicates("team_abbr").set_index("team_abbr")
  out = site / "data" / "draft"
  out.mkdir(parents=True, exist_ok=True)
  draft = draft.assign(fr=draft.team.map(lambda x: FRANCHISE.get(x, x)))
  draft["in_rd"] = draft.pick - draft.groupby(["season", "round"]).pick.transform("min") + 1
  years = sorted(int(y) for y in draft.season.unique())
  # the search over every draft (owner 2026-10-21: a name search shouldn't need its year): per year, "name|college"
  # lines in the year file's row order, colleges as indexes into one list; ~100 KB gzipped, loaded on a first search
  colleges, cidx, search = [], {}, {}
  for y in years:
    d = draft[draft.season == y].sort_values("pick")
    cols = COLS + ["fr", "in_rd"]
    doc = {"v": V, "season": y, "cols": cols, "rows": [[clean(getattr(r, c)) for c in cols] for r in d.itertuples()],
           "teams": {a: {"nick": t.at[a, "team_nick"], "logo": t.at[a, "team_logo_espn"], "color": t.at[a, "team_color"]}
                     for a in d.fr.unique() if a in t.index}}
    (out / f"{y}.json").write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    lines = []
    for nm, col in zip(d.pfr_player_name, d.college):
      col = col if isinstance(col, str) else ""
      if col not in cidx:
        cidx[col] = len(colleges)
        colleges.append(col)
      lines.append(f"{(nm if isinstance(nm, str) else '').replace('|', ' ')}|{cidx[col]}")
    search[str(y)] = "\n".join(lines)
  (out / "search.json").write_text(json.dumps({"v": 1, "c": colleges, "y": search}, separators=(",", ":")), encoding="utf-8")
  (out / "index.json").write_text(json.dumps({"v": V, "years": years}), encoding="utf-8")
  print(f"[draft] {len(years)} drafts -> {out}", flush=True)


if __name__ == "__main__":
  main()
