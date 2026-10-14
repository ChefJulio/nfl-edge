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
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402

V = 2
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
    tags = {}
    if season >= 2002:
      ros = cache.get("rosters", season, lambda: nfl.load_rosters_weekly([season]),
                      stale=live and cache.age_hours("rosters", season) > 24)
      if ros is not None and len(ros):
        r = ros[ros.status_description_abbr.isin(ROSTER_TAG)]
        tags.update({(g, int(w)): ROSTER_TAG[c] for g, w, c in zip(r.gsis_id, r.week, r.status_description_abbr) if isinstance(g, str)})
    if season >= 2009:
      inj = cache.get("injuries", season, lambda: nfl.load_injuries([season]),
                      stale=live and cache.age_hours("injuries", season) > 6)
      if inj is not None and len(inj):
        i = inj[inj.report_status.isin(GAME_TAG)]
        for g, w, st in zip(i.gsis_id, i.week, i.report_status):
          tags.setdefault((g, int(w)), GAME_TAG[st])  # a reserve list outranks a game status
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


if __name__ == "__main__":
  main()
