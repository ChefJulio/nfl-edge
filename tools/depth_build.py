"""Depth charts for the team page's Depth tab: data/depth/<season>/<TEAM>.json (2001 on, week by week) + index.json.

Usage: python tools/depth_build.py [--site=site] [--seasons=2001-2026]   (CI runs it daily)
Source: nflverse load_depth_charts. Through 2024: one chart per team-week (labels vary by team and year, cleaned
here). 2025 on: daily snapshots of ESPN's charts; a week's chart = the last snapshot before its first game (the
latest one for the current week). Teams' own "unofficial" depth charts exist only as PDFs in their game notes.
Each player carries that week's official tag: the injury report's game status (O / D / Q, 2009 on) or a reserve
list from that week's roster (IR, PUP, NFI, SUSP, HOLD = did not report). Players with a page on the site (career
log) keep their gsis id; everyone else links to ESPN by ESPN id.
"""
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.report import ROSTER_TEAM  # noqa: E402

V = 7  # 7: each player's last 3 healthy games (skips games missed or left hurt); 6: recency-weighted window, games missed hurt skipped; 5: INA counts as on the team, injured starters kept (flag); 4: + depth by playing time ("u"); 3: pages
FIRST = 2001
FRANCHISE = {"OAK": "LV", "SD": "LAC", "STL": "LA", "LAR": "LA"}  # relocated clubs -> today's code (team pages)
KIND = {"Offense": "off", "Defense": "def", "Special Teams": "st"}
# slot order per unit (older charts use many label variants); unknown labels go last
ORDER = {
  "off": "QB RB HB FB WR WR1 WR2 LWR RWR TE LTE RTE LT LOT LG C OC RG RT ROT".split(),
  "def": ("LDE LE DE EDGE RUSH LEO JACK LDT DT DL UT NT N RDT RDE RE LOLB OLB SAM SLB LILB ILB MLB MIKE RILB WLB WILL "
          "WIL ROLB LB LCB CB NCB NB NKL NICK RCB DB SS FS S").split(),
  "st": "K PK KO P H LS KR KOR PR".split(),
}
ROSTER_TAG = {"R01": "IR", "R48": "IR", "R04": "PUP", "R05": "NFI", "R40": "SUSP", "R03": "HOLD"}
GAME_TAG = {"Out": "O", "Doubtful": "D", "Questionable": "Q"}


def label(slot, pos) -> str:
  s = str(slot or "").strip().upper()
  return s if re.fullmatch(r"[A-Z]{1,5}\d?", s) else str(pos or "").strip().upper()


def weekly_old(raw: pd.DataFrame) -> pd.DataFrame:
  """<= 2024 format -> rows (team, week, kind, abb, label, name, gsis_id, rank, order, slot)."""
  d = raw[raw.formation.isin(KIND) & raw.week.notna() & raw.full_name.notna()].copy()
  d["kind"] = d.formation.map(KIND)
  d["abb"] = [label(a, b) for a, b in zip(d.depth_position, d.position)]
  d["rank"] = pd.to_numeric(d.depth_team, errors="coerce").fillna(9).astype(int)
  d["order"] = [ORDER[k].index(a) if a in ORDER[k] else 99 for k, a in zip(d.kind, d.abb)]
  d = d.rename(columns={"club_code": "team", "full_name": "name"})
  d["week"] = d.week.astype(int)
  return d.assign(slot=0, label=d.abb)[["team", "week", "kind", "abb", "label", "name", "gsis_id", "rank", "order", "slot"]]


