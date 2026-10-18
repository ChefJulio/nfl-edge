"""(AV) "out ahead" counts reserve-list starters (pre-registered 2026-10-18, docs/INSIGHTS.md).

Usage: python tools/ahead_eval.py
The healthy-scratch model (InjuryModel scratch_table / _fit_scratch features and settings) refit walk-forward:
season s trained on the seasons before it (2019 on), both with production's ahead_out and with injuries.ahead_reserve
(starters on a reserve list or off the roster rows still count as out ahead). Brier on not-on-report rows 2021-25.
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
    first = 1 if im.cfg.get("injuries", {}).get("scratch_carry") is True else 2
    out[s] = t[t.final & (t.week <= im.data.completed_weeks(s)) & ~t.on_report & t.observable & (t.week >= first)].copy()
  return out


def main():
  cfg, sc = load_config(), load_scoring()
  data = load_all(cfg)
  season, week = data.current_season, RUN.display_week(data)
  eng, _ = RUN.cached_model(data, cfg, sc, season, week)
  im = eng.injury_model
  seasons = [s for s in range(2019, 2026) if s in data.seasons]
  base = tables(im, seasons)
  im.cfg = copy.deepcopy(im.cfg); im.cfg.setdefault("injuries", {})["ahead_reserve"] = True
  new = tables(im, seasons)
  cols = im.scratch_cols
  out = []
  for s in range(2021, 2026):
    trA = pd.concat([base[x] for x in seasons if x < s]); trB = pd.concat([new[x] for x in seasons if x < s])
    mA = HistGradientBoostingClassifier(**im._gb_params(), random_state=0).fit(trA[cols], trA.active)
    mB = HistGradientBoostingClassifier(**im._gb_params(), random_state=0).fit(trB[cols], trB.active)
    a = base[s].set_index(["week", "gsis_id"]); b = new[s].set_index(["week", "gsis_id"])
    j = a[cols + ["active"]].join(b[cols], rsuffix="_n", how="inner")
    j["pA"] = mA.predict_proba(j[cols])[:, 1]
    j["pB"] = mB.predict_proba(j[[c + "_n" for c in cols]].set_axis(cols, axis=1))[:, 1]
    j["changed"] = j.ahead_out != j.ahead_out_n
    j["season"] = s
    out.append(j.reset_index())
  T = pd.concat(out)
  y = T.active.astype(float)
  T["d"] = (T.pB - y) ** 2 - (T.pA - y) ** 2
  T["g"] = T.season.astype(str) + "-" + T.week.astype(str)

  def ci(x):
    gs = x.groupby("g").d.agg(["sum", "size"])
    idx = np.random.default_rng(0).integers(0, len(gs), (4000, len(gs)))
    bt = gs["sum"].to_numpy()[idx].sum(1) / gs["size"].to_numpy()[idx].sum(1)
    return x.d.mean(), *np.percentile(bt, [2.5, 97.5])
  ch = T[T.changed]
  print(f"[AV] rows {len(T)}, ahead_out changed on {len(ch)} ({len(ch) / len(T):.1%}); by position {ch.groupby(ch.pos if 'pos' in ch else ch.index).size().to_dict() if 'pos' in ch else ''}")
  m, lo, hi = ci(ch)
  print(f"[AV] changed rows: played {ch.active.mean():.1%}, model {ch.pA.mean():.1%} -> {ch.pB.mean():.1%}; Brier {((ch.pA - ch.active) ** 2).mean():.4f} -> {((ch.pB - ch.active) ** 2).mean():.4f}, {m:+.4f} [{lo:+.4f}, {hi:+.4f}]")
  ma, loa, hia = ci(T)
  print(f"[AV] all rows: {ma:+.5f} [{loa:+.5f}, {hia:+.5f}]")
  print("[AV] GATE:", "PASS" if hi < 0 and hia < 0.0005 else "FAIL")
  # this week (live), production's fitted model vs the variant's inputs
  cur = im.scratch_table(season); cur = cur[cur.week == week]
  names = dict(zip(data.rosters.gsis_id, data.rosters.full_name))
  for g in ("00-0038400",):
    r_ = cur[cur.gsis_id == g]
    if len(r_):
      print(f"[AV] live: {names.get(g)} ahead_out {int(r_.ahead_out.iloc[0])}, rank {int(r_['rank'].iloc[0])}")


if __name__ == "__main__":
  main()
