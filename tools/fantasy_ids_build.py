"""My League (owner 2026-10-15): data/fantasy_ids.json, other platforms' player ids -> our gsis ids.

Usage: python tools/fantasy_ids_build.py --site=site   (CI step)
An imported Sleeper / ESPN roster lists the platform's own player ids; this maps them to ours so every rostered
player lines up with our projections. Sources: nflverse's fantasy id crosswalk (DynastyProcess: sleeper / espn /
yahoo / gsis, ~3.4k players with a gsis id) and the weekly rosters' own sleeper / espn / yahoo columns for gaps.
Players active since 2024 only (~100 KB).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402

PLATFORMS = ("sleeper", "espn", "yahoo")


def clean(v) -> str:
  s = str(v).strip()
  return "" if s in ("", "nan", "None", "<NA>") else s.removesuffix(".0")


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = ROOT / opt.get("site", "site")
  import nflreadpy as nfl
  f = nfl.load_ff_playerids()
  f = f.to_pandas() if hasattr(f, "to_pandas") else f
  c = D.Cache(ROOT / "cache")
  pl = c.get("players", "all", None, stale=False)
  recent = set(pl[pd.to_numeric(pl.last_season, errors="coerce") >= 2024].gsis_id.dropna())
  out = {p: {} for p in PLATFORMS}
  for x in f.dropna(subset=["gsis_id"]).itertuples():
    if x.gsis_id not in recent:
      continue
    for p in PLATFORMS:
      k = clean(getattr(x, f"{p}_id"))
      if k:
        out[p].setdefault(k, x.gsis_id)
  # weekly rosters fill gaps (newer players the crosswalk hasn't caught up with)
  seasons = sorted(set(pd.to_numeric(pl.last_season, errors="coerce").dropna().astype(int)))[-3:]
  for s in seasons:
    r = c.get("rosters", s, None, stale=False)
    if r is None:
      continue
    for p in PLATFORMS:
      col = f"{p}_id"
      if col in r:
        for k, g in zip(r[col], r.gsis_id):
          k = clean(k)
          if k and isinstance(g, str) and g in recent:
            out[p].setdefault(k, g)
  # names for every mapped player (Sleeper's API has none short of a 5 MB players file): gsis -> [name, pos, team]
  mapped = set().union(*[set(v.values()) for v in out.values()])
  latest = None
  for s_ in reversed(seasons):
    r = c.get("rosters", s_, None, stale=False)
    if r is not None:
      r = r.dropna(subset=["gsis_id"]).sort_values("week").drop_duplicates("gsis_id", keep="last")
      latest = r if latest is None else pd.concat([latest, r[~r.gsis_id.isin(latest.gsis_id)]])
  out["names"] = {g: [n, ps, t] for g, n, ps, t in zip(latest.gsis_id, latest.full_name, latest.position, latest.team) if g in mapped}
  (site / "data").mkdir(parents=True, exist_ok=True)
  path = site / "data" / "fantasy_ids.json"
  path.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
  print(f"[fantasy-ids] " + ", ".join(f"{p} {len(out[p])}" for p in PLATFORMS) + f", names {len(out['names'])} ({path.stat().st_size // 1024} KB)", flush=True)


if __name__ == "__main__":
  main()
