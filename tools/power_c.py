"""Power rank C: rest-of-season strength, injury-aware (pre-registered 2026-10-16, docs/INSIGHTS.md (M)).

Usage: python tools/power_c.py [--jobs=N] [--first=2021] [--last=2026]
Writes cache/power_c.parquet (one row per team per season-week: A, C, outcomes) and prints the gate.

For each season and week w (2 on), as of the Tuesday before week w:
  A    net rating with the team's most recent starting QB (what Power ranked by before (M))
  N    net rating with the QB who started week w's game (stand-in for the announced starter; INSIGHTS (Q))
  C    mean over the team's remaining regular-season games of P(usual starter back) x net with him + (1 - P) x net
       with the backup; P from the return-timing chain (nfledge/returns.py) fit on outcomes known before w
Outcome: the team's actual point differential per game over its remaining games (completed seasons).
One worker process per season (each loads the data and trains that season's engine once); all cores by default.
"""
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

OUT = ROOT / "cache" / "power_c.parquet"


def season_rows(season: int) -> pd.DataFrame:
  for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(v, "2")
  from nfledge import data as D
  from nfledge.config import load_config, load_scoring
  from nfledge.engine import Engine
  from nfledge.report import formula_weights, league_volume, starters_asof, unit_points
  cfg = load_config()
  d = D.load_all(cfg)
  eng = Engine(d, cfg, load_scoring(), ["QB", "RB", "WR", "TE"]).train(season)
  fw = formula_weights(eng)
  sch = d.schedules[(d.schedules.season == season) & (d.schedules.game_type == "REG")]
  games = {}
  for g in sch.itertuples():
    for t, us, them in ((g.home_team, g.home_score, g.away_score), (g.away_team, g.away_score, g.home_score)):
      games.setdefault(t, []).append((int(g.week), us, them))
  games = {t: sorted(v) for t, v in games.items()}
  last_final = int(sch[sch.home_score.notna()].week.max()) if sch.home_score.notna().any() else 0
  rows = []
  from nfledge import powerc
  for w in range(2, min(int(sch.week.max()), last_final + 1) + 1):
    rw = eng.tm.fit(season, w)
    vol = league_volume(eng, season, w, rw)
    recent = starters_asof(eng, season, w)
    usual, backup, pbar = powerc.inputs(eng, season, w, recent)  # the site's own computation (nfledge/powerc.py)
    u_a = unit_points(rw, vol, recent, fw)
    tl = eng.team_ledger
    now = tl[(tl.season == season) & (tl.week == w)].dropna(subset=["qb"])
    u_n = unit_points(rw, vol, {**recent, **dict(zip(now.team, now.qb))}, fw)  # this game's starter (INSIGHTS (Q))
    c_units = powerc.blend(unit_points(rw, vol, usual, fw), unit_points(rw, vol, backup, fw), pbar)
    out_qb = {q for t, q in usual.items() if pbar.get(t, 1.0) < 1.0}
    for t in rw.teams:
      rem = [(wk, us, them) for wk, us, them in games.get(t, []) if wk >= w]
      if not rem:
        continue
      played = [(us - them) for wk, us, them in games.get(t, []) if wk < w and pd.notna(us)]
      fut = [(us - them) for wk, us, them in rem if pd.notna(us)]
      rows.append({"season": season, "week": w, "team": t, "A": float(u_a.net.get(t, np.nan)), "N": float(u_n.net.get(t, np.nan)), "C": float(c_units.net.get(t, np.nan)),
                   "usual_out": pbar.get(t, 1.0) < 1.0, "pbar": pbar.get(t, 1.0),
                   "pd_so_far": float(np.mean(played)) if played else np.nan,
                   "wins_so_far": float(np.mean([x > 0 for x in played])) if played else np.nan,
                   "fut_pd": float(np.mean(fut)) if fut else np.nan, "fut_n": len(fut), "rem_n": len(rem)})
    print(f"[power C] {season} week {w}: {len(out_qb)} usual starters out", flush=True)
  return pd.DataFrame(rows)


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  first, last = int(opt.get("first", 2021)), int(opt.get("last", 2026))
  seasons = list(range(first, last + 1))
  jobs = int(opt.get("jobs", min(len(seasons), os.cpu_count() or 1)))
  with ProcessPoolExecutor(jobs) as ex:
    df = pd.concat(list(ex.map(season_rows, seasons)), ignore_index=True)
  df.to_parquet(OUT, index=False)
  print(f"wrote {OUT} ({len(df)} rows)")


if __name__ == "__main__":
  main()
