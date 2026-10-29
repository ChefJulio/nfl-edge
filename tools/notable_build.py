"""Notable moves (owner 2026-10-29: "we don't really have a 'big news' section ... stuff like 'player graded 80+ out for
the season' or players of a certain grade getting traded"): data/notable.json, the league year's moves that change what
our numbers say, for Home's strip, Players > Moves' Notable filter and the player card's banner.

Usage: python tools/notable_build.py [--site=site]     (CI: full builds after the grades, and the news lane)

A move is notable when it is one of these and its player passes ANY of the ways in (thresholds backtested on 2024-26,
owner-approved 2026-10-29; scratchpad lists in the session, rules recorded in docs/INSIGHTS.md "Notable moves"):
  trade            OVR 75+ starter | first-round pick in his first 4 seasons, starting | market deal | a first-round
                   pick in the trade | a veteran QB to a new team on a starter's deal
  release          OVR 85+ starter | young first-rounder starting | market deal
  season-ending    OVR 85+ starter | young first-rounder starting | market deal; ESPN says season-ending (comment or a
                   return date past the regular season) with 4+ weeks of it left
  suspension       OVR 80+ starter
  signing (new team)  OVR 85+ starter | young first-rounder starting | market deal | veteran QB on a starter's deal
  extension / re-signing  market deal only
where OVR = the grade going into the move (this season's once he has 4 games, else last season's; displayed 50-99),
starter = half his unit's snaps or more over his last 4 games, market deal = the contract's cap share at least
MARKET of the top running deal at his position group (OverTheCap via nflverse), and a QB starter's deal = QB_START of
the top QB deal (every veteran QB who signed with a new team at that price 2018-26 started week 1 for it).

Sources: ESPN's transactions log (data/transactions/<season>.json, built just before), the contract table (a deal
first seen this run is a signing dated today: ESPN's log missed Prescott's, Tua's and Josh Allen's extensions), ESPN's
injury feed (data/espn_injuries/latest.json), the grades (data/grades/<season>.json) and the career logs
(data/players/<gsis>.json). The previous run's file (this site's, else the live one) keeps first-seen dates and the
contracts already seen.
"""
import json
import re
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402

V = 1
LIVE = "https://chefjulio.github.io/nfl-edge/data/notable.json"
TRADE_OVR, BIG_OVR, SUSP_OVR = 75, 85, 80
MARKET, QB_START = 0.75, 0.16
STARTER_SNAP, YOUNG_SEASONS, WEEKS_LEFT = 50, 3, 4
# position -> market group (contracts are compared within these)
GRP = {"QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE", "T": "OT", "OT": "OT", "LT": "OT", "RT": "OT",
       "G": "IOL", "OG": "IOL", "LG": "IOL", "RG": "IOL", "C": "IOL", "OL": "IOL", "DE": "EDGE", "OLB": "EDGE", "EDGE": "EDGE",
       "ED": "EDGE", "DT": "DT", "NT": "DT", "DL": "DT", "IDL": "DT", "LB": "LB", "ILB": "LB", "MLB": "LB", "CB": "CB",
       "DB": "CB", "S": "S", "SS": "S", "FS": "S", "SAF": "S"}
# nflverse's position labels as the site shows them
SHOW_POS = {"SAF": "S", "FS": "S", "SS": "S", "MLB": "LB", "ILB": "LB", "OLB": "LB", "NT": "DT", "OG": "G", "OT": "T"}
FIRST_RX = re.compile(r"first-round|1st-round|first round", re.I)
FUTURE_RX = re.compile(r"reserve/future|future contract", re.I)
SEASON_END = re.compile(r"(?:rest|remainder) of the (?:\d{4} )?(?:NFL )?season|ruled out for the (?:rest of the )?season|"
                        r"season-ending|out for the (?:rest of the |entire )?(?:\d{4} )?(?:NFL )?season|"
                        r"miss(?:ed|ing)? the (?:entire |rest of the )?(?:\d{4} )?(?:NFL )?season", re.I)
KIND = {"traded": "trade", "acquired": "trade", "released": "release", "waived": "release", "suspended": "susp",
        "signed": "signing", "re_signed": "extension", "extended": "extension", "claimed": "signing"}


def ovr(pct) -> int:
  return 50 + round(pct * 49 / 99)


