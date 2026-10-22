"""(CF) shadow corners, the pre-registered test (docs/INSIGHTS.md, 2026-10-21). The list (data/history/
shadow_corners.csv) is built from published reporting only; this script is the first look at outcomes.

WR1 of an offense in a game = its top WR by targets that season before the game (3+ games). A WR1-game is "shadowed"
when the defense has a listed corner (that season, confidence high or medium) who played that week (nflverse snap
counts: defense snaps > 0, matched by name + team). Measures:
  (a) WR1's half-PPR points minus his own average over his other games that season (play-by-play 2016-25);
  (b) the model's miss, actual - projected (cached baseline backtests 2021-25, relevant rows).
GATE: (b) for shadowed WR1-games below 0 with a 95% season-week bootstrap CI excluding 0; per corner with 3+ such
games, >= 2/3 negative; 2021-23 and 2024-25 the same sign.

  python tools/shadow_eval.py [--conf=high,medium]
"""
import glob
import os
import re
import sys
from pathlib import Path

import nflreadpy as nfl
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from experiments import relevant  # noqa: E402

TEAM = {"LAR": "LA", "STL": "LA", "SD": "LAC", "OAK": "LV", "JAC": "JAX", "WSH": "WAS"}


def norm(n) -> str:
  n = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", str(n).lower())
  return re.sub(r"[^a-z]", "", n)


def ci(v: pd.Series, cl: pd.Series, reps=4000):
  gr = pd.DataFrame({"v": v.to_numpy(), "c": cl.to_numpy()}).groupby("c").v.agg(["sum", "size"])
  s_, n_ = gr["sum"].to_numpy(), gr["size"].to_numpy()
  idx = np.random.default_rng(0).integers(0, len(gr), (reps, len(gr)))
  bt = s_[idx].sum(1) / n_[idx].sum(1)
  return v.mean(), np.percentile(bt, 2.5), np.percentile(bt, 97.5)


