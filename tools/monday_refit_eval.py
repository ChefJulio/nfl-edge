"""(BA) Refit the team ratings once Sunday's games are in (pre-registered 2026-10-19, docs/INSIGHTS.md (BA)).

Usage: python tools/monday_refit_eval.py [--jobs=N] [--first=2021] [--last=2025]
Writes cache/monday_refit.parquet (one row per scored game per arm snapshot) and prints the gate.

For each season and week N (2-17), three snapshots of the ratings and Elo:
  stale    what the site has Monday today: games before week N (TeamModel.fit(season, N), Elo before N)
  monday   the variant: also week N's games except those after its Sunday (the Monday game(s)), Elo the same way
  tuesday  the post-rollover fit: every game through week N (reference, not gated)
Win chance = the live model-only form (config [report.win_model]): logistic(home + rank_gap x (away rank - home rank)
+ elo_per_100 x Elo diff / 100), with the week_* coefficients (Matchups) for week N's and N+1's games, the base ones
(playoff odds) beyond; ranks from each snapshot's net ratings with each team's usual starter (no injury
plan in a backtest; the same QBs in every arm, so only the ratings and Elo differ). Scored: weeks N+1..N+4 (N+1 is
gated) and week N's Monday games (stale vs monday). One worker process per season.
"""
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

OUT = ROOT / "cache" / "monday_refit.parquet"
AHEAD = 4


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
    late = frozenset(wk.game_id[wk.day > sundays.max()]) if len(sundays) else frozenset()
    usual = powerc.usual_starters(eng, season, n)
    masked = allsch.copy()
    masked.loc[masked.game_id.isin(late), ["home_score", "away_score"]] = np.nan
    snap = {}
    for arm, tw, ex, sc in (("stale", n, None, allsch), ("monday", n + 1, late, masked), ("tuesday", n + 1, None, allsch)):
      r = eng.tm.fit(season, tw, exclude=ex)
      net = unit_points(r, league_volume(eng, season, tw, r), usual, fw).net
      snap[arm] = (net.rank(ascending=False, method="min").to_dict(), elo.ratings_before(sc, season, tw, wm))

    def chance(arm, g, k):
      rk, el = snap[arm]
      c = "week_" if k <= 1 else ""  # Matchups' this-week form for week N's / N+1's games; the playoff-odds form beyond
      h, a = rel(g.home_team), rel(g.away_team)
      if h not in rk or a not in rk:
        return np.nan
      x = (wm[c + "home"] * (g.location != "Neutral") + wm[c + "rank_gap"] * (rk[a] - rk[h])
           + wm[c + "elo_per_100"] * (el.get(h, elo.MEAN) - el.get(a, elo.MEAN)) / 100)
      return float(logistic(x))
    mon_teams = {rel(t) for g in wk[wk.game_id.isin(late)].itertuples() for t in (g.home_team, g.away_team)}
    targets = [(k, sch[(sch.week == n + k)]) for k in range(1, AHEAD + 1)] + [(0, wk[wk.game_id.isin(late)])]
    for k, gs in targets:
      for g in gs.itertuples():
        if pd.isna(g.home_score) or g.home_score == g.away_score:
          continue
        rows.append({"season": season, "week": n, "k": k, "game_id": g.game_id, "y": float(g.home_score > g.away_score),
                     "p_stale": chance("stale", g, k), "p_monday": chance("monday", g, k),
                     "p_tuesday": chance("tuesday", g, k) if k > 0 else np.nan, "n_late": len(late),
                     "mon_team": rel(g.home_team) in mon_teams or rel(g.away_team) in mon_teams})
    print(f"[BA] {season} week {n}: {len(late)} Monday game(s) left out", flush=True)
  return pd.DataFrame(rows)


def boot_ci(e: np.ndarray, keys: np.ndarray, n: int = 4000) -> tuple[float, float, float]:
  u = np.unique(keys)
  idx = [np.flatnonzero(keys == x) for x in u]
  rng = np.random.default_rng(0)
  bs = []
  for _ in range(n):
    pick = np.concatenate([idx[i] for i in rng.integers(0, len(u), len(u))])
    bs.append(e[pick].mean())
  return float(e.mean()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def report(df: pd.DataFrame) -> None:
  df = df.dropna(subset=["p_stale", "p_monday"])
  key = (df.season.astype(str) + "-" + df.week.astype(str)).to_numpy()
  err = {a: (df[f"p_{a}"].to_numpy() - df.y.to_numpy()) ** 2 for a in ("stale", "monday", "tuesday")}
  fmt = lambda t: f"{t[0]:+.4f} [{t[1]:+.4f}, {t[2]:+.4f}]"  # noqa: E731
  print(f"{len(df)} scored rows, seasons {df.season.min()}-{df.season.max()}")
  for k in range(1, AHEAD + 1):
    m = (df.k == k).to_numpy()
    print(f"  week N+{k}: {m.sum()} games  Brier stale {err['stale'][m].mean():.4f}  monday {err['monday'][m].mean():.4f}  "
          f"tuesday {err['tuesday'][m].mean():.4f}   monday - stale {fmt(boot_ci((err['monday'] - err['stale'])[m], key[m]))}   "
          f"monday - tuesday {fmt(boot_ci((err['monday'] - err['tuesday'])[m], key[m]))}")
  m1 = (df.k == 1).to_numpy()
  g1 = boot_ci((err["monday"] - err["stale"])[m1], key[m1])
  for s in sorted(df.season.unique()):
    ms = m1 & (df.season == s).to_numpy()
    print(f"    {s}: monday - stale {(err['monday'] - err['stale'])[ms].mean():+.4f} ({ms.sum()} games)")
  for flag, lab in ((True, "involving a Monday-night team"), (False, "not")):
    mm = m1 & (df.mon_team == flag).to_numpy()
    print(f"    N+1 games {lab}: {mm.sum()}  monday - stale {fmt(boot_ci((err['monday'] - err['stale'])[mm], key[mm]))}")
  m0 = (df.k == 0).to_numpy()
  g2 = boot_ci((err["monday"] - err["stale"])[m0], key[m0])
  print(f"  week N's Monday games: {m0.sum()}  Brier stale {err['stale'][m0].mean():.4f}  monday {err['monday'][m0].mean():.4f}"
        f"   monday - stale {fmt(g2)}")
  ok1, ok2 = g1[2] < 0, g2[2] < 0.01
  print(f"GATE (1) week N+1 monday better, CI excluding 0: {'PASS' if ok1 else 'FAIL'} {fmt(g1)}")
  print(f"GATE (2) Monday games not worse, CI upper < +0.01: {'PASS' if ok2 else 'FAIL'} {fmt(g2)}")
  print("RESULT:", "PASS" if ok1 and ok2 else "FAIL")


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  if "report" in opt or "--report" in sys.argv:
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
