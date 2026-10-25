"""Standings data for the Teams > Standings tab: data/standings/<season>.json for every season of the current
alignment (2002 on) plus data/standings/index.json (season list). Pure data; the page renders it (standings.js).

Usage: python tools/standings_build.py [--site=site] [--seasons=2002-2026]   (CI runs it after run.py)
Past seasons never change, so they are written only when missing (or when the file's shape version is older).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.standings import RELOCATED, League, Rec, playoff_teams_per_conf  # noqa: E402

V = 1  # shape version of the JSON; bump when fields change so old files are rebuilt
FIRST = 2002


def season_doc(sched, teams, season: int) -> dict:
  L = League.from_schedule(sched, teams, season)
  played = L.games
  n_playoff = playoff_teams_per_conf(season)
  div_order = {d: L.order_with_reasons(v, "division") for d, v in
               ((d, [t for t, x in L.div.items() if x == d]) for d in sorted(set(L.div.values())))}
  conf_order = {c: L.conference_order(c) for c in ("AFC", "NFC")}
  reg = sched[(sched.season == season) & (sched.game_type == "REG")]
  info = teams.assign(team_abbr=teams.team_abbr.replace(RELOCATED)).drop_duplicates("team_abbr").set_index("team_abbr")
  rows = []
  for d, order in div_order.items():
    for rank, (t, why) in enumerate(order, 1):
      g = played[played.team == t].sort_values("week")
      rec = L.overall(t)
      home_weeks = set(reg[reg.home_team.replace(RELOCATED) == t].week)  # home / away split
      hr, ar = Rec(), Rec()
      for wk, res in zip(g.week, g.res):
        (hr if wk in home_weeks else ar).add(res)
      streak = ""
      if len(g):
        last = g.res.iloc[-1]
        n = 0
        for x in reversed(list(g.res)):
          if x != last:
            break
          n += 1
        streak = f"{'W' if last == 1 else 'L' if last == 0 else 'T'}{n}"
      conf_pos = [x for x, _ in conf_order[L.conf[t]]].index(t) + 1
      cw = dict(conf_order[L.conf[t]])
      fmt = lambda r: f"{int(r.w)}-{int(r.l)}" + (f"-{int(r.t)}" if r.t else "")
      rows.append({
        "team": t, "name": info.at[t, "team_name"] if t in info.index else t, "nick": info.at[t, "team_nick"] if t in info.index else t,
        "logo": info.at[t, "team_logo_espn"] if t in info.index else "", "color": info.at[t, "team_color"] if t in info.index else "",
        "conf": L.conf[t], "div": d, "div_rank": rank, "div_why": why,
        "seed": conf_pos if conf_pos <= n_playoff else None, "conf_rank": conf_pos, "conf_why": cw.get(t, ""),
        "w": int(rec.w), "l": int(rec.l), "t": int(rec.t), "pct": round(rec.pct, 3),
        "pf": int(g.pf.sum()), "pa": int(g.pa.sum()), "diff": int((g.pf - g.pa).sum()),
        "div_rec": fmt(L.rec(t, L.div_teams(t))), "conf_rec": fmt(L.rec(t, L.conf_teams(t))),
        "home": fmt(hr), "away": fmt(ar), "streak": streak,
        "last5": "".join("W" if x == 1 else "L" if x == 0 else "T" for x in list(g.res)[-5:]),
      })
  final = reg.home_score.notna()
  return {"v": V, "season": season, "playoff_teams": n_playoff,
          "through_week": int(reg[final].week.max()) if final.any() else 0, "complete": bool(final.all()),
          # the games counted (tools/news_watch.py builds when ESPN has a final that isn't here)
          "finals": sorted(reg[final].game_id.astype(str)),
          "teams": rows}


ESPN_SB = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?seasontype=2&week={w}&dates={s}"
ESPN_CODE = {"LAR": "LA", "WSH": "WAS"}


def espn_fill(sched: pd.DataFrame, season: int) -> pd.DataFrame:
  """(owner 2026-10-25: "standings page not updating after the game results?") nflverse's schedule file posts a result
  some time after the game, and the cached copy is refreshed every 6 hours: this season's games already played with
  no result take ESPN's final score (its scoreboard for that week). Only finals; a game in progress stays open."""
  import urllib.request
  reg = (sched.season == season) & (sched.game_type == "REG")
  todo = sched[reg & sched.home_score.isna() & (pd.to_datetime(sched.gameday) <= pd.Timestamp.now().normalize())]
  if todo.empty:
    return sched
  sched = sched.copy()
  n = 0
  for w in sorted(todo.week.unique()):
    try:
      with urllib.request.urlopen(urllib.request.Request(ESPN_SB.format(w=int(w), s=season), headers={"User-Agent": "nfl-edge/1.0"}),
                                  timeout=30) as r:
        evs = json.load(r).get("events", [])
    except Exception as e:  # nflverse's results stand
      print(f"[standings] ESPN week {w} unavailable ({e})", flush=True)
      continue
    for ev in evs:
      c = ev["competitions"][0]
      if not c.get("status", ev.get("status", {})).get("type", {}).get("completed"):
        continue
      side = {x["homeAway"]: x for x in c["competitors"]}
      code = lambda x: ESPN_CODE.get(x["team"]["abbreviation"], x["team"]["abbreviation"])  # noqa: E731
      m = reg & (sched.week == w) & (sched.home_team == code(side["home"])) & (sched.away_team == code(side["away"])) & sched.home_score.isna()
      if m.any():
        sched.loc[m, ["home_score", "away_score"]] = [float(side["home"]["score"]), float(side["away"]["score"])]
        n += 1
  if n:
    print(f"[standings] {n} final(s) from ESPN ahead of nflverse's schedule file", flush=True)
  return sched


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = Path(opt.get("site", "site"))
  cfg = load_config()
  import nflreadpy as nfl
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  current = int(nfl.get_current_season())
  sched = cache.get("schedules", "since1999", lambda: nfl.load_schedules(list(range(1999, current + 1))),
                    stale=cache.age_hours("schedules", "since1999") > 6)
  teams = cache.get("teams", "all", lambda: nfl.load_teams(), stale=False)
  cache.save_meta()
  sched = espn_fill(sched, current)
  a, _, b = opt.get("seasons", f"{FIRST}-{current}").partition("-")
  out = site / "data" / "standings"
  out.mkdir(parents=True, exist_ok=True)
  seasons = [s for s in range(int(a), int(b or a) + 1) if (sched.season == s).any()]
  n = 0
  for s in seasons:
    f = out / f"{s}.json"
    if f.exists() and s != current:
      try:
        if json.loads(f.read_text(encoding="utf-8")).get("v") == V:
          continue
      except ValueError:
        pass
    f.write_text(json.dumps(season_doc(sched, teams, s), separators=(",", ":")), encoding="utf-8")
    n += 1
  (out / "index.json").write_text(json.dumps({"v": V, "seasons": seasons, "current": current}), encoding="utf-8")
  print(f"[standings] wrote {n} season file(s) to {out}", flush=True)


if __name__ == "__main__":
  main()