def wr1_games(yrs) -> pd.DataFrame:
  p = nfl.load_pbp(yrs).select(["season", "week", "season_type", "posteam", "defteam", "receiver_player_id", "pass_attempt",
                                "complete_pass", "receiving_yards", "pass_touchdown", "sack"]).to_pandas()
  p = p[(p.season_type == "REG") & (p.pass_attempt == 1) & (p.sack != 1) & p.receiver_player_id.notna()]
  pos = nfl.load_players().to_pandas().set_index("gsis_id").position
  p = p[p.receiver_player_id.map(pos) == "WR"]
  g = p.groupby(["season", "week", "posteam", "defteam", "receiver_player_id"]).agg(
    tgt=("pass_attempt", "size"), rec=("complete_pass", "sum"), yd=("receiving_yards", "sum"), td=("pass_touchdown", "sum")).reset_index()
  g["pts"] = g.yd.fillna(0) / 10 + 0.5 * g.rec + 6 * g.td
  g = g.sort_values(["season", "receiver_player_id", "week"])
  s_ = g.groupby(["season", "receiver_player_id"])
  g["n"] = s_.pts.transform("size")
  g["res"] = g.pts - (s_.pts.transform("sum") - g.pts) / (g.n - 1).replace(0, np.nan)
  g["tgt_before"] = g.groupby(["season", "posteam", "receiver_player_id"]).tgt.transform(lambda x: x.shift().fillna(0).cumsum())
  g["gb"] = g.groupby(["season", "posteam", "receiver_player_id"]).cumcount()
  g = g[(g.gb >= 3) & (g.n >= 6)]
  g["rank"] = g.groupby(["season", "week", "posteam"]).tgt_before.rank(ascending=False, method="first")
  g = g[g["rank"] == 1].rename(columns={"receiver_player_id": "gsis_id"})
  for c in ("posteam", "defteam"):
    g[c] = g[c].replace(TEAM)
  return g[["season", "week", "posteam", "defteam", "gsis_id", "pts", "res"]]


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  conf = set(opt.get("conf", "high,medium").split(","))
  lst = pd.read_csv(ROOT / "data" / "history" / "shadow_corners.csv")
  lst = lst[lst.confidence.str.strip().str.lower().isin(conf)].copy()
  lst["team"] = lst.team.str.strip().replace(TEAM)
  lst["key"] = lst.player.map(norm)
  yrs = list(range(2016, 2026))
  sn = nfl.load_snap_counts(yrs).to_pandas()
  sn = sn[(sn.game_type == "REG") & (sn.defense_snaps.fillna(0) > 0)]
  sn = sn.assign(key=sn.player.map(norm), team=sn.team.replace(TEAM))
  played = set(zip(sn.season, sn.week, sn.team, sn.key))
  listed = {(int(r.season), r.team): [] for r in lst.itertuples()}
  for r in lst.itertuples():
    listed[(int(r.season), r.team)].append((r.key, r.player))
  w = wr1_games(yrs)
  who = []
  for r in w.itertuples():
    on = [nm for k, nm in listed.get((int(r.season), r.defteam), []) if (r.season, r.week, r.defteam, k) in played]
    who.append(on[0] if on else "")
  w["corner"] = who
  w["shadow"] = w.corner != ""
  w["sw"] = w.season.astype(str) + "-" + w.week.astype(str)
  print(f"list: {len(lst)} corner-seasons ({', '.join(sorted(conf))}); WR1-games 2016-25: {len(w)}, against a listed corner who played: {int(w.shadow.sum())}")
  have = set(zip(sn.season, sn.team, sn.key))
  unmatched = [f"{r.player} {r.season} {r.team}" for r in lst.itertuples() if (int(r.season), r.team, r.key) not in have]
  if unmatched:
    print(f"  listed corners with no snap rows that season (name / team mismatch?): {sorted(set(unmatched))}")
  m, lo, hi = ci(w[w.shadow].res, w[w.shadow].sw)
  m0 = w[~w.shadow].res.mean()
  print(f"\n(a) WR1 points vs his own average: shadowed {m:+.2f} [{lo:+.2f}, {hi:+.2f}] (n {int(w.shadow.sum())}); others {m0:+.2f}")
  # (b) the model's miss
  fr = []
  for s in range(2021, 2026):
    fs = sorted(glob.glob(str(ROOT / "cache" / "experiments" / f"baseline_{s}_*.parquet")), key=os.path.getmtime)
    fr.append(relevant(pd.read_parquet(fs[-1])))
  b = pd.concat(fr, ignore_index=True)
  b = b[b.pos == "WR"][["season", "week", "gsis_id", "proj", "actual"]]
  x = w.merge(b, on=["season", "week", "gsis_id"])
  x["miss"] = x.actual - x.proj
  ms, mlo, mhi = ci(x[x.shadow].miss, x[x.shadow].sw)
  print(f"(b) model miss (actual - projected), 2021-25: shadowed {ms:+.2f} [{mlo:+.2f}, {mhi:+.2f}] (n {int(x.shadow.sum())}); others {x[~x.shadow].miss.mean():+.2f} (n {int((~x.shadow).sum())})")
  per = x[x.shadow].groupby("corner").miss.agg(["size", "mean"])
  per3 = per[per["size"] >= 3]
  print(f"    per corner with 3+ games: {int((per3['mean'] < 0).sum())} of {len(per3)} negative")
  print(per3.sort_values("mean").round(2).to_string())
  a_, b_ = x[x.shadow & (x.season <= 2023)].miss.mean(), x[x.shadow & (x.season >= 2024)].miss.mean()
  print(f"    2021-23 {a_:+.2f}, 2024-25 {b_:+.2f}")
  gate = mhi < 0 and len(per3) and (per3["mean"] < 0).mean() >= 2 / 3 and a_ < 0 and b_ < 0
  print(f"\nGATE: {'PASS' if gate else 'FAIL'}")


if __name__ == "__main__":
  main()
