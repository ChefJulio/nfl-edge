"""Coaches data for the team pages' Coaches tile (owner 2026-10-26) -> data/coaches.json.

Per team: the head coach (nflverse schedules: his name game by game, so a mid-season firing shows the interim; ESPN:
photo and years in the league) with his records (this club, career, playoffs, favored / underdog, against the spread)
and his seasons here with the offense and defense ranks; the offensive, defensive and special teams coordinators
(Wikipedia: today's staff templates, data/history/coach_staff.json for every past season) with each one's jobs since
1999 and how his unit ranked in each season of them (offense / defense EPA per play, data/stats/teams_<season>.json);
this season's tendencies ranked across the league (neutral early-down pass rate, seconds per snap, no-huddle and
two-point rates, challenges won; play-by-play, the pbp_calc cache) and fourth-down decisions against our model
(data/calc/graded_<season>.json).

Usage: python tools/coaches_build.py [--site=site]   (CI: full builds, after stats_build and calc_grade)
A failed source leaves its part out; today's staffs fall back to the last site's file when Wikipedia is unreachable.
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import coaches as C  # noqa: E402
from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.standings import RELOCATED  # noqa: E402

V = 1
FIRST = 1999
ESPN_CODE = {"LAR": "LA", "WSH": "WAS"}
HIST = ROOT / "data" / "history" / "coach_staff.json"
# Who calls the plays (owner 2026-10-26): no feed has it, so a researched table (each entry sourced and dated) with the
# staff it was researched against; when a club's staff changes, its entry is flagged to recheck until someone (a Claude
# session) researches it again and updates the file.
CALLS = ROOT / "data" / "playcallers.json"


def play_callers(now: dict, cur_hc: dict) -> tuple[dict, list]:
  """team -> {off, def, as_of, stale}; and the teams whose staff changed since their entry was researched."""
  if not CALLS.exists(): return {}, []
  doc = json.loads(CALLS.read_text(encoding="utf-8"))
  out, stale = {}, []
  for t, e in (doc.get("teams") or {}).items():
    was = e.get("staff") or {}
    is_ = {"hc": cur_hc.get(t), "oc": now.get(t, {}).get("oc"), "dc": now.get(t, {}).get("dc")}
    changed = [f"{r} {was.get(r)} -> {is_[r]}" for r in ("hc", "oc", "dc") if was.get(r) != is_[r]]
    if changed: stale.append(f"{t}: {'; '.join(changed)}")
    out[t] = {"off": e.get("off"), "def": e.get("def"), "as_of": e.get("as_of") or doc.get("as_of"), "stale": bool(changed)}
  return out, stale


def get_json(url: str):
  with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": C.UA}), timeout=20) as r:
    return json.load(r)


def espn_heads(season: int) -> dict:
  """team -> {name, photo, exp} for the head coaches ESPN lists this season ({} on failure)."""
  out = {}
  try:
    ids = {str(t["team"]["id"]): ESPN_CODE.get(t["team"]["abbreviation"], t["team"]["abbreviation"])
           for t in get_json("https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams")["sports"][0]["leagues"][0]["teams"]}
    refs = get_json(f"https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/{season}/coaches?limit=100")["items"]
    for r in refs:
      c = get_json(r["$ref"].replace("http://", "https://"))
      tid = re.search(r"/teams/(\d+)", (c.get("team") or {}).get("$ref", ""))
      t = tid and ids.get(tid.group(1))
      if t:
        out[t] = {"name": f"{c.get('firstName', '')} {c.get('lastName', '')}".strip(),
                  "photo": (c.get("headshot") or {}).get("href"), "exp": c.get("experience")}
  except Exception as e:
    print(f"[coaches] ESPN head coaches unavailable: {e}", flush=True)
  return out


def units(site: Path, seasons) -> dict:
  """season -> team -> (offense EPA/play, defense EPA/play allowed, offense rank, defense rank); 1 = best."""
  out = {}
  for s in seasons:
    f = site / "data" / "stats" / f"teams_{s}.json"
    if not f.exists(): continue
    d = json.loads(f.read_text(encoding="utf-8")); ix = {c: i for i, c in enumerate(d["cols"])}
    rows = {t: (v[ix["o_epa"]] / max(1, v[ix["o_plays"]]), v[ix["d_epa"]] / max(1, v[ix["d_plays"]])) for t, v in d["teams"].items()}
    orank = {t: i + 1 for i, t in enumerate(sorted(rows, key=lambda t: -rows[t][0]))}
    drank = {t: i + 1 for i, t in enumerate(sorted(rows, key=lambda t: rows[t][1]))}
    out[s] = {t: (round(o, 3), round(dd, 3), orank[t], drank[t]) for t, (o, dd) in rows.items()}
  return out


def team_games(sched: pd.DataFrame) -> pd.DataFrame:
  """One row per team per finished game: season, type, team, coach, margin, line (team's side, + = favored)."""
  g = sched.dropna(subset=["result"]).copy()
  for c in ("home_team", "away_team"): g[c] = g[c].replace(RELOCATED)
  h = pd.DataFrame({"season": g.season, "week": g.week, "type": g.game_type, "team": g.home_team, "coach": g.home_coach,
                    "margin": g.result, "line": g.spread_line})
  a = pd.DataFrame({"season": g.season, "week": g.week, "type": g.game_type, "team": g.away_team, "coach": g.away_coach,
                    "margin": -g.result, "line": -g.spread_line})
  return pd.concat([h, a], ignore_index=True)


def wlt(m: pd.Series) -> list:
  return [int((m > 0).sum()), int((m < 0).sum()), int((m == 0).sum())]


def head_coach(G: pd.DataFrame, U: dict, team: str, name: str) -> dict:
  me = G[G.coach == name]
  here = me[me.team == team]
  reg = me[me.type == "REG"]
  lined = me.dropna(subset=["line"])
  seasons = []
  for s, x in here[here.type == "REG"].groupby("season"):
    u = U.get(int(s), {}).get(team)
    seasons.append([int(s), *wlt(x.margin), u[2] if u else None, u[3] if u else None])
  po = here[here.type != "REG"]
  stops = []  # every club he has head-coached, in order
  for t, x in me.groupby("team", sort=False):
    stops.append([t, int(x.season.min()), int(x.season.max()), *wlt(x[x.type == "REG"].margin)])
  stops.sort(key=lambda r: r[1])
  return {"name": name, "since": int(here.season.min()) if len(here) else None,
          "rec": {"here": wlt(here[here.type == "REG"].margin), "car": wlt(reg.margin),
                  "po": wlt(me[me.type != "REG"].margin)[:2], "po_here": wlt(po.margin)[:2],
                  "fav": wlt(lined[lined.line > 0].margin), "dog": wlt(lined[lined.line < 0].margin),
                  "ats": wlt(lined.margin - lined.line)},
          "seasons": seasons, "stops": stops}


def stints(staff: dict, U: dict) -> dict:
  """name -> [[role, team, from, to, [rank per season]]]: every job in the staff lists (consecutive seasons with one
  club in one role are one stint); the rank is his unit's (oc: offense, dc: defense, hc: [offense, defense])."""
  seen = {}
  for s in sorted(staff, key=int):
    for t, row in staff[s].items():
      for role, who in row.items():
        seen.setdefault(who, []).append((int(s), t, role))
  # a season page that lists no one in a role is a gap in the source, not a change: a run bridges it when nobody else
  # held the job in between (2026-10-26: Dave Toub, KC 2013 and 2016-26, KC's 2014-15 pages list no ST coordinator)
  held = {(int(s), t, role) for s in staff for t, row in staff[s].items() for role in row}
  out = {}
  for who, jobs in seen.items():
    jobs.sort(key=lambda j: (j[2], j[1], j[0]))
    runs = []
    for s, t, role in jobs:
      prev = runs[-1] if runs else None
      if prev and prev[0] == role and prev[1] == t and all((y, t, role) not in held for y in range(prev[3] + 1, s)): prev[3] = s
      else: runs.append([role, t, s, s])
    for r in runs:
      rk = []
      for s in range(r[2], r[3] + 1):
        u = U.get(s, {}).get(r[1])
        rk.append(None if not u else u[2] if r[0] == "oc" else u[3] if r[0] == "dc" else [u[2], u[3]] if r[0] == "hc" else None)
      r.append(rk)
    out[who] = sorted(runs, key=lambda r: r[2])
  return out


def city(team: str, season: int) -> str:
  nm = C.name_in(team, season) or C.NAME[team]
  return nm.rsplit(" ", 1)[0]


def tendencies(pbp: pd.DataFrame, season: int) -> dict:
  """team -> {metric: [value, rank]} this season (rank 1 = most / fastest / best)."""
  p = pbp[(pbp.season_type == "REG") & pbp.posteam.notna()].copy()
  for c in ("posteam", "defteam"): p[c] = p[c].replace(RELOCATED)
  desc = p.desc.fillna("")
  real = p.play_type.isin(["pass", "run"]) & (p.qb_kneel != 1) & (p.qb_spike != 1)
  neutral = real & p.wp.between(0.2, 0.8) & (p.qtr <= 3)
  dropback = (p.play_type == "pass") | desc.str.contains(r"\bscrambles\b", regex=True)
  m = {}
  ed = p[neutral & p.down.isin([1, 2])]
  m["pass_rate"] = dropback[ed.index].groupby(ed.posteam).mean()
  # seconds from one snap to the next within a drive, neutral situations (the clock runs between them)
  q = p[real].sort_values(["game_id", "play_id"])
  nxt = q.groupby(["game_id", "drive"]).game_seconds_remaining.shift(-1)
  gap = (q.game_seconds_remaining - nxt).where(neutral[q.index])
  gap = gap[(gap > 0) & (gap <= 60)]
  m["pace"] = gap.groupby(q.posteam[gap.index]).median()
  m["no_huddle"] = desc[real].str.contains("No Huddle").groupby(p.posteam[real]).mean()
  tries = p[(p.two_point_attempt == 1) | p.extra_point_result.notna()]
  m["two_pt"] = (tries.two_point_attempt == 1).groupby(tries.posteam).mean()
  # challenges: "Carolina challenged ... REVERSED" / "Upheld"; the challenger is whichever side's city leads the phrase
  ch = p[desc.str.contains(" challenged ", regex=False)]
  who, won = [], []
  for _, r in ch.iterrows():
    c = [t for t in (r.posteam, r.defteam) if isinstance(t, str) and re.search(
      rf"{re.escape(city(t, season))}( {re.escape(C.NAME[t].rsplit(' ', 1)[1])})? challenged", r.desc)]
    if len(c) == 1 or (len(c) == 2 and (c := [t for t in c if f"{C.NAME[t]} challenged" in r.desc])):
      who.append(c[0]); won.append("REVERSED" in r.desc.upper().split("CHALLENGED", 1)[1][:160])
  chal = pd.DataFrame({"team": who, "won": won})
  out = {}
  higher_better = {"pass_rate": True, "pace": False, "no_huddle": True, "two_pt": True}
  for k, ser in m.items():
    ser = ser.dropna()
    order = ser.sort_values(ascending=not higher_better[k])
    for i, (t, v) in enumerate(order.items(), 1):
      out.setdefault(t, {})[k] = [round(float(v), 3), i]
  for t, x in chal.groupby("team"):
    out.setdefault(t, {})["chal"] = [int(len(x)), int(x.won.sum())]
  return out


def fourth(site: Path, season: int) -> dict:
  """team -> {n, go, model_go, agree, bad, wp_lost, aggr_rk}: this season's graded fourth downs (calc_grade.mjs)."""
  f = site / "data" / "calc" / f"graded_{season}.json"
  if not f.exists(): return {}
  rows = pd.DataFrame(json.loads(f.read_text(encoding="utf-8"))["rows"])
  if rows.empty: return {}
  rows["t"] = rows.t.replace(RELOCATED)
  out = {}
  for t, x in rows.groupby("t"):
    out[t] = {"n": int(len(x)), "go": int((x.c == "go").sum()), "model_go": int((x.b == "go").sum()),
              "agree": int((x.b == x.c).sum()), "bad": int((x.x >= 0.03).sum()), "wp_lost": round(float(x.x.sum()), 3)}
  # aggressiveness against the model: went for it minus the model's go calls, per decision; 1 = boldest
  ag = {t: (v["go"] - v["model_go"]) / max(1, v["n"]) for t, v in out.items()}
  for i, t in enumerate(sorted(ag, key=lambda t: -ag[t]), 1):
    out[t]["aggr"] = round(ag[t], 3); out[t]["aggr_rk"] = i
  return out


def main() -> None:
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = Path(opt.get("site", "site"))
  cfg = load_config()
  import nflreadpy as nfl
  from nfledge import winprob as W
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  current = int(nfl.get_current_season())
  sched = cache.get("schedules", "since1999", lambda: nfl.load_schedules(list(range(FIRST, current + 1))),
                    stale=cache.age_hours("schedules", "since1999") > 6)
  pbp = cache.get("pbp_calc", current, lambda: nfl.load_pbp([current]).select(W.PBP_COLS),
                  stale=cache.age_hours("pbp_calc", current) > 6)
  cache.save_meta()
  out_f = site / "data" / "coaches.json"
  last = json.loads(out_f.read_text(encoding="utf-8")) if out_f.exists() else {}

  # staffs: every past season (committed), today's from the templates (else the last site's)
  hist = json.loads(HIST.read_text(encoding="utf-8"))["staff"] if HIST.exists() else {}
  now = {}
  for t in C.NAME:
    try: now[t] = C.current(t)
    except Exception as e:
      print(f"[coaches] {t} staff unavailable ({e}); keeping the last one", flush=True)
      now[t] = ((last.get("teams") or {}).get(t) or {}).get("staff") or {}
  staff = dict(hist); staff[str(current)] = now

  U = units(site, range(FIRST, current + 1))
  G = team_games(sched)
  heads = espn_heads(current)
  # nflverse's coach column runs a season behind for the current one (2026-10-26: Gannon still Arizona's head coach,
  # though he is Green Bay's DC; "Klint Kubliak"): this season's games go to ESPN's head coach, else Wikipedia's.
  # Limitation: a mid-season change credits the whole season to today's coach (no per-game source names him).
  cur_hc = {t: (heads.get(t) or {}).get("name") or now[t].get("hc") for t in C.NAME}
  m = G.season == current
  G.loc[m, "coach"] = G.loc[m, "team"].map(cur_hc).fillna(G.loc[m, "coach"])
  T = tendencies(pbp, current) if pbp is not None else {}
  F4 = fourth(site, current)
  ST = stints(staff, U)
  PC, stale = play_callers(now, cur_hc)
  if stale:  # a GitHub Actions warning on the run, and the tile says "to recheck" instead of a name
    print(f"::warning::Play-callers to recheck (staff changed since data/playcallers.json was researched): {' | '.join(stale)}", flush=True)
  teams = {}
  for t in C.NAME:
    # the head coach today (ESPN, else Wikipedia); his record from every game nflverse credits to him (+ this season's)
    nm = cur_hc[t]
    hc = head_coach(G, U, t, nm) if nm else {"name": None}
    e = heads.get(t) or {}
    if e.get("name") == nm: hc.update(photo=e.get("photo"), exp=e.get("exp"))
    co = {}
    for r in ("oc", "dc", "st"):
      who = now[t].get(r)
      if not who: continue
      runs = ST.get(who, [])
      here = [x for x in runs if x[0] == r and x[1] == t and x[3] == current]
      co[r] = {"name": who, "since": here[0][2] if here else current, "jobs": runs}
    teams[t] = {"hc": hc, **co, "staff": now[t], "hc_jobs": ST.get(now[t].get("hc") or "", []),
                "tend": T.get(t, {}), "fourth": F4.get(t, {}), "calls": PC.get(t)}
  doc = {"v": V, "season": current, "built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
         "src": {"staff": "Wikipedia staff templates and season articles (CC BY-SA)", "head": "nflverse schedules, ESPN"},
         "teams": teams}
  out_f.parent.mkdir(parents=True, exist_ok=True)
  out_f.write_text(json.dumps(doc, separators=(",", ":"), allow_nan=False), encoding="utf-8")
  print(f"[coaches] wrote {out_f} ({out_f.stat().st_size // 1024} KB); play-callers: {len(PC)} teams, {len(stale)} to recheck", flush=True)


if __name__ == "__main__":
  main()
