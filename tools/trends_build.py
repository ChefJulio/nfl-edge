"""Play-level data for Players > Trends (the query builder, assets/trends.js): data/plays/<season>.json + index.json.

Usage: python tools/trends_build.py [--site=site] [--seasons=1999-2026]   (CI runs it daily; finished seasons cached)
Every run and pass play since 1999 (regular season and playoffs; no kneels, spikes, two-point tries or no-plays),
columnar and compact: teams, games and players are indexed lists, play fields are small integers (EPA x 100).
type: 0 designed run, 1 dropback (pass or sack), 2 QB scramble (a dropback that became a run: counts as a rush,
as in nflverse's rushing stats). One season is ~35k plays, ~0.5 MB gzipped, loaded only when a query needs it.
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402

V = 1
FIRST = 1999
COLS = ["game_id", "season", "week", "season_type", "posteam", "defteam", "home_team", "play_type", "qtr", "down", "ydstogo",
        "yardline_100", "score_differential", "game_seconds_remaining", "half_seconds_remaining", "yards_gained", "epa",
        "success", "touchdown", "first_down", "shotgun", "no_huddle", "sack", "interception", "complete_pass", "pass_attempt",
        "qb_scramble", "air_yards", "yards_after_catch", "pass_location", "run_location", "run_gap", "rusher_player_id",
        "rusher_player_name", "passer_player_id", "passer_player_name", "receiver_player_id", "receiver_player_name",
        "qb_kneel", "qb_spike", "two_point_attempt", "fumble_lost"]
LOC = {"left": 1, "middle": 2, "right": 3}
GAP = {"end": 1, "tackle": 2, "guard": 3}


def build(pbp: pd.DataFrame, season: int) -> dict:
  p = pbp[pbp.play_type.isin(["run", "pass"]) & (pbp.qb_kneel != 1) & (pbp.qb_spike != 1) & (pbp.two_point_attempt != 1)
          & pbp.posteam.notna() & pbp.defteam.notna()].copy()
  for c in ("posteam", "defteam", "home_team"):
    p[c] = p[c].replace(D.RELOCATED)
  teams = sorted(set(p.posteam) | set(p.defteam))
  ti = {t: i for i, t in enumerate(teams)}
  games = p.drop_duplicates("game_id")[["game_id", "week", "season_type", "home_team"]]
  gi = {g: i for i, g in enumerate(games.game_id)}
  # players: every rusher / passer / receiver once, by gsis id
  ids = {}
  for idc, nmc in (("rusher_player_id", "rusher_player_name"), ("passer_player_id", "passer_player_name"),
                   ("receiver_player_id", "receiver_player_name")):
    for g, n in zip(p[idc], p[nmc]):
      if isinstance(g, str) and g not in ids:
        ids[g] = n if isinstance(n, str) else g
  plist = list(ids.items())
  pi = {g: i for i, (g, _) in enumerate(plist)}
  num = lambda c, d=0: pd.to_numeric(p[c], errors="coerce").fillna(d)  # noqa: E731
  scr = num("qb_scramble").astype(int)
  typ = np.where(p.play_type == "run", 0, np.where(scr == 1, 2, 1))
  pid = lambda c: [pi.get(g, -1) if isinstance(g, str) else -1 for g in p[c]]  # noqa: E731
  cols = {
    "g": [gi[g] for g in p.game_id], "o": [ti[t] for t in p.posteam], "d": [ti[t] for t in p.defteam], "ty": typ.tolist(),
    "q": num("qtr").astype(int).tolist(), "dn": num("down").astype(int).tolist(), "tg": num("ydstogo").astype(int).tolist(),
    "yl": num("yardline_100", 50).astype(int).tolist(), "sd": num("score_differential").astype(int).tolist(),
    "hs": (num("half_seconds_remaining", 1800) // 10).astype(int).tolist(),  # tens of seconds left in the half
    "y": num("yards_gained").astype(int).tolist(), "e": (num("epa") * 100).round().astype(int).tolist(),
    "s": num("success").astype(int).tolist(), "td": num("touchdown").astype(int).tolist(), "fd": num("first_down").astype(int).tolist(),
    "sg": num("shotgun").astype(int).tolist(), "nh": num("no_huddle").astype(int).tolist(), "sk": num("sack").astype(int).tolist(),
    "in": num("interception").astype(int).tolist(), "c": num("complete_pass").astype(int).tolist(), "pa": num("pass_attempt").astype(int).tolist(),
    "ay": num("air_yards", -99).astype(int).tolist(), "yc": num("yards_after_catch", -99).astype(int).tolist(),
    "pl": [LOC.get(x, 0) for x in p.pass_location], "rl": [LOC.get(x, 0) for x in p.run_location], "gp": [GAP.get(x, 0) for x in p.run_gap],
    "fl": num("fumble_lost").astype(int).tolist(),
    "ru": pid("rusher_player_id"), "pp": pid("passer_player_id"), "re": pid("receiver_player_id"),
  }
  return {"v": V, "season": season, "teams": teams,
          "games": [[g, int(w), 1 if st == "POST" else 0, ti.get(D.RELOCATED.get(h, h), -1)] for g, w, st, h in games.itertuples(index=False)],
          "players": plist, "n": len(p), "cols": cols}


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = Path(opt.get("site", "site"))
  import nflreadpy as nfl
  cfg = load_config()
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  current = int(nfl.get_current_season())
  a, _, b = opt.get("seasons", f"{FIRST}-{current}").partition("-")
  out = site / "data" / "plays"
  out.mkdir(parents=True, exist_ok=True)
  kept = ROOT / cfg["data"]["cache_dir"] / "plays_site" / f"v{V}"
  kept.mkdir(parents=True, exist_ok=True)
  for s in range(int(a), int(b or a) + 1):
    f, k = out / f"{s}.json", kept / f"{s}.json"
    if s < current and k.exists():  # finished seasons never change (playoffs included once they're over)
      shutil.copyfile(k, f)
      continue
    try:
      pbp = nfl.load_pbp([s]).select(COLS).to_pandas()
    except Exception as e:
      print(f"[plays] {s}: unavailable ({e})", flush=True)
      continue
    doc = build(pbp, s)
    f.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    if s < current:
      shutil.copyfile(f, k)
    print(f"[plays] {s}: {doc['n']} plays, {len(doc['players'])} players, {f.stat().st_size / 1e6:.1f} MB", flush=True)
  seasons = sorted(int(p.stem) for p in out.glob("[0-9][0-9][0-9][0-9].json"))
  (out / "index.json").write_text(json.dumps({"v": V, "seasons": seasons, "current": current}), encoding="utf-8")


if __name__ == "__main__":
  main()
