"""Reference tables (owner 2026-10-18): league-wide rates from the play-by-play, descriptive, not part of the model.

Usage: python tools/reference_build.py [--out site/data/reference.json]
Every table keeps its counts per season, so the page (assets/reference.js) sums any window: all seasons, the last
ten, the last three, or since a rule change. Regular season only. nflverse play-by-play, its own column set,
cached per season as cache/pbpref_<season>.parquet (the current season is refetched).

Tables
  conv      down (1-4) x distance (1-15, 16+), not goal to go: plays, the series converted (series_success), a first
            down or touchdown on that play. 4th down counts only plays where the offense went for it (run / pass).
  goal      goal to go, down x yards to the goal (1-10+): plays, touchdown on the drive, field goal on the drive
  turn      down x distance: plays, interceptions, fumbles lost
  fourth    4th down, distance x field zone: 4th-down plays, went for it, converted
  fg        field goals by distance, 1-yard bands (18-60+): attempts, made
  xp        extra points: attempts, good          (rule: 2015, the snap moved back to the 15)
  two       two-point tries, pass / run: attempts, converted
  onside    onside kicks: attempts, recovered by the kicking team (rule: 2018 kickoff rules)
  kick      kickoffs (not onside): plays, touchbacks (rule: 2024 dynamic kickoff)
  drive     drives by starting spot (yards from own goal, 10-yard bands): drives, TD, FG, no points
  ep        expected points on 1st & 10 by yards to the end zone (5-yard bands), nflfastR's model: sum and count
  redzone   drives reaching the opponent's 20: drives, TD, FG
  lead      a lead of N points (bands) at a moment (Q2 end, Q3 start, Q4 15:00 / 10:00 / 5:00 / 2:00): games, leader won
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

FIRST = 2001
COLS = ["season", "week", "season_type", "game_id", "play_type", "down", "ydstogo", "yardline_100", "goal_to_go",
        "series_success", "first_down", "touchdown", "posteam", "defteam", "interception", "fumble_lost",
        "field_goal_result", "kick_distance", "extra_point_result", "two_point_attempt", "two_point_conv_result",
        "kickoff_attempt", "own_kickoff_recovery", "touchback", "desc", "fixed_drive", "fixed_drive_result", "ep",
        "score_differential", "game_seconds_remaining", "result", "home_team", "qb_kneel", "qb_spike", "pass", "rush",
        "penalty", "qtr", "posteam_score", "defteam_score"]
DIST = [str(i) for i in range(1, 16)] + ["16+"]
LEAD = [(1, 3), (4, 7), (8, 10), (11, 14), (15, 17), (18, 21), (22, 99)]
MOMENTS = [("Halftime", 1800), ("Q4 start", 900), ("Q4 10:00", 600), ("Q4 5:00", 300), ("Q4 2:00", 120)]


def load(seasons, cur):
  import nflreadpy as nfl
  out = []
  for s in seasons:
    p = ROOT / "cache" / f"pbpref_{s}.parquet"
    if p.exists() and s != cur:
      out.append(pd.read_parquet(p)); continue
    try:
      df = nfl.load_pbp([s])
      df = df.select([c for c in COLS if c in df.columns]).to_pandas()
    except Exception as e:
      print(f"[ref] {s}: {type(e).__name__} {str(e)[:80]}", flush=True)
      if p.exists(): out.append(pd.read_parquet(p))
      continue
    df.to_parquet(p, index=False); out.append(df)
    print(f"[ref] {s}: {len(df)} plays", flush=True)
  return pd.concat(out, ignore_index=True)


def by_season(df, keys, vals):
  """{season: {key...: [n, *sums]}} as nested lists the page can sum."""
  out = {}
  g = df.groupby(["season"] + keys)
  agg = g.size().to_frame("n")
  for v in vals:
    agg[v] = g[v].sum()
  for idx, r in agg.iterrows():
    s, *k = idx if isinstance(idx, tuple) else (idx,)
    out.setdefault(str(int(s)), {})["|".join(str(int(x)) if isinstance(x, float) and x == int(x) else str(x) for x in k)] = [int(r.n)] + [round(float(r[v]), 3) if v == "ep" else int(r[v]) for v in vals]
  return out


def dist_label(y):
  return "16+" if y >= 16 else str(int(y))


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--out", default=str(ROOT / "scratch" / "site" / "data" / "reference.json"))
  a = ap.parse_args()
  cur = dt.date.today().year if dt.date.today().month >= 9 else dt.date.today().year - 1
  P = load(range(FIRST, cur + 1), cur)
  P = P[P.season_type == "REG"].copy()
  for c in ["down", "ydstogo", "yardline_100", "kick_distance", "series_success", "first_down", "touchdown", "interception",
            "fumble_lost", "goal_to_go", "qb_kneel", "qb_spike", "pass", "rush", "two_point_attempt", "kickoff_attempt",
            "own_kickoff_recovery", "touchback", "score_differential", "game_seconds_remaining", "qtr"]:
    if c in P: P[c] = pd.to_numeric(P[c], errors="coerce")
  T, meta = {}, {}
  scrim = P[P.play_type.isin(["pass", "run"]) & P.down.notna() & (P.qb_kneel != 1) & (P.qb_spike != 1)].copy()
  scrim["dist"] = scrim.ydstogo.map(dist_label)
  scrim["conv_now"] = ((scrim.first_down == 1) | (scrim.touchdown == 1)).astype(int)
  scrim["ss"] = scrim.series_success.fillna(0).astype(int)
  nog = scrim[scrim.goal_to_go != 1]
  T["conv"] = by_season(nog, ["down", "dist"], ["ss", "conv_now"])
  # goal to go: the drive's result
  gtg = scrim[scrim.goal_to_go == 1].copy()
  gtg["yds"] = gtg.yardline_100.clip(upper=10).map(lambda y: "10+" if y >= 10 else str(int(y)))
  gtg["td"] = (gtg.fixed_drive_result == "Touchdown").astype(int)
  gtg["fg"] = (gtg.fixed_drive_result == "Field goal").astype(int)
  T["goal"] = by_season(gtg, ["down", "yds"], ["td", "fg"])
  scrim["int"] = scrim.interception.fillna(0).astype(int); scrim["fum"] = scrim.fumble_lost.fillna(0).astype(int)
  T["turn"] = by_season(scrim, ["down", "dist"], ["int", "fum"])
  # 4th down decisions
  f4 = P[(P.down == 4) & P.play_type.isin(["pass", "run", "punt", "field_goal"])].copy()
  f4["dist"] = f4.ydstogo.map(lambda y: "1" if y <= 1 else "2" if y <= 2 else "3-4" if y <= 4 else "5-7" if y <= 7 else "8+")
  f4["zone"] = f4.yardline_100.map(lambda y: "own" if y > 60 else "mid" if y > 40 else "fg" if y > 20 else "rz")
  f4["went"] = f4.play_type.isin(["pass", "run"]).astype(int)
  f4["conv"] = (f4.went.astype(bool) & (f4.series_success == 1)).astype(int)
  T["fourth"] = by_season(f4, ["dist", "zone"], ["went", "conv"])
  # kicking
  fg = P[P.play_type == "field_goal"].copy()
  fg["d"] = fg.kick_distance.map(lambda y: "60+" if y >= 60 else str(int(y)) if y == y else None)
  fg = fg[fg.d.notna()]; fg["made"] = (fg.field_goal_result == "made").astype(int)
  T["fg"] = by_season(fg, ["d"], ["made"])
  xp = P[P.play_type == "extra_point"].copy(); xp["k"] = "all"; xp["good"] = (xp.extra_point_result == "good").astype(int)
  T["xp"] = by_season(xp, ["k"], ["good"])
  tw = P[P.two_point_attempt == 1].copy()
  tw["how"] = np.where(tw.play_type == "pass", "pass", np.where(tw.play_type == "run", "run", "other"))
  tw["ok"] = (tw.two_point_conv_result == "success").astype(int)
  T["two"] = by_season(tw[tw.how != "other"], ["how"], ["ok"])
  ko = P[P.play_type == "kickoff"].copy()
  ko["onside"] = ko.desc.fillna("").str.contains("onside", case=False)
  on = ko[ko.onside].copy(); on["k"] = "all"; on["rec"] = (on.own_kickoff_recovery == 1).astype(int)
  T["onside"] = by_season(on, ["k"], ["rec"])
  kk = ko[~ko.onside].copy(); kk["k"] = "all"; kk["tb"] = (kk.touchback == 1).astype(int)
  T["kick"] = by_season(kk, ["k"], ["tb"])
  # drives: the first snap of each drive
  sn = P[P.down.notna() & P.fixed_drive.notna()].sort_values(["game_id", "fixed_drive", "game_seconds_remaining"], ascending=[True, True, False])
  first = sn.groupby(["game_id", "fixed_drive"]).head(1).copy()
  first["start"] = (100 - first.yardline_100).clip(1, 99).map(lambda y: f"{int((y - 1) // 10) * 10 + 1}-{int((y - 1) // 10) * 10 + 10}")
  first["td"] = (first.fixed_drive_result == "Touchdown").astype(int); first["fg"] = (first.fixed_drive_result == "Field goal").astype(int)
  T["drive"] = by_season(first, ["start"], ["td", "fg"])
  rz = sn.groupby(["season", "game_id", "fixed_drive"]).agg(minY=("yardline_100", "min"), res=("fixed_drive_result", "first")).reset_index()
  rz = rz[rz.minY <= 20].copy(); rz["k"] = "all"; rz["td"] = (rz.res == "Touchdown").astype(int); rz["fg"] = (rz.res == "Field goal").astype(int)
  T["redzone"] = by_season(rz, ["k"], ["td", "fg"])
  e = scrim[(scrim.down == 1) & (scrim.ydstogo == 10) & scrim.ep.notna()].copy()
  e["yl"] = e.yardline_100.map(lambda y: f"{int((y - 1) // 5) * 5 + 1}-{int((y - 1) // 5) * 5 + 5}")
  T["ep"] = by_season(e, ["yl"], ["ep"])
  # leads: the first play at or after each moment, from the leader's side
  g = P[P.game_seconds_remaining.notna() & P.score_differential.notna() & P.posteam.notna() & P.result.notna()].sort_values(["game_id", "game_seconds_remaining"], ascending=[True, False])
  rows = []
  for lab, secs in MOMENTS:
    snap = g[g.game_seconds_remaining <= secs].groupby("game_id").head(1)
    lead = snap.score_differential.abs()
    home_pos = snap.posteam == snap.home_team
    home_margin = np.where(home_pos, snap.score_differential, -snap.score_differential)
    leader_home = home_margin > 0
    won = np.where(snap.result == 0, 0.5, np.where(leader_home, snap.result > 0, snap.result < 0).astype(float))
    for (lo, hi) in LEAD:
      m = (lead >= lo) & (lead <= hi)
      rows.append(pd.DataFrame({"season": snap.season[m], "moment": lab, "lead": f"{lo}-{hi}" if hi < 99 else f"{lo}+", "won": won[m.to_numpy()]}))
  L = pd.concat(rows, ignore_index=True)
  out = {}
  for (s, mo, le), x in L.groupby(["season", "moment", "lead"]):
    out.setdefault(str(int(s)), {})[f"{mo}|{le}"] = [len(x), round(float(x.won.sum()), 1)]
  T["lead"] = out
  meta = {"seasons": [int(s) for s in sorted(P.season.unique())], "built": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"),
          "rules": {"xp": [2015, "Extra points snapped from the 15 since 2015"], "onside": [2018, "Onside kick rules changed in 2018 (no running start)"],
                    "kick": [2024, "Dynamic kickoff since 2024 (landing zone, touchbacks to the 30, then the 35 in 2025)"]},
          "dist": DIST, "moments": [m for m, _ in MOMENTS], "lead": [f"{lo}-{hi}" if hi < 99 else f"{lo}+" for lo, hi in LEAD]}
  Path(a.out).parent.mkdir(parents=True, exist_ok=True)
  Path(a.out).write_text(json.dumps({"meta": meta, "t": T}, separators=(",", ":")), encoding="utf-8")
  print(f"[ref] wrote {a.out} ({Path(a.out).stat().st_size // 1024} KB)", flush=True)


if __name__ == "__main__":
  main()
