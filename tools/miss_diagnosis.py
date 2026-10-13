"""Why does the game model lose to Vegas? Tag every game with candidate information gaps and measure how much each
inflates the model's EXCESS error (|model margin - actual| minus |Vegas spread - actual|; positive = Vegas closer).

Usage: python tools/miss_diagnosis.py        (2021 to now, ~3 min with 6 workers)

A tag matters if games with it carry clearly more excess error than games without it, consistently across seasons.
Tags (all knowable before kickoff except "surprise QB", which is the information gap itself):
  surprise_qb      the game's actual starting QB (most dropbacks) differs from the team's previous starter
  inexp_qb         the actual starter had < 150 career dropbacks
  early / late     weeks 1-3 / weeks 17-18
  rest_gap         |home rest - away rest| >= 3 days (incl. off a bye, Thursday games)
  division         divisional game
  windy / cold     wind >= 15 mph / temperature <= 32 F (outdoor)
  out_off / out_def  recent snap share of players ruled Out/Doubtful for the game, >= 1.0 (one full starter)
  stale            the model missed the team by 7+ pts on average over its previous 3 games (ratings lagging)
"""
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import copy  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import game_eval as ge  # noqa: E402
from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.team_model import team_game_ledger, qb_experience  # noqa: E402

pd.set_option("display.width", 220)


