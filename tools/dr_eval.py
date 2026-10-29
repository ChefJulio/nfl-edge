"""(DR) the return model's injury for players on a reserve list (pre-registered 2026-10-28, docs/INSIGHTS.md).

Usage: python tools/dr_eval.py

The return model reads a player's injury from that week's report; a player on IR / PUP is off it, so ~93% of
reserve-list weeks had no body part. Arms (injury known at the time only):
  R0  as is
  R1  no body part that week -> his last report listing this season since the start of this absence (from the
      week of his last game played - 2)
  R2  R1, then ESPN news naming the injury at the reserve-list move (data/history/ir_names.json "espn", 2023 on),
      published after his last game played and on or before the state's game day
Walk-forward (each season trains on every earlier loaded season); scored 2022-25, 2026 the untouched check.
GATE: (a) Brier vs R0, upper 95% (season-week clusters) < 0; (b) QB RB WR TE no worse, upper < +0.0005; (c) 2026 no
worse (point estimate). The simplest passing arm ships.
"""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.returns import POS_GROUP, ReturnModel, _injury_code, played_set  # noqa: E402

FANTASY = {"QB", "RB", "WR", "TE"}
SCORED = range(2022, 2026)


def gb(feats):
  from sklearn.ensemble import HistGradientBoostingClassifier
  cat = [feats.index(c) for c in ("inj_code", "pos_code") if c in feats]
  return HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_depth=3, random_state=0, categorical_features=cat)


