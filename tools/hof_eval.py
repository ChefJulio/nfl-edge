"""(DP) a Hall of Fame model (pre-registered 2026-10-28, docs/INSIGHTS.md).

Usage: python tools/hof_eval.py

Rows: nflverse draft picks (Pro Football Reference's career columns), drafted 1980 on. Train / test: careers over by 2015
(6+ ballots by the 2026 class). Held out: careers over 2016-20 (most still on the ballot). Major awards (MVP, OPOY,
DPOY, Super Bowl MVP) from ESPN's award history (1980 on), Super Bowl titles from champions' season rosters (nflverse,
1980 on), both matched to draft rows by name within the player's career years. Cached: scratch/hof_inputs.json.
"""
import json
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

CACHE = ROOT / "data" / "history" / "hof_inputs.json"  # finished seasons' awards and champion rosters, committed
ALIAS = {"patsurtain": "patricksurtain", "jimcovert": "jimbocovert"}  # another source's name -> the draft row's (normalized)
DRAFT_NAMES = {}  # frame() fills it: the draft rows' normalized names and draft years, for outside()'s duplicates
AWARD = {477: "mvp", 478: "opoy", 479: "dpoy", 317: "sbmvp"}
# Super Bowl champions before nflverse's schedules (1999): season -> roster team code (nflverse's old rosters)
SB_OLD = {1980: "OAK", 1981: "SF", 1982: "WAS", 1983: "RAI", 1984: "SF", 1985: "CHI", 1986: "NYG", 1987: "WAS", 1988: "SF",
          1989: "SF", 1990: "NYG", 1991: "WAS", 1992: "DAL", 1993: "DAL", 1994: "SF", 1995: "DAL", 1996: "GB", 1997: "DEN",
          1998: "DEN"}
GROUP = {"QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE", "T": "OL", "G": "OL", "C": "OL", "OL": "OL", "OT": "OL",
         "OG": "OL", "DE": "DL", "DT": "DL", "NT": "DL", "DL": "DL", "LB": "LB", "OLB": "LB", "ILB": "LB", "CB": "DB", "S": "DB",
         "SAF": "DB", "DB": "DB", "K": "ST", "P": "ST", "LS": "ST"}
STAT = {"QB": "pass_yards", "RB": "rush_yards", "WR": "rec_yards", "TE": "rec_yards", "DL": "def_sacks", "LB": "def_sacks",
        "DB": "def_ints"}


def norm(n) -> str:
  n = unicodedata.normalize("NFKD", n if isinstance(n, str) else "").encode("ascii", "ignore").decode().lower()
  n = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", n)
  return re.sub(r"[^a-z]", "", n)


def get(url):
  with urllib.request.urlopen(urllib.request.Request(url.replace("http://", "https://"), headers={"User-Agent": "nfl-edge/1.0"}), timeout=30) as r:
    return json.loads(r.read().decode())


def inputs(nfl, last: int) -> dict:
  """{"awards": [[season, code, name]], "rings": [[season, name, team]], "decade": [[decade, name]]}, cached (history
  doesn't change)."""
  if CACHE.exists():
    j = json.loads(CACHE.read_text(encoding="utf-8"))
    if "decade" not in j or "sel_old" not in j:  # (DP2) added to a file cached before them
      j.setdefault("decade", all_decade())
      j.setdefault("sel_old", selections_old())
      CACHE.write_text(json.dumps(j), encoding="utf-8")
    return j
  aw = []
  for s in range(1980, last + 1):
    lst = get(f"https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/{s}/awards?limit=100")
    for it in lst.get("items", []):
      aid = int(re.search(r"/awards/(\d+)", it["$ref"]).group(1))
      if aid in AWARD:
        for w in get(it["$ref"]).get("winners", []):
          ref = (w.get("athlete") or {}).get("$ref")
          if ref:
            aw.append([s, AWARD[aid], get(ref).get("displayName", "")])
  sched = nfl.load_schedules(list(range(1999, last + 1))).to_pandas()
  sb = sched[(sched.game_type == "SB") & sched.result.notna()]
  champ = dict(SB_OLD)
  champ.update({int(r.season): (r.home_team if r.result > 0 else r.away_team) for r in sb.itertuples()})
  ros = nfl.load_rosters(sorted(champ)).to_pandas()
  rings = [[int(s), n, t] for s, n, t in zip(ros.season, ros.full_name, ros.team) if champ.get(int(s)) == t and isinstance(n, str)]
  out = {"awards": aw, "rings": rings, "decade": all_decade()}
  CACHE.parent.mkdir(exist_ok=True)
  CACHE.write_text(json.dumps(out), encoding="utf-8")
  return out


