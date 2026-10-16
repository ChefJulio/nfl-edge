"""Thread 3 (INSIGHTS 2026-10-16): do change events the stats can't see explain the model's excess miss vs Vegas?

Usage: python tools/event_misses.py [--games=PATH]   (PATH: tools/game_eval.py 2021-2025 --only=fitted --save output,
                                                      the corrected harness that rates each game's own starting QB)
Excess per game = |model margin miss| - |Vegas spread miss| (positive = Vegas closer). Each team-game gets events
from data knowable before kickoff, by how many of the team's games ago they happened (0 = this game, 1-2 = the
previous one or two):
  qb_change     the starting QB (most dropbacks) differs from the previous game's
  coach_change  the head coach (schedule) differs from the previous game's (a mid-season firing)
  new_lead      the offense-snap leader at RB, WR or TE differs from the game before (v1 used the top-2 WR set: it
                changed in 82% of games, too noisy)
  arrival       a player with >= 50% offense snaps who hadn't played for this team before this season but had played
                for another team (trade / signing)
A game counts an event if either team has it. Reported per event and lag: games, mean excess vs games with no event
at all (95% CI over games), and per season, so a pocket in one season isn't read as a finding.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

GAMES = Path(r"C:\Users\hunte\AppData\Local\Temp\claude\C--Users-hunte\e847d357-6c86-407f-8c67-67c02542deb8\scratchpad\games.parquet")
EVENTS = ("qb_change", "coach_change", "new_lead", "arrival")


def team_events(d) -> pd.DataFrame:
  """One row per (season, week, team) with each event's lag in team games (NaN = none in the last 3)."""
  from nfledge import data as D
  from nfledge.team_model import team_game_ledger
  rel = lambda t: D.RELOCATED.get(t, t)  # noqa: E731
  led = team_game_ledger(d.pbp, d.schedules)
  led = led[led.season >= 2020].sort_values(["team", "season", "week"])
  s = d.schedules[(d.schedules.game_type == "REG") & (d.schedules.season >= 2020)]
  coach = {}
  for g in s.itertuples():
    coach[(int(g.season), int(g.week), rel(g.home_team))] = g.home_coach
    coach[(int(g.season), int(g.week), rel(g.away_team))] = g.away_coach
  sn = d.snaps.dropna(subset=["gsis_id"])
  sn = sn[(sn.season >= 2020) & (sn.game_type == "REG" if "game_type" in sn else True)].copy()
  sn["team"] = sn.team.map(rel)
  lead = {}
  for (se, wk, tm), g in sn.groupby(["season", "week", "team"]):
    key = []
    for pos, k in (("RB", 1), ("WR", 1), ("TE", 1)):
      x = g[g.position == pos].nlargest(k, "offense_pct")
      key.append(frozenset(x.gsis_id))
    lead[(int(se), int(wk), tm)] = tuple(key)
  first = sn.sort_values(["season", "week"]).groupby(["season", "gsis_id", "team"]).week.min()
  played_other = sn.groupby(["season", "gsis_id"]).team.nunique()
  arrivals = {}
  big = sn[sn.offense_pct >= 0.5]
  for (se, gid, tm), w0 in first.items():
    if played_other.get((se, gid), 1) < 2 or w0 < 2:
      continue
    hit = big[(big.season == se) & (big.gsis_id == gid) & (big.team == tm)]
    if len(hit):
      arrivals.setdefault((int(se), tm), []).append(int(hit.week.min()))
  rows = []
  for (se, tm), g in led.groupby(["season", "team"]):
    wks, qbs = list(g.week.astype(int)), list(g.qb)
    ev_week = {e: [] for e in EVENTS}
    for i in range(1, len(wks)):
      if isinstance(qbs[i], str) and isinstance(qbs[i - 1], str) and qbs[i] != qbs[i - 1]:
        ev_week["qb_change"].append(i)
      c0, c1 = coach.get((se, wks[i - 1], tm)), coach.get((se, wks[i], tm))
      if c0 and c1 and c0 != c1:
        ev_week["coach_change"].append(i)
      l0, l1 = lead.get((se, wks[i - 1], tm)), lead.get((se, wks[i], tm))
      if i >= 1 and l0 and l1 and l0 != l1:
        ev_week["new_lead"].append(i)
    for w in arrivals.get((se, tm), []):
      if w in wks:
        ev_week["arrival"].append(wks.index(w))
    for i, w in enumerate(wks):
      r = {"season": int(se), "week": w, "team": tm}
      for e in EVENTS:
        # lag 0 for coach_change / qb_change at game i means the change IS this game (coach: announced beforehand;
        # QB: the starter the harness rates); new_lead / arrival at game i are seen only after it, so lag >= 1
        lags = [i - j for j in ev_week[e] if 0 <= i - j <= 2]
        if e in ("new_lead", "arrival"):
          lags = [i - j for j in ev_week[e] if 1 <= i - j <= 3]
          lags = [x - 1 + 1 for x in lags]
        r[e] = min(lags) if lags else np.nan
      rows.append(r)
  return pd.DataFrame(rows)


def main():
  from nfledge import data as D
  from nfledge.config import load_config
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  g = pd.read_parquet(opt.get("games", GAMES))
  g = g[(g.variant == "fitted") & g.spread_line.notna()].copy()
  g["excess"] = (g.model_margin - g.actual_margin).abs() - (g.spread_line - g.actual_margin).abs()
  d = D.load_all(load_config())
  ev = team_events(d).set_index(["season", "week", "team"])
  rel = lambda t: D.RELOCATED.get(t, t)  # noqa: E731
  for e in EVENTS:
    h = ev[e].reindex(list(zip(g.season, g.week, g.home_team.map(rel)))).to_numpy()
    a = ev[e].reindex(list(zip(g.season, g.week, g.away_team.map(rel)))).to_numpy()
    g[e] = np.fmin(h, a)
  none = g[g[list(EVENTS)].isna().all(axis=1)]
  rng = np.random.default_rng(0)
  print(f"{len(g)} games 2021-25 with a line; mean excess {g.excess.mean():+.2f}; no event at all (n {len(none)}) "
        f"{none.excess.mean():+.2f}\n")
  print(f"{'event':13s} lag    n  excess  vs games without it [95% CI]          by season 2021..2025 (n)")
  for e in EVENTS:
    for lag in sorted(g[e].dropna().unique()):
      x, rest = g[g[e] == lag], g[g[e].isna()]
      diff = x.excess.mean() - rest.excess.mean()
      b = rng.choice(x.excess.to_numpy(), (4000, len(x))).mean(1) - rng.choice(rest.excess.to_numpy(), (4000, len(rest))).mean(1)
      by = " ".join(f"{x[x.season == s].excess.mean():+.1f}({(x.season == s).sum()})" for s in range(2021, 2026))
      print(f"{e:13s} {int(lag):3d} {len(x):4d}  {x.excess.mean():+.2f}  {diff:+.2f} [{np.percentile(b, 2.5):+.2f}, "
            f"{np.percentile(b, 97.5):+.2f}]   {by}")
  nb = none.groupby("season").excess.mean()
  print("\nno event, by season: " + " ".join(f"{s} {v:+.2f}" for s, v in nb.items()))


if __name__ == "__main__":
  main()
