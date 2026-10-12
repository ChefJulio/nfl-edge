"""Where does projection error come from? Decompose model error on the saved walk-forward backtest.

Usage: python tools/error_breakdown.py [backtest.parquet]   (default: newest cache/backtest_*.parquet)

The model's projection is team volume x player share x per-opportunity rates. Swapping in what actually happened,
one layer at a time, shows how much squared error each layer is responsible for:
  1. team volume   projected opportunities rescaled by the team's actual dropbacks / rushes
  2. share         the player's actual dropbacks, rushes (incl. scrambles) and targets at projected rates
  3. efficiency    actual yards, receptions, interceptions and fumbles; touchdowns still at projected TD rates
  4. touchdowns    actual touchdowns (what is left is official-stat vs play-by-play bookkeeping: 2-pt, laterals)
Sequential shares depend on the order, so each layer is also fixed ALONE (everything else projected).
Evaluation rows match the backtest's 'relevant' set: players who played, >= 2 prior games, top-N by consensus.
Availability error is outside this view by design (only players who played are scored).
"""
import glob
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nfledge.backtest import RELEVANT_TOP  # noqa: E402
from nfledge.config import load_scoring  # noqa: E402
from nfledge.player_model import OPP_TYPES  # noqa: E402

pd.set_option("display.width", 200)
POS = ["QB", "RB", "WR", "TE"]
TD = {"pass_td", "rush_td", "rec_td"}


def newest(pattern: str) -> str:
  files = glob.glob(str(ROOT / pattern))
  if not files:
    sys.exit(f"no {pattern}; run run.py first")
  return max(files, key=lambda f: Path(f).stat().st_mtime)


def load(path: str):
  res = pd.read_parquet(path)
  with open(newest("cache/model_*.pkl"), "rb") as f:
    eng, _ = pickle.load(f)  # only the ledgers are used: actual opportunities and stats per game
  return res, eng.pm.ledger, eng.team_ledger


def ledger_cols() -> list[str]:
  return list(OPP_TYPES) + [c for _, (_, _, cs) in OPP_TYPES.items() for c in cs] + ["fumble_lost"]


def eval_rows(res: pd.DataFrame) -> pd.DataFrame:
  d = res[res.played & (res.raw_games >= 2) & res.pos.isin(POS)].copy()
  d["consensus"] = d[["proj", "raw_fpg", "vegas"]].mean(axis=1)
  d["crank"] = d.groupby(["season", "week", "pos"]).consensus.rank(ascending=False)
  return d[d.crank <= d.pos.map(RELEVANT_TOP)].reset_index(drop=True)


def attach_actual_usage(d: pd.DataFrame, led: pd.DataFrame, tl: pd.DataFrame) -> pd.DataFrame:
  """a_<opportunity/stat> = what the player actually did that week (0 if he played without a touch);
  a_team_db / a_team_rush = his team's actual dropbacks and rushes."""
  a = led.groupby(["season", "week", "gsis_id"])[ledger_cols()].sum().add_prefix("a_")
  d = d.join(a, on=["season", "week", "gsis_id"])
  d[a.columns] = d[a.columns].fillna(0.0)  # played without a touch
  t = tl.groupby(["season", "week", "team"])[["dropbacks", "rushes"]].sum()
  t.columns = ["a_team_db", "a_team_rush"]
  return d.join(t, on=["season", "week", "team"])