def selections_old() -> list:
  """(DP2) [[season, AP1 / AP2 / PB, name, team]] for 1980-98 from Wikipedia's yearly All-Pro and Pro Bowl pages (1999 on:
  data/history/honors.json, by our id), the same parsing as tools/honors_build.py."""
  sys.path.insert(0, str(ROOT / "tools"))
  from honors_build import ap_code, entries, wiki
  out = []
  for s in range(1980, 1999):
    for name, team, rest, _ in entries(wiki(f"{s} All-Pro Team") or ""):
      tags = re.search(r"\(([^)]*)\)", rest or "")
      tags = [t.strip() for t in tags.group(1).split(",")] if tags else []
      code = ap_code(tags)
      if code:
        out.append([s, code, name, team])
    pb = wiki(f"{s + 1} Pro Bowl") or ""
    i = re.search(r"^==\s*(AFC roster|Rosters?|Roster|AFC rosters?|AFC|Selections)\s*==", pb, re.M | re.I)
    blk = pb[i.start():] if i else ""
    j = re.search(r"^==\s*(Number of selections|References|Notes|See also|External links|Broadcast)", blk, re.M | re.I)
    blk = blk[:j.start()] if j else blk
    out += [[s, "PB", name, team] for name, team, _, _ in entries(blk)]
    # the mid-90s pages: "[[Steve Young]] – SF", "*[[John Elway]] – [[Denver Broncos]]" (a dash, not a comma)
    dash = re.findall(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\]'*\s*[–—-]\s*(\[\[[^\]]+\]\]|[A-Z][A-Za-z. ]*)", blk)
    seen = {r[2] for r in out if r[0] == s and r[1] == "PB"}
    out += [[s, "PB", n.strip(), t] for n, t in dash if n.strip() not in seen]
  return out


