"""(DN) Refit the team ratings after a week's Thursday (Friday / Saturday) games (pre-registered 2026-10-26,
docs/INSIGHTS.md (DN)).

Usage: python tools/thursday_refit_eval.py [--jobs=N] [--first=2021] [--last=2025] [--report]
Writes cache/thursday_refit.parquet. For each season and week N (2-17) with games before its Sunday:
  stale   games before week N (TeamModel.fit(season, N), Elo before N): what the site has before Sunday today
  early   also week N's games before its Sunday (fit(season, N + 1) excluding the week's Sunday and Monday games; Elo
          on a schedule with those scores masked)
Win chance as tools/monday_refit_eval.py ((BA)): the live model-only form, the usual starters in both arms. Scored:
week N's Sunday and Monday games (k = 0, gated) and week N+1 (k = 1, reported).
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

from monday_refit_eval import boot_ci  # noqa: E402

OUT = ROOT / "cache" / "thursday_refit.parquet"


def season_rows(season: int) -> pd.DataFrame:
  for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(v, "2")
  from nfledge import data as D, elo, powerc
  from nfledge.config import load_config, load_scoring
  from nfledge.engine import Engine
  from nfledge.report import formula_weights, league_volume, logistic, unit_points
  cfg = load_config()
  wm = cfg["report"]["win_model"]
  d = D.load_all(cfg)
  eng = Engine(d, cfg, load_scoring(), ["QB", "RB", "WR", "TE"]).train(season)
  fw = formula_weights(eng)
  allsch = d.schedules
  sch = allsch[(allsch.season == season) & (allsch.game_type == "REG")].copy()
  sch["day"] = pd.to_datetime(sch.gameday)
  rel = lambda t: D.RELOCATED.get(t, t)  # noqa: E731
  last = int(sch.week.max())
  rows = []
  for n in range(2, last):
    wk = sch[sch.week == n]
    if wk.home_score.isna().any():
      break
    sundays = wk.day[wk.day.dt.weekday == 6]
    if not len(sundays):
      continue
    first_sun = sundays.min()
    early = frozenset(wk.game_id[wk.day < first_sun])
    if not early:
      continue
    rest = frozenset(wk.game_id) - early
    usual = powerc.usual_starters(eng, season, n)
    masked = allsch.copy()
    masked.loc[masked.game_id.isin(rest), ["home_score", "away_score"]] = np.nan
    snap = {}
    for arm, tw, ex, sc in (("stale", n, None, allsch), ("early", n + 1, rest, masked)):
      r = eng.tm.fit(season, tw, exclude=ex)
      # both arms on week N's pre-game league volume (league_volume at N + 1 would count the excluded Sunday games' plays)
      net = unit_points(r, league_volume(eng, season, n, r), usual, fw).net
      snap[arm] = (net.rank(ascending=False, method="min").to_dict(), elo.ratings_before(sc, season, tw, wm))

    def chance(arm, g):
      rk, el = snap[arm]
      h, a = rel(g.home_team), rel(g.away_team)
      if h not in rk or a not in rk:
        return np.nan
      x = (wm["week_home"] * (g.location != "Neutral") + wm["week_rank_gap"] * (rk[a] - rk[h])
           + wm["week_elo_per_100"] * (el.get(h, elo.MEAN) - el.get(a, elo.MEAN)) / 100)
      return float(logistic(x))
    thu_teams = {rel(t) for g in wk[wk.game_id.isin(early)].itertuples() for t in (g.home_team, g.away_team)}
    for k, gs in ((0, wk[wk.game_id.isin(rest)]), (1, sch[sch.week == n + 1])):
      for g in gs.itertuples():
        if pd.isna(g.home_score) or g.home_score == g.away_score:
          continue
        rows.append({"season": season, "week": n, "k": k, "game_id": g.game_id, "y": float(g.home_score > g.away_score),
                     "p_stale": chance("stale", g), "p_early": chance("early", g), "n_early": len(early),
                     "thu_team": rel(g.home_team) in thu_teams or rel(g.away_team) in thu_teams})
    print(f"[DN] {season} week {n}: {len(early)} early game(s)", flush=True)
  return pd.DataFrame(rows)


def report(df: pd.DataFrame) -> None:
  df = df.dropna(subset=["p_stale", "p_early"])
  key = (df.season.astype(str) + "-" + df.week.astype(str)).to_numpy()
  e = ((df.p_early - df.y) ** 2 - (df.p_stale - df.y) ** 2).to_numpy()
  fmt = lambda t: f"{t[0]:+.4f} [{t[1]:+.4f}, {t[2]:+.4f}]"  # noqa: E731
  print(f"{len(df)} scored rows, seasons {df.season.min()}-{df.season.max()}")
  for k, lab in ((0, "week N's Sunday / Monday games"), (1, "week N+1")):
    m = (df.k == k).to_numpy()
    print(f"  {lab}: {m.sum()} games  Brier stale {((df.p_stale - df.y) ** 2)[m].mean():.4f}  early {((df.p_early - df.y) ** 2)[m].mean():.4f}"
          f"   early - stale {fmt(boot_ci(e[m], key[m]))}")
  m0 = (df.k == 0).to_numpy()
  for flag, lab in ((True, "involving a Thursday team"), (False, "not")):
    mm = m0 & (df.thu_team == flag).to_numpy()
    if mm.any():  # a Thursday team plays no second game that week: none on this side
      print(f"    week N games {lab}: {mm.sum()}  early - stale {fmt(boot_ci(e[mm], key[mm]))}")
  for s in sorted(df.season.unique()):
    ms = m0 & (df.season == s).to_numpy()
    print(f"    {s}: early - stale {e[ms].mean():+.4f} ({ms.sum()} games)")
  g = boot_ci(e[m0], key[m0])
  print(f"  mean win-chance move on those games: {100 * (df.p_early - df.p_stale)[m0].abs().mean():.1f} points")
  ok = g[2] < 0.005
  print(f"GATE week N's Sunday / Monday games not worse, CI upper < +0.005: {'PASS' if ok else 'FAIL'} {fmt(g)}")


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  if "--report" in sys.argv:
    return report(pd.read_parquet(OUT))
  first, last = int(opt.get("first", 2021)), int(opt.get("last", 2025))
  seasons = list(range(first, last + 1))
  jobs = int(opt.get("jobs", min(len(seasons), os.cpu_count() or 1)))
  with ProcessPoolExecutor(jobs) as ex:
    df = pd.concat(list(ex.map(season_rows, seasons)), ignore_index=True)
  df.to_parquet(OUT, index=False)
  print(f"wrote {OUT} ({len(df)} rows)")
  report(df)


if __name__ == "__main__":
  main()
