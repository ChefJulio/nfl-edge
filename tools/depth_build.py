"""Depth charts for the team page's Depth tab: data/depth/latest.json (every team, latest snapshot).

Usage: python tools/depth_build.py [--site=site]   (CI runs it daily)
Source: nflverse load_depth_charts (2025 on: daily snapshots of ESPN's depth charts, every slot of the team's
offense, base defense and special teams, with depth order). Teams also publish "unofficial" depth charts in their
weekly game notes, but only as PDFs in each club's own format, often stale by design; ESPN's are maintained daily.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402

V = 1
# offense in reading order (ESPN lists its slots WR, WR, LT, LG, C, RG, RT, WR, QB, TE, RB)
OFF_ORDER = ["QB", "RB", "FB", "WR", "TE", "LT", "LG", "C", "RG", "RT"]


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = Path(opt.get("site", "site"))
  import nflreadpy as nfl
  cfg = load_config()
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  season = int(nfl.get_current_season())
  raw = cache.get("depth", season, lambda: nfl.load_depth_charts([season]), stale=cache.age_hours("depth", season) > 12)
  cache.save_meta()
  if raw is None or raw.empty or "dt" not in raw.columns:
    print("[depth] no daily depth charts for", season)
    return
  d = raw[(raw.dt == raw.dt.max()) & raw.player_name.notna()].copy()  # some slots list no one (NaN name)
  d["team"] = D.team_name_fix(d.team)
  # players with a page on the site (a career log, tools/player_logs.py: offensive skill players); others link to ESPN
  pages = {f.stem for f in (site / "data" / "players").glob("*.json")}
  teams = {}
  for team, t in d.groupby("team"):
    groups, info = {}, {}
    for grp, g in t.groupby("pos_grp"):
      kind = "st" if grp == "Special Teams" else "def" if grp.endswith(" D") else "off"
      info[kind] = grp
      rows = []
      for (slot, abb), s in g.groupby(["pos_slot", "pos_abb"], sort=False):
        s = s.sort_values("pos_rank")
        rows.append((int(slot), abb, s.pos_name.iloc[0],
                     [[n, gid if isinstance(gid, str) and gid in pages else None, str(e) if isinstance(e, str) and e else None]
                      for n, gid, e in zip(s.player_name, s.gsis_id, s.espn_id)]))  # name, gsis (if he has a page), ESPN id
      if kind == "off":
        rows.sort(key=lambda r: (OFF_ORDER.index(r[1]) if r[1] in OFF_ORDER else 99, r[0]))
      else:
        rows.sort(key=lambda r: r[0])
      groups[kind] = [[abb, name, players] for _, abb, name, players in rows]
    teams[team] = {"formation": info.get("off", ""), "front": info.get("def", ""), **groups}
  out = site / "data" / "depth"
  out.mkdir(parents=True, exist_ok=True)
  (out / "latest.json").write_text(json.dumps({"v": V, "season": season, "asof": d.dt.max(), "teams": teams},
                                              separators=(",", ":"), allow_nan=False), encoding="utf-8")
  print(f"[depth] {len(teams)} teams as of {d.dt.max()}")


if __name__ == "__main__":
  main()
