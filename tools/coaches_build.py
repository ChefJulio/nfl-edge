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
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

from nfledge import coaches as C  # noqa: E402
from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.standings import RELOCATED  # noqa: E402

V = 1
FIRST = 1999
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


def player_card(b: dict, name: str, pfr: dict, P: pd.DataFrame, last_season: dict) -> str | None:
  """His player card's id (gsis), if he played in the NFL in our data's years (1999 on): the page's PFR id ("OConKe00";
  some pages write "L/LeviAn00"), else one player of that exact name whose career overlaps the page's NFL years."""
  nfl_years = [y for p in b.get("played", []) if p[1] for y in (p[2], p[3] or p[2])]
  if not nfl_years:
    return None
  g = pfr.get(re.sub(r"^[A-Z]/", "", b.get("pfr") or ""))
  if not g:
    base = re.sub(r"\s+(Sr\.|Jr\.|II|III|IV)$", "", name).strip()
    c = P[(P.display_name == base) | (P.display_name == name)]
    if len(c):
      ro = pd.to_numeric(c.rookie_season, errors="coerce").fillna(0)
      la = pd.to_numeric(c.last_season, errors="coerce").fillna(9999)
      c = c[(ro <= max(nfl_years) + 1) & (la >= min(nfl_years) - 1)]
    g = c.gsis_id.iloc[0] if len(c) == 1 else None
  return g if g and (last_season.get(g) or 0) >= FIRST else None


BIO_DAYS = 14  # a coach's page is refetched after this many days (careers change between seasons, rarely within)
BIO_V = 2  # what C.bio reads (2: the photo); a cached page from an older version is refetched
SIDE = {"oc": 0, "dc": 1}


