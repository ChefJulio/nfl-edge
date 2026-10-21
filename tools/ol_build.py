"""Pass protection values: ridge plus-minus on pressure (owner 2026-10-20: "sacks allowed, pressures allowed ...").

Usage: python tools/ol_build.py [--valid]
Every dropback 2016-25 with pressure charted (participation: was_pressure, number_of_pass_rushers; play-by-play: sack):
outcome = pressured or sacked (0/1). Context: down, log distance, field position, home offense, number of pass rushers
(3 or fewer / 4 / 5 / 6+, unknown). Each of the 11 offensive players and 11 defenders gets an effect, ridge-shrunk
toward his position group's typical value for how much he played (tools/rapm_build.Fit). A lineman's pass-protection
value = minus his effect (pressures prevented per dropback). --valid: single-season fits, rank correlation of each
player's value with his next season's (300+ dropbacks both), by position group, against the EPA-based values (OL .30).
Writes cache/ol_pp_single.parquet.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import rapm_build as R  # noqa: E402

FIRST, LAST = 2016, 2025
LAMBDAS = [100.0, 300.0, 1000.0, 3000.0, 10000.0]


def context(p: pd.DataFrame) -> np.ndarray:
  base = R.CONTEXT_BASE(p)
  n = p.number_of_pass_rushers
  extra = [(n <= 3).to_numpy(), (n == 5).to_numpy(), (n >= 6).to_numpy(), n.isna().to_numpy()]
  return np.column_stack([base] + extra).astype(float)


def load() -> pd.DataFrame:
  out = []
  for y in range(FIRST, LAST + 1):
    p = pd.read_parquet(ROOT / "cache" / f"pbp_{y}.parquet", columns=["game_id", "play_id", "season", "posteam", "home_team", "down", "ydstogo", "yardline_100", "wp"])
    d = pd.read_parquet(ROOT / "cache" / f"pbp_dir_{y}.parquet")
    pa = pd.read_parquet(ROOT / "cache" / f"participation_{y}.parquet")
    pp = pd.read_parquet(ROOT / "cache" / f"participation_pp_{y}.parquet")
    p = p.merge(d, on=["game_id", "play_id"]).merge(pa, left_on=["game_id", "play_id"], right_on=["nflverse_game_id", "play_id"])
    p = p.merge(pp.drop(columns=["nflverse_game_id"]).assign(game_id=pp.nflverse_game_id), on=["game_id", "play_id"])
    p = p[(p.qb_dropback == 1) & p.was_pressure.notna() & p.down.notna() & (p.n_offense == 11) & (p.n_defense == 11)]
    p["epa"] = ((p.was_pressure.astype(float) > 0) | (p.sack.fillna(0) > 0)).astype(float)  # the target (Fit reads .epa)
    out.append(p)
  p = pd.concat(out, ignore_index=True)
  p["off"], p["dfn"] = p.offense_players.str.split(";"), p.defense_players.str.split(";")
  return p


def tune(p, grp, season):
  """lambda per side by predicting `season`'s pressures from a fit on the three seasons before."""
  tr = p[p.season.between(season - 3, season - 1)]
  f = R.Fit(tr, R.weights(tr, season), grp)
  te = p[p.season == season]
  best, loss = None, np.inf
  for lo in LAMBDAS:
    for ld in LAMBDAS:
      b0 = f.solve(lo, ld)
      mu, coef = f.prior(b0)
      beta = f.solve(lo, ld, mu=mu)
      e = float(np.mean((te.epa.to_numpy() - R.predict(f, beta, coef, te, grp)) ** 2))
      if e < loss:
        best, loss = (lo, ld), e
  return best, loss


def main():
  R.CONTEXT_BASE = R.context
  R.context = context  # Fit / predict build their context columns through rapm_build.context
  pl = pd.read_parquet(ROOT / "cache" / "players_all.parquet")[["gsis_id", "position"]].dropna()
  grp = dict(zip(pl.gsis_id, pl.position.map(R.GROUP).fillna("OTH")))
  p = load()
  print(f"{len(p)} dropbacks {FIRST}-{LAST}, pressured or sacked {p.epa.mean():.3f}", flush=True)
  lam, loss = tune(p, grp, 2022)
  print(f"lambdas off/def {lam} (tuned predicting 2022 from 2019-21), MSE {loss:.5f}", flush=True)
  rows = []
  for y in range(FIRST, LAST + 1):
    tr = p[p.season == y]
    f = R.Fit(tr, np.ones(len(tr)), grp)
    b0 = f.solve(*lam)
    mu, _ = f.prior(b0)
    beta = f.solve(*lam, mu=mu)
    for i, x in enumerate(f.ids):
      rows.append({"season": y, "gsis_id": x, "side": f.side[i], "grp": f.g[i], "value": float(-beta[f.nc + i] if f.side[i] == "off" else beta[f.nc + i]),
                   "plays": float(f.n[i])})
    print(f"[pp] {y}", flush=True)
  S = pd.DataFrame(rows)
  S.to_parquet(ROOT / "cache" / "ol_pp_single.parquet", index=False)
  a = S.merge(S.assign(season=S.season - 1), on=["season", "gsis_id", "side"], suffixes=("", "_next"))
  a = a[(a.plays >= 300) & (a.plays_next >= 300)]
  print("\npass protection value, rank corr with next season (300+ dropbacks both; + = prevents pressure / creates it on defense):")
  print(a.groupby(["side", "grp"]).apply(lambda t: pd.Series({"n": len(t), "corr": t.value.corr(t.value_next, method="spearman")})).round(3).to_string())


if __name__ == "__main__":
  main()