def all_decade() -> list:
  """(DP2) [[first season of the decade, name]]: the NFL's All-Decade teams, 1980s-2010s (Wikipedia; every player cell
  is "[[Name]] <small>(teams)</small>", first and second teams alike)."""
  out = []
  for dec in (1980, 1990, 2000, 2010):
    req = urllib.request.Request(f"https://en.wikipedia.org/w/index.php?title=NFL_{dec}s_All-Decade_Team&action=raw",
                                 headers={"User-Agent": "nfl-edge/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
      t = r.read().decode("utf-8", errors="ignore")
    for ln in t.split("\n"):
      if ln.startswith("|") and "<small" in ln:
        m = re.search(r"\[\[(?:[^\]|]+\|)?([^\]]+)\]\][^<]*<small", ln)
        if m:
          out.append([dec, m.group(1).strip()])
  return out


def frame(nfl, last: int) -> pd.DataFrame:
  d = nfl.load_draft_picks().to_pandas()
  d = d[(d.season >= 1980) & d.to.notna()].copy()
  d["hof"] = d.hof.fillna(False).astype(bool)
  d["g"] = d.position.map(GROUP).fillna("ST")
  for c in ("allpro", "probowls", "seasons_started", "w_av", "games", "pass_yards", "rush_yards", "rec_yards", "def_sacks", "def_ints"):
    d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0)
  # (2026-10-28, owner on Josh Allen) Pro Football Reference's draft table lags on active players' selections (Allen 4
  # Pro Bowls there, 6 in fact; 22 active players short a first-team All-Pro): for players drafted 1999 on, our
  # audited counts (data/history/honors.json, tools/honors_audit.py) replace them. On the training careers (over by
  # 2015) the two agree but for 2 players each way, so the fit is the same
  hj = json.loads((ROOT / "data" / "history" / "honors.json").read_text(encoding="utf-8"))["seasons"]
  pbo, apo = {}, {}
  for _s, rows in hj.items():
    for code, g, *_ in rows:
      if code == "PB":
        pbo[g] = pbo.get(g, 0) + 1
      elif code == "AP1":
        apo[g] = apo.get(g, 0) + 1
  m99 = (d.season >= 1999) & d.gsis_id.notna()
  d.loc[m99, "probowls"] = d.loc[m99, "gsis_id"].map(pbo).fillna(0).to_numpy()
  d.loc[m99, "allpro"] = d.loc[m99, "gsis_id"].map(apo).fillna(0).to_numpy()
  d["k"] = d.pfr_player_name.map(norm)
  DRAFT_NAMES.update(k=list(d.k), s=[int(x) for x in d.season])
  I = inputs(nfl, last)
  # a name within a career window, one draft row: the honor is his
  by = {}
  for i, k, a, z in zip(d.index, d.k, d.season, d.to):
    by.setdefault(k, []).append((i, int(a), int(z)))
  side = dict(zip(d.index, d.side))
  def who(name, s, code=None):
    k = norm(name)
    c = [i for i, a, z in by.get(ALIAS.get(k, k), []) if a <= s <= z + 1]
    if len(c) > 1 and code in ("opoy", "dpoy"):  # two of a name in the league (Chris Johnson, 2009): the award's side
      c = [i for i in c if side.get(i) == ("O" if code == "opoy" else "D")] or c
    return c[0] if len(c) == 1 else None
  for c in ("mvp", "opoy", "dpoy", "sbmvp", "rings"):
    d[c] = 0
  miss = {"awards": 0, "rings": 0}
  for s, code, name in I["awards"]:
    i = who(name, s, code)
    if i is None:
      miss["awards"] += 1
    else:
      d.loc[i, code] += 1
  for s, name, _ in I["rings"]:
    i = who(name, s)
    if i is not None:
      d.loc[i, "rings"] += 1
  # the position's main career stat as a percentile within its group (all draft rows)
  d["stat"] = 0.5
  for g, col in STAT.items():
    m = d.g == g
    d.loc[m, "stat"] = d.loc[m, col].rank(pct=True)
  # (DP2) candidates. All-Decade selections (first or second team), matched by name within the decade
  d["decade"] = 0
  for dec, name in I.get("decade", []):
    c = [i for i, a, z in by.get(ALIAS.get(norm(name), norm(name)), []) if a <= dec + 9 and z >= dec]
    if len(c) == 1:
      d.loc[c[0], "decade"] += 1
  # all-time rank at the position (every draft row in the data): the best of its stats (receivers: yards or catches)
  d["rk"] = 999
  for g, cols in {"QB": ["pass_yards"], "RB": ["rush_yards"], "WR": ["rec_yards", "receptions"], "TE": ["rec_yards", "receptions"],
                  "DL": ["def_sacks"], "LB": ["def_sacks"], "DB": ["def_ints"]}.items():
    m = d.g == g
    for col in cols:
      v = pd.to_numeric(d.loc[m, col], errors="coerce").fillna(0)
      d.loc[m, "rk"] = np.minimum(d.loc[m, "rk"], v.rank(ascending=False, method="min"))
  # (DP6 candidate) a QB's rank: the better of pass yards and rushing TDs
  mq = d.g == "QB"
  # (DP7 candidate) a QB's rank on passing + rushing: the better of total yards and total TDs
  num = lambda c: pd.to_numeric(d.loc[mq, c], errors="coerce").fillna(0)  # noqa: E731
  d["rk_t"] = d.rk
  d.loc[mq, "rk_t"] = np.minimum((num("pass_yards") + num("rush_yards")).rank(ascending=False, method="min"),
                                 (num("pass_tds") + num("rush_tds")).rank(ascending=False, method="min"))
  d["rk_q"] = d.rk
  d.loc[mq, "rk_q"] = np.minimum(d.loc[mq, "rk"], pd.to_numeric(d.loc[mq, "rush_tds"], errors="coerce").fillna(0).rank(ascending=False, method="min"))
  # (DP4 candidate) a DB's rank: the better of interceptions and interceptions + sacks
  d["rk2"] = d.rk
  m = d.g == "DB"
  both = (pd.to_numeric(d.loc[m, "def_ints"], errors="coerce").fillna(0) + pd.to_numeric(d.loc[m, "def_sacks"], errors="coerce").fillna(0))
  d.loc[m, "rk2"] = np.minimum(d.loc[m, "rk"], both.rank(ascending=False, method="min"))
  # (DP4, FAIL on the gate (inconclusive), shipped by the owner's call 2026-10-28: "clear improvement besides [sample
  # size], i think we should add it") the shipped rank is rk2; rk_int keeps DP2's interceptions-only rank for the test
  d["rk_int"] = d.rk
  d["rk"] = d.rk2
  # (DP5 candidate) snubbed seasons (tools/snubs_eval.py, 2004 on)
  snf = ROOT / "data" / "history" / "snubs.json"
  sn = json.loads(snf.read_text(encoding="utf-8")).get("s", {}) if snf.exists() else {}
  d["sn_pb"] = [sum(1 for x in sn.get(g, []) if x[1] == "PB") if isinstance(g, str) else 0 for g in d.gsis_id]
  d["sn_ap"] = [sum(1 for x in sn.get(g, []) if x[1] == "AP") if isinstance(g, str) else 0 for g in d.gsis_id]
  d["fb"] = (d.position == "FB").astype(int)
  # ballots so far: classes he has been eligible for through the coming one (last + 1), capped
  d["ye"] = (last + 1 - (d.to + 6) + 1).clip(lower=0, upper=30)
  print(f"[hof] {len(I['awards'])} awards ({miss['awards']} not matched), {len(I['rings'])} champion roster rows", flush=True)
  return d


FEATS = {"allpro": ["ap1", "ap1_3", "ap1_5"], "probowl": ["pb", "pb_7"], "career": ["av", "starts", "games"],
         "awards": ["mvp", "opoy", "dpoy", "sbmvp"], "rings": ["rings"], "position": ["p_QB", "p_RB", "p_WR", "p_TE", "p_OL", "p_DL", "p_LB", "p_DB", "p_ST"],
         "stat": ["stat"],
         # (DP2, PASS 2026-10-28) All-Decade selections; all-time rank at the position (top 5 / 10 / 25)
         "decade": ["decade"], "rank": ["rk5", "rk10", "rk25"]}


def design(d: pd.DataFrame) -> pd.DataFrame:
  x = pd.DataFrame(index=d.index)
  x["ap1"], x["ap1_3"], x["ap1_5"] = np.log1p(d.allpro), (d.allpro >= 3).astype(float), (d.allpro >= 5).astype(float)
  x["pb"], x["pb_7"] = np.log1p(d.probowls), (d.probowls >= 7).astype(float)
  x["av"], x["starts"], x["games"] = d.w_av / 100, d.seasons_started / 10, d.games / 100
  for c in ("mvp", "opoy", "dpoy", "sbmvp"):
    x[c] = d[c].clip(upper=3)
  x["rings"] = d.rings.clip(upper=3)
  for g in ("QB", "RB", "WR", "TE", "OL", "DL", "LB", "DB", "ST"):
    x[f"p_{g}"] = (d.g == g).astype(float)
  x["stat"] = d.stat
  # (DP2) candidates
  if "decade" in d:
    x["decade"] = d.decade.clip(upper=2)
    x["rk5"], x["rk10"], x["rk25"] = (d.rk <= 5).astype(float), (d.rk <= 10).astype(float), (d.rk <= 25).astype(float)
    x["ye"] = np.log1p(d.ye)
    x["fb"] = d.fb.astype(float)
  if "sn_pb" in d:
    x["sn_pb"], x["sn_ap"] = np.log1p(d.sn_pb), np.log1p(d.sn_ap)
  return x


# (DP2) model C, for players outside the draft table (undrafted, the 1984 / 1987 supplemental drafts): B's inputs that
# exist for everyone. No career value, starts, games or stats: Pro Football Reference's, drafted rows only
FEATS_C = ["ap1", "ap1_3", "ap1_5", "pb", "pb_7", "mvp", "opoy", "dpoy", "sbmvp", "rings",
           "p_QB", "p_RB", "p_WR", "p_TE", "p_OL", "p_DL", "p_LB", "p_DB", "p_ST", "decade"]


def outside(nfl, last: int, drafted: set) -> pd.DataFrame:
  """(DP2) every player outside the draft table whose career began 1980 on (nflverse players: id, name, years,
  position), with the draft rows' columns model C reads: first-team All-Pros and Pro Bowls (1999 on: our honors data by
  id; before: Wikipedia's yearly pages by name within his years), awards, rings and All-Decade selections (by name),
  hof from data/history/hof.csv."""
  pl = nfl.load_players().to_pandas()
  u = pl[pl.gsis_id.notna() & ~pl.gsis_id.isin(drafted) & (pd.to_numeric(pl.rookie_season, errors="coerce") >= 1980)
         & pl.last_season.notna()].copy()
  # a drafted player under a second id (Jim / Jimbo Covert): his draft row stands
  dk = set(zip(DRAFT_NAMES.get("k", []), DRAFT_NAMES.get("s", [])))
  key = lambda n: ALIAS.get(norm(n), norm(n))  # noqa: E731
  u = u[[(key(n), int(s)) not in dk and (key(n), int(s) - 1) not in dk for n, s in zip(u.display_name, pd.to_numeric(u.rookie_season))]]
  u["season"], u["to"] = pd.to_numeric(u.rookie_season).astype(int), pd.to_numeric(u.last_season).astype(int)
  u["pfr_player_name"] = u.display_name
  u["g"] = u.position.map(GROUP).fillna(u.position.map({"ILB": "LB", "MLB": "LB", "SS": "DB", "FS": "DB", "OT": "OL", "OG": "OL"})).fillna("ST")
  u = u.reset_index(drop=True)
  by = {}
  for i, n, f, l, a, z in zip(u.index, u.display_name, u.football_name, u.last_name, u.season, u.to):
    for k in {norm(n), norm(f"{f} {l}") if isinstance(f, str) and isinstance(l, str) else ""} - {""}:
      by.setdefault(k, []).append((i, a, z))
  def who(name, s):
    k = norm(name)
    c = {i for i, a, z in by.get(ALIAS.get(k, k), []) if a <= s <= z + 1}
    return next(iter(c)) if len(c) == 1 else None
  for c in ("allpro", "ap2", "probowls", "mvp", "opoy", "dpoy", "sbmvp", "rings", "decade"):
    u[c] = 0
  I = inputs(nfl, last)
  col = {"AP1": "allpro", "AP2": "ap2", "PB": "probowls"}
  for s, code, name, _ in I.get("sel_old", []):
    i = who(name, s)
    if i is not None:
      u.loc[i, col[code]] += 1
  ix = {g: i for i, g in zip(u.index, u.gsis_id)}
  hist = json.loads((ROOT / "data" / "history" / "honors.json").read_text(encoding="utf-8"))["seasons"]
  for s, rows in hist.items():
    for code, g, *_ in rows:
      if code in col and g in ix:
        u.loc[ix[g], col[code]] += 1
  for s, code, name in I["awards"]:
    i = who(name, s)
    if i is not None:
      u.loc[i, code] += 1
  for s, name, _ in I["rings"]:
    i = who(name, s)
    if i is not None:
      u.loc[i, "rings"] += 1
  for dec, name in I.get("decade", []):
    c = {i for i, a, z in by.get(ALIAS.get(norm(name), norm(name)), []) if a <= dec + 9 and z >= dec}
    if len(c) == 1:
      u.loc[next(iter(c)), "decade"] += 1
  hof = set(pd.read_csv(ROOT / "data" / "history" / "hof.csv").gsis_id)
  u["hof"] = u.gsis_id.isin(hof)
  # the draft-only columns design() builds (C reads none of them)
  for c in ("w_av", "seasons_started", "games", "fb", "ye"):
    u[c] = 0
  u["stat"], u["rk"] = 0.5, 999
  return u


def dp2_c(nfl, d: pd.DataFrame, last: int) -> None:
  """(DP2) model C on the drafted rows' folds against A; then fit on them and scored on everyone outside the table."""
  tr = d[d.to <= 2015].reset_index(drop=True)
  y, groups = tr.hof.to_numpy(int), tr.season.to_numpy()
  bins = pd.get_dummies(pd.cut(tr.allpro, [-1, 0, 1, 2, 3, 4, 99]), dtype=float)
  from sklearn.linear_model import LogisticRegression, LogisticRegressionCV
  from sklearn.model_selection import GroupKFold
  from sklearn.metrics import roc_auc_score
  pa = np.zeros(len(tr))
  for a, b in GroupKFold(5).split(bins, y, groups):
    pa[b] = LogisticRegression(C=1e6, max_iter=2000).fit(bins.iloc[a], y[a]).predict_proba(bins.iloc[b])[:, 1]
  pc = oof(tr, FEATS_C, groups)
  m, lo, hi = ci(ll(y, pc) - ll(y, np.clip(pa, 1e-4, 1 - 1e-4)))
  print(f"\n(DP2) C (no career value) vs A on drafted rows: {m:+.4f} [{lo:+.4f}, {hi:+.4f}]  {'PASS' if hi < 0 else 'FAIL'}"
        f"; C log loss {ll(y, pc).mean():.4f}, AUC {roc_auc_score(y, pc):.3f}")
  X = design(tr)[FEATS_C].to_numpy(float)
  fm = LogisticRegressionCV(Cs=[0.03, 0.1, 0.3, 1, 3, 10], cv=list(GroupKFold(5).split(X, y, groups)), scoring="neg_log_loss", max_iter=5000).fit(X, y)
  u = outside(nfl, last, set(d.gsis_id.dropna()))
  u["p"] = fm.predict_proba(design(u)[FEATS_C].to_numpy(float))[:, 1]
  e = u[u.to <= 2015]
  print(f"Outside the draft table: {len(u):,} players since 1980 ({int(u.hof.sum())} inductees); careers over by 2015: "
        f"{len(e):,}, {int(e.hof.sum())} in, predicted {e.p.sum():.1f}, AUC {roc_auc_score(e.hof, e.p) if e.hof.any() else float('nan'):.3f}")
  print(u.sort_values("p", ascending=False).head(15)[["display_name", "g", "allpro", "probowls", "rings", "decade", "to", "hof", "p"]].round(2).to_string(index=False))
  print("Inductees:", u[u.hof][["display_name", "allpro", "probowls", "p"]].round(2).values.tolist())


def dp6(d: pd.DataFrame, col: str = "rk_q", lab6: str = "(DP6) QB rushing in the rank") -> None:
  """(DP6) QBs ranked on the better of pass yards and rushing TDs (DBs as shipped); (DP7, col rk_t) on passing +
  rushing yards and TDs."""
  tr = d[d.to <= 2015].reset_index(drop=True)
  y, groups = tr.hof.to_numpy(int), tr.season.to_numpy()
  allc = [c for v in FEATS.values() for c in v]
  t2 = tr.assign(rk=np.where(tr.g == "QB", tr[col], tr.rk))
  pb, pn = oof(tr, allc, groups), oof(t2, allc, groups)
  m, lo, hi = ci(ll(y, pn) - ll(y, pb))
  print(f"\n{lab6}: {m:+.5f} [{lo:+.5f}, {hi:+.5f}]  {'PASS' if hi < 0 else 'FAIL'}")
  q = (tr.g == "QB").to_numpy()
  print(f"  QBs alone ({q.sum()}, {y[q].sum()} in): log loss {ll(y[q], pb[q]).mean():.4f} -> {ll(y[q], pn[q]).mean():.4f}")
  from sklearn.linear_model import LogisticRegressionCV
  from sklearn.model_selection import GroupKFold
  names = ["Josh Allen", "Cam Newton", "Lamar Jackson", "Jalen Hurts", "Steve Young", "Michael Vick"]
  for lab, f in (("today", tr), ("with rushing", t2)):
    X = design(f)[allc].to_numpy(float)
    fm = LogisticRegressionCV(Cs=[0.03, 0.1, 0.3, 1, 3, 10], cv=list(GroupKFold(5).split(X, y, groups)), scoring="neg_log_loss", max_iter=5000).fit(X, y)
    qq = d[d.pfr_player_name.isin(names) & (d.g == "QB")].copy()
    if lab == "with rushing":
      qq["rk"] = qq[col]
    print(f"  {lab}: " + ", ".join(f"{n} {p:.2f}" for n, p in zip(qq.pfr_player_name, fm.predict_proba(design(qq)[allc].to_numpy(float))[:, 1])))


def dp5(d: pd.DataFrame) -> None:
  """(DP5) snubs added to the shipped model."""
  tr = d[d.to <= 2015].reset_index(drop=True)
  y, groups = tr.hof.to_numpy(int), tr.season.to_numpy()
  allc = [c for v in FEATS.values() for c in v]
  pb, pn = oof(tr, allc, groups), oof(tr, allc + ["sn_pb", "sn_ap"], groups)
  m, lo, hi = ci(ll(y, pn) - ll(y, pb))
  print(f"\n(DP5) snubs added: {m:+.5f} [{lo:+.5f}, {hi:+.5f}]  {'PASS' if hi < 0 else 'FAIL'}")
  w = tr[(tr.sn_pb + tr.sn_ap) > 0].assign(old=pb[(tr.sn_pb + tr.sn_ap).to_numpy() > 0], new=pn[(tr.sn_pb + tr.sn_ap).to_numpy() > 0])
  print(f"  training players with a snub: {len(w)} ({int(w.hof.sum())} in)")
  print(w.sort_values("new", ascending=False)[["pfr_player_name", "g", "allpro", "probowls", "sn_pb", "sn_ap", "hof", "old", "new"]].round(2).head(15).to_string(index=False))
  # do voters correct snubs? among players with 5-8 Pro Bowls, Hall rate with and without a snub
  b = tr[tr.probowls.between(5, 8)]
  for lab, m_ in (("with a snub", (b.sn_pb + b.sn_ap) > 0), ("without", (b.sn_pb + b.sn_ap) == 0)):
    print(f"  5-8 Pro Bowls, {lab}: {int(m_.sum())} players, {100 * b[m_].hof.mean() if m_.any() else float('nan'):.0f}% in")


def dp4(d: pd.DataFrame) -> None:
  """(DP4) the shipped model with DBs ranked on the better of interceptions and interceptions + sacks."""
  from sklearn.metrics import roc_auc_score
  tr = d[d.to <= 2015].reset_index(drop=True)
  y, groups = tr.hof.to_numpy(int), tr.season.to_numpy()
  allc = [c for v in FEATS.values() for c in v]
  # (as run before shipping: today's = DP2's interceptions-only rank for DBs)
  tr = tr.assign(rk=tr.rk_int)
  pb = oof(tr, allc, groups)
  t2 = tr.assign(rk=tr.rk2)
  pn = oof(t2, allc, groups)
  m, lo, hi = ci(ll(y, pn) - ll(y, pb))
  print(f"\n(DP4) DB rank with sacks vs today's: {m:+.5f} [{lo:+.5f}, {hi:+.5f}]  {'PASS' if hi < 0 else 'FAIL'}")
  db = (tr.g == "DB").to_numpy()
  print(f"  DBs alone ({db.sum()}, {y[db].sum()} in): log loss {ll(y[db], pb[db]).mean():.4f} -> {ll(y[db], pn[db]).mean():.4f}; "
        f"AUC {roc_auc_score(y[db], pb[db]):.3f} -> {roc_auc_score(y[db], pn[db]):.3f}")
  changed = tr[(tr.rk != tr.rk2)]
  print(f"  DBs whose rank flags change: {int(((tr.rk <= 25) != (tr.rk2 <= 25)).sum())}; e.g.",
        changed.assign(old=pb[changed.index], new=pn[changed.index]).sort_values("new", ascending=False).head(8)[["pfr_player_name", "def_ints", "def_sacks", "rk", "rk2", "hof", "old", "new"]].round(3).values.tolist())
  # Smith (active) and Harrison: the final fit each way
  from sklearn.linear_model import LogisticRegressionCV
  from sklearn.model_selection import GroupKFold
  for lab, frame_ in (("today", tr), ("with sacks", t2)):
    X = design(frame_)[allc].to_numpy(float)
    fm = LogisticRegressionCV(Cs=[0.03, 0.1, 0.3, 1, 3, 10], cv=list(GroupKFold(5).split(X, y, groups)), scoring="neg_log_loss", max_iter=5000).fit(X, y)
    q = d[d.pfr_player_name.isin(["Harrison Smith", "Rodney Harrison"])].copy()
    q["rk"] = q.rk2 if lab == "with sacks" else q.rk_int
    print(f"  {lab}: " + ", ".join(f"{n} {p:.2f}" for n, p in zip(q.pfr_player_name, fm.predict_proba(design(q)[allc].to_numpy(float))[:, 1])))


# as tested in DP2 (all-decade and all-time rank passed and joined FEATS; this list is the test as it ran)
CAND = {"all-decade": ["decade"], "all-time rank": ["rk5", "rk10", "rk25"], "years eligible": ["ye"], "fullback": ["fb"]}


def dp2(tr: pd.DataFrame) -> None:
  """(DP2) each candidate input added to B: out-of-fold log loss, with interval (gate: lower, the interval below 0)."""
  y, groups = tr.hof.to_numpy(int), tr.season.to_numpy()
  base = [c for v in FEATS.values() for c in v]
  lb = ll(y, oof(tr, base, groups))
  print(f"\n(DP2) B {lb.mean():.4f}; each candidate added (new - B; gate: interval below 0):")
  keep = []
  for name, cols in CAND.items():
    m, lo, hi = ci(ll(y, oof(tr, base + cols, groups)) - lb)
    ok = hi < 0
    keep += cols if ok else []
    print(f"  {name:14s} {m:+.4f} [{lo:+.4f}, {hi:+.4f}]  {'PASS' if ok else 'FAIL'}")
  if keep:
    p = oof(tr, base + keep, groups)
    m, lo, hi = ci(ll(y, p) - lb)
    from sklearn.metrics import roc_auc_score
    s = tr.probowls.to_numpy() >= 3
    print(f"  together {keep}: {m:+.4f} [{lo:+.4f}, {hi:+.4f}]; 3+ Pro Bowls AUC {roc_auc_score(y[s], p[s]):.3f}, "
          f"right at 50% {100 * ((p[s] >= 0.5) == y[s]).mean():.1f}%")


def oof(d, cols, groups, model="ridge"):
  """Out-of-fold P(hof), 5 folds grouped by draft class; ridge strength picked inside each training fold."""
  from sklearn.linear_model import LogisticRegression, LogisticRegressionCV
  from sklearn.model_selection import GroupKFold
  X, y = design(d)[cols].to_numpy(float), d.hof.to_numpy(int)
  p = np.zeros(len(d))
  for tr, te in GroupKFold(5).split(X, y, groups):
    if model == "bins":
      m = LogisticRegression(C=1e6, max_iter=2000).fit(X[tr], y[tr])
    else:
      inner = list(GroupKFold(4).split(X[tr], y[tr], groups[tr]))
      m = LogisticRegressionCV(Cs=[0.03, 0.1, 0.3, 1, 3, 10], cv=inner, scoring="neg_log_loss", max_iter=5000)
      m.fit(X[tr], y[tr])
    p[te] = m.predict_proba(X[te])[:, 1]
  return np.clip(p, 1e-4, 1 - 1e-4)


def ll(y, p):
  return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def ci(a, n=4000):
  rng = np.random.default_rng(0)
  b = [a[rng.integers(0, len(a), len(a))].mean() for _ in range(n)]
  return a.mean(), np.percentile(b, 2.5), np.percentile(b, 97.5)


def main():
  import nflreadpy as nfl
  last = int(nfl.get_current_season()) - 1
  d = frame(nfl, last)
  tr = d[d.to <= 2015].reset_index(drop=True)
  y, groups = tr.hof.to_numpy(int), tr.season.to_numpy()
  print(f"[hof] rows: {len(tr):,} careers over by 2015, {y.sum()} in the Hall")
  # A: first-team All-Pro bins alone
  bins = pd.get_dummies(pd.cut(tr.allpro, [-1, 0, 1, 2, 3, 4, 99]), dtype=float)
  from sklearn.linear_model import LogisticRegression
  from sklearn.model_selection import GroupKFold
  pa = np.zeros(len(tr))
  for a, b in GroupKFold(5).split(bins, y, groups):
    pa[b] = LogisticRegression(C=1e6, max_iter=2000).fit(bins.iloc[a], y[a]).predict_proba(bins.iloc[b])[:, 1]
  pa = np.clip(pa, 1e-4, 1 - 1e-4)
  allc = [c for v in FEATS.values() for c in v]
  pb = oof(tr, allc, groups)
  la, lb = ll(y, pa), ll(y, pb)
  m, lo, hi = ci(lb - la)
  from sklearn.metrics import roc_auc_score
  print(f"\nGATE: log loss A (All-Pro count) {la.mean():.4f}  B (full) {lb.mean():.4f}  B - A {m:+.4f} [{lo:+.4f}, {hi:+.4f}]"
        f"  -> {'PASS' if hi < 0 else 'FAIL'};  AUC A {roc_auc_score(y, pa):.3f}  B {roc_auc_score(y, pb):.3f}")
  print("\nEach input's worth (B with the group dropped, minus B; + = it helps):")
  for name, cols in FEATS.items():
    pd_ = oof(tr, [c for c in allc if c not in cols], groups)
    mm, l2, h2 = ci(ll(y, pd_) - lb)
    print(f"  {name:9s} {mm:+.4f} [{l2:+.4f}, {h2:+.4f}]{'  *' if l2 > 0 else ''}")
  print("\nCalibration (B, out of fold), by decile of the highest-risk 300 and the rest:")
  o = np.argsort(-pb)
  for lab, idx in (("top 25", o[:25]), ("26-50", o[25:50]), ("51-100", o[50:100]), ("101-300", o[100:300]), ("rest", o[300:])):
    print(f"  {lab:8s} predicted {pb[idx].sum():6.1f}  actual {y[idx].sum():4d}  (n {len(idx)})")
  # misses: inductees B thought unlikely, and non-inductees it thought likely
  tr["p"] = pb
  print("\nInductees B rated lowest:", tr[tr.hof].nsmallest(6, "p")[["pfr_player_name", "g", "allpro", "probowls", "w_av", "p"]].round(2).values.tolist())
  print("Not in, B rated highest:", tr[~tr.hof].nlargest(8, "p")[["pfr_player_name", "g", "allpro", "probowls", "w_av", "to", "p"]].round(2).values.tolist())
  # the final model on every training row; held-out careers over 2016-20
  from sklearn.linear_model import LogisticRegressionCV
  Xa = design(tr)[allc].to_numpy(float)
  fm = LogisticRegressionCV(Cs=[0.03, 0.1, 0.3, 1, 3, 10], cv=list(GroupKFold(5).split(Xa, y, groups)), scoring="neg_log_loss", max_iter=5000)
  fm.fit(Xa, y)
  print(f"\nFinal ridge C {fm.C_[0]}; coefficients: " + ", ".join(f"{c} {v:+.2f}" for c, v in zip(allc, fm.coef_[0])))
  ho = d[(d.to >= 2016) & (d.to <= 2020)].copy()
  ho["p"] = fm.predict_proba(design(ho)[allc].to_numpy(float))[:, 1]
  print(f"\nHeld out, careers over 2016-20: {len(ho):,}, in so far {int(ho.hof.sum())}; predicted total {ho.p.sum():.1f}")
  print(ho.nlargest(20, "p")[["pfr_player_name", "g", "allpro", "probowls", "rings", "hof", "p"]].round(2).to_string(index=False))
  print("\nRecipe by position (inductees, careers over by 2015): median AP1 / PB / starter seasons / AV; n")
  for g, s in tr[tr.hof].groupby("g"):
    print(f"  {g}: {s.allpro.median():.0f} / {s.probowls.median():.0f} / {s.seasons_started.median():.0f} / {s.w_av.median():.0f}; {len(s)}")


def export(site: Path) -> None:
  """data/hof_chance.json: the shipped model (B with DP2's All-Decade and all-time rank, fit on every career over by
  2015) applied to every drafted player not in the Hall, and model C to everyone outside the draft table (undrafted,
  the 1984 / 1987 supplemental drafts), each career as it stands (an active player: "if his career ended today"). {"v", "built",
  "c": {gsis: [chance, eligible, name, group, last season]}}; eligible = retired 5+ seasons. Under 1% left out."""
  import nflreadpy as nfl
  from datetime import datetime, timezone
  from sklearn.linear_model import LogisticRegressionCV
  from sklearn.model_selection import GroupKFold
  cur = int(nfl.get_current_season())
  d = frame(nfl, cur - 1)
  tr = d[d.to <= 2015]
  allc = [c for v in FEATS.values() for c in v]
  X, y = design(tr)[allc].to_numpy(float), tr.hof.to_numpy(int)
  fm = LogisticRegressionCV(Cs=[0.03, 0.1, 0.3, 1, 3, 10], cv=list(GroupKFold(5).split(X, y, tr.season.to_numpy())),
                            scoring="neg_log_loss", max_iter=5000).fit(X, y)
  out = d[~d.hof & d.gsis_id.notna()].copy()
  out["p"] = fm.predict_proba(design(out)[allc].to_numpy(float))[:, 1]
  # (DP2) everyone outside the draft table (undrafted, supplemental drafts): model C, on the same training rows
  Xc = design(tr)[FEATS_C].to_numpy(float)
  fc = LogisticRegressionCV(Cs=[0.03, 0.1, 0.3, 1, 3, 10], cv=list(GroupKFold(5).split(Xc, y, tr.season.to_numpy())),
                            scoring="neg_log_loss", max_iter=5000).fit(Xc, y)
  u = outside(nfl, cur - 1, set(d.gsis_id.dropna()))
  u = u[~u.hof].copy()
  u["p"] = fc.predict_proba(design(u)[FEATS_C].to_numpy(float))[:, 1]
  out = pd.concat([out, u[["gsis_id", "p", "to", "pfr_player_name", "g"]]], ignore_index=True)
  out = out[out.p >= 0.01]
  # [chance, eligible, name, position group, last season] (names for the watch list)
  doc = {"v": 1, "built": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "eligible_through": cur - 6,
         "c": {g: [round(float(p), 3), int(z <= cur - 6), n, grp, int(z)]
               for g, p, z, n, grp in zip(out.gsis_id, out.p, out.to, out.pfr_player_name, out.g)}}
  f = site / "data" / "hof_chance.json"
  f.parent.mkdir(parents=True, exist_ok=True)
  f.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
  print(f"[hof] wrote {f} ({len(doc['c'])} players at 1%+)", flush=True)


if __name__ == "__main__":
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  if "export" in opt:
    export(ROOT / opt["export"])
  elif opt.get("dp7") == "1":
    import nflreadpy as nfl
    dp6(frame(nfl, int(nfl.get_current_season()) - 1), "rk_t", "(DP7) QBs on passing + rushing yards and TDs")
  elif opt.get("dp6") == "1":
    import nflreadpy as nfl
    dp6(frame(nfl, int(nfl.get_current_season()) - 1))
  elif opt.get("dp5") == "1":
    import nflreadpy as nfl
    dp5(frame(nfl, int(nfl.get_current_season()) - 1))
  elif opt.get("dp4") == "1":
    import nflreadpy as nfl
    dp4(frame(nfl, int(nfl.get_current_season()) - 1))
  elif opt.get("dp2") == "1":
    import nflreadpy as nfl
    d = frame(nfl, int(nfl.get_current_season()) - 1)
    print(f"[hof] All-Decade selections matched: {int(d.decade.sum())}; top-10 all-time ranks: {int((d.rk <= 10).sum())}", flush=True)
    if opt.get("only") != "c":
      dp2(d[d.to <= 2015].reset_index(drop=True))
    dp2_c(nfl, d, int(nfl.get_current_season()) - 1)
  else:
    main()