def ci(diff: pd.Series, cl: pd.Series):
  gr = pd.DataFrame({"d": diff.to_numpy(), "c": cl.to_numpy()}).groupby("c").d.agg(["sum", "size"])
  s_, n_ = gr["sum"].to_numpy(), gr["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(gr), (4000, len(gr)))
  bt = s_[idx].sum(1) / n_[idx].sum(1)
  return diff.mean(), np.percentile(bt, 2.5), np.percentile(bt, 97.5)


def main():
  cfg = copy.deepcopy(load_config())
  cfg["data"]["history_seasons"] = 8
  data = D.load_all(cfg)
  m = ReturnModel(data, played_set(data))
  S = m.states(sorted(data.seasons))
  S["grp"] = S.position.map(POS_GROUP).fillna("other")
  # R1: his last listing this season, from 2 weeks before his last game played on
  inj = data.injuries
  inj = inj[(inj.game_type == "REG") & inj.gsis_id.notna() & inj.report_primary_injury.notna()]
  listed = {}
  for s, w, g, part in zip(inj.season, inj.week, inj.gsis_id, inj.report_primary_injury):
    listed.setdefault((int(s), g), []).append((int(w), str(part)))
  for k in listed:
    listed[k].sort()

  def carried(x):
    if isinstance(x.injury, str) and x.injury:
      return x.injury
    lo = (int(x.last_played) if x.last_played == x.last_played and x.last_played is not None else int(x.week) - int(x.missed)) - 2
    hit = [p for w, p in listed.get((int(x.season), x.gsis_id), []) if lo <= w <= int(x.week)]
    return hit[-1] if hit else None
  S["inj_r1"] = [carried(x) for x in S.itertuples()]
  # R2: ESPN's reserve-list news, published after his last game and by this state's game day
  names = json.loads((ROOT / "data" / "history" / "ir_names.json").read_text(encoding="utf-8")).get("p", {})

  def espn(x):
    if isinstance(x.inj_r1, str) and x.inj_r1:
      return x.inj_r1
    d1 = m._day(x.season, x.week, x.team)
    lp = x.last_played if x.last_played == x.last_played else None
    d0 = m._day(x.season, lp, x.team) if lp is not None else pd.NaT
    if pd.isna(d1):
      return None
    hits = [(d, part) for ns, d, part, src in names.get(x.gsis_id, [])
            if src == "espn" and ns == x.season and d and not d.startswith("wk:") and part != "Undisclosed"
            and pd.Timestamp(d) <= d1 and (pd.isna(d0) or pd.Timestamp(d) > d0)]
    return max(hits)[1] if hits else None  # the latest by this game day
  S["inj_r2"] = [espn(x) for x in S.itertuples()]
  res = S.desig.isin(["ir", "ir_return", "pup", "reserve_other"])
  for a, c in (("R0", "injury"), ("R1", "inj_r1"), ("R2", "inj_r2")):
    has = S[c].apply(lambda v: isinstance(v, str) and v != "")
    print(f"{a}: body part on {100 * has[res].mean():.1f}% of reserve-list states ({res.sum()}), {100 * has.mean():.1f}% of all ({len(S)})")
  feats = list(m.feats)
  arms = {"R0": "injury", "R1": "inj_r1", "R2": "inj_r2"}
  out = []
  for s in list(SCORED) + [max(data.seasons)]:
    tr, te = S[S.season < s].copy(), S[S.season == s].copy()
    if not len(te):
      continue
    for a, c in arms.items():
      trc, tec = tr.assign(inj_code=_injury_code(tr[c])), te.assign(inj_code=_injury_code(te[c]))
      te[a] = gb(feats).fit(trc[feats], trc.back).predict_proba(tec[feats])[:, 1]
    out.append(te)
  r = pd.concat(out, ignore_index=True)
  r["y"] = r.back.astype(float)
  r["cl"] = r.season.astype(str) + "-" + r.week.astype(str)
  for a in arms:
    r[f"b_{a}"] = (r[a] - r.y) ** 2
  r["res"] = r.desig.isin(["ir", "ir_return", "pup", "reserve_other"])
  sc, chk = r[r.season.isin(SCORED)], r[r.season == max(data.seasons)]
  print(f"\nscored 2022-25: {len(sc)} states ({sc.res.sum()} on a reserve list); 2026 check: {len(chk)}")
  verdict = {}
  for a in ("R1", "R2"):
    d_all = ci(sc[f"b_{a}"] - sc.b_R0, sc.cl)
    f = sc[sc.position.isin(FANTASY)]
    d_f = ci(f[f"b_{a}"] - f.b_R0, f.cl)
    rr = sc[sc.res]
    d_r = ci(rr[f"b_{a}"] - rr.b_R0, rr.cl)
    d_c = ci(chk[f"b_{a}"] - chk.b_R0, chk.cl) if len(chk) else (np.nan, np.nan, np.nan)
    ga, gb_, gc = d_all[2] < 0, d_f[2] < 0.0005, not (d_c[0] > 0)
    verdict[a] = ga and gb_ and gc
    print(f"\n{a} vs R0, Brier R0 {sc.b_R0.mean():.4f} -> {sc[f'b_{a}'].mean():.4f}")
    print(f"  (a) all scored     {d_all[0]:+.4f} [{d_all[1]:+.4f}, {d_all[2]:+.4f}]  {'PASS' if ga else 'FAIL'}")
    print(f"  (b) QB RB WR TE    {d_f[0]:+.4f} [{d_f[1]:+.4f}, {d_f[2]:+.4f}]  {'PASS' if gb_ else 'FAIL'}")
    print(f"  (c) 2026 check     {d_c[0]:+.4f} [{d_c[1]:+.4f}, {d_c[2]:+.4f}]  {'PASS' if gc else 'FAIL'}")
    print(f"  reserve-list only  {d_r[0]:+.4f} [{d_r[1]:+.4f}, {d_r[2]:+.4f}]")
  for a in ("R0", "R1", "R2"):
    x = sc[sc.res]
    print(f"calibration, reserve-list states, {a}: predicted {x[a].mean():.3f} vs back {x.y.mean():.3f}")
  ship = next((a for a in ("R1", "R2") if verdict[a]), None)
  print(f"\n(DR) RESULT: {'PASS, ship ' + ship if ship else 'FAIL, the model stays as is'}")


if __name__ == "__main__":
  main()
