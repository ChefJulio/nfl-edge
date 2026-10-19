"""(AY3) the healthy-scratch model's label = the game-day active list, not a snap (pre-registered 2026-10-18,
docs/INSIGHTS.md).

Usage: python tools/scratch_dressed_eval.py
Walk-forward 2021-25: season s trained on 2019..s-1, production's scratch model (label: took a snap) and the variant
(injuries.scratch_label = "dressed": label and history = on the game-day active list). Both scored against the dressed
label on rows not on the injury report whose week's inactives are published. GATE: Brier lower, 95% CI over
season-weeks excluding 0; predicted vs actual inactive rate within 2 points overall and for QBs.
"""
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402

import run as RUN  # noqa: E402
from nfledge.config import load_config, load_scoring  # noqa: E402
from nfledge.data import load_all  # noqa: E402


def tables(im, seasons):
  out = {}
  for s in seasons:
    t = im.scratch_table(s)
    out[s] = t[t.final & (t.week <= im.data.completed_weeks(s)) & ~t.on_report & t.observable & (t.week >= 2)].copy()
  return out


def main():
  cfg, sc = load_config(), load_scoring()
  data = load_all(cfg)
  season, week = data.current_season, RUN.display_week(data)
  eng, _ = RUN.cached_model(data, cfg, sc, season, week)
  im = eng.injury_model
  seasons = [s for s in range(2019, 2026) if s in data.seasons]
  im.cfg = copy.deepcopy(im.cfg); im.cfg.setdefault("injuries", {})["scratch_label"] = None
  base = tables(im, seasons)
  im.cfg["injuries"]["scratch_label"] = "dressed"
  new = tables(im, seasons)
  cols = im.scratch_cols
  out = []
  for s in range(2021, 2026):
    trA = pd.concat([base[x] for x in seasons if x < s]); trB = pd.concat([new[x] for x in seasons if x < s])
    mA = HistGradientBoostingClassifier(**im._gb_params(), random_state=0).fit(trA[cols], trA.active)
    mB = HistGradientBoostingClassifier(**im._gb_params(), random_state=0).fit(trB[cols], trB.active)
    a = base[s].set_index(["week", "gsis_id"]); b = new[s].set_index(["week", "gsis_id"])
    j = b[cols + ["active", "pos"]].join(a[cols], rsuffix="_o", how="inner")  # the dressed label, both models' inputs
    j["pA"] = mA.predict_proba(j[[c + "_o" for c in cols]].set_axis(cols, axis=1))[:, 1]
    j["pB"] = mB.predict_proba(j[cols])[:, 1]
    j["season"] = s
    out.append(j.reset_index())
  T = pd.concat(out)
  y = T.active.astype(float)
  T["d"] = (T.pB - y) ** 2 - (T.pA - y) ** 2
  T["g"] = T.season.astype(str) + "-" + T.week.astype(str)
  gs = T.groupby("g").d.agg(["sum", "size"])
  idx = np.random.default_rng(0).integers(0, len(gs), (4000, len(gs)))
  bt = gs["sum"].to_numpy()[idx].sum(1) / gs["size"].to_numpy()[idx].sum(1)
  lo, hi = np.percentile(bt, [2.5, 97.5])
  print(f"[AY3] rows {len(T)} (not on the report, inactives published), dressed {y.mean():.1%}")
  print(f"[AY3] Brier vs the dressed label: snap model {((T.pA - y) ** 2).mean():.4f} -> dressed model {((T.pB - y) ** 2).mean():.4f}, "
        f"{T.d.mean():+.4f} [{lo:+.4f}, {hi:+.4f}]")
  cal = []
  for lab, m in (("all", T.index == T.index), ("QB", T.pos == "QB"), ("RB", T.pos == "RB"), ("WR", T.pos == "WR"), ("TE", T.pos == "TE")):
    z = T[m]
    act, pa, pb = 1 - z.active.mean(), 1 - z.pA.mean(), 1 - z.pB.mean()
    cal.append((lab, abs(pb - act)))
    print(f"[AY3]   {lab}: inactive {act:.1%}, snap model says {pa:.1%}, dressed model {pb:.1%} (n {len(z)})")
  ok = hi < 0 and all(e <= 0.02 for lab, e in cal if lab in ("all", "QB"))
  print("[AY3] GATE:", "PASS" if ok else "FAIL")
  # live: this week, production rows vs the variant fitted on every finished season
  allB = pd.concat(new.values())
  mL = HistGradientBoostingClassifier(**im._gb_params(), random_state=0).fit(allB[cols], allB.active)
  cur = im.scratch_table(season); cur = cur[cur.week == week]
  names = dict(zip(data.rosters.gsis_id, data.rosters.full_name))
  for g in ("00-0038400",):
    r_ = cur[cur.gsis_id == g]
    if len(r_):
      print(f"[AY3] live: {names.get(g)} P(dressed) {mL.predict_proba(r_[cols])[:, 1][0]:.1%}")


if __name__ == "__main__":
  main()