def weekly_espn(raw: pd.DataFrame, sched: pd.DataFrame, season: int) -> tuple[pd.DataFrame, dict]:
  """2025+ daily snapshots -> one per week (the last before its first game; the newest for the current week)."""
  dts = sorted(pd.to_datetime(raw.dt.unique(), utc=True))
  now = pd.Timestamp.now(tz="UTC")
  out, groups = [], {}
  for wk, g in sched[sched.season == season].groupby("week"):
    first = pd.to_datetime(g.gameday).min()
    if pd.isna(first) or first.tz_localize("UTC") - pd.Timedelta(days=6) > now:
      continue  # weeks more than a few days out: no chart yet
    before = [t for t in dts if t < first.tz_localize("UTC") + pd.Timedelta(days=1)]
    snap = (before or dts)[-1].strftime("%Y-%m-%dT%H:%M:%SZ")
    w = raw[(raw.dt == snap) & raw.player_name.notna()].copy()
    w["week"] = int(wk)
    out.append(w)
    for team, t in w.groupby("team"):
      groups[(team, int(wk))] = {("st" if x == "Special Teams" else "def" if str(x).endswith(" D") else "off"): x for x in t.pos_grp.unique()}
  if not out:
    return pd.DataFrame(), {}
  d = pd.concat(out)
  d["kind"] = ["st" if x == "Special Teams" else "def" if str(x).endswith(" D") else "off" for x in d.pos_grp]
  # offense in reading order (ESPN's slots run WR, WR, LT, LG, C, RG, RT, WR, QB, TE, RB); defense / ST as listed
  d["order"] = [ORDER["off"].index(a) if k == "off" and a in ORDER["off"] else (0 if k != "off" else 99) for k, a in zip(d.kind, d.pos_abb)]
  d = d.rename(columns={"player_name": "name", "pos_abb": "abb", "pos_rank": "rank", "pos_slot": "slot", "pos_name": "label"})
  return d[["team", "week", "kind", "abb", "label", "name", "gsis_id", "rank", "order", "slot"]], groups

# ---------------------------------------------------------------------------------------------------------------
# Depth by playing time (the tab's default from a team's 2nd game on). Tested 2025-26 (scratch/depth_accuracy.py,
# depth_week1.py): a chart's starters = the game's top snap-getters at the position 88% of the time this way vs 76%
# for ESPN's listed chart; in week 1 ESPN's preseason chart wins (83% vs 71% from last season's usage), so week 1
# keeps the listed chart.
GROUP = {"QB": "QB", "RB": "RB", "FB": "RB", "HB": "RB", "WR": "WR", "TE": "TE", **{p: "OL" for p in "T OT G OG C OL".split()},
         **{p: "DL" for p in "DE DT NT DL".split()}, **{p: "LB" for p in "LB ILB OLB MLB".split()}, "CB": "CB",
         **{p: "S" for p in "S SS FS SAF DB".split()}}
GROUPS = ["QB", "RB", "WR", "TE", "OL", "DL", "LB", "CB", "S"]
DEFAULT_N = {"QB": 1, "RB": 1, "WR": 3, "TE": 1, "OL": 5, "DL": 4, "LB": 3, "CB": 2, "S": 2}  # only if a week has no listed chart
WINDOW = 3  # games
# Window weights, newest game first, and games a player missed while hurt (on that week's injury report or a reserve
# list, 0 snaps) leave his average instead of counting 0. Pre-registered test (tools/depth_window_eval.py, 2019-2026,
# 27,780 team-game cells): per-starter accuracy 81.7% (plain 3-game average) -> 83.6%, +2.0 pts [+1.8, +2.1], better
# at every position group; starters back from an injury absence 73.6% -> 82.0%.
RECENCY = (0.5, 0.3, 0.2)
# Owner design (2026-10-14, Justin Jefferson): each player's last 3 HEALTHY games that season, reaching back as far as
# needed: a game he missed hurt (0 snaps, listed / reserve that week) or LEFT hurt (under half his max share of his
# previous 3 played games, and listed / reserve the next team week) doesn't count. Tested in tools/depth_window_eval.py.
LEFT_HURT = 0.5


