"""(AP) the week's stage from the calendar, (AQ) short-week practice reports (pre-registered 2026-10-18, INSIGHTS).

Usage: python tools/stage_eval.py
Uses the dated practice weeks cached by tools/offreport_eval.py (cache/practice_dated_<season>.parquet) and the
played labels of data.avail_hist. Models as production (nfledge/injuries.py _fit_practice): the full-week model on
every labelled week (status not Out), the partial models on 3-day weeks cut to their first k days; walk-forward,
season s trained on seasons before s (2018 on).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.injuries import InjuryModel, practice_features  # noqa: E402
from offreport_eval import dated  # noqa: E402

TEST = [2021, 2022, 2023, 2024, 2025]
LAG = {6: [4, 3, 2], 0: [4, 3, 2], 3: [3, 2, 1], 4: [3, 2, 1], 5: [4, 3, 2], 2: [3, 2, 1]}  # game weekday (Mon=0) -> days before


def ci(diff, groups):
  gs = pd.DataFrame({"d": np.asarray(diff), "g": np.asarray(groups)}).groupby("g").d.agg(["sum", "size"])
  idx = np.random.default_rng(0).integers(0, len(gs), (4000, len(gs)))
  bt = gs["sum"].to_numpy()[idx].sum(1) / gs["size"].to_numpy()[idx].sum(1)
  return float(np.mean(diff)), *np.percentile(bt, [2.5, 97.5])


def main():
  cfg = load_config()
  d = D.load_all(cfg)
  cdir = ROOT / cfg["data"]["cache_dir"]
  im = InjuryModel(d, None, cfg)
  feats = lambda r: im._with_rest(im._with_role(practice_features(r), r), r)
  gb = lambda: HistGradientBoostingClassifier(**im._gb_params(), random_state=0)
  ah = d.avail_hist.copy()
  sch = d.schedules[d.schedules.game_type == "REG"].copy()
  sch["gd"] = pd.to_datetime(sch.gameday)
  gday, prevgap = {}, {}
  for t in set(sch.home_team) | set(sch.away_team):
    g = sch[(sch.home_team == t) | (sch.away_team == t)].sort_values("gd")
    for s_, w_, gd, prev in zip(g.season, g.week, g.gd, g.gd.shift(1)):
      tt = D.RELOCATED.get(t, t)
      gday[(int(s_), int(w_), tt)] = gd
      prevgap[(int(s_), int(w_), tt)] = (gd - prev).days if pd.notna(prev) and (gd - prev).days < 30 else 99
  ah["team"] = ah.team.map(lambda t: D.RELOCATED.get(t, t))
  ah["short"] = [float(prevgap.get((int(s_), int(w_), t), 99) <= 5) for s_, w_, t in zip(ah.season, ah.week, ah.team)]

  # ---------------- (AQ) short-week flag in the full-week model
  rows = []
  for s in TEST:
    tr = ah[(ah.season < s) & (ah.game_status != "OUT")]
    te = ah[(ah.season == s) & (ah.game_status != "OUT")].copy()
    m0 = gb().fit(feats(tr), tr.played)
    m1 = gb().fit(feats(tr).assign(short=tr.short.to_numpy()), tr.played)
    te["p0"] = m0.predict_proba(feats(te))[:, 1]
    te["p1"] = m1.predict_proba(feats(te).assign(short=te.short.to_numpy()))[:, 1]
    rows.append(te)
  Q = pd.concat(rows)
  y = Q.played.astype(float)
  Q["d"] = (Q.p1 - y) ** 2 - (Q.p0 - y) ** 2
  Q["g"] = Q.season.astype(str) + "-" + Q.week.astype(str)
  sh = Q[Q.short > 0]
  m, lo, hi = ci(sh.d, sh.g); ma, loa, hia = ci(Q.d, Q.g)
  c = sh.assign(dec=pd.qcut(sh.p1.rank(method="first"), 10, labels=False)).groupby("dec").agg(p=("p1", "mean"), y=("played", "mean"))
  print(f"[AQ] short-week rows {len(sh)} of {len(Q)}; played {sh.played.mean():.1%} vs {Q[Q.short == 0].played.mean():.1%} other weeks")
  print(f"[AQ] short-week rows: Brier {((sh.p0 - sh.played) ** 2).mean():.4f} -> {((sh.p1 - sh.played) ** 2).mean():.4f}, {m:+.4f} [{lo:+.4f}, {hi:+.4f}]")
  print(f"[AQ] all rows: {ma:+.4f} [{loa:+.4f}, {hia:+.4f}]; calibration (short weeks) max decile gap {100 * (c.p - c.y).abs().max():.1f} points")
  print("[AQ] GATE:", "PASS" if hi < 0 and hia < 0.0005 and (c.p - c.y).abs().max() <= 0.02 else "FAIL")

  # ---------------- (AP) stage by the calendar vs the heuristic, replayed at the end of each derived report day
  pr = pd.concat([dated(cdir, s) for s in TEST], ignore_index=True).drop_duplicates(["season", "week", "gsis_id"], keep="last")
  A = ah[ah.season.isin(TEST)].merge(pr[["season", "week", "gsis_id", "dates", "days"]].rename(columns={"days": "days_api"}),
                                     on=["season", "week", "gsis_id"], how="inner")
  A = A[A.dates.notna()].copy()
  A["dl"] = A.dates.str.split(",").map(lambda v: [x for x in v if x])
  A["cs"] = A.days_api.fillna("").str.replace("?", "", regex=False)
  A = A[A.dl.str.len() == A.cs.str.len()]
  out = []
  for s in TEST:
    tr = ah[ah.season < s]
    full = gb().fit(feats(tr[tr.game_status != "OUT"]), tr[tr.game_status != "OUT"].played)
    f3 = tr[tr.days.fillna("").str.len() == 3]
    part = {k: gb().fit(feats(f3.assign(days=f3.days.str[:k], game_status="None")), f3.played) for k in (1, 2)}
    te = A[A.season == s]
    for (w, t), g in te.groupby(["week", "team"]):
      gd = gday.get((s, int(w), t))
      if gd is None:
        continue
      rd = [(gd - pd.Timedelta(days=x)).strftime("%Y-%m-%d") for x in LAG.get(gd.weekday(), [4, 3, 2])]
      for k, day in enumerate(rd, 1):
        vis = []
        for x in g.itertuples():
          dd = "".join(c for c, dt in zip(x.cs, x.dl) if dt <= day)
          if dd:
            vis.append((x, dd))
        if not vis:
          continue
        gs_vis = k == 3
        heur = any(len(dd) >= 3 for _, dd in vis) or (gs_vis and any(x.game_status not in ("None", None, "nan") for x, _ in vis))
        cal = k == 3
        for x, dd in vis:
          gst = x.game_status if gs_vis else "None"
          if gst == "OUT":
            continue
          r = pd.DataFrame([{"season": s, "week": int(w), "gsis_id": x.gsis_id, "position": x.position, "team": t,
                             "days": dd, "game_status": gst}])
          X = feats(r)
          pf = full.predict_proba(X)[:, 1][0]
          pp = part[len(dd)].predict_proba(X)[:, 1][0] if len(dd) in part else pf
          out.append({"season": s, "week": int(w), "k": k, "y": float(x.played), "heur": heur, "cal": cal,
                      "ph": pf if heur else pp, "pc": pf if cal else pp})
  R = pd.DataFrame(out)
  R["g"] = R.season.astype(str) + "-" + R.week.astype(str)
  R["d"] = (R.pc - R.y) ** 2 - (R.ph - R.y) ** 2
  dis = R[R.heur != R.cal]
  print(f"[AP] replayed player-days {len(R)}; rules disagree on {len(dis)} ({len(dis) / len(R):.1%}): "
        f"heuristic final early {int((dis.heur & ~dis.cal).sum())}, late {int((~dis.heur & dis.cal).sum())}")
  if len(dis):
    m, lo, hi = ci(dis.d, dis.g)
    print(f"[AP] disagreeing rows: Brier heuristic {((dis.ph - dis.y) ** 2).mean():.4f} -> calendar {((dis.pc - dis.y) ** 2).mean():.4f}, {m:+.4f} [{lo:+.4f}, {hi:+.4f}]")
  ma, loa, hia = ci(R.d, R.g)
  print(f"[AP] all rows: {ma:+.5f} [{loa:+.5f}, {hia:+.5f}]")
  print("[AP] GATE:", "PASS" if len(dis) and hi < 0 and hia < 0.0005 else "FAIL")


if __name__ == "__main__":
  main()
