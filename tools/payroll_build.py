"""Teams > team card > Payroll (owner 2026-10-27: "i want a payroll tile for teams"): every team's salary cap this season
and next from OverTheCap's team pages (total cap liabilities, cap space, the active roster's cap numbers, dead money,
practice squad and reserve lists), with positions from nflverse's contracts table (OverTheCap's player id -> our id and
position). Writes data/payroll.json.

nflverse's contracts alone fall short: they carry each active deal's cap number by season but no dead money (Miami's
2026 reads $90M against OverTheCap's $301M, Tua Tagovailoa's release among the rest) and no cap space.

  python tools/payroll_build.py --site=site      (CI step "Payroll", the full build)

Refetched once a day (OverTheCap updates within a day of a move); a team whose page fails keeps its last entry.
"""
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

from nfledge import coaches as C  # noqa: E402
from nfledge import data as D  # noqa: E402

V = 4  # what each team's entry holds (2: each list's TOTAL row; next season's projected cap; 3: the whole roster;
# 4: each player's later seasons); a new V refetches every team
FUTURE = 5  # later seasons read per page (OverTheCap lists up to ~5)
URL = "https://overthecap.com/salary-cap/{slug}"
UA = {"User-Agent": "Mozilla/5.0 (nfl-edge; https://github.com/ChefJulio/nfl-edge)"}
FRESH_H = 20  # hours before a team's page is fetched again
# nflverse / OverTheCap positions -> the card's groups, offense then defense then specialists
GROUP = {"QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE", "LT": "OL", "RT": "OL", "LG": "OL", "RG": "OL", "C": "OL",
         "IDL": "DL", "ED": "EDGE", "LB": "LB", "CB": "CB", "S": "S", "K": "ST", "P": "ST", "LS": "ST"}
GROUPS = ["QB", "RB", "WR", "TE", "OL", "DL", "EDGE", "LB", "CB", "S", "ST"]


def money(s: str) -> float:
  """'$11,011,200' / '($1,500)' -> millions."""
  s = (s or "").strip()
  neg = s.startswith("(") or s.startswith("-")
  v = float(re.sub(r"[^\d.]", "", s) or 0) / 1e6
  return -v if neg else v


def parse(html: str, season: int) -> dict:
  """One team page -> {season: {liab, space, act, dead, ps, res, players: [[otc_id, name, cap, list]]}} for this
  season and every later one the page lists (each season's block is div#y<season>; its tables follow their headings)."""
  import lxml.html as L
  doc = L.fromstring(html)
  out = {}
  for s in range(season, season + FUTURE + 1):
    box = doc.xpath(f'//div[@id="y{s}"]')
    if not box:
      continue
    box = box[0]
    txt = re.sub(r"\s+", " ", box.text_content())
    m_l = re.search(r"Total Cap Liabilities:\s*(\(?-?\$[\d,]+\)?)", txt)
    m_s = re.search(r"Team Cap Space:\s*(\(?-?\$[\d,]+\)?)", txt)
    e = {"liab": round(money(m_l.group(1)), 3) if m_l else None, "space": round(money(m_s.group(1)), 3) if m_s else None,
         "act": 0.0, "dead": 0.0, "ps": 0.0, "res": 0.0, "players": []}
    for t in box.iter("table"):
      head = t.xpath("preceding::*[self::h2 or self::h3 or self::h4 or self::h5][1]")
      h = head[0].text_content().strip().lower() if head else ""
      kind = "act" if h.startswith("active roster") else "dead" if h.startswith("dead money") else \
        "ps" if h.startswith("practice squad") else "res" if h else None
      if not kind:
        continue
      listed = 0.0
      for tr in t.findall(".//tr"):
        tds = tr.findall("td")
        if not tds:
          continue
        a = tr.xpath(".//a[contains(@href, '/player/')]")
        name = (a[0].text_content() if a else tds[0].text_content()).strip()
        if name.upper() == "TOTAL":
          # the list's own total, not the sum of its rows: dead money's total carries charges the rows don't itemize
          # (2026-10-27 check: every team's rows came to $0.4-1.4M under it, e.g. MIN $54.14M listed vs $55.56M total,
          # and the totals are what add up to Total Cap Liabilities)
          e[kind] += money(next((c.text_content() for c in reversed(tds) if "$" in c.text_content()), "$0")) - listed
          listed = 0.0
          continue
        if not name:
          continue
        oid = re.search(r"/player/[^/]+/(\d+)", a[0].get("href")).group(1) if a else None
        # the cap number: the 12th cell on the active / reserve layout, the last money cell on the two-column lists
        cells = [c.text_content().strip() for c in tds]
        cap = money(cells[11]) if len(cells) > 12 else money(next((c for c in reversed(cells) if "$" in c), "$0"))
        e[kind] += cap
        listed += cap
        e["players"].append([oid, name, round(cap, 3), kind])
    for k in ("act", "dead", "ps", "res"):
      e[k] = round(e[k], 3)
    out[s] = e
  return out


def fetch(url: str) -> str:
  import urllib.request
  with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
    return r.read().decode("utf-8", errors="ignore")


