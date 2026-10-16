"""One availability model for every day of the week (pre-registered 2026-10-16, docs/INSIGHTS.md (I)).

Usage: python tools/week_avail_eval.py [--first=2021] [--last=2025]

Rows (nfledge/tuesday.py week_rows): (player, game) at stage 0 (Tuesday, no report), 1 (Wednesday), 2 (Thursday),
3 (final report). The one model sees the Tuesday block from his last game + this week's report as it stood at that
stage. Each stage is compared with what the site uses there today, retrained here on the same rows and labels:
stage 0 the Tuesday model; 1-2 the partial-week practice models (3-day weeks cut to k days, no game status); 3 the
full-week practice model; both practice models with the role input as configured. Walk-forward: season s trains on
seasons before s. Game status Out at stage 3 is excluded (0% by rule).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge import tuesday as T  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.injuries import InjuryModel, practice_features  # noqa: E402


def ci(diff: pd.Series, cl: pd.Series):
  gr = pd.DataFrame({"d": diff.to_numpy(), "c": cl.to_numpy()}).groupby("c").d.agg(["sum", "size"])
  s_, n_ = gr["sum"].to_numpy(), gr["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(gr), (4000, len(gr)))
  bt = s_[idx].sum(1) / n_[idx].sum(1)
  return diff.mean(), np.percentile(bt, 2.5), np.percentile(bt, 97.5)


def prac_frame(x: pd.DataFrame, final: bool) -> pd.DataFrame:
  """Rows in the shape the site's practice models take."""
  gs = x.gs_now.str.upper().where(x.gs_now != "None", "None") if final else pd.Series("None", index=x.index)
  return pd.DataFrame({"gsis_id": x.gsis_id.to_numpy(), "season": x.season.to_numpy(), "week": x.week.to_numpy(),
                       "position": x.pos.to_numpy(), "days": x.days_now.to_numpy(), "game_status": gs.to_numpy()}, index=x.index)


