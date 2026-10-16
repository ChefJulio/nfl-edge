"""How far backtest accuracy overstates live accuracy (INSIGHTS 2026-10-16, thread 1).

Usage: python tools/live_vs_backtest.py [--site=../nfl-edge-archive] [--season=2026]
Needs <site>/data/live_inputs/*.json (what each live build fed the model and showed, nfledge/live_inputs.py, from
2026-10-16 on) and <site>/<season>/week-NN.json (the walk-forward page built after the week: final lines, recorded
wind, final injury report, Friday ECR - what the backtest sees). Per player, the live projection is the last build
before his game's kickoff. Reports, per position, MAE live vs walk-forward on the same players, the distribution of
live - walk-forward projections, and the largest gaps with what differed: the team's line (implied points), wind,
chance to play, ECR.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402


def live_rows(site: Path, season: int, kick: dict) -> pd.DataFrame:
  """gsis_id x week -> the last live build before that player's kickoff."""
  rows = []
  for f in sorted((site / "data" / "live_inputs").glob(f"{season}_*.json")):
    d = json.loads(f.read_text(encoding="utf-8"))
    built = pd.Timestamp(d["built"])
    for gid, vals in d["p"].items():
      rows.append({"week": d["week"], "gsis_id": gid, "built": built, **dict(zip(d["stats"], vals))})
  df = pd.DataFrame(rows)
  if df.empty:
    return df
  return df  # kickoff filter applied after the team is known (needs the week page)


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = Path(opt.get("site", ROOT.parent / "nfl-edge-archive"))
  season = int(opt.get("season", 2026))
  from nfledge import data as D
  from nfledge.config import load_config
  sched = D.load_all(load_config()).schedules
  s = sched[(sched.season == season) & (sched.game_type == "REG")]
  kick = {}
  for g in s.itertuples():
    t = pd.Timestamp(f"{g.gameday} {g.gametime or '13:00'}").tz_localize("America/New_York").tz_convert("UTC")
    for team in (g.home_team, g.away_team):
      kick[(int(g.week), D.RELOCATED.get(team, team))] = (t, g.game_id, g.home_team == team)
  live = live_rows(site, season, kick)
  if live.empty:
    sys.exit(f"no live inputs under {site / 'data' / 'live_inputs'} for {season}")
  wb = []
  for wk in sorted(live.week.unique()):
    f = site / str(season) / f"week-{int(wk):02d}.json"
    if not f.exists():
      print(f"week {wk}: no walk-forward page yet ({f.name}); skipped")
      continue
    w = json.loads(f.read_text(encoding="utf-8"))
    for pid, p in w["players"].items():
      if p.get("act") is None:
        continue
      wb.append({"week": int(wk), "gsis_id": pid, "pos": p["pos"], "team": p["team"], "name": p["name"],
                 "wf_proj": p["proj"], "act": p["act"], "wf_avail": 1 - float(p.get("inactive") or 0.0),
                 "wf_ecr": p.get("ecr")})
  wb = pd.DataFrame(wb)
  if wb.empty:
    sys.exit("no finished week has both live inputs and a walk-forward page yet")
  m = live.merge(wb, on=["week", "gsis_id"])
  m["kick"] = [kick.get((w, D.RELOCATED.get(t, t)), (pd.NaT,))[0] for w, t in zip(m.week, m.team)]
  m = m[m.built < m.kick].sort_values("built").groupby(["week", "gsis_id"]).tail(1)
  # the walk-forward page's view of the same game: final line, recorded wind
  sw = s.set_index("game_id")
  gid = [kick.get((w, D.RELOCATED.get(t, t)), (None, None, None)) for w, t in zip(m.week, m.team)]
  m["game_id"], m["is_home"] = [g[1] for g in gid], [g[2] for g in gid]
  final_spread = sw.spread_line.reindex(m.game_id).to_numpy()
  final_total = sw.total_line.reindex(m.game_id).to_numpy()
  m["wf_implied"] = final_total / 2 + np.where(m.is_home, 1, -1) * final_spread / 2
  m["wf_wind"] = sw.wind.reindex(m.game_id).to_numpy() if "wind" in sw else np.nan
  m["d_proj"] = m.proj - m.wf_proj
  m["e_live"], m["e_wf"] = (m.proj - m.act).abs(), (m.wf_proj - m.act).abs()
  print(f"{season} weeks {sorted(m.week.unique())}: {len(m)} players with a live projection before kickoff and a result")
  rng = np.random.default_rng(0)
  for pos, g in [("ALL", m)] + list(m.groupby("pos")):
    d = (g.e_live - g.e_wf).to_numpy()
    b = rng.choice(d, (2000, len(d))).mean(1) if len(d) > 1 else np.array([d.mean()] * 2)
    print(f"  {pos:3s} n {len(g):4d}  MAE live {g.e_live.mean():.3f}  walk-forward {g.e_wf.mean():.3f}  "
          f"diff {d.mean():+.3f} [{np.percentile(b, 2.5):+.3f}, {np.percentile(b, 97.5):+.3f}]")
  q = m.d_proj.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
  print("live - walk-forward projection, quantiles 5/25/50/75/95%: " + " / ".join(f"{v:+.2f}" for v in q))
  print(f"share of players moved > 1 pt: {(m.d_proj.abs() > 1).mean():.1%}")
  m["d_implied"] = m.implied_pts - m.wf_implied
  m["d_wind"] = m.wind_penalty  # live penalty share; the walk-forward page applies the recorded wind
  m["d_avail"] = m.avail - m.wf_avail
  m["d_ecr"] = m.ecr - m.wf_ecr
  print("largest gaps (live - walk-forward) and what differed:")
  cols = ["week", "name", "pos", "team", "proj", "wf_proj", "act", "d_implied", "avail", "wf_avail", "d_ecr", "wind_penalty"]
  print(m.reindex(m.d_proj.abs().sort_values(ascending=False).index)[cols].head(25).round(2).to_string(index=False))
  for c, lab in (("d_implied", "implied points (line moved)"), ("d_avail", "chance to play"), ("d_ecr", "ECR rank")):
    x = m[[c, "d_proj"]].dropna()
    if len(x) > 2:
      print(f"corr(d_proj, {lab}) = {np.corrcoef(x[c], x.d_proj)[0, 1]:+.2f} (n {len(x)})")


if __name__ == "__main__":
  main()
