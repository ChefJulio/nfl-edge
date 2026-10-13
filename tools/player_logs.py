"""Career game logs for the player card: one small JSON per player, <site>/data/players/<gsis_id>.json.

Usage: python tools/player_logs.py --site=site        (CI runs it after the pages are built)

Every regular-season game of the player's career (nflverse weekly stats, 1999 on; snap share from 2012 on), each
with our own pregame matchup rank and projection for that week where we have one: read from the published week
data files (<site>/index.json, <site>/<season>/week-NN.json; 2021 on, plus this season's upcoming weeks), so the
matchup color is what our model said BEFORE that game, not hindsight. Players: everyone on any published week page.
The page re-scores fantasy points with the viewer's scoring; the weekly position rank uses the site's scoring.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config, load_scoring  # noqa: E402
from nfledge.report import SCORE_KEYS  # noqa: E402

FIRST_SEASON = 1999
POS = ("QB", "RB", "WR", "TE")


def week_files(site: Path) -> list[Path]:
  return [p for p in [site / "index.json", *sorted(site.glob("[0-9][0-9][0-9][0-9]/week-[0-9][0-9].json"))] if p.exists()]


def our_weeks(site: Path) -> tuple[dict, dict, set]:
  """(season, week, gsis) -> our projection + matchup rank; (season, week, opp, pos) -> matchup rank; all gsis."""
  per_player, per_opp, everyone = {}, {}, set()
  for f in week_files(site):
    d = json.loads(f.read_text(encoding="utf-8"))
    s, w = int(d["season"]), int(d["week"])
    for pid, p in d["players"].items():
      everyone.add(pid)
      m = re.match(r"(\d+)", str(p.get("dvp") or ""))
      rank = int(m.group(1)) if m else None
      per_player[(s, w, pid)] = {"pj": round(float(p["proj"]), 1), "pjl": p["sc"]["pj"], "mr": rank}
      if rank and p.get("opp"):
        per_opp[(s, w, p["opp"], p["pos"])] = rank
  return per_player, per_opp, everyone


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = Path(opt.get("site", "site"))
  cfg, scoring = load_config(), load_scoring()
  data = D.load_all(cfg)
  import nflreadpy as nfl
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  first_loaded = min(data.seasons)
  old = [cache.get("stats", s, lambda: nfl.load_player_stats([s]).select(D.STAT_COLS), stale=False)
         for s in range(FIRST_SEASON, first_loaded)]
  old = [o[o.season_type == "REG"].assign(team=lambda x: x.team.replace(D.RELOCATED),
                                          opponent_team=lambda x: x.opponent_team.replace(D.RELOCATED))
         for o in old if o is not None and len(o)]
  st = pd.concat(old + [data.stats], ignore_index=True)
  st = st[st.position.isin(POS)].copy()
  for c in D.STAT_COLS[8:]:
    st[c] = pd.to_numeric(st[c], errors="coerce").fillna(0)
  st["fumble_lost"] = st.sack_fumbles_lost + st.rushing_fumbles_lost + st.receiving_fumbles_lost
  ren = {"passing_yards": "pass_yd", "passing_tds": "pass_td", "passing_interceptions": "interception",
         "rushing_yards": "rush_yd", "rushing_tds": "rush_td", "receptions": "reception", "receiving_yards": "rec_yd",
         "receiving_tds": "rec_td"}
  st = st.rename(columns=ren)
  w = {k: float(v) for k, v in scoring.weights.items()}
  st["fp"] = sum(st[k] * w.get(k, 0.0) for k in SCORE_KEYS) + np.where(st.position == "TE", st.reception * float(scoring.te_reception_bonus), 0)
  st["prk"] = st.groupby(["season", "week", "position"]).fp.rank(ascending=False, method="min").astype(int)
  # Snap share: loaded seasons already carry gsis ids; older ones map pfr -> gsis through nflverse's player table.
  players = cache.get("players", "all", lambda: nfl.load_players(), stale=cache.age_hours("players", "all") > 24 * 7)
  pfr = players.dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates("pfr_id").set_index("pfr_id").gsis_id
  sn_old = [cache.get("snaps", s, lambda: nfl.load_snap_counts([s]), stale=False) for s in range(2012, first_loaded)]
  sn_old = [x[x.game_type == "REG"].assign(gsis_id=lambda x: x.pfr_player_id.map(pfr)) for x in sn_old if x is not None and len(x)]
  sn = pd.concat(sn_old + [data.snaps], ignore_index=True).dropna(subset=["gsis_id"])
  snap = sn.groupby(["season", "week", "gsis_id"]).offense_pct.max()
  ours, opp_rank, everyone = our_weeks(site)
  # Home / away for every past game (the stats feed doesn't say): full schedule history.
  allsched = cache.get("schedules", "since1999", lambda: nfl.load_schedules(list(range(FIRST_SEASON, data.current_season + 1))),
                       stale=cache.age_hours("schedules", "since1999") > 12)
  allsched = allsched[allsched.game_type == "REG"]
  home_of = {}
  for g in allsched.itertuples():
    h, a = D.RELOCATED.get(g.home_team, g.home_team), D.RELOCATED.get(g.away_team, g.away_team)
    home_of[(int(g.season), int(g.week), h)] = 1
    home_of[(int(g.season), int(g.week), a)] = 0

  # Upcoming weeks of this season (and byes) from the schedule.
  sched = data.schedules[(data.schedules.season == data.current_season) & (data.schedules.game_type == "REG")]
  last_week = int(sched.week.max())
  team_games = {}
  for g in sched.itertuples():
    team_games[(g.home_team, g.week)] = (g.away_team, 1, g.home_score)
    team_games[(g.away_team, g.week)] = (g.home_team, 0, g.home_score)
  cur_team = (data.rosters[data.rosters.season == data.current_season].sort_values("week")
              .drop_duplicates("gsis_id", keep="last").set_index("gsis_id").team)

  out_dir = site / "data" / "players"
  out_dir.mkdir(parents=True, exist_ok=True)
  sts = st[st.player_id.isin(everyone)].sort_values(["season", "week"])
  by_player = {pid: g for pid, g in sts.groupby("player_id")}
  n = 0
  for pid in everyone:
    g = by_player.get(pid)
    pos = g.position.iloc[-1] if g is not None and len(g) else None
    seasons = {}
    if g is not None:
      for r in g.itertuples():
        o = ours.get((int(r.season), int(r.week), pid), {})
        mr = o.get("mr") or opp_rank.get((int(r.season), int(r.week), r.opponent_team, r.position))
        sp = snap.get((int(r.season), int(r.week), pid))
        game = {"w": int(r.week), "o": r.opponent_team, "t": r.team, "h": home_of.get((int(r.season), int(r.week), r.team), 1),
                "c": [round(float(getattr(r, k)), 1) for k in SCORE_KEYS],
                "x": [int(r.completions), int(r.attempts), int(r.carries), int(r.targets)], "rk": int(r.prk)}
        if sp is not None and not pd.isna(sp):
          game["sn"] = int(round(100 * float(sp)))
        if mr:
          game["mr"] = int(mr)
        if o.get("pj") is not None:
          game["pj"] = o["pj"]
          game["pjl"] = [round(float(v), 2) for v in o["pjl"]]
        seasons.setdefault(int(r.season), []).append(game)
    # This season's remaining schedule (with byes), our projection and matchup where a page exists.
    team = cur_team.get(pid)
    upcoming = []
    if team is not None:
      played = {x["w"] for x in seasons.get(data.current_season, [])}
      for wk in range(1, last_week + 1):
        if wk in played:
          continue
        tg = team_games.get((team, wk))
        if tg is None:
          upcoming.append({"w": wk, "bye": 1})
          continue
        if pd.notna(tg[2]):
          continue  # game already final (he didn't play, or stats not in yet)
        o = ours.get((data.current_season, wk, pid), {})
        e = {"w": wk, "o": tg[0], "h": tg[1]}
        mr = o.get("mr") or (opp_rank.get((data.current_season, wk, tg[0], pos)) if pos else None)
        if mr:
          e["mr"] = int(mr)
        if o.get("pj") is not None:
          e["pj"] = o["pj"]
          e["pjl"] = [round(float(v), 2) for v in o["pjl"]]
        upcoming.append(e)
    doc = {"pid": pid, "pos": pos, "keys": SCORE_KEYS, "cur": data.current_season, "team": team,
           "seasons": [{"s": s, "g": seasons[s]} for s in sorted(seasons, reverse=True)], "up": upcoming}
    (out_dir / f"{pid}.json").write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    n += 1
  size = sum(f.stat().st_size for f in out_dir.glob("*.json"))
  print(f"[logs] wrote {n} player game logs ({size / 1e6:.1f} MB) to {out_dir}", flush=True)


if __name__ == "__main__":
  main()
