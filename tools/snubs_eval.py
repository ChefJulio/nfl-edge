"""(DQ) Pro Bowl / All-Pro selection and snubs (pre-registered 2026-10-28, docs/INSIGHTS.md).

Usage: python tools/snubs_eval.py [--export=site]

Player-seasons 2004-25, regular season, QB / RB / WR / TE / DL / LB / DB with 8+ games. Per position group, a logistic
of selection on the season's stats (percentiles within season and group), games, team win share, and reputation
(Pro Bowls and first-team All-Pros before the season, selected the season before). 5 folds grouped by season.
Selections: data/history/honors.json (1999 on). Stats: nflverse player stats (by our player id).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

FIRST, LAST = 2004, 2025
STATS = {"QB": {"passing_yards": 1, "passing_tds": 1, "passing_epa": 1, "passing_interceptions": -1},
         "RB": {"rushing_yards": 1, "rushing_tds": 1, "receiving_yards": 1},
         "WR": {"receptions": 1, "receiving_yards": 1, "receiving_tds": 1},
         "TE": {"receptions": 1, "receiving_yards": 1, "receiving_tds": 1},
         "DL": {"def_sacks": 1, "def_qb_hits": 1, "def_tackles_for_loss": 1},
         "LB": {"tackles": 1, "def_sacks": 1, "def_tackles_for_loss": 1, "ballhawk": 1},
         "DB": {"def_interceptions": 1, "def_pass_defended": 1, "tackles": 1}}
REP = ["pb_before", "ap_before", "pb_last"]


def frame() -> pd.DataFrame:
  import nflreadpy as nfl
  st = nfl.load_player_stats(list(range(FIRST - 5, LAST + 1))).to_pandas()
  st = st[(st.season_type == "REG") & st.position_group.isin(STATS)]
  num = [c for c in st.columns if st[c].dtype.kind in "fi" and c not in ("season", "week")]
  g = st.groupby(["player_id", "season"])
  s = g[num].sum()
  s["games"] = g.week.nunique()
  mode = lambda x: x.mode().iloc[0] if x.notna().any() else None  # noqa: E731 (a season with no team / group listed)
  s["grp"] = g.position_group.agg(mode)
  s["team"] = g.team.agg(mode)
  s["name"] = g.player_display_name.first()
  s = s.reset_index()
  s["tackles"] = s.def_tackles_solo + s.def_tackle_assists
  s["ballhawk"] = s.def_interceptions + s.def_pass_defended
  # team win share
  sch = nfl.load_schedules(list(range(FIRST - 5, LAST + 1))).to_pandas()
  sch = sch[(sch.game_type == "REG") & sch.result.notna()]
  w = pd.concat([pd.DataFrame({"season": sch.season, "team": sch.home_team, "w": (sch.result > 0) + 0.5 * (sch.result == 0)}),
                 pd.DataFrame({"season": sch.season, "team": sch.away_team, "w": (sch.result < 0) + 0.5 * (sch.result == 0)})])
  s = s.merge(w.groupby(["season", "team"]).w.mean().rename("win").reset_index(), on=["season", "team"], how="left")
  s["win"] = s.win.fillna(0.5)
  # selections
  hist = json.loads((ROOT / "data" / "history" / "honors.json").read_text(encoding="utf-8"))["seasons"]
  sel = {}
  for yr, rows in hist.items():
    for code, gid, *_ in rows:
      if code in ("PB", "AP1"):
        sel.setdefault((gid, int(yr)), set()).add(code)
  s["pb"] = [int("PB" in sel.get((p, y), ())) for p, y in zip(s.player_id, s.season)]
  s["ap"] = [int("AP1" in sel.get((p, y), ())) for p, y in zip(s.player_id, s.season)]
  s = s.sort_values(["player_id", "season"])
  # reputation: selections before this season (from 1999), last season's
  pb_by, ap_by = {}, {}
  for (gid, yr), codes in sel.items():
    pb_by.setdefault(gid, []).append(yr) if "PB" in codes else None
    ap_by.setdefault(gid, []).append(yr) if "AP1" in codes else None
  s["pb_before"] = [np.log1p(sum(1 for y in pb_by.get(p, []) if y < t)) for p, t in zip(s.player_id, s.season)]
  s["ap_before"] = [np.log1p(sum(1 for y in ap_by.get(p, []) if y < t)) for p, t in zip(s.player_id, s.season)]
  s["pb_last"] = [int((t - 1) in pb_by.get(p, [])) for p, t in zip(s.player_id, s.season)]
  s = s[(s.season >= FIRST) & (s.games >= 8)].copy()
  # the season's numbers as percentiles within season and group
  for grp, cols in STATS.items():
    m = s.grp == grp
    for c, sign in cols.items():
      s.loc[m, f"q_{c}"] = (sign * s.loc[m, c]).groupby(s.loc[m, "season"]).rank(pct=True)
  return s.reset_index(drop=True)


def feats(grp, rep=True, win=True):
  return [f"q_{c}" for c in STATS[grp]] + ["games"] + (["win"] if win else []) + (REP if rep else [])


def oof(s, target, rep=True, win=True):
  from sklearn.linear_model import LogisticRegression
  from sklearn.model_selection import GroupKFold
  p = np.zeros(len(s))
  for grp in STATS:
    m = (s.grp == grp).to_numpy()
    x = s[m]
    X, y = x[feats(grp, rep, win)].fillna(0).to_numpy(float), x[target].to_numpy(int)
    X = np.column_stack([X, X[:, :len(STATS[grp])] ** 2])  # a bend: selection is about the top of the range
    pp = np.zeros(len(x))
    for a, b in GroupKFold(5).split(X, y, x.season):
      pp[b] = LogisticRegression(C=1.0, max_iter=5000).fit(X[a], y[a]).predict_proba(X[b])[:, 1]
    p[m] = pp
  return np.clip(p, 1e-4, 1 - 1e-4)


def ll(y, p):
  return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def ci_by(s, a, n=2000):
  per = pd.Series(a).groupby(s.player_id.to_numpy()).sum()
  v, rng = per.to_numpy(), np.random.default_rng(0)
  b = [v[rng.integers(0, len(v), len(v))].sum() / len(a) for _ in range(n)]
  return a.mean(), np.percentile(b, 2.5), np.percentile(b, 97.5)


def main():
  s = frame()
  print(f"[DQ] {len(s):,} player-seasons {FIRST}-{LAST}; Pro Bowls {int(s.pb.sum())}, first-team All-Pros {int(s.ap.sum())}")
  from sklearn.metrics import roc_auc_score
  for target in ("pb", "ap"):
    y = s[target].to_numpy(int)
    full, norep, nowin = oof(s, target), oof(s, target, rep=False), oof(s, target, win=False)
    print(f"\n== {'Pro Bowl' if target == 'pb' else 'first-team All-Pro'}: AUC {roc_auc_score(y, full):.3f}, log loss {ll(y, full).mean():.4f}")
    for lab, alt in (("(1) reputation", norep), ("(2) team record", nowin)):
      m, lo, hi = ci_by(s, ll(y, full) - ll(y, alt))
      print(f"  {lab}: with - without {m:+.5f} [{lo:+.5f}, {hi:+.5f}]  {'PASS' if hi < 0 else 'FAIL'}")
    s[f"p_{target}"] = full
    o = np.argsort(-full)
    for lab, idx in (("top 100", o[:100]), ("101-300", o[100:300]), ("301-1000", o[300:1000]), ("rest", o[1000:])):
      print(f"  calibration {lab:9s} predicted {full[idx].sum():6.1f}  actual {y[idx].sum():5d}")
  # reputation as odds (Pro Bowl): a fitted model on all rows per group, last season's selection
  from sklearn.linear_model import LogisticRegression
  print("\nReputation (Pro Bowl), odds multiplier for 'selected last season', same season otherwise:")
  for grp in STATS:
    x = s[s.grp == grp]
    X = x[feats(grp)].fillna(0).to_numpy(float)
    X = np.column_stack([X, X[:, :len(STATS[grp])] ** 2])
    m = LogisticRegression(C=1.0, max_iter=5000).fit(X, x.pb)
    k = feats(grp).index("pb_last")
    print(f"  {grp}: x{np.exp(m.coef_[0][k]):.1f}")
  sn = s[(s.p_pb >= 0.6) & (s.pb == 0)].sort_values("p_pb", ascending=False)
  # a reputation pick: a weak season by the model, picked anyway, by a player with Pro Bowls before it and a real role
  # at his position (some stat in his group's top half: special-teams Pro Bowlers, picked for that slot, fall out)
  qcols = [c for c in s.columns if c.startswith("q_")]
  role = s[qcols].max(axis=1) >= 0.5
  rp = s[(s.p_pb <= 0.15) & (s.pb == 1) & (s.pb_before > 0) & role].sort_values("p_pb")
  print(f"\nPro Bowl snubs (60%+, not picked): {len(sn)}; reputation picks (15% or less, picked): {len(rp)}")
  print(sn.head(15)[["season", "name", "grp", "team", "p_pb", "pb_before"]].round(2).to_string(index=False))
  print(rp.head(10)[["season", "name", "grp", "team", "p_pb", "pb_before"]].round(2).to_string(index=False))
  print("\nMost Pro Bowl snubs over a career:", sn.groupby("name").size().sort_values(ascending=False).head(10).to_dict())
  print("Snubs per team (all seasons):", sn.groupby("team").size().sort_values(ascending=False).head(6).to_dict())
  print("Snub rate by position (snubs / 60%+ seasons):",
        {g: round(float(((x.p_pb >= .6) & (x.pb == 0)).sum() / max(1, (x.p_pb >= .6).sum())), 2) for g, x in s.groupby("grp")})
  print("Harrison Smith:", s[s.name == "Harrison Smith"][["season", "p_pb", "pb", "p_ap", "ap"]].round(2).values.tolist())
  s.to_pickle(ROOT / "scratch" / "snubs.pkl")


HIST = ROOT / "data" / "history" / "snubs.json"


def export() -> None:
  """data/history/snubs.json (committed; rerun once a year when the new selections are in): {"v", "through",
  "s": {gsis: [[season, kind, chance]]}}, kind PB / AP: a season the out-of-fold chance put at 60%+ and he wasn't picked
  (DQ's definition). The site copies it to data/snubs.json."""
  s = frame()
  out = {}
  for target, kind in (("pb", "PB"), ("ap", "AP")):
    s[f"p_{target}"] = oof(s, target)
    x = s[(s[f"p_{target}"] >= 0.6) & (s[target] == 0)]
    for g, yr, p in zip(x.player_id, x.season, x[f"p_{target}"]):
      out.setdefault(g, []).append([int(yr), kind, round(float(p), 2)])
  for g in out:
    out[g].sort()
  HIST.write_text(json.dumps({"v": 1, "through": LAST, "s": out}, separators=(",", ":")), encoding="utf-8")
  print(f"[snubs] wrote {HIST} ({len(out)} players, {sum(len(v) for v in out.values())} snubbed seasons)", flush=True)


def dq2() -> None:
  """(DQ2) QB rushing (yards, TDs as percentiles within season) added to the QB selection model, Pro Bowl and All-Pro."""
  s = frame()
  m = s.grp == "QB"
  for c in ("rushing_yards", "rushing_tds"):
    s.loc[m, f"q_{c}"] = s.loc[m, c].groupby(s.loc[m, "season"]).rank(pct=True)
  base = dict(STATS["QB"])
  for target in ("pb", "ap"):
    y = s[target].to_numpy(int)
    p0 = oof(s, target)
    STATS["QB"] = {**base, "rushing_yards": 1, "rushing_tds": 1}
    p1 = oof(s, target)
    STATS["QB"] = base
    q = m.to_numpy()
    mm, lo, hi = ci_by(s[q].reset_index(drop=True), ll(y[q], p1[q]) - ll(y[q], p0[q]))
    print(f"(DQ2) {target}: QB rows {q.sum()}, with rushing - without {mm:+.5f} [{lo:+.5f}, {hi:+.5f}]  {'PASS' if hi < 0 else 'FAIL'}")
    a = s[q & (s.name == "Josh Allen")].assign(old=p0[q & (s.name == "Josh Allen").to_numpy()], new=p1[q & (s.name == "Josh Allen").to_numpy()])
    print("  Josh Allen:", a[["season", target, "old", "new"]].round(2).values.tolist())


if __name__ == "__main__":
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  if opt.get("dq2") == "1":
    dq2()
  elif opt.get("export") == "1":
    export()
  else:
    main()