def injury_games(A: pd.DataFrame, hurt_set: set) -> pd.DataFrame:
  """players x weeks: True where the game was injury-affected (missed hurt, or left hurt)."""
  weeks = list(A.columns)
  V = A.to_numpy()
  bad = np.zeros(V.shape, dtype=bool)
  for r, g in enumerate(A.index):
    seen = []
    for j, w in enumerate(weeks):
      v = V[r, j]
      if v == 0:
        bad[r, j] = (g, int(w)) in hurt_set
        continue
      ref = max(seen[-3:]) if seen else None
      nxt = weeks[j + 1] if j + 1 < len(weeks) else None
      if ref and v < LEFT_HURT * ref and nxt is not None and (g, int(nxt)) in hurt_set:
        bad[r, j] = True
      else:
        seen.append(v)
  return pd.DataFrame(bad, index=A.index, columns=weeks)


INJURED_ROLE = 0.15  # an injured player with at least this healthy-game snap share stays listed (tagged)


def usage_weeks(season: int, sn: pd.DataFrame, ros, out: set, reserve: set, listed: pd.DataFrame, pos_of: dict,
                hurt_set: set | None = None) -> dict:
  """(team, week) -> [[group, n starters, [[gsis, name, avg snap %], ...]], ...] for every listed week where the team
  has already played this season. A player's share = his last 3 healthy games that season (injury_games), newest
  weighted most (RECENCY); a game missed for any other reason counts 0. Left out: players not on the team's roster that week (latest roster
  week for weeks not out yet), ruled Out on that week's report, or on a reserve list. An Out / reserve player who
  would have been a starter by playing time is kept at the end of his group, flagged (an injured starter shouldn't
  vanish: owner 2026-10-14, Jordan Addison), and so is an Out / reserve player with a real role (a healthy-game share
  of INJURED_ROLE or more: owner 2026-10-15, Jordan Mason, RB2 at 45% before IR). Roster = ACT, INA or RES: inactive
  for a game or on a reserve list (IR, PUP...) is still on the team (the ACT-only check dropped Addison after one
  missed game; ACT / INA dropped every IR player before the injured-player rule could see him)."""
  out_map = {}
  if sn is None or sn.empty:
    return out_map
  ros_by = {}
  if ros is not None and len(ros):
    r = ros[ros.status.isin(["ACT", "INA", "RES"])]
    for (team, wk), g in r.groupby(["team", "week"]):
      ros_by[(team, int(wk))] = set(g.gsis_id)
  starters_n = {}
  for (team, wk), g in listed.groupby(["team", "week"]):
    first = g.sort_values("rank").drop_duplicates(["kind", "slot", "abb"])
    first = first[first.kind != "st"]
    if "slot" in first and (first.slot == 0).all():  # older charts: every depth-1 player counts
      first = g[(g["rank"] == 1) & (g.kind != "st")]
    cnt = pd.Series([GROUP.get(pos_of.get(x)) for x in first.gsis_id]).value_counts()
    starters_n[(team, int(wk))] = {k: int(v) for k, v in cnt.items() if k}
  for team, ts in sn.groupby("team"):
    played = sorted(ts.week.unique())
    A = ts.pivot_table(index="gsis_id", columns="week", values="pct", aggfunc="max").reindex(columns=played).fillna(0.0)
    bad = injury_games(A, hurt_set or set())
    for wk in sorted(listed[listed.team == team].week.unique()):
      prior = [w for w in played if w < wk][-WINDOW:]
      if not prior:
        continue  # the team's first game: the listed chart is better (week-1 test above)
      win = ts[ts.week < wk]  # candidates: anyone who played for the team this season (healthy games reach back)
      rweeks = [w for (t, w) in ros_by if t == team and w <= wk]
      on = ros_by.get((team, max(rweeks))) if rweeks else None
      on_team = lambda g: on is None or g in on  # noqa: E731
      # a week whose roster isn't out yet keeps the latest roster's reserve lists (IR doesn't lapse by itself)
      rwk = int(wk) if (team, int(wk)) in ros_by else (max(rweeks) if rweeks else int(wk))
      hurt = lambda g: (g, int(wk)) in out or (g, int(wk)) in reserve or (g, rwk) in reserve  # noqa: E731
      win = win[win.gsis_id.map(on_team)]
      n = starters_n.get((team, int(wk)), {})
      rows = []
      for grp in GROUPS:
        gw = win[win.grp == grp]
        if gw.empty:
          continue
        k = n.get(grp) or DEFAULT_N[grp]
        # his last 3 healthy games, newest first, weighted RECENCY
        before = [w for w in played if w < wk][::-1]
        def healthy(g):
          vals = [A.at[g, w] for w in before if not bad.at[g, w]][:len(RECENCY)]
          if not vals:
            return 0.0
          wt = np.array(RECENCY[:len(vals)])
          return float(np.dot(vals, wt) / wt.sum())
        every = pd.Series({g: healthy(g) for g in gw.gsis_id.unique()}).sort_values(ascending=False)
        is_hurt = every.index.map(hurt).to_numpy().astype(bool)
        share = every[~is_hurt]
        share = share[share >= 0.01].head(6)
        # injured starters: would have been among the group's k starters by playing time
        cut = every.iloc[min(k, len(every)) - 1] if len(every) else 1.0
        inj = every[is_hurt & ((every >= cut) | (every >= INJURED_ROLE)).to_numpy() & (every >= 0.01).to_numpy()]
        names = gw.drop_duplicates("gsis_id").set_index("gsis_id").player
        rows.append([grp, k, [[g, names.get(g, g), int(round(100 * v)), 0] for g, v in share.items()]
                     + [[g, names.get(g, g), int(round(100 * v)), 1] for g, v in inj.items()]])
      out_map[(team, int(wk))] = rows
  return out_map