def tags(d: pd.DataFrame, data) -> pd.DataFrame:
  led = team_game_ledger(data.pbp, data.schedules)
  qb_game = led.set_index(["game_id", "team"]).qb
  prev = led.dropna(subset=["qb"]).sort_values(["season", "week"])
  prev["prev_qb"] = prev.groupby(["season", "team"]).qb.shift(1)
  prev_qb = prev.set_index(["game_id", "team"]).prev_qb
  exp = qb_experience(data.pbp, data.qb_career)
  sched = data.schedules.set_index("game_id")
  # recent offense / defense snap share of players ruled Out / Doubtful for each team-week
  sn = data.snaps.dropna(subset=["gsis_id"]).sort_values(["season", "week"])
  sn["off3"] = sn.groupby(["season", "gsis_id"]).offense_pct.transform(lambda s: s.shift(1).rolling(3, 1).mean())
  sn["def3"] = sn.groupby(["season", "gsis_id"]).defense_pct.transform(lambda s: s.shift(1).rolling(3, 1).mean())
  last = sn.groupby(["season", "week", "gsis_id"])[["off3", "def3"]].last()
  inj = data.injuries
  inj = inj[inj.report_status.isin(["Out", "Doubtful"]) & inj.gsis_id.notna()]
  inj = inj.join(last, on=["season", "week", "gsis_id"])
  out = inj.groupby(["season", "week", "team"])[["off3", "def3"]].sum()
  rows = []
  for g in d.itertuples():
    t = {}
    for side, team in (("home", g.home_team), ("away", g.away_team)):
      actual = qb_game.get((g.game_id, team))
      before = prev_qb.get((g.game_id, team))
      t[f"surprise_{side}"] = bool(isinstance(actual, str) and isinstance(before, str) and actual != before)
      prior = exp[(exp.qb == actual) & ((exp.season < g.season) | ((exp.season == g.season) & (exp.week < g.week)))].n.sum() \
        if isinstance(actual, str) else np.nan
      t[f"inexp_{side}"] = bool(isinstance(actual, str) and prior + (data.qb_career.get(actual, 0) if data.qb_career is not None else 0) < 150)
      o = out.loc[(g.season, g.week, team)] if (g.season, g.week, team) in out.index else None
      t[f"out_off_{side}"] = float(o.off3) if o is not None and pd.notna(o.off3) else 0.0
      t[f"out_def_{side}"] = float(o.def3) if o is not None and pd.notna(o.def3) else 0.0
    s = sched.loc[g.game_id] if g.game_id in sched.index else None
    rows.append({
      "surprise_qb": t["surprise_home"] or t["surprise_away"], "inexp_qb": t["inexp_home"] or t["inexp_away"],
      "early": g.week <= 3, "late": g.week >= 17,
      "rest_gap": bool(s is not None and pd.notna(s.home_rest) and abs(s.home_rest - s.away_rest) >= 3),
      "division": bool(s is not None and s.div_game == 1),
      "windy": bool(s is not None and pd.notna(s.wind) and s.wind >= 15),
      "cold": bool(s is not None and pd.notna(s.temp) and s.temp <= 32),
      "out_off": max(t["out_off_home"], t["out_off_away"]) >= 1.0,
      "out_def": max(t["out_def_home"], t["out_def_away"]) >= 1.0})
  return pd.concat([d.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def stale(d: pd.DataFrame, k: int = 3) -> pd.Series:
  rows = []
  for g in d.itertuples():
    rows += [(g.season, g.week, g.home_team, g.actual - g.model_margin),
             (g.season, g.week, g.away_team, g.model_margin - g.actual)]
  t = pd.DataFrame(rows, columns=["season", "week", "team", "miss"]).sort_values(["season", "team", "week"])
  t["mem"] = t.groupby(["season", "team"]).miss.transform(lambda s: s.shift(1).rolling(k, 1).mean()).fillna(0)
  m = t.set_index(["season", "week", "team"]).mem
  return pd.Series([max(abs(m.get((s, w, h), 0)), abs(m.get((s, w, a), 0))) >= 7
                    for s, w, h, a in zip(d.season, d.week, d.home_team, d.away_team)], index=d.index)


if __name__ == "__main__":
  base = load_config()
  seasons = list(range(2021, 2027))
  with ProcessPoolExecutor(max_workers=6) as ex:
    parts = list(ex.map(ge.season_games, [base] * len(seasons), [8] * len(seasons), seasons))
  d = pd.concat([p[0] for p in parts], ignore_index=True)
  d = d[(d.variant == "fitted_6yr") & d.spread_line.notna()].copy()
  d["actual"] = d.home_score - d.away_score
  d["excess"] = (d.model_margin - d.actual).abs() - (d.spread_line - d.actual).abs()
  cfg = copy.deepcopy(base)
  cfg["data"]["history_seasons"] = 8
  data = D.load_all(cfg)
  d = tags(d, data)
  d["stale"] = stale(d).to_numpy()
  print(f"{len(d)} games; model excess error vs Vegas: mean {d.excess.mean():+.2f} pts per game")
  cols = ["surprise_qb", "inexp_qb", "early", "late", "rest_gap", "division", "windy", "cold", "out_off", "out_def",
          "stale"]
  rows = []
  for c in cols:
    w, wo = d[d[c]], d[~d[c]]
    per = [round(d[(d.season == s) & d[c]].excess.mean() - d[(d.season == s) & ~d[c]].excess.mean(), 2)
           for s in seasons]
    rows.append({"tag": c, "games": len(w), "share": len(w) / len(d), "excess_with": w.excess.mean(),
                 "excess_without": wo.excess.mean(), "gap": w.excess.mean() - wo.excess.mean(),
                 "gap_by_season": per, "share_of_total_excess": w.excess.sum() / d.excess.sum()})
  r = pd.DataFrame(rows).sort_values("gap", ascending=False)
  print(r.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
  big = d[(d.model_margin - d.spread_line).abs() >= 5]
  print(f"\nBig disagreements (|model - Vegas| >= 5): {len(big)} games, Vegas closer in {(big.excess > 0).mean():.0%}")
  print("tag rates, Vegas-closer big misses vs all games:")
  vb = big[big.excess > 0]
  print("  " + "  ".join(f"{c} {vb[c].mean():.0%}/{d[c].mean():.0%}" for c in cols))
  worst = d.sort_values("excess", ascending=False).head(20)
  print("\n20 worst (model vs Vegas):")
  print(worst[["season", "week", "away_team", "home_team", "model_margin", "spread_line", "actual", "excess"]
              + [c for c in cols if c != "stale"]].to_string(index=False, float_format=lambda x: f"{x:.1f}"))
