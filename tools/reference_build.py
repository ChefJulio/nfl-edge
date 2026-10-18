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
        "penalty", "qtr", "posteam_score", "defteam_score", "yards_gained", "sack", "rusher_player_id", "receiver_player_id",
        "pass_attempt", "rush_attempt", "rush_touchdown", "pass_touchdown", "penalty_type", "penalty_yards", "penalty_team",
        "replay_or_challenge", "replay_or_challenge_result", "return_yards", "punt_fair_catch", "punt_in_endzone",
        "return_touchdown", "punt_blocked", "total_home_score", "total_away_score", "away_team"]
DIST = [str(i) for i in range(1, 16)] + ["16+"]
LEAD = [(1, 3), (4, 7), (8, 10), (11, 14), (15, 17), (18, 21), (22, 99)]
MOMENTS = [("Halftime", 1800), ("Q4 start", 900), ("Q4 10:00", 600), ("Q4 5:00", 300), ("Q4 2:00", 120)]


def load(seasons, cur):
  import nflreadpy as nfl
  out = []
  for s in seasons:
    p = ROOT / "cache" / f"pbpref2_{s}.parquet"
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
    out.setdefault(str(int(s)), {})["|".join(str(int(x)) if isinstance(x, float) and x == int(x) else str(x) for x in k)] = [int(r.n)] + [
      (int(r[v]) if float(r[v]).is_integer() else round(float(r[v]), 2)) for v in vals]
  return out


MARGINS = [str(i) for i in range(0, 22)] + ["22+"]
COME_T = [("Q1 start", 3600), ("Q2 start", 2700), ("Halftime", 1800), ("Q3 7:30", 1350), ("Q4 start", 900), ("Q4 10:00", 600),
          ("Q4 5:00", 300), ("Q4 2:00", 120), ("Q4 1:00", 60)]
COME_M = ["-17+", "-14 to -16", "-11 to -13", "-9 to -10", "-7 to -8", "-4 to -6", "-1 to -3", "0", "+1 to +3", "+4 to +6", "+7 to +8",
          "+9 to +10", "+11 to +13", "+14 to +16", "+17+"]


def cb_band(m):
  """A score margin as the comeback grid's band label ("-7 to -8", "+17+", "0")."""
  a = abs(m)
  if a == 0:
    return "0"
  sg = "+" if m > 0 else "-"
  if a >= 17:
    return f"{sg}17+"
  lo, hi = next((lo, hi) for lo, hi in ((14, 16), (11, 13), (9, 10), (7, 8), (4, 6), (1, 3)) if a >= lo)
  return f"{sg}{lo} to {sg}{hi}"