def season_snaps(cache, nfl, season: int, pfr: pd.Series, live: bool) -> pd.DataFrame | None:
  if season < 2012:
    return None
  sn = cache.get("snaps", season, lambda: nfl.load_snap_counts([season]), stale=live and cache.age_hours("snaps", season) > 6)
  if sn is None or sn.empty:
    return None
  sn = sn.copy()
  sn["gsis_id"] = sn.pfr_player_id.map(pfr)
  sn["team"] = sn.team.replace(FRANCHISE)
  sn["grp"] = sn.position.map(GROUP)
  sn["pct"] = sn[["offense_pct", "defense_pct"]].max(axis=1).fillna(0)
  return sn.dropna(subset=["gsis_id", "grp"])


# The player directory for the site's searches (owner 2026-10-21: a search finds a player "whether they have a
# projection this week or not"): everyone on a current roster at a fantasy position, on the active roster, a reserve
# list or the practice squad. Each team's latest published roster week (teams' rosters post on different days).
DIR_POS = ("QB", "RB", "FB", "WR", "TE", "K")
DIR_STATUS = {"ACT": "", "DEV": "PS"}  # PS = practice squad; RES = a reserve list (its ROSTER_TAG, else "RES")


def roster_directory(site: Path, cache, nfl, current: int, espn_of: dict):
  """<site>/data/roster.json: {"v", "season", "cols": [pid, name, pos, team, tag, espn], "rows"} (tag: "" active,
  "PS", "IR", "PUP", "NFI", "SUSP", "HOLD" or "RES"). Released, traded or retired rows are left out."""
  ros = cache.get("rosters", current, lambda: nfl.load_rosters_weekly([current]), stale=cache.age_hours("rosters", current) > 24)
  if ros is None or not len(ros):
    return
  ros = ros.dropna(subset=["gsis_id"]).copy()
  ros["team"] = ros.team.replace({**FRANCHISE, **ROSTER_TEAM})
  ros = ros[ros.week == ros.groupby("team").week.transform("max")]
  ros = ros[ros.position.isin(DIR_POS) & ros.status.isin(set(DIR_STATUS) | {"RES"})].drop_duplicates("gsis_id", keep="last")
  rows = []
  for r in ros.sort_values(["team", "position", "full_name"]).itertuples(index=False):
    tag = DIR_STATUS.get(r.status, ROSTER_TAG.get(r.status_description_abbr, "RES"))
    espn = espn_of.get(r.gsis_id) or (str(int(r.espn_id)) if pd.notna(r.espn_id) else None)
    rows.append([r.gsis_id, r.full_name, "RB" if r.position == "FB" else r.position, r.team, tag, espn])
  doc = {"v": 1, "season": current, "cols": ["pid", "name", "pos", "team", "tag", "espn"], "rows": rows}
  (site / "data" / "roster.json").write_text(json.dumps(doc, separators=(",", ":"), allow_nan=False), encoding="utf-8")
  print(f"[depth] roster directory: {len(rows)} players", flush=True)


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = Path(opt.get("site", "site"))
  import nflreadpy as nfl
  cfg = load_config()
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  current = int(nfl.get_current_season())
  a, _, b = opt.get("seasons", f"{FIRST}-{current}").partition("-")
  sched = cache.get("schedules", "since1999", lambda: nfl.load_schedules(list(range(1999, current + 1))),
                    stale=cache.age_hours("schedules", "since1999") > 6)
  players = cache.get("players", "all", lambda: nfl.load_players(), stale=cache.age_hours("players", "all") > 24 * 7)
  espn_of = {g: str(e) for g, e in zip(players.gsis_id, players.espn_id) if isinstance(g, str) and pd.notna(e) and str(e)}
  pages = {f.stem for f in (site / "data" / "players").glob("*.json")}
  pfr = players.dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates("pfr_id").set_index("pfr_id").gsis_id
  pos_of = players.dropna(subset=["gsis_id"]).drop_duplicates("gsis_id").set_index("gsis_id").position.to_dict()
  # the live week: ESPN's injury list (daily) rules players out before the official report
  live_out = set()
  espn_inj = site / "data" / "espn_injuries" / "latest.json"
  if espn_inj.exists():
    gsis_of = {str(e).replace(".0", ""): g for g, e in zip(players.gsis_id, players.espn_id) if isinstance(g, str) and pd.notna(e)}
    live_out = {gsis_of.get(str(r["espn_id"])) for r in json.loads(espn_inj.read_text(encoding="utf-8"))["rows"]
                if r.get("status") in ("Out", "Injured Reserve", "Suspension")} - {None}
  out_root = site / "data" / "depth"
  for season in range(int(a), int(b or a) + 1):
    live = season == current
    # finished seasons never change: built once into the cache (keyed by the file format), copied after that
    kept = ROOT / cfg["data"]["cache_dir"] / "depth_site" / f"v{V}" / str(season)
    if season < current - 1 and kept.is_dir():
      shutil.copytree(kept, out_root / str(season), dirs_exist_ok=True)
      continue
    raw = cache.get("depth", season, lambda: nfl.load_depth_charts([season]),
                    stale=live and cache.age_hours("depth", season) > 12)
    if raw is None or raw.empty:
      continue
    d, groups = weekly_espn(raw, sched, season) if "dt" in raw.columns else (weekly_old(raw), {})
    if d.empty:
      continue
    d["team"] = d.team.replace(FRANCHISE)
    # that week's official tags: reserve lists from the weekly roster, game status from the injury report
    tags, ros = {}, None
    if season >= 2002:
      ros = cache.get("rosters", season, lambda: nfl.load_rosters_weekly([season]),
                      stale=live and cache.age_hours("rosters", season) > 24)
      if ros is not None and len(ros):
        r = ros[ros.status_description_abbr.isin(ROSTER_TAG)]
        tags.update({(g, int(w)): ROSTER_TAG[c] for g, w, c in zip(r.gsis_id, r.week, r.status_description_abbr) if isinstance(g, str)})
        # weeks whose roster isn't published yet keep the latest roster's reserve lists (IR doesn't lapse by itself;
        # Jordan Mason showed as a healthy RB2 in week 6 while the latest roster, week 5, had him on IR)
        # per team: some teams' week-N rosters post before others'
        last = ros.groupby("team").week.max()
        for g, w, tm, c in zip(r.gsis_id, r.week, r.team, r.status_description_abbr):
          if isinstance(g, str) and int(w) == int(last.get(tm, w)):
            for nxt in range(int(w) + 1, int(d.week.max()) + 1):
              tags.setdefault((g, nxt), ROSTER_TAG[c])
    if season >= 2009:
      inj = cache.get("injuries", season, lambda: nfl.load_injuries([season]),
                      stale=live and cache.age_hours("injuries", season) > 6)
      if inj is not None and len(inj):
        i = inj[inj.report_status.isin(GAME_TAG)]
        for g, w, st in zip(i.gsis_id, i.week, i.report_status):
          tags.setdefault((g, int(w)), GAME_TAG[st])  # a reserve list outranks a game status
    # depth by playing time (2013 on: snap counts; nflverse has none for 2012)
    sn = season_snaps(cache, nfl, season, pfr, live)
    out_set = {k for k, v in tags.items() if v == "O"}
    reserve = {k for k, v in tags.items() if v in ("IR", "PUP", "NFI", "SUSP", "HOLD")}
    if live and live_out:
      last_wk = int(d.week.max())
      out_set |= {(g, last_wk) for g in live_out}
    rs = ros.assign(team=ros.team.replace({**FRANCHISE, **ROSTER_TEAM})) if ros is not None and len(ros) else None
    usage = usage_weeks(season, sn, rs, out_set, reserve, d, pos_of, set(tags)) if sn is not None else {}
    (out_root / str(season)).mkdir(parents=True, exist_ok=True)
    for team, t in d.groupby("team"):
      plist, pidx = [], {}

      def pi(name, gid):
        gid = gid if isinstance(gid, str) and gid else None
        k = gid or name
        if k not in pidx:
          pidx[k] = len(plist)
          plist.append([name, gid if gid in pages else None, espn_of.get(gid)])  # name, gsis (has a page), ESPN id
        return pidx[k]

      weeks = {}
      for wk, w in t.groupby("week"):
        wkd = {}
        for kind, k in w.groupby("kind"):
          rows = []
          for _, s in k.groupby(["order", "slot", "abb"], sort=True):
            s = s.sort_values("rank").drop_duplicates("name")
            rows.append([str(s.abb.iloc[0]), str(s.label.iloc[0]),
                         [[pi(n, g), int(rk), tags.get((g, int(wk)))] for n, g, rk in zip(s.name, s.gsis_id, s["rank"])]])
          wkd[kind] = rows
        u = usage.get((team, int(wk)))
        if u:  # [[group, n starters, [[player index, avg snap %, tag, injured starter 0/1], ...]], ...]
          wkd["u"] = [[grp, n, [[pi(name, g), pct, tags.get((g, int(wk))), x] for g, name, pct, x in pl]] for grp, n, pl in u]
        gr = groups.get((team, int(wk)), {})
        wkd["f"], wkd["d"] = gr.get("off", ""), gr.get("def", "")
        weeks[str(int(wk))] = wkd
      doc = {"v": V, "season": season, "team": team, "players": plist, "weeks": weeks}
      (out_root / str(season) / f"{team}.json").write_text(json.dumps(doc, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    if season < current - 1:
      shutil.copytree(out_root / str(season), kept, dirs_exist_ok=True)
    print(f"[depth] {season}: {d.team.nunique()} teams, weeks {d.week.min()}-{d.week.max()}", flush=True)
  cache.save_meta()
  seasons = sorted(int(p.name) for p in out_root.glob("[0-9][0-9][0-9][0-9]") if p.is_dir())
  (out_root / "index.json").write_text(json.dumps({"v": V, "seasons": seasons, "current": current}), encoding="utf-8")
  (out_root / "latest.json").unlink(missing_ok=True)  # the v1 single snapshot
  roster_directory(site, cache, nfl, current, espn_of)


if __name__ == "__main__":
  main()