def bios(links: dict, cur_hc: dict, now: dict, last: dict, players: pd.DataFrame | None, U: dict, current: int) -> dict:
  """page title -> {pos, college, draft, pfr, pid, played, coached} for today's head coaches and coordinators
  (Wikipedia infoboxes, C.bio). Cached in the site's coaches.json (bio_cache) and refetched after BIO_DAYS. pid: his
  player card (PFR id -> gsis id, nflverse's players table). Each coaching row ends with his unit's rank per season
  where the job ran one (offensive / defensive coordinator: that side; head coach: [offense, defense]), from 1999."""
  today = datetime.now(timezone.utc).date()
  cached = last.get("bios") or {}
  P = players if players is not None and "pfr_id" in players else pd.DataFrame(columns=["pfr_id", "gsis_id", "display_name", "rookie_season", "last_season"])
  pfr = dict(zip(P.pfr_id, P.gsis_id))
  last_season = dict(zip(P.gsis_id, pd.to_numeric(P.last_season, errors="coerce")))
  head = {g: u for g, u in zip(P.gsis_id, P.headshot) if isinstance(u, str) and u.startswith("http")} if "headshot" in P else {}
  name_of = {links[t][r]: now[t].get(r) for t in links for r in links[t] if now.get(t, {}).get(r)}
  out = {}
  titles = sorted({v for t in links for v in links[t].values() if v})
  for title in titles:
    c = cached.get(title)
    fresh = c and c.get("bv") == BIO_V and (today - datetime.fromisoformat(c.get("f", "2000-01-01")).date()).days < BIO_DAYS
    if fresh:
      out[title] = c
      continue
    try:
      b = C.bio(C.raw(title))
    except Exception as e:
      print(f"[coaches] {title}: page unavailable ({e}); keeping the cached one", flush=True)
      out[title] = c
      continue
    b["f"], b["bv"] = today.isoformat(), BIO_V
    out[title] = b
  for title, b in out.items():
    if not b:
      continue
    # a team that reads like a job came from a mis-filed infobox line (Mike Rutenberg: "Player personnel intern")
    b["played"] = [p for p in b.get("played", []) if not re.search(r"\b(intern|coach|assistant|scout)\b", p[0], re.I)]
    b["pid"] = player_card(b, name_of.get(title) or title, pfr, P, last_season)
    # his playing-days headshot (nflverse), the last photo choice after ESPN's and his Wikipedia page's (2026-10-26:
    # half the coordinators have neither; ESPN keeps coach headshots for a dozen long-time head coaches only)
    b["pimg"] = (head.get(b["pid"]) or None) if b["pid"] else None
    for row in b.get("coached", []):
      del row[5:]  # ranks are recomputed each build (this season's move)
      team, code, a, z, role = row[:5]
      rl = (role or "").lower()
      kind = "oc" if "offensive coordinator" in rl else "dc" if "defensive coordinator" in rl else \
        "hc" if re.search(r"(^|[^t] )head coach", rl) and "assistant head coach" not in rl else None
      if not code or not kind or not a:
        continue
      rk = []
      for s in range(max(a, FIRST), (z or current) + 1):
        u = U.get(s, {}).get(code)
        rk.append(None if not u else [u[2], u[3]] if kind == "hc" else u[2 + SIDE[kind]])
      if any(x is not None for x in rk):
        row.append([kind, max(a, FIRST), rk])
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
  now, links, full = {}, {}, {}
  for t in C.NAME:
    try: now[t], links[t], full[t] = C.current_links(t)
    except Exception as e:
      print(f"[coaches] {t} staff unavailable ({e}); keeping the last one", flush=True)
      lt = (last.get("teams") or {}).get(t) or {}
      now[t], links[t], full[t] = lt.get("staff") or {}, lt.get("links") or {}, lt.get("all") or []
  staff = dict(hist); staff[str(current)] = now

  U = units(site, range(FIRST, current + 1))
  heads = C.espn_heads(current)
  # this season's games go to today's head coach (C.fix_current: nflverse's column runs a season behind)
  cur_hc = {t: (heads.get(t) or {}).get("name") or now[t].get("hc") for t in C.NAME}
  sched = pd.concat([sched[sched.season != current], C.fix_current(sched[sched.season == current], current, current, cur_hc, RELOCATED)])
  G = team_games(sched)
  T = tendencies(pbp, current) if pbp is not None else {}
  F4 = fourth(site, current)
  ST = stints(staff, U)
  PC, stale = play_callers(now, cur_hc)
  if stale:  # a GitHub Actions warning on the run, and the tile says "to recheck" instead of a name
    print(f"::warning::Play-callers to recheck (staff changed since data/playcallers.json was researched): {' | '.join(stale)}", flush=True)
  players = cache.get("players", "all", lambda: nfl.load_players(), stale=cache.age_hours("players", "all") > 24 * 7)
  B = bios(links, cur_hc, now, last, players, U, current)
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
    # each one's own page (coaching and playing careers), by the staff list's link; the head coach's when the list's
    # head coach is ESPN's
    hc_link = links[t].get("hc") if now[t].get("hc") == nm else None
    hc["bio"] = hc_link if B.get(hc_link) else None
    for r in co:
      co[r]["bio"] = links[t].get(r) if B.get(links[t].get(r)) else None
    teams[t] = {"hc": hc, **co, "staff": now[t], "links": links[t], "all": full[t],
                "unit": list(U.get(current, {}).get(t, [None] * 4)[2:]),  # this season's [offense, defense] rank
                "hc_jobs": ST.get(now[t].get("hc") or "", []),
                "tend": T.get(t, {}), "fourth": F4.get(t, {}), "calls": PC.get(t)}
  doc = {"v": V, "season": current, "built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
         "src": {"staff": "Wikipedia staff templates, season articles and coaches' pages (CC BY-SA)", "head": "nflverse schedules, ESPN"},
         "teams": teams, "bios": {k: v for k, v in B.items() if v}}  # by page title; teams name theirs (bio)
  out_f.parent.mkdir(parents=True, exist_ok=True)
  out_f.write_text(json.dumps(doc, separators=(",", ":"), allow_nan=False), encoding="utf-8")
  print(f"[coaches] wrote {out_f} ({out_f.stat().st_size // 1024} KB); play-callers: {len(PC)} teams, {len(stale)} to recheck", flush=True)


if __name__ == "__main__":
  main()
