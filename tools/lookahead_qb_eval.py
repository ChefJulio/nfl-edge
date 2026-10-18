"""(AW) the game model rates a starting QB in the player projections (pre-registered 2026-10-18, docs/INSIGHTS.md).

Usage: python tools/lookahead_qb_eval.py [--jobs=N] [--proj (the second look: runs only the proj arm)] [--reuse (score saved runs)]
Walk-forward 2021-25, weeks 3+, injuries on, model-only mode (use_vegas=False, what a lookahead week sees). Arms:
none (production: no QB rated by the game model), asof (each team's most recent starter before the week), game (the
game's starter, most dropbacks). Rows: tools/experiments.py "relevant" rows of the none arm. GATE (asof vs none):
player MAE lower, 95% CI over season-weeks excluding 0, no position's CI entirely above 0.
"""
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SEASONS = [2021, 2022, 2023, 2024, 2025]
ARMS = ("none", "asof", "game", "proj")
PROJ_ONLY = "--proj" in sys.argv
OUT = ROOT / "cache" / "experiments"


def season_job(season: int) -> pd.DataFrame:
  from nfledge import backtest as B
  from nfledge.config import load_config, load_scoring
  from nfledge.data import load_all
  from nfledge.engine import Engine
  cfg = load_config()
  cfg["data"]["history_seasons"] = 8
  data, scoring = load_all(cfg), load_scoring()
  eng = Engine(data, cfg, scoring, positions=["QB", "RB", "WR", "TE"])
  eng.train(season, use_injuries=True)
  tl = eng.team_ledger
  out = []
  for w in range(3, data.completed_weeks(season) + 1):
    past = tl[((tl.season == season) & (tl.week < w)) | (tl.season < season)].dropna(subset=["qb"])
    asof = past.sort_values(["season", "week"]).groupby("team").qb.last().to_dict()
    now = tl[(tl.season == season) & (tl.week == w)].dropna(subset=["qb"])
    game = dict(asof); game.update(dict(zip(now.team, now.qb)))
    raw, team_ppg, implied = B.raw_baselines(eng, season, w)
    arms = (("proj", "proj"),) if PROJ_ONLY else (("none", None), ("asof", asof), ("game", game))
    for arm, st in arms:
      if st == "proj":  # second look: the projected starter (top non-sitting QB of a first projection)
        p0 = eng.project_week(season, w, use_injuries=True, use_vegas=False, quiet=True)
        q0 = p0[(p0.pos == "QB") & ~p0.sits].sort_values("db").groupby("team").tail(1)
        st = dict(asof); st.update(dict(zip(q0.team, q0.gsis_id)))
      p = eng.project_week(season, w, use_injuries=True, use_vegas=False, quiet=True, starters=st)
      p = eng.attach_actuals(p, season, w).join(raw, on="gsis_id")
      p["vegas"] = p.raw_fpg * (p.team.map(implied) / p.team.map(team_ppg)).fillna(1.0)
      tp = eng.last_team_preds[["game_id", "team", "points_hat"]].assign(season=season, week=w, arm=arm).merge(
        tl[(tl.season == season) & (tl.week == w)][["team", "points"]], on="team", how="left")
      out.append((p.assign(arm=arm), tp))
  P = pd.concat([x[0] for x in out], ignore_index=True)
  T = pd.concat([x[1] for x in out], ignore_index=True)
  keep = ["season", "week", "gsis_id", "team", "pos", "proj", "actual", "played", "raw_fpg", "raw_games", "vegas", "arm"]
  P = P[keep]
  OUT.mkdir(parents=True, exist_ok=True)
  tag = "aw_proj" if PROJ_ONLY else "aw"
  P.to_parquet(OUT / f"{tag}_players_{season}.parquet"); T.to_parquet(OUT / f"{tag}_teams_{season}.parquet")
  print(f"[AW] {season} done", flush=True)
  return season


def main():
  jobs = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--jobs=")), 1)
  todo = [s for s in SEASONS if "--reuse" not in sys.argv]
  if jobs > 1:
    with ProcessPoolExecutor(jobs) as ex:
      list(ex.map(season_job, todo))
  else:
    for s in todo:
      season_job(s)
  from experiments import relevant, week_bootstrap
  P = pd.concat([pd.read_parquet(OUT / f"{t}_players_{s}.parquet") for s in SEASONS for t in ("aw", "aw_proj")
                 if (OUT / f"{t}_players_{s}.parquet").exists()], ignore_index=True)
  keys = ["season", "week", "gsis_id"]
  base = relevant(P[P.arm == "none"])[keys + ["pos", "actual", "proj"]]
  verdict = {}
  for arm in [a for a in ("asof", "game", "proj") if (P.arm == a).any()]:
    j = base.merge(P[P.arm == arm][keys + ["proj"]].drop_duplicates(keys), on=keys, how="left", suffixes=("_ref", ""))
    j["proj"] = j.proj.fillna(j.proj_ref)
    print(f"[AW] {arm} vs none (relevant rows, model-only mode):")
    worst_lo = []
    for pos in ["QB", "RB", "WR", "TE", "ALL"]:
      m = j if pos == "ALL" else j[j.pos == pos]
      d = (m.actual - m.proj).abs() - (m.actual - m.proj_ref).abs()
      lo, hi = week_bootstrap(d, m.season.astype(str) + "-" + m.week.astype(str))
      by = {int(s): round(float(x.mean()), 4) for s, x in d.groupby(m.season)}
      print(f"  {pos:4s} n {len(m):6d}  MAE {(m.actual - m.proj_ref).abs().mean():.3f} -> {(m.actual - m.proj).abs().mean():.3f}"
            f"  {d.mean():+.4f} [{lo:+.4f}, {hi:+.4f}]  by season {by}")
      if pos == "ALL":
        verdict[arm] = hi < 0
      else:
        worst_lo.append(lo)
    verdict[arm] = verdict[arm] and max(worst_lo) <= 0
  T = pd.concat([pd.read_parquet(OUT / f"{t}_teams_{s}.parquet") for s in SEASONS for t in ("aw", "aw_proj")
                 if (OUT / f"{t}_teams_{s}.parquet").exists()], ignore_index=True)
  T = T.dropna(subset=["points"])
  for arm in [a for a in ("asof", "game", "proj") if (T.arm == a).any()]:
    a0 = T[T.arm == "none"].set_index(["season", "week", "team"]); a1 = T[T.arm == arm].set_index(["season", "week", "team"])
    j = a0.join(a1.points_hat.rename("ph"), how="inner")
    d = (j.points - j.ph).abs() - (j.points - j.points_hat).abs()
    lo, hi = week_bootstrap(d.reset_index(drop=True), pd.Series([f"{s}-{w}" for s, w, _ in j.index]))
    print(f"[AW] team points MAE, {arm} vs none: {(j.points - j.points_hat).abs().mean():.3f} -> {(j.points - j.ph).abs().mean():.3f}"
          f"  {d.mean():+.4f} [{lo:+.4f}, {hi:+.4f}]  (n {len(j)})")
  print("[AW] GATE (asof vs none):", "PASS" if verdict["asof"] else "FAIL", "| game arm:", "better" if verdict["game"] else "not shown better")
  if "proj" in verdict:
    print("[AW] second look GATE (proj vs none):", "PASS" if verdict["proj"] else "FAIL")


if __name__ == "__main__":
  main()
