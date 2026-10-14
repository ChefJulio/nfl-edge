"""Penalties for team and player pages: data/penalties/<season>.json (1999 on) + index.json.

Usage: python tools/penalties_build.py [--site=site] [--seasons=1999-2026]   (CI daily; finished seasons cached)
Regular season only (playoffs are kept apart site-wide). One flagged play = one penalty: nflverse play-by-play
records the main penalty of each play (penalty_team, penalty_player_id, penalty_type, penalty_yards; yards 0 when
declined or offset). ~3,600 a season; ~92% name a player (the rest are team calls: delay of game, too many men).
  teams:   {TEAM: {g, n, y, dn, dy, types: [[type, n, y]], players: [[gsis, n, y]]}}   dn / dy = drawn (opponents')
  players: {gsis: [team, n, y, [[type, n, y]]]}                  names: {gsis: name}   pos: {gsis: position that season}
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402

V = 2
FIRST = 1999
COLS = ["game_id", "play_id", "season_type", "posteam", "defteam", "penalty", "penalty_team", "penalty_player_id",
        "penalty_player_name", "penalty_type", "penalty_yards"]


def build(pbp: pd.DataFrame, season: int, full: dict, pos: dict) -> dict:
  p = pbp[(pbp.season_type == "REG")]
  games = pd.concat([p[["game_id", "posteam"]].rename(columns={"posteam": "t"}), p[["game_id", "defteam"]].rename(columns={"defteam": "t"})])
  games["t"] = games.t.replace(D.RELOCATED)
  gp = games.dropna().drop_duplicates().groupby("t").size()
  f = p[(p.penalty == 1) & p.penalty_team.notna()].drop_duplicates(["game_id", "play_id"]).copy()
  for c in ("posteam", "defteam", "penalty_team"):
    f[c] = f[c].replace(D.RELOCATED)
  f["y"] = pd.to_numeric(f.penalty_yards, errors="coerce").fillna(0).astype(int)
  f["ty"] = f.penalty_type.fillna("Other")
  f["opp"] = f.posteam.where(f.penalty_team != f.posteam, f.defteam)  # the team that drew it
  teams = {}
  for t, g in f.groupby("penalty_team"):
    d = f[f.opp == t]
    ty = g.groupby("ty").agg(n=("y", "size"), y=("y", "sum")).sort_values(["n", "y"], ascending=False).head(8)
    pl = g.dropna(subset=["penalty_player_id"]).groupby("penalty_player_id").agg(n=("y", "size"), y=("y", "sum"))
    pl = pl.sort_values(["n", "y"], ascending=False).head(6)
    teams[t] = {"g": int(gp.get(t, 0)), "n": len(g), "y": int(g.y.sum()), "dn": len(d), "dy": int(d.y.sum()),
                "types": [[k, int(r.n), int(r.y)] for k, r in ty.iterrows()],
                "players": [[k, int(r.n), int(r.y)] for k, r in pl.iterrows()]}
  players, names, poss = {}, {}, {}
  for pid, g in f.dropna(subset=["penalty_player_id"]).groupby("penalty_player_id"):
    ty = g.groupby("ty").agg(n=("y", "size"), y=("y", "sum")).sort_values(["n", "y"], ascending=False)
    players[pid] = [g.penalty_team.mode().iloc[0], len(g), int(g.y.sum()), [[k, int(r.n), int(r.y)] for k, r in ty.iterrows()]]
    nm = g.penalty_player_name.dropna()
    names[pid] = full.get(pid) or (nm.iloc[0] if len(nm) else pid)
    if pos.get(pid):
      poss[pid] = pos[pid]
  return {"v": V, "season": season, "teams": teams, "players": players, "names": names, "pos": poss}


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = Path(opt.get("site", "site"))
  import nflreadpy as nfl
  cfg = load_config()
  current = int(nfl.get_current_season())
  a, _, b = opt.get("seasons", f"{FIRST}-{current}").partition("-")
  out = site / "data" / "penalties"
  out.mkdir(parents=True, exist_ok=True)
  kept = ROOT / cfg["data"]["cache_dir"] / "penalties_site" / f"v{V}"
  kept.mkdir(parents=True, exist_ok=True)
  pl = nfl.load_players().select(["gsis_id", "display_name", "position"]).to_pandas()
  full = {g: n for g, n in zip(pl.gsis_id, pl.display_name) if isinstance(g, str) and isinstance(n, str)}
  pos_now = {g: p for g, p in zip(pl.gsis_id, pl.position) if isinstance(g, str) and isinstance(p, str)}
  for s in range(int(a), int(b or a) + 1):
    f, k = out / f"{s}.json", kept / f"{s}.json"
    if s < current and k.exists():  # finished seasons never change
      shutil.copyfile(k, f)
      continue
    try:
      pbp = nfl.load_pbp([s]).select(COLS).to_pandas()
    except Exception as e:
      print(f"[penalties] {s}: unavailable ({e})", flush=True)
      continue
    # position that season (seasonal roster), else his current one
    pos = dict(pos_now)
    try:
      # the specific spot (CB / SS / T / DT / ILB...) where listed; the roster's group (DB / OL / DL) otherwise
      ro = nfl.load_rosters([s]).select(["gsis_id", "position", "depth_chart_position"]).to_pandas().dropna(subset=["gsis_id"])
      spot = ro.depth_chart_position.where(ro.depth_chart_position.notna() & (ro.depth_chart_position != ""), ro.position)
      pos.update({g: v for g, v in zip(ro.gsis_id, spot) if isinstance(v, str)})
    except Exception:
      pass
    doc = build(pbp, s, full, pos)
    f.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    if s < current:
      shutil.copyfile(f, k)
    n = sum(t["n"] for t in doc["teams"].values())
    print(f"[penalties] {s}: {n} penalties, {len(doc['players'])} players", flush=True)
  seasons = sorted(int(p.stem) for p in out.glob("[0-9][0-9][0-9][0-9].json"))
  (out / "index.json").write_text(json.dumps({"seasons": seasons, "current": current}), encoding="utf-8")


if __name__ == "__main__":
  main()