class Ctx:
  def __init__(self, site: Path):
    import nflreadpy as nfl
    from player_logs import load_contracts
    self.site, self.data = site, site / "data"
    cfg = load_config()
    cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
    self.cur = int(nfl.get_current_season())
    sch = cache.get("schedules", "since1999", lambda: nfl.load_schedules(list(range(1999, self.cur + 1))), stale=False)
    sch = sch[(sch.game_type == "REG") & (sch.season >= self.cur - 1)].copy()
    sch["gd"] = sch.gameday.astype(str).str[:10]
    self.wk = sch.groupby(["season", "week"]).gd.agg(["min", "max"]).reset_index()
    self.start = sch.groupby("season").gd.min().to_dict()
    self.end = sch.groupby("season").gd.max().to_dict()
    cpath = cache.path("contracts", "all")
    old = cpath.exists() and "last_year" not in pd.read_parquet(cpath).columns
    self.contracts = cache.get("contracts", "all", lambda: load_contracts(nfl), stale=old or cache.age_hours("contracts", "all") > 24)
    players = cache.get("players", "all", lambda: nfl.load_players(), stale=cache.age_hours("players", "all") > 24 * 7)
    pl = players.dropna(subset=["gsis_id"]).drop_duplicates("gsis_id").set_index("gsis_id")
    self.pos = pl.position.to_dict()
    self.pname = pl.display_name.to_dict()
    cache.save_meta()
    c = self.contracts.copy()
    c["grp"] = c.gsis_id.map(self.pos).map(GRP)
    self.c = c
    self._top, self._logs, self._grades, self._rank = {}, {}, {}, {}
    ids = json.loads((self.data / "espn_ids.json").read_text(encoding="utf-8")) if (self.data / "espn_ids.json").exists() else {}
    self.from_espn = {str(e): g for g, e in ids.items()}

  # ---- calendar ----
  def season_of(self, d: str) -> int:  # the league year a date falls in (March on)
    y = int(d[:4])
    return y if d[5:7] >= "03" else y - 1

  def week_of(self, s: int, d: str) -> int:  # 0 before week 1, 19 after the regular season
    if d < self.start.get(s, "9"):
      return 0
    x = self.wk[(self.wk.season == s) & (self.wk["max"] >= d)]
    return int(x.week.min()) if len(x) else 19

  def weeks_left(self, s: int, d: str) -> int:
    last = int(self.wk[self.wk.season == s].week.max()) if (self.wk.season == s).any() else 18
    w = self.week_of(s, d)
    return last - w + 1 if w else last

  # ---- player facts ----
  def log(self, pid: str):
    if pid not in self._logs:
      f = self.data / "players" / f"{pid}.json"
      self._logs[pid] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    return self._logs[pid]

  def grades(self, s: int) -> dict:
    if s not in self._grades:
      f = self.data / "grades" / f"{s}.json"
      self._grades[s] = json.loads(f.read_text(encoding="utf-8")).get("players", {}) if f.exists() else {}
    return self._grades[s]

  def games_before(self, pid: str, d: str) -> list:
    """His regular-season games before date d, in order (this league year's and earlier)."""
    L = self.log(pid) or {}
    s = self.season_of(d)
    w = self.week_of(s, d)
    out = []
    for S in sorted(L.get("seasons", []), key=lambda S: S["s"]):
      out += [g for g in S.get("g", []) if S["s"] < s or (S["s"] == s and g["w"] < w)]
    return out

  def grade_at(self, pid: str, d: str):
    """(displayed OVR, position, rank, qualified count) going into date d: this season's grade once he has 4 games
    in it, else last season's; unqualified grades count (a short season is often the injury itself)."""
    s = self.season_of(d)
    L = self.log(pid) or {}
    this = next((S for S in L.get("seasons", []) if S["s"] == s), None)
    n_now = len([g for g in (this or {}).get("g", []) if g["w"] < self.week_of(s, d)])
    for gs in ((s, s - 1) if n_now >= 4 else (s - 1, s - 2)):
      rec = self.grades(gs).get(pid)
      if rec:
        return ovr(rec[0]), rec[1], self.rank(gs, rec[1], rec[0]), self.n_pos(gs, rec[1])
    return None

  def rank(self, s, pos, pct):
    key = (s, pos)
    if key not in self._rank:
      self._rank[key] = sorted((r[0] for r in self.grades(s).values() if r[1] == pos and not (len(r) > 9 and r[9])), reverse=True)
    return 1 + sum(1 for x in self._rank[key] if x > pct)

  def n_pos(self, s, pos):
    self.rank(s, pos, 0)
    return len(self._rank[(s, pos)])

  def snap_at(self, pid: str, d: str):
    sn = [g["sn"] for g in self.games_before(pid, d)[-4:] if g.get("sn") is not None]
    return round(sum(sn) / len(sn)) if sn else None

  def last_team(self, pid: str, d: str):
    g = self.games_before(pid, d)
    return D.RELOCATED.get(g[-1]["t"], g[-1]["t"]) if g else None

  def next_team(self, pid: str, d: str, old: str | None):
    """Where he went: the team of his first game (or missed game) after date d, else his current team (the career
    log's), when it isn't the one he left."""
    L = self.log(pid) or {}
    s = self.season_of(d)
    w = self.week_of(s, d)
    for S in sorted(L.get("seasons", []), key=lambda S: S["s"]):
      for g in sorted(S.get("g", []) + [m for m in S.get("m", []) if m.get("t")], key=lambda g: g["w"]):
        if (S["s"], g["w"]) >= (s, w):
          t = D.RELOCATED.get(g["t"], g["t"])
          if t != old:
            return t
    t = L.get("team")
    return D.RELOCATED.get(t, t) if t and t != old else None

  def draft(self, pid: str) -> dict:
    return ((self.log(pid) or {}).get("bio") or {}).get("draft") or {}

  def young_first(self, pid: str, d: str) -> bool:
    dr = self.draft(pid)
    return dr.get("r") == 1 and self.season_of(d) - int(dr.get("y") or 0) <= YOUNG_SEASONS

  # ---- contracts ----
  def top(self, grp: str, y: int) -> float:
    if (grp, y) not in self._top:
      c = self.c
      pool = c[(c.grp == grp) & c.year_signed.between(y - 5, y) & (c.last_year >= y)]
      self._top[(grp, y)] = float(pool.apy_cap_pct.max()) if len(pool) and pool.apy_cap_pct.notna().any() else 0.0
    return self._top[(grp, y)]

  def deal(self, pid: str, y: int, signed_in: int | None = None):
    """His deal running in league year y (signed_in: the one signed that year), with its share of his position's top."""
    c = self.c[(self.c.gsis_id == pid) & self.c.apy_cap_pct.notna()]
    c = c[c.year_signed == signed_in] if signed_in else c[(c.year_signed <= y) & (c.last_year >= y)]
    if not len(c):
      return None
    r = c.sort_values(["year_signed", "apy"]).iloc[-1]
    grp = r.grp if isinstance(r.grp, str) else None
    top = self.top(grp, y) if grp else 0
    return {"apy": round(float(r.apy), 2), "cap": round(float(r.apy_cap_pct), 3), "grp": grp,
            "of_top": round(float(r.apy_cap_pct) / top, 2) if top else None, "yr": int(r.year_signed)}


