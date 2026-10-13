"""Walk-forward test of the injury return-timing model (nfledge/returns.py).

Usage: python tools/returns_eval.py [SEASONS]   (default 2021-2025; data from 2018)

For each test season: fit on every earlier loaded season, then score the chance each injured-out player plays
his team's next game (Brier, lower = better) against two baselines: a table by designation x games missed (with
a prior toward the overall rate) and the overall rate alone. Then multi-game calibration: predicted P(active)
1-4 games ahead vs how often those players actually were active.
"""
import copy
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.returns import ReturnModel  # noqa: E402

pd.set_option("display.width", 200)


def played_set(data) -> set:
  sn = data.snaps.dropna(subset=["gsis_id"])
  any_snap = (sn.offense_snaps.fillna(0) + sn.defense_snaps.fillna(0) + sn.st_snaps.fillna(0)) > 0
  return set(map(tuple, sn.loc[any_snap, ["season", "week", "gsis_id"]].itertuples(index=False)))


def main():
  rng = sys.argv[1] if len(sys.argv) > 1 else "2021-2025"
  a, _, b = rng.partition("-")
  seasons = list(range(int(a), int(b or a) + 1))
  cfg = copy.deepcopy(load_config())
  cfg["data"]["history_seasons"] = 8
  data = D.load_all(cfg)
  m = ReturnModel(data, played_set(data))
  all_states = m.states(sorted(data.seasons))
  print(f"{len(all_states)} injured-out player-weeks since {min(data.seasons)}; "
        f"{all_states.back.mean():.1%} played the next game")
  rows, cal = [], []
  for s in seasons:
    train = all_states[all_states.season < s]
    test = all_states[all_states.season == s].copy()
    if test.empty or train.empty:
      continue
    m.fit_frame(train)
    test["p_model"] = m.hazard(test)
    k = 20.0
    base = train.back.mean()
    tab = train.groupby(["desig", train.missed.clip(upper=6)]).back.agg(["sum", "size"])
    tab = (tab["sum"] + k * base) / (tab["size"] + k)
    test["p_table"] = [tab.get((d_, min(mi, 6)), base) for d_, mi in zip(test.desig, test.missed)]
    test["p_rate"] = base
    brier = {c: float(((test[c] - test.back) ** 2).mean()) for c in ("p_model", "p_table", "p_rate")}
    rows.append({"season": s, "n": len(test), **brier})
    # multi-game: from each state, predicted P(active) h games ahead vs the player's actual status then
    ahead = m.p_active(test, 4)
    for h in range(4):
      tw = test.copy()
      tw["pred"] = ahead[:, h]
      tw["actual"] = [m.active_after(r.season, r.gsis_id, r.team, r.week, h + 1) for r in tw.itertuples()]
      tw = tw[tw.actual.notna()]
      cal.append(tw.assign(h=h + 1)[["h", "pred", "actual"]])
  res = pd.DataFrame(rows)
  print("\nNext-game return, Brier (lower = better):")
  print(res.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
  tot = {c: np.average(res[c], weights=res.n) for c in ("p_model", "p_table", "p_rate")}
  print("pooled:", {k: round(v, 4) for k, v in tot.items()})
  c = pd.concat(cal)
  c["bin"] = pd.cut(c.pred, [0, .1, .3, .5, .7, .9, 1.0], include_lowest=True)
  print("\nMulti-game calibration (predicted vs actual share active):")
  print(c.groupby(["h", "bin"], observed=True).agg(n=("actual", "size"), predicted=("pred", "mean"),
                                                     actual=("actual", "mean")).round(3).to_string())


if __name__ == "__main__":
  main()
