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
ALIAS = {"patsurtain": "patricksurtain"}  # ESPN's name -> the draft row's (normalized)
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
  """{"awards": [[season, code, name]], "rings": [[season, name, team]]}, cached (history doesn't change)."""
  if CACHE.exists():
    return json.loads(CACHE.read_text(encoding="utf-8"))
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
  out = {"awards": aw, "rings": rings}
  CACHE.parent.mkdir(exist_ok=True)
  CACHE.write_text(json.dumps(out), encoding="utf-8")
  return out


def frame(nfl, last: int) -> pd.DataFrame:
  d = nfl.load_draft_picks().to_pandas()
  d = d[(d.season >= 1980) & d.to.notna()].copy()
  d["hof"] = d.hof.fillna(False).astype(bool)
  d["g"] = d.position.map(GROUP).fillna("ST")
  for c in ("allpro", "probowls", "seasons_started", "w_av", "games", "pass_yards", "rush_yards", "rec_yards", "def_sacks", "def_ints"):
    d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0)
  d["k"] = d.pfr_player_name.map(norm)
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
  print(f"[hof] {len(I['awards'])} awards ({miss['awards']} not matched), {len(I['rings'])} champion roster rows", flush=True)
  return d


FEATS = {"allpro": ["ap1", "ap1_3", "ap1_5"], "probowl": ["pb", "pb_7"], "career": ["av", "starts", "games"],
         "awards": ["mvp", "opoy", "dpoy", "sbmvp"], "rings": ["rings"], "position": ["p_QB", "p_RB", "p_WR", "p_TE", "p_OL", "p_DL", "p_LB", "p_DB", "p_ST"],
         "stat": ["stat"]}


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
  return x


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
  """data/hof_chance.json: the shipped model (B, fit on every career over by 2015) applied to every drafted player not
  in the Hall, his career columns as they stand (an active player: "if his career ended today"). {"v", "built",
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
  else:
    main()