def more(P, scrim, sn, first, T):
  """The second batch: TD chance by yard line, explosive plays, short yardage, comeback grid, overtime, final margins,
  home teams, takeaways to points, pass rate by situation, penalties, challenges, punts, blocks and return TDs."""
  import nflreadpy as nfl
  # 1) TD chance of a carry / a target, by yards to the end zone (1-20)
  rz = scrim[scrim.yardline_100.between(1, 20)].copy(); rz["yl"] = rz.yardline_100.astype(int).astype(str)
  car = rz[(rz.play_type == "run")].copy(); car["td"] = (car.rush_touchdown == 1).astype(int)
  tgt = rz[(rz.play_type == "pass") & rz.receiver_player_id.notna()].copy(); tgt["td"] = (tgt.pass_touchdown == 1).astype(int)
  car["kind"] = "carry"; tgt["kind"] = "target"
  import pandas as pd
  T["tdyl"] = by_season(pd.concat([car, tgt]), ["kind", "yl"], ["td"])
  # 2) explosive plays by down and distance band
  sc = scrim.copy()
  sc["band"] = sc.ydstogo.map(lambda y: "1-3" if y <= 3 else "4-6" if y <= 6 else "7-10" if y <= 10 else "11+")
  sc["kind"] = sc.play_type
  sc["big"] = np.where(sc.play_type == "run", sc.yards_gained >= 10, sc.yards_gained >= 20).astype(int)
  T["expl"] = by_season(sc, ["kind", "down", "band"], ["big"])
  # 3) short yardage: 3rd / 4th & 1-2, run / pass / QB run, converted on the play
  try:
    pl = nfl.load_players().to_pandas()
    qbs = set(pl[pl.position == "QB"].gsis_id.dropna())
  except Exception:
    qbs = set()
  sy = scrim[scrim.down.isin([3, 4]) & (scrim.ydstogo <= 2) & (scrim.goal_to_go != 1)].copy()
  sy["how"] = np.where(sy.play_type == "pass", "pass", np.where(sy.rusher_player_id.isin(qbs), "QB run", "run"))
  sy["yd"] = sy.ydstogo.astype(int).astype(str)
  T["short"] = by_season(sy, ["down", "yd", "how"], ["conv_now"])
  # 4) comeback grid: margin for a team at a moment -> that team won (ties half)
  g = P[P.game_seconds_remaining.notna() & P.score_differential.notna() & P.posteam.notna() & P.result.notna()].sort_values(["game_id", "game_seconds_remaining"], ascending=[True, False])
  rows = []
  for lab, secs in COME_T:
    snap = g[g.game_seconds_remaining <= secs].groupby("game_id").head(1)
    home_m = np.where(snap.posteam == snap.home_team, snap.score_differential, -snap.score_differential)
    for side, m, won in (("home", home_m, np.where(snap.result == 0, 0.5, (snap.result > 0).astype(float))),
                         ("away", -home_m, np.where(snap.result == 0, 0.5, (snap.result < 0).astype(float)))):
      rows.append(pd.DataFrame({"season": snap.season.to_numpy(), "t": lab, "m": [cb_band(int(v)) for v in m], "won": won}))
  C = pd.concat(rows, ignore_index=True); out = {}
  for (se, t, m), x in C.groupby(["season", "t", "m"]):
    out.setdefault(str(int(se)), {})[f"{t}|{m}"] = [len(x), round(float(x.won.sum()), 1)]
  T["comeback"] = out
  # 5) overtime: the team with the first possession won
  ot = P[(P.qtr == 5) & P.posteam.notna() & P.down.notna()].sort_values(["game_id", "game_seconds_remaining"], ascending=[True, False]).groupby("game_id").head(1).copy()
  ot["first_home"] = ot.posteam == ot.home_team
  ot["won"] = np.where(ot.result == 0, 0.5, np.where(ot.first_home, ot.result > 0, ot.result < 0).astype(float))
  ot["tie"] = (ot.result == 0).astype(int); ot["k"] = "all"
  T["ot"] = by_season(ot, ["k"], ["won", "tie"])
  # 6) final margins and 7) home teams, one row per game
  games = P.groupby("game_id").agg(season=("season", "first"), result=("result", "first")).dropna()
  games["m"] = games.result.abs().map(lambda v: "22+" if v >= 22 else str(int(v)))
  T["margin"] = by_season(games.assign(one=1), ["m"], ["one"])
  games["k"] = "all"; games["home_w"] = np.where(games.result == 0, 0.5, (games.result > 0).astype(float))
  games["home_by"] = games.result.astype(float)
  T["home"] = by_season(games, ["k"], ["home_w", "home_by"])
  # 8) takeaways to points: the drive after a turnover, by where it starts
  dr = first.sort_values(["game_id", "fixed_drive"]).copy()
  dr["prev"] = dr.groupby("game_id").fixed_drive_result.shift(1)
  ta = dr[dr.prev == "Turnover"].copy()
  T["takeaway"] = by_season(ta, ["start"], ["td", "fg"])
  # 9) pass rate by down, distance band and score
  pr = scrim[scrim.score_differential.notna()].copy()
  pr["band"] = pr.ydstogo.map(lambda y: "1-3" if y <= 3 else "4-6" if y <= 6 else "7-10" if y <= 10 else "11+")
  pr["score"] = pr.score_differential.map(lambda d: "down 9+" if d <= -9 else "down 1-8" if d < 0 else "tied" if d == 0 else "up 1-8" if d <= 8 else "up 9+")
  pr["isp"] = (pr.play_type == "pass").astype(int)
  T["passrate"] = by_season(pr, ["down", "band", "score"], ["isp"])
  # 10) penalties: per type, flags and yards (accepted: the ones the play-by-play enforces)
  pe = P[(P.penalty == 1) & P.penalty_type.notna()].copy(); pe["yd"] = pd.to_numeric(pe.penalty_yards, errors="coerce").fillna(0)
  T["pen"] = by_season(pe, ["penalty_type"], ["yd"])
  T["games"] = by_season(games, ["k"], [])
  # 11) replay: coach's challenges (the text says "challenged") and their result
  rv = P[(pd.to_numeric(P.replay_or_challenge, errors="coerce") == 1)].copy()
  rv["who"] = np.where(rv.desc.fillna("").str.contains("challenged", case=False), "coach", "booth")
  rv["rev"] = (rv.replay_or_challenge_result == "reversed").astype(int)
  T["replay"] = by_season(rv, ["who"], ["rev"])
  # 12) punts by where the punt is from (yards from own goal): gross, net, fair catch, touchback, return TD
  pu = P[(P.play_type == "punt") & P.kick_distance.notna()].copy()
  pu["from"] = (100 - pu.yardline_100).map(lambda y: "own 1-20" if y <= 20 else "own 21-35" if y <= 35 else "own 36-50" if y <= 50 else "opp 49-35" if y <= 65 else "opp 34-")
  pu["gross"] = pd.to_numeric(pu.kick_distance, errors="coerce")
  pu["tb"] = (pd.to_numeric(pu.punt_in_endzone, errors="coerce").fillna(0) == 1).astype(int) | (pd.to_numeric(pu.touchback, errors="coerce").fillna(0) == 1).astype(int)
  pu["net"] = pu.gross - pd.to_numeric(pu.return_yards, errors="coerce").fillna(0) - 20 * pu.tb
  pu["fc"] = (pd.to_numeric(pu.punt_fair_catch, errors="coerce").fillna(0) == 1).astype(int)
  pu["rtd"] = (pd.to_numeric(pu.return_touchdown, errors="coerce").fillna(0) == 1).astype(int)
  T["punt"] = by_season(pu, ["from"], ["gross", "net", "fc", "tb", "rtd"])
  # 13) blocked kicks and return touchdowns, per game
  kk = P[P.play_type.isin(["punt", "field_goal", "extra_point", "kickoff"])].copy()
  kk["blk"] = ((pd.to_numeric(kk.punt_blocked, errors="coerce").fillna(0) == 1) | (kk.field_goal_result == "blocked") | (kk.extra_point_result == "blocked")).astype(int)
  kk["rtd"] = ((pd.to_numeric(kk.return_touchdown, errors="coerce").fillna(0) == 1) & kk.play_type.isin(["punt", "kickoff"])).astype(int)
  T["kicktd"] = by_season(kk, ["play_type"], ["blk", "rtd"])


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
  more(P, scrim, sn, first, T)
  meta = {"seasons": [int(s) for s in sorted(P.season.unique())], "built": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"),
          "rules": {"xp": [2015, "Extra points snapped from the 15 since 2015"], "onside": [2018, "Onside kick rules changed in 2018 (no running start)"],
                    "kick": [2024, "Dynamic kickoff since 2024 (landing zone, touchbacks to the 30, then the 35 in 2025)"],
                    "ot": [2017, "Overtime shortened to 10 minutes in 2017; since 2024 (regular season) both teams get the ball unless the first drive scores a TD"]},
          "margins": MARGINS, "comeback": [c for c, _ in COME_T], "cb_lead": COME_M,
          "dist": DIST, "moments": [m for m, _ in MOMENTS], "lead": [f"{lo}-{hi}" if hi < 99 else f"{lo}+" for lo, hi in LEAD]}
  Path(a.out).parent.mkdir(parents=True, exist_ok=True)
  Path(a.out).write_text(json.dumps({"meta": meta, "t": T}, separators=(",", ":")), encoding="utf-8")
  print(f"[ref] wrote {a.out} ({Path(a.out).stat().st_size // 1024} KB)", flush=True)


if __name__ == "__main__":
  main()