def build(site: Path) -> None:
  import nflreadpy as nfl
  current = int(nfl.get_current_season())
  out_f = site / "data" / "payroll.json"
  last = json.loads(out_f.read_text(encoding="utf-8")) if out_f.exists() else {}
  cache = D.Cache(ROOT / "cache")
  k = cache.get("contracts_otc", "all", lambda: nfl.load_contracts().select(["otc_id", "gsis_id", "position"]),
                stale=cache.age_hours("contracts_otc", "all") > 24)
  k = k.dropna(subset=["otc_id"]).drop_duplicates("otc_id")
  ids = {str(int(o)): (g if isinstance(g, str) else None, p) for o, g, p in zip(k.otc_id, k.gsis_id, k.position)}
  now = datetime.now(timezone.utc)
  teams = {}
  for t, name in sorted(C.NAME.items()):
    prev = (last.get("teams") or {}).get(t)
    if prev and last.get("season") == current and last.get("v") == V and (now - datetime.fromisoformat(prev["f"])).total_seconds() < FRESH_H * 3600:
      teams[t] = prev
      continue
    try:
      p = parse(fetch(URL.format(slug=name.lower().replace(" ", "-"))), current)
      if current not in p:
        raise ValueError("no season block")
      time.sleep(1.5)  # polite: one page every couple of seconds
    except Exception as e:
      print(f"[payroll] {t}: page unavailable ({e}); keeping the last one", flush=True)
      if prev:
        teams[t] = prev
      continue
    cur, nxt = p[current], p.get(current + 1)
    act = [x for x in cur["players"] if x[3] == "act"]
    grp = {g: 0.0 for g in GROUPS}
    for oid, nm, cap, _ in act:
      g = GROUP.get(ids.get(oid or "", (None, None))[1] or "")
      if g:
        grp[g] += cap
    # everyone carrying a cap number this season, biggest first (owner 2026-10-27: "a show more expand that shows
    # everyone on the roster"): [name, gsis, position, cap, list] with list a = active roster, r = reserve, p = practice squad
    # ... and each one's cap number in every later season his deal runs (owner 2026-10-27: "individual players cap hit
    # on their remaining contract by season"): from the page's later seasons' active-roster lists (void years aren't on
    # them: those charges land as dead money), aligned to current + 1, current + 2, ...; trailing empty seasons dropped
    later = {}
    for s in range(current + 1, current + FUTURE + 1):
      for oid, _, cap, k in (p.get(s) or {}).get("players", []):
        if k == "act" and oid and cap > 0:
          later.setdefault(oid, {})[s] = cap
    def fut(oid):
      f = later.get(oid) or {}
      xs = [round(f.get(s, 0), 3) for s in range(current + 1, current + FUTURE + 1)]
      while xs and not xs[-1]:
        xs.pop()
      return xs
    roster = [[nm, *ids.get(oid or "", (None, None)), cap, {"act": "a", "res": "r", "ps": "p"}[k], fut(oid)]
              for oid, nm, cap, k in sorted((x for x in cur["players"] if x[3] in ("act", "res", "ps")), key=lambda x: -x[2])]
    dead = sorted([x for x in cur["players"] if x[3] == "dead"], key=lambda x: -x[2])[:5]
    teams[t] = {"f": now.isoformat(timespec="seconds"), "liab": cur["liab"], "space": cur["space"], "act": cur["act"],
                "dead": cur["dead"], "ps": cur["ps"], "res": cur["res"], "grp": {g: round(v, 3) for g, v in grp.items()},
                "roster": roster, "dead_top": [[nm, ids.get(oid or "", (None,))[0], cap] for oid, nm, cap, _ in dead],
                # next season's space is against OverTheCap's projected cap (2026-10-27: liab + space = $327.0M for
                # every team, no carryover yet), kept as "cap" so the sheet can say so
                "next": {"liab": nxt["liab"], "space": nxt["space"], "dead": nxt["dead"],
                         "cap": round(nxt["liab"] + nxt["space"], 1) if nxt["liab"] is not None and nxt["space"] is not None else None} if nxt else None}
  # league ranks: cap space (1 = most), dead money (1 = most), each group's spending (1 = most)
  def rank(key, get):
    vals = {t: get(v) for t, v in teams.items() if get(v) is not None}
    for i, t in enumerate(sorted(vals, key=lambda t: -vals[t]), 1):
      teams[t].setdefault("rk", {})[key] = i
  rank("space", lambda v: v.get("space"))
  rank("dead", lambda v: v.get("dead"))
  for g in GROUPS:
    rank(g, lambda v, g=g: (v.get("grp") or {}).get(g))
  lg = {g: round(sum(v["grp"][g] for v in teams.values()) / max(1, len(teams)), 3) for g in GROUPS}
  doc = {"v": V, "season": current, "built": now.strftime("%Y-%m-%dT%H:%MZ"), "groups": GROUPS, "league": lg,
         "src": "OverTheCap team salary cap pages; positions from nflverse contracts", "teams": teams}
  out_f.parent.mkdir(parents=True, exist_ok=True)
  out_f.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
  print(f"[payroll] wrote {out_f} ({len(teams)} teams)", flush=True)


if __name__ == "__main__":
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  build(ROOT / opt.get("site", "site"))