def layers(d: pd.DataFrame, scoring) -> dict:
  """Projected points under each substitution (see module docstring)."""
  pts = lambda s: np.asarray(scoring.points(s, d.pos), dtype=float)  # noqa: E731
  proj_opp = {o: d[o].fillna(0.0).to_numpy() for o in OPP_TYPES}
  act_opp = {o: d[f"a_{o}"].to_numpy() for o in OPP_TYPES}
  team_ratio = {"team_db": d.a_team_db / d.team_db, "team_rush": d.a_team_rush / d.team_rush}
  team_ratio = {k: v.replace([np.inf, -np.inf], np.nan).fillna(1.0).to_numpy() for k, v in team_ratio.items()}
  rate, act_rate = {}, {}
  for o, (_, _, cs) in OPP_TYPES.items():
    for c in cs:
      with np.errstate(divide="ignore", invalid="ignore"):
        rate[c] = np.where(proj_opp[o] > 0, d[c].fillna(0.0) / proj_opp[o], 0.0)
        act_rate[c] = np.where(act_opp[o] > 0, d[f"a_{c}"] / act_opp[o], rate[c])
  opp_of = {c: o for o, (_, _, cs) in OPP_TYPES.items() for c in cs}
  team_of = {o: t for o, (t, _, _) in OPP_TYPES.items()}

  def build(opp, eff_actual=False, td_actual=False, fum_actual=False):
    s = pd.DataFrame(index=d.index)
    for c, o in opp_of.items():
      actual_rate = (td_actual if c in TD else eff_actual)
      s[c] = (act_rate[c] if actual_rate else rate[c]) * opp[o]
    s["fumble_lost"] = d.a_fumble_lost.to_numpy() if fum_actual else d.fumble_lost.fillna(0.0).to_numpy()
    return pts(s)

  team_vol = {o: proj_opp[o] * team_ratio[team_of[o]] for o in OPP_TYPES}
  share_only = {o: np.where(d[f"a_{team_of[o]}"] > 0, act_opp[o] / d[f"a_{team_of[o]}"].to_numpy(), 0)
                * d[team_of[o]].to_numpy() for o in OPP_TYPES}
  return {
    "projected": build(proj_opp),
    "+ team volume": build(team_vol),
    "+ share": build(act_opp),
    "+ efficiency": build(act_opp, eff_actual=True, fum_actual=True),
    "+ touchdowns": build(act_opp, eff_actual=True, td_actual=True, fum_actual=True),
    "only team volume": build(team_vol),
    "only share": build(share_only),
    "only efficiency": build(proj_opp, eff_actual=True, fum_actual=True),
    "only touchdowns": build(proj_opp, td_actual=True),
  }


def report(d: pd.DataFrame, L: dict):
  y = d.actual.to_numpy()
  seq = ["projected", "+ team volume", "+ share", "+ efficiency", "+ touchdowns"]
  alone = ["only team volume", "only share", "only efficiency", "only touchdowns"]
  rows = []
  for pos in POS:
    m = (d.pos == pos).to_numpy()
    mse = {k: float(np.mean((y[m] - v[m]) ** 2)) for k, v in L.items()}
    base = mse["projected"]
    row = {"pos": pos, "n": int(m.sum()), "MAE": float(np.mean(np.abs(y[m] - L["projected"][m]))),
           "bias": float(np.mean(y[m] - L["projected"][m])), "MSE": base}
    for a, b in zip(seq, seq[1:]):
      row[f"seq {b[2:]}"] = (mse[a] - mse[b]) / base
    row["bookkeeping"] = mse["+ touchdowns"] / base
    for k in alone:
      row[k] = (base - mse[k]) / base
    rows.append(row)
  out = pd.DataFrame(rows).set_index("pos")
  pct = [c for c in out.columns if c.startswith(("seq", "only")) or c == "bookkeeping"]
  fmt = out.copy()
  fmt[pct] = (out[pct] * 100).round(1)
  fmt[["MAE", "bias", "MSE"]] = out[["MAE", "bias", "MSE"]].round(2)
  print("Share of squared error removed by fixing each layer (%). 'seq' = cumulative in order; 'only' = alone.")
  print(fmt.to_string())


def main():
  """Args: backtest parquet files or globs (e.g. 'cache/experiments/baseline_*'); experiment runs already carry
  the actual usage columns, the site's backtest cache gets them from the cached model's ledger."""
  paths = [f for a in sys.argv[1:] for f in sorted(glob.glob(a))] or [newest("cache/backtest_*.parquet")]
  res = pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)
  d = eval_rows(res)
  if "a_team_db" not in d:
    _, led, tl = load(paths[0])
    d = attach_actual_usage(d, led, tl)
  path = paths[0] if len(paths) == 1 else f"{len(paths)} files"
  scoring = load_scoring()
  L = layers(d, scoring)
  gap = np.abs(L["projected"] - d.proj_model.to_numpy())
  print(f"{Path(path).name}: {len(d)} player-weeks; seasons {sorted(map(int, d.season.unique()))}. "
        f"Check: stat-sum vs proj_model mean |diff| {gap.mean():.2f}")
  report(d, L)
  for s in sorted(d.season.unique()):
    print(f"\n-- {s} only --")
    report(d[d.season == s].reset_index(drop=True), {k: v[(d.season == s).to_numpy()] for k, v in L.items()})


if __name__ == "__main__":
  main()