def facts(cx: Ctx, pid: str, d: str, deal_signed_in: int | None = None) -> dict:
  g = cx.grade_at(pid, d)
  s = cx.season_of(d)
  dl = cx.deal(pid, s, deal_signed_in)
  dr = cx.draft(pid)
  f = {"pid": pid, "pos": SHOW_POS.get(cx.pos.get(pid), cx.pos.get(pid)), "snap": cx.snap_at(pid, d), "from": cx.last_team(pid, d)}
  if g:
    f.update(ovr=g[0], gpos=g[1], rk=g[2], of=g[3])
  if dl:
    f["deal"] = dl
  if dr.get("r"):
    f["draft"] = [dr.get("y"), dr.get("r"), dr.get("o") or dr.get("p")]
  f["young1st"] = cx.young_first(pid, d)
  return f


def reasons(f: dict, bar: int, *, pedigree=True, market=True, qb=False, new_team=False) -> list:
  """Why this player clears the bar (empty: he doesn't)."""
  out = []
  starter = (f.get("snap") or 0) >= STARTER_SNAP
  if f.get("ovr") is not None and f["ovr"] >= bar and starter:
    out.append(f"{f['ovr']} OVR starter")
  if pedigree and f.get("young1st") and starter:
    out.append("first-round pick, starting")
  dl = f.get("deal") or {}
  if market and (dl.get("of_top") or 0) >= MARKET:
    out.append("top-of-market deal")
  if qb and new_team and f.get("pos") == "QB" and f.get("from") and dl.get("grp") == "QB" and (dl.get("of_top") or 0) >= QB_START:
    out.append("a starter's deal at QB")
  return out