def main():
  from sklearn.ensemble import HistGradientBoostingClassifier
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  first, last = int(opt.get("first", 2021)), int(opt.get("last", 2025))
  cfg = load_config()
  d = D.load_all(cfg)
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  rep, hurt = T.report_rows(d), T.hurt_notes(d, cache)
  w = T.week_rows(d, rep, hurt).dropna(subset=["y"])
  tue = T.build_rows(d, rep, hurt).dropna(subset=["y"])
  w = w[~((w.stage == 3) & (w.gs_now == "Out"))]
  print(f"week rows {len(w)}: " + ", ".join(f"stage {s} {int((w.stage == s).sum())}" for s in T.STAGES), flush=True)
  im = InjuryModel.__new__(InjuryModel)
  im.data, im.cfg = d, cfg
  gb = im._gb_params()
  X = lambda f: im._with_role(practice_features(f), f)  # noqa: E731  the site's practice-model inputs
  calib = opt.get("calibrate", "1") == "1"  # (I2) calibrated; --calibrate=0 reproduces (I)
  out = []
  newest = int(w.season.max())
  seasons = list(range(first, last + 1)) + ([newest] if calib and newest > last else [])
  for s in seasons:
    tr, te = w[w.season < s], w[w.season == s].copy()
    if not len(te):
      continue
    te["p_new"] = (T.week_predict(T.week_model(w, s), te) if calib
                   else T.week_fit(tr).predict_proba(T.week_features(te))[:, 1])
    te["p_base"] = np.nan
    # stage 0: the shipped Tuesday model, on its own population
    tt = tue[tue.season < s]
    m0 = T.fit(tt)
    t0 = tue[tue.season == s]
    p0 = dict(zip(zip(t0.gsis_id, t0.week), m0.predict_proba(T.features(t0))[:, 1]))
    i0 = te.index[te.stage == 0]
    te.loc[i0, "p_base"] = [p0.get((g, wk), np.nan) for g, wk in zip(te.loc[i0, "gsis_id"], te.loc[i0, "week"])]
    # stage 3: the full-week practice model, trained on final reports
    f3 = tr[(tr.stage == 3) & (tr.on_now == 1)]
    m3 = HistGradientBoostingClassifier(**gb, random_state=0).fit(X(prac_frame(f3, True)), f3.y)
    cols = list(X(prac_frame(f3.head(5), True)).columns)
    i3 = te.index[(te.stage == 3) & (te.on_now == 1)]
    te.loc[i3, "p_base"] = m3.predict_proba(X(prac_frame(te.loc[i3], True))[cols])[:, 1]
    # stages 1-2: partial-week models, 3-day final weeks cut to k days, no game status
    full3 = f3[f3.days_now.str.len() == 3]
    for k in (1, 2):
      cut = full3.assign(days_now=full3.days_now.str[:k])
      mk = HistGradientBoostingClassifier(**gb, random_state=0).fit(X(prac_frame(cut, False))[cols], cut.y)
      ik = te.index[(te.stage == k) & (te.on_now == 1)]
      te.loc[ik, "p_base"] = mk.predict_proba(X(prac_frame(te.loc[ik], False))[cols])[:, 1]
    out.append(te)
  r = pd.concat(out)
  r["b_new"] = (r.p_new - r.y) ** 2
  r["b_base"] = (r.p_base - r.y) ** 2
  fresh = r[r.season > last]  # (I2) this season so far: nothing was fit or tuned on it
  r = r[r.season <= last]
  ok_all = True
  names = {0: "stage 0 Tuesday (vs Tuesday model)", 1: "stage 1 Wednesday (vs partial 1-day)",
           2: "stage 2 Thursday (vs partial 2-day)", 3: "stage 3 final report (vs practice model)"}
  for st in T.STAGES:
    g = r[(r.stage == st) & r.p_base.notna()]
    m, lo, hi = ci(g.b_new - g.b_base, g.season.astype(str) + "-" + g.week.astype(str))
    dec = g.assign(dec=pd.qcut(g.p_new, 10, labels=False, duplicates="drop")).groupby("dec").agg(p=("p_new", "mean"), a=("y", "mean"))
    worst = float((dec.p - dec.a).abs().max())
    wins = sum(x.b_new.mean() < x.b_base.mean() for _, x in g.groupby("season"))
    if opt.get("deciles"):
      print((dec * 100).round(1).T.to_string())
    if st == 3:
      ok = hi < 0
    elif st in (1, 2):
      ok = hi < 0.002
    else:
      ok = hi < 0.002 if not calib else True  # (I2) Tuesday keeps the dedicated Tuesday model: shown, not gated
    ok = ok and (worst <= 0.04 or (calib and st == 0))
    ok_all &= ok
    print(f"\n{names[st]} (n {len(g)}): Brier {g.b_base.mean():.4f} -> {g.b_new.mean():.4f}  diff {m:+.4f} [{lo:+.4f}, {hi:+.4f}]  "
          f"better {wins}/{g.season.nunique()} seasons; worst decile {100 * worst:.1f} pts  -> {'ok' if ok else 'FAIL'}")
    if st == 3:
      for p, x in g.groupby("pos"):
        mp, lp, hp = ci(x.b_new - x.b_base, x.season.astype(str) + "-" + x.week.astype(str))
        bad = lp > 0
        ok_all &= not bad
        print(f"  {p}: {x.b_base.mean():.4f} -> {x.b_new.mean():.4f}  {mp:+.4f} [{lp:+.4f}, {hp:+.4f}]{'  WORSE' if bad else ''}")
      mp_ = g[g.played_last == 0]
      print(f"  missed last game (n {len(mp_)}): {mp_.b_base.mean():.4f} -> {mp_.b_new.mean():.4f}; predicted "
            f"{100 * mp_.p_base.mean():.1f} / {100 * mp_.p_new.mean():.1f}% vs played {100 * mp_.y.mean():.1f}%")
  g = r[(r.stage == 0) & r.p_base.isna()]
  print(f"\nstage 0 rows outside the Tuesday population (first listed this week; site shows them healthy), n {len(g)}: "
        f"model {g.b_new.mean():.4f}, predicted {100 * g.p_new.mean():.1f}% vs played {100 * g.y.mean():.1f}%")
  for k in (1, 2):
    g = r[(r.stage == k) & (r.p_base.notna())]
    mc = g[(g.played_last == 0)]
    print(f"stage {k}, missed last game (n {len(mc)}): {mc.b_base.mean():.4f} -> {mc.b_new.mean():.4f}; predicted "
          f"{100 * mc.p_base.mean():.1f} / {100 * mc.p_new.mean():.1f}% vs played {100 * mc.y.mean():.1f}%")
  if len(fresh):
    print(f"\nuntouched check: {int(fresh.season.max())} weeks {int(fresh.week.min())}-{int(fresh.week.max())} (trained through {last})")
    for st in (1, 2, 3):
      g = fresh[(fresh.stage == st) & fresh.p_base.notna()]
      dlt = g.b_new.mean() - g.b_base.mean()
      good = bool(dlt < 0) if st == 3 else bool(dlt <= 0)
      ok_all &= good
      print(f"  stage {st} (n {len(g)}): {g.b_base.mean():.4f} -> {g.b_new.mean():.4f}  ({dlt:+.4f})  {'ok' if good else 'FAIL'}")
  print(f"\nAVAILABILITY GATE: {'PASS' if ok_all else 'FAIL'}  (then fantasy MAE via tools/experiments.py before shipping)")


if __name__ == "__main__":
  main()
