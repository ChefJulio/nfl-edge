"""The weekly forecast record (owner 2026-10-22: "would someone else trying to compare to us be able to get results?"
... "should we start publishing a finalized report of all our projection records at the end of a week?").

For a finished week: every player the live site projected, with what it PUBLISHED before his game (from the per-build
snapshots, data/live_inputs/<season>_<week>_<UTC stamp>.json: never recomputed), at fixed checkpoints on his team's
calendar (nfledge/week_clock.py):
  tue     the last build before his team's first report deadline (Tuesday's picture)
  day1    the last build before its second report deadline (first report in)
  day2    the last build before its third report deadline (two reports in)
  final   the last build before inactives (kickoff - 90 min: the final report in)
  prekick the last build before kickoff (inactives in)
each with its build time; then what happened (an offensive snap or a stat line; half-PPR points) and the week's
scorecard: chance-to-play Brier and calibration per checkpoint, projection error and bias by position (fantasy-relevant
players: the top 24 QB / 48 RB / 60 WR / 24 TE by published projection), the biggest misses. Append-only: a week's file
is written once its games are final and never rewritten (--force to rebuild).

  python tools/forecast_record.py [--season=2026] [--week=N] [--inputs=site/data/live_inputs] [--out=site/data/records]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge.config import load_config, load_scoring  # noqa: E402
from nfledge.data import load_all  # noqa: E402
from nfledge.player_model import actual_points  # noqa: E402
from nfledge.week_clock import INACTIVES_MIN, Clock  # noqa: E402

CHECKS = ("tue", "day1", "day2", "final", "prekick")
TOP = {"QB": 24, "RB": 48, "WR": 60, "TE": 24}
BANDS = [0, .1, .3, .5, .7, .9, 1.0001]


def snapshots(inputs: Path, season: int, week: int) -> list[tuple[pd.Timestamp, dict]]:
  out = []
  for f in sorted(inputs.glob(f"{season}_{week:02d}_*.json")):
    d = json.loads(f.read_text(encoding="utf-8"))
    built = pd.Timestamp(d["built"]).tz_convert("America/New_York")
    out.append((built, {g: dict(zip(d["stats"], v)) for g, v in d["p"].items()}))
  return sorted(out, key=lambda x: x[0])


def build(season: int, week: int, inputs: Path) -> dict:
  cfg, scoring = load_config(), load_scoring()
  data = load_all(cfg)
  snaps = snapshots(inputs, season, week)
  if not snaps:
    raise SystemExit(f"no snapshots for {season} week {week} in {inputs}")
  clock = Clock(data.schedules)
  teams = clock.teams(season, week)
  if not all(tw.final for tw in teams.values()):
    raise SystemExit(f"{season} week {week}: not every game is final yet")
  ro = data.rosters[(data.rosters.season == season) & (data.rosters.week <= week) & data.rosters.gsis_id.notna()]
  last = ro.sort_values("week").drop_duplicates("gsis_id", keep="last").set_index("gsis_id")
  team_of, name_of = last.team.replace({"LAR": "LA"}).to_dict(), last.full_name.to_dict()
  pos_of = last.position.replace({"FB": "RB", "HB": "RB"}).to_dict()
  # outcomes: an offensive snap or a stat line; half-PPR (the site's scoring) points
  st = data.stats[(data.stats.season == season) & (data.stats.week == week)]
  pts = actual_points(st, scoring).set_index("gsis_id").actual if len(st) else pd.Series(dtype=float)
  sn = data.snaps[(data.snaps.season == season) & (data.snaps.week == week)]
  need = set(teams)
  have_st = set(st.team.replace({"LAR": "LA"})) if "team" in st else set()
  have_sn = set(sn.team.replace({"LAR": "LA"})) if "team" in sn else set()
  if not need <= have_st or not need <= have_sn:  # nflverse posts stats / snap counts after the scores: wait for them
    raise SystemExit(f"{season} week {week}: stats or snap counts not complete yet "
                     f"(missing {sorted((need - have_st) | (need - have_sn))[:6]})")
  played = set(sn[sn.offense_snaps.fillna(0) > 0].gsis_id.dropna()) | set(pts.index)
  # checkpoint times per team
  cut = {}
  for t, tw in teams.items():
    due = [d for _, d in tw.reports]
    cut[t] = {"tue": due[0] if due else None, "day1": due[1] if len(due) > 1 else None,
              "day2": due[2] if len(due) > 2 else None, "final": tw.kick - pd.Timedelta(minutes=INACTIVES_MIN),
              "prekick": tw.kick}
  players = sorted({g for _, p in snaps for g in p})
  rows = []
  for g in players:
    t = team_of.get(g)
    if t not in cut:
      continue
    r = {"gsis_id": g, "name": name_of.get(g, g), "team": t, "pos": pos_of.get(g, ""), "kickoff": cut[t]["prekick"].isoformat()}
    for c in CHECKS:
      when = cut[t][c]
      hit = [(b, p[g]) for b, p in snaps if when is not None and b < when and g in p]
      if hit:
        b, v = hit[-1]
        r[f"{c}_play"] = None if v.get("avail") is None else round(float(v["avail"]), 4)
        r[f"{c}_proj"] = None if v.get("proj") is None else round(float(v["proj"]), 2)
        r[f"{c}_built"] = b.isoformat()
    if "prekick_proj" not in r:
      continue  # nothing published before his game
    r["played"] = g in played
    r["actual"] = round(float(pts.get(g, 0.0)), 2) if g in played else 0.0
    rows.append(r)
  x = pd.DataFrame(rows)
  y = x.played.astype(float)
  # chance to play: everyone with any risk at that checkpoint (< 97%), and the calibration bands
  avail = {}
  for c in CHECKS:
    col = f"{c}_play"
    if col not in x:
      continue
    k = x[col].notna() & (x[col] < 0.97)
    if k.sum():
      g = x[k]
      bands = []
      for lo, hi in zip(BANDS[:-1], BANDS[1:]):
        b = g[(g[col] >= lo) & (g[col] < hi)]
        if len(b):
          bands.append({"band": f"{round(lo * 100)}-{min(100, round(hi * 100))}%", "n": int(len(b)),
                        "predicted": round(100 * float(b[col].mean()), 1), "played": round(100 * float(b.played.mean()), 1)})
      avail[c] = {"n": int(k.sum()), "brier": round(float(((g[col] - y[k]) ** 2).mean()), 4),
                  "predicted": round(100 * float(g[col].mean()), 1), "played": round(100 * float(g.played.mean()), 1),
                  "bands": bands}
  # projections: fantasy-relevant players who played, by published (pre-kickoff) projection
  p = x[x.played].copy()
  p["rk"] = p.groupby("pos").prekick_proj.rank(ascending=False, method="first")
  rel = p[p.apply(lambda r: r.rk <= TOP.get(r.pos, 0), axis=1)]
  rel = rel.assign(err=rel.actual - rel.prekick_proj)
  proj = {pos: {"n": int(len(g)), "mae": round(float(g.err.abs().mean()), 3), "bias": round(float(g.err.mean()), 3)}
          for pos, g in rel.groupby("pos")}
  proj["ALL"] = {"n": int(len(rel)), "mae": round(float(rel.err.abs().mean()), 3), "bias": round(float(rel.err.mean()), 3)}
  miss = rel.reindex(rel.err.abs().sort_values(ascending=False).index).head(10)
  return {"season": season, "week": week, "generated": pd.Timestamp.now(tz="America/New_York").isoformat(timespec="seconds"),
          "snapshots": len(snaps), "first_build": snaps[0][0].isoformat(), "last_build": snaps[-1][0].isoformat(),
          "checkpoints": {"tue": "last build before his team's first report deadline", "day1": "before its second",
                          "day2": "before its third", "final": "before inactives (kickoff - 90 min)", "prekick": "before kickoff"},
          "scoring": scoring.name, "chance_to_play": avail, "projections": proj,
          "biggest_misses": [{"name": r.name, "team": r.team, "pos": r.pos, "projected": r.prekick_proj, "actual": r.actual}
                             for r in miss.itertuples()],
          "players": x.replace({np.nan: None}).to_dict("records")}


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  season = int(opt.get("season", 2026))
  out = Path(opt.get("out", ROOT / "site" / "data" / "records"))
  inputs = Path(opt.get("inputs", ROOT / "site" / "data" / "live_inputs"))
  out.mkdir(parents=True, exist_ok=True)
  if "week" in opt:
    weeks = [int(opt["week"])]
  else:  # every week with snapshots whose games are all final and no record yet
    weeks = sorted({int(f.name.split("_")[1]) for f in inputs.glob(f"{season}_*_*.json")})
  for w in weeks:
    f = out / f"{season}_wk{w:02d}.json"
    if f.exists() and "--force" not in sys.argv:
      continue
    try:
      doc = build(season, w, inputs)
    except SystemExit as e:
      print(f"[record] {season} week {w}: skipped ({e})", flush=True)
      continue
    f.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    pd.DataFrame(doc["players"]).to_csv(out / f"{season}_wk{w:02d}.csv", index=False)
    print(f"[record] {season} week {w}: {len(doc['players'])} players, projections {doc['projections'].get('ALL')}, "
          f"chance to play (final) {doc['chance_to_play'].get('final', {}).get('brier')}", flush=True)
  idx = []
  for f in sorted(out.glob(f"{season}_wk*.json")):
    d = json.loads(f.read_text(encoding="utf-8"))
    idx.append({"season": d["season"], "week": d["week"], "file": f.name, "csv": f.name.replace(".json", ".csv"),
                "projections": d["projections"].get("ALL"),
                "chance_to_play": {c: {k: v for k, v in d["chance_to_play"].get(c, {}).items() if k != "bands"} for c in CHECKS
                                   if c in d["chance_to_play"]}})
  (out / "index.json").write_text(json.dumps({"weeks": idx}, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
  main()