def trade_groups(rows: list) -> list:
  """Trade rows -> trades: rows naming the same player within 3 days are one trade (each team logs its side)."""
  parent = list(range(len(rows)))
  def find(i):
    while parent[i] != i:
      parent[i] = parent[parent[i]]
      i = parent[i]
    return i
  by_text = {}
  for i, r in enumerate(rows):
    by_text.setdefault(r["text"], []).append(i)
  for ids in by_text.values():
    for j in ids[1:]:
      parent[find(j)] = find(ids[0])
  for i, a in enumerate(rows):
    for j in range(i + 1, len(rows)):
      b = rows[j]
      if a["pid"] == b["pid"] and abs((date.fromisoformat(a["date"]) - date.fromisoformat(b["date"])).days) <= 3:
        parent[find(j)] = find(i)
  groups = {}
  for i in range(len(rows)):
    groups.setdefault(find(i), []).append(rows[i])
  return list(groups.values())


def previous(site: Path) -> dict:
  f = site / "data" / "notable.json"
  try:
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else json.load(urllib.request.urlopen(LIVE, timeout=20))
  except Exception:
    return {}


def build(site: Path) -> dict:
  cx = Ctx(site)
  today = datetime.now(timezone.utc).astimezone().date().isoformat()
  ly = cx.season_of(today)
  prev = previous(site)
  items = []

  # ESPN's transactions log, this league year
  tf = cx.data / "transactions" / f"{ly}.json"
  rows = []
  if tf.exists():
    doc = json.loads(tf.read_text(encoding="utf-8"))
    ci = {k: doc["cols"].index(k) for k in doc["cols"]}
    for r in doc["rows"]:
      k = KIND.get(r[ci["type"]])
      pid = r[ci["pid"]]
      if k and pid and cx.season_of(r[ci["date"]]) == ly:
        rows.append({"date": r[ci["date"]], "team": D.RELOCATED.get(r[ci["team"]], r[ci["team"]]), "kind": k, "pid": pid,
                     "name": r[ci["name"]], "text": r[ci["text"]]})

  # trades: one item per trade, notable when any player in it is, or a first-round pick moves
  for grp in trade_groups([r for r in rows if r["kind"] == "trade"]):
    d0 = min(r["date"] for r in grp)
    with1st = any(FIRST_RX.search(r["text"]) for r in grp)
    seen, people = set(), []
    for r in sorted(grp, key=lambda r: r["date"]):
      if r["pid"] in seen:
        continue
      seen.add(r["pid"])
      f = facts(cx, r["pid"], d0)
      f["name"] = r["name"]
      # his new team: his first game after it (or his roster now), else the other team in the trade
      f["to"] = cx.next_team(r["pid"], d0, f.get("from")) or next((x["team"] for x in grp if x["team"] != f.get("from")), None)
      f["why"] = reasons(f, TRADE_OVR, qb=True, new_team=True)
      people.append(f)
    why = (["a first-round pick in the trade"] if with1st else [])
    if why or any(p["why"] for p in people):
      people.sort(key=lambda p: (not p["why"], -(p.get("ovr") or 0)))
      items.append({"id": f"trade|{d0}|{people[0]['pid']}", "kind": "trade", "date": d0, "players": people, "why": why,
                    "text": max((r["text"] for r in grp), key=len)})

  # releases, suspensions, signings from the log
  done = {}  # (kind, pid) -> the date it was listed: one move logged twice (Terrion Arnold, released 06-29 and 07-06)
  for r in sorted(rows, key=lambda r: r["date"]):
    k = r["kind"]
    last = done.get((k, r["pid"]))
    if k == "trade" or (last and (date.fromisoformat(r["date"]) - date.fromisoformat(last)).days <= 30):
      continue
    if k in ("signing", "extension") and FUTURE_RX.search(r["text"]):
      continue
    f = facts(cx, r["pid"], r["date"], deal_signed_in=ly if k in ("signing", "extension") else None)
    f["name"] = r["name"]
    if k == "signing" and not f.get("from"):
      continue  # a rookie or a first NFL deal: the draft's news, not this feed's
    if k == "signing" and f.get("from") == r["team"]:
      k = "extension"
    elif k == "extension" and f.get("from") and f["from"] != r["team"]:
      k = "signing"  # ESPN's "re-signed" for a player whose last games were elsewhere
    if k == "release":
      why = reasons(f, BIG_OVR)
    elif k == "susp":
      why = reasons(f, SUSP_OVR, pedigree=False, market=False)
    elif k == "signing":
      f["to"] = r["team"]
      why = reasons(f, BIG_OVR, qb=True, new_team=True)
    else:
      why = ["top-of-market deal"] if ((f.get("deal") or {}).get("of_top") or 0) >= MARKET else []
    if why:
      done[(k, r["pid"])] = r["date"]
      f["why"] = why
      items.append({"id": f"{k}|{r['date']}|{r['pid']}", "kind": k, "date": r["date"], "team": r["team"], "players": [f],
                    "why": [], "text": r["text"]})

  # new contracts the log didn't carry: first seen this run = signed today
  key = lambda x: f"{x.gsis_id}|{int(x.year_signed)}|{round(float(x.apy), 2)}"  # noqa: E731
  fresh = cx.c[(cx.c.year_signed >= ly) & cx.c.apy_cap_pct.notna() & cx.c.gsis_id.notna()]
  now_keys = {key(x): x for x in fresh.itertuples()}
  seen_before = set(prev.get("contracts_seen", [])) if prev.get("contracts_seen") is not None else None
  logged = {(i["players"][0]["pid"]) for i in items if i["kind"] in ("signing", "extension")} | {r["pid"] for r in rows if r["kind"] in ("signing", "extension")}
  if seen_before is not None:
    for kk, x in now_keys.items():
      if kk in seen_before or x.gsis_id in logged:
        continue
      f = facts(cx, x.gsis_id, today, deal_signed_in=int(x.year_signed))
      f["name"] = cx.pname.get(x.gsis_id, x.gsis_id)
      k = "extension"  # the table has no team: a new team's deal shows up in ESPN's log as a signing
      why = ["top-of-market deal"] if ((f.get("deal") or {}).get("of_top") or 0) >= MARKET else []
      if why:
        f["why"] = why
        items.append({"id": f"{k}|{today}|{x.gsis_id}", "kind": k, "date": today, "players": [f], "why": [], "src": "contracts"})

  # season-ending injuries: ESPN says so (its note, or a return date after the regular season), 4+ weeks left
  inj = cx.data / "espn_injuries" / "latest.json"
  if inj.exists() and ly in cx.end:
    for r in json.loads(inj.read_text(encoding="utf-8")).get("rows", []):
      pid = cx.from_espn.get(str(r.get("espn_id")))
      if not pid:
        continue
      out = SEASON_END.search(r.get("comment") or "") or (r.get("return_date") or "") > cx.end[ly]
      d = (r.get("updated") or today)[:10]
      if not out or cx.weeks_left(ly, d) < WEEKS_LEFT or cx.season_of(d) != ly:
        continue
      f = facts(cx, pid, d)
      f["name"] = r.get("name") or cx.pname.get(pid, pid)
      why = reasons(f, BIG_OVR)
      if why:
        f["why"] = why
        f["injury"] = " ".join(x for x in (r.get("side") if r.get("side") not in (None, "Not Specified") else None, r.get("type")) if x)
        items.append({"id": f"season|{pid}|{ly}", "kind": "season", "date": d, "players": [f], "why": [],
                      "text": r.get("comment") or ""})

  # keep what an earlier run found (first-seen dates; a season-ending note ESPN has since replaced), this league year
  ids = {i["id"] for i in items}
  for i in prev.get("items", []):
    if i.get("id") not in ids and cx.season_of(i.get("date", "1900-01-01")) == ly:
      items.append(i)
  # one season-ending item per player (the first date it was seen)
  first = {}
  for i in sorted(items, key=lambda i: i["date"]):
    if i["kind"] == "season":
      first.setdefault(i["players"][0]["pid"], i)
  items = [i for i in items if i["kind"] != "season" or first.get(i["players"][0]["pid"]) is i]
  items.sort(key=lambda i: (i["date"], i["id"]), reverse=True)
  return {"v": V, "built": today, "league_year": ly,
          "rules": {"trade_ovr": TRADE_OVR, "big_ovr": BIG_OVR, "susp_ovr": SUSP_OVR, "market": MARKET, "qb_start": QB_START,
                    "starter_snap": STARTER_SNAP, "weeks_left": WEEKS_LEFT},
          "items": items, "contracts_seen": sorted(now_keys)}


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = Path(opt.get("site", "site"))
  doc = build(site)
  out = site / "data" / "notable.json"
  out.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
  ks = {}
  for i in doc["items"]:
    ks[i["kind"]] = ks.get(i["kind"], 0) + 1
  print(f"[notable] {len(doc['items'])} notable moves this league year {ks}; {len(doc['contracts_seen'])} contracts seen", flush=True)


if __name__ == "__main__":
  main()
