"""Play-level data for Players > Trends (the query builder, assets/trends.js): data/plays/<season>.json (+ _x) + index.json.

Usage: python tools/trends_build.py [--site=site] [--seasons=1999-2026]   (CI runs it daily; finished seasons cached)
Every run and pass play since 1999 (regular season and playoffs; no kneels, spikes, two-point tries or no-plays),
columnar and compact: teams, games, players and coaches are indexed lists, play fields are small integers.

<season>.json   nflverse play-by-play (1999 on). Missing values: ay / yc -99; cp / xy / temp / wind -999; xp -1;
                pl / rl / gp 0. ty: 0 designed run, 1 dropback (pass or sack), 2 QB scramble (counts as a rush, as in
                nflverse's rushing stats). wp is the offense's win probability x100; wa is WPA x1000; cp is CPOE x10;
                xp is xpass x100 (for pass rate over expected); xy is expected YAC x10. y is the play's yards; yru / yre /
                ypa are the rushing / receiving / passing yards credited (official-stat rules, laterals split); tdr / tdv
                the rusher / receiver scored it, tdq a passing TD, tdo the offense scored.
                games: [game_id, week, is_post, home team idx, indoor 0/1, turf 0/1/-1, temp F, wind mph, division 0/1,
                spread x10 (home favored > 0), total x10, home coach idx, away coach idx].
<season>_x.json charting, same play order, loaded only when a query uses it. NGS participation (2016-2025: formation,
                personnel, box, pass rushers, time to throw, pressure, targeted route, man/zone, coverage shell) and FTN
                charting (2022 on, CC-BY-SA: motion, play action, screen, RPO, blitzers, pocket, drops, catchable,
                contested, interception-worthy, throwaways, read). Box / rushers / alignment fall back to FTN when
                participation is missing (the current season). Missing: -1 for numbers and flags, 0 for vocab codes.
<season>_on.json skill players on the field per play (2016 on, participation); build_on.
<season>_g.json  game context (score, rest, kickoff, site) and who was on each roster / played, per game; build_g.
<season>_st.json special teams (kickoffs, punts, field goals, extra points), kicking team's side; build_st.
index.json      seasons + cov: {season: [columns with values on >= 90% of the plays they apply to]}. Trends.js only
                uses a column in covered seasons and says which seasons it dropped, so a charting gap is never a zero.
Vocabularies changed in 2023 (participation provider): formations and routes are mapped onto one set (FORM, ROUTE);
the out / flat / swing family is merged because its boundaries moved. Coverage labels kept as charted.
"""
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402

V = 8  # 8: a scramble-then-throw is a pass; 7: blank-type 1999 plays kept; 6: credited yards / touchdowns (yru, yre, ypa, tdr, tdv, tdq, tdo) and lateral credit (lv, lvy, lu, luy, ltd)
FIRST = 1999
COVERED = 0.9
COLS = ["game_id", "play_id", "season", "week", "season_type", "posteam", "defteam", "home_team", "play_type", "qtr", "down",
        "ydstogo", "yardline_100", "rush_attempt", "score_differential", "half_seconds_remaining", "yards_gained", "epa", "success",
        "touchdown", "first_down", "shotgun", "no_huddle", "sack", "interception", "complete_pass", "pass_attempt",
        "qb_scramble", "air_yards", "yards_after_catch", "pass_location", "run_location", "run_gap", "rusher_player_id",
        "rusher_player_name", "passer_player_id", "passer_player_name", "receiver_player_id", "receiver_player_name",
        "qb_kneel", "qb_spike", "two_point_attempt", "fumble_lost", "wp", "wpa", "cpoe", "xpass", "qb_hit",
        "tackled_for_loss", "xyac_mean_yardage", "roof", "surface", "temp", "wind", "div_game", "spread_line", "total_line",
        "home_coach", "away_coach", "away_team", "rushing_yards", "receiving_yards", "passing_yards", "rush_touchdown",
        "pass_touchdown", "td_team", "td_player_id", "lateral_receiver_player_id", "lateral_receiver_player_name",
        "lateral_receiving_yards", "lateral_rusher_player_id", "lateral_rusher_player_name", "lateral_rushing_yards",
        # special teams (<season>_st.json)
        "kicker_player_id", "kicker_player_name", "punter_player_id", "punter_player_name", "kickoff_returner_player_id",
        "kickoff_returner_player_name", "punt_returner_player_id", "punt_returner_player_name", "kick_distance",
        "return_yards", "touchback", "punt_inside_twenty", "punt_fair_catch", "punt_blocked", "field_goal_result",
        "extra_point_result", "return_touchdown"]
ST_TYPES = {"kickoff": 0, "punt": 1, "field_goal": 2, "extra_point": 3}
LOC = {"left": 1, "middle": 2, "right": 3}
GAP = {"end": 1, "tackle": 2, "guard": 3}
FORM = {"SHOTGUN": "Shotgun", "EMPTY": "Shotgun", "S": "Shotgun", "UNDER CENTER": "Under center", "SINGLEBACK": "Under center",
        "I_FORM": "Under center", "JUMBO": "Under center", "U": "Under center", "PISTOL": "Pistol", "P": "Pistol", "WILDCAT": "Wildcat"}
ROUTE = {"GO": "Go", "POST": "Post", "CORNER": "Corner", "SLANT": "Slant", "SCREEN": "Screen", "WHEEL": "Wheel",
         "HITCH": "Hitch / curl", "HITCH/CURL": "Hitch / curl", "IN": "In / dig", "IN/DIG": "In / dig",
         "CROSS": "Cross / drag", "SHALLOW CROSS/DRAG": "Cross / drag", "ANGLE": "Angle", "TEXAS/ANGLE": "Angle",
         "OUT": "Out / flat / swing", "FLAT": "Out / flat / swing", "QUICK OUT": "Out / flat / swing",
         "DEEP OUT": "Out / flat / swing", "SWING": "Out / flat / swing"}
COVER = {"COVER_0": "Cover 0", "COVER_1": "Cover 1", "COVER_2": "Cover 2", "2_MAN": "2-man", "COVER_3": "Cover 3",
         "COVER_4": "Cover 4", "COVER_6": "Cover 6", "COVER_9": "Cover 9", "COMBO": "Combo", "PREVENT": "Prevent", "BLOWN": "Blown"}
READ = {"1": "1st read", "2": "2nd read", "3": "3rd+ read", "CHK": "Checkdown", "DES": "Designed", "SD": "Scramble drill"}
TURF = {"grass": 0, "dessograss": 0}
# which plays a column applies to (its coverage denominator): d = dropbacks, t = targets, r = runs, o = outside runs, a = all
APPLIES = {"ay": "t", "yc": "c", "pl": "t", "rl": "r", "gp": "o", "cp": "t", "xp": "a", "xy": "c", "wp": "a", "wa": "a",
           "fm": "a", "op": "a", "db": "a", "bx": "a", "pr": "d", "tt": "d", "pz": "d", "rt": "t", "mz": "d", "cv": "d",
           "mo": "a", "px": "a", "sc": "t", "rp": "a", "tr": "a", "oo": "d", "iw": "t", "ta": "d", "cb": "t", "ct": "t",
           "dr": "t", "cr": "t", "bl": "d", "bf": "a", "rd": "t"}
MISSING = {"ay": -99, "yc": -99, "cp": -999, "xy": -999, "xp": -1, "wp": -1, "wa": None, "pl": 0, "rl": 0, "gp": 0,
           "fm": 0, "op": 0, "rt": 0, "cv": 0, "mz": 0, "rd": 0}


def vocab(values, mapping=None):
  """Strings -> (codes 1.. with 0 = missing, labels)."""
  vals = [mapping.get(v) if mapping is not None else v for v in values]
  vals = [v if isinstance(v, str) and v else None for v in vals]
  labels = sorted({v for v in vals if v})
  idx = {v: i + 1 for i, v in enumerate(labels)}
  return [idx.get(v, 0) for v in vals], labels


def personnel(s):
  """'1 RB, 1 TE, 3 WR' (or the 2023+ form listing every position) -> '11' (backs incl. FB, tight ends)."""
  if not isinstance(s, str) or not s:
    return None
  n = lambda pos: sum(int(m) for m in re.findall(rf"(\d+) {pos}\b", s))  # noqa: E731
  return f"{n('RB') + n('FB')}{n('TE')}"


def dbs(s):
  """Defense personnel -> defensive backs on the field (4 base, 5 nickel, 6+ dime); -1 unknown."""
  if not isinstance(s, str) or not s:
    return -1
  return sum(int(m) for m in re.findall(r"(\d+) (?:DB|CB|FS|SS|S)\b", s))


def build(pbp: pd.DataFrame, season: int, full: dict) -> dict:
  # 1999 files plays with a post-play penalty under a blank play type (owner 2026-10-22 audit: 388 plays, e.g. 88 of
  # Peyton Manning's passing yards): a pass or rush attempt says what it was
  pbp = pbp.copy()
  blank = pbp.play_type.isna() & ((pbp.pass_attempt == 1) | (pbp.rush_attempt == 1))
  pbp.loc[blank, "play_type"] = np.where(pbp.loc[blank, "pass_attempt"] == 1, "pass", "run")
  p = pbp[pbp.play_type.isin(["run", "pass"]) & (pbp.qb_kneel != 1) & (pbp.qb_spike != 1) & (pbp.two_point_attempt != 1)
          & pbp.posteam.notna() & pbp.defteam.notna()].copy()
  for c in ("posteam", "defteam", "home_team", "away_team", "td_team"):
    p[c] = p[c].replace(D.RELOCATED)
  teams = sorted(set(p.posteam) | set(p.defteam))
  ti = {t: i for i, t in enumerate(teams)}
  g = p.drop_duplicates("game_id")
  coaches = sorted({c for c in pd.concat([g.home_coach, g.away_coach]) if isinstance(c, str) and c})
  ci = {c: i for i, c in enumerate(coaches)}
  gi = {gid: i for i, gid in enumerate(g.game_id)}
  ids = {}
  for idc, nmc in (("rusher_player_id", "rusher_player_name"), ("passer_player_id", "passer_player_name"),
                   ("receiver_player_id", "receiver_player_name"), ("lateral_receiver_player_id", "lateral_receiver_player_name"),
                   ("lateral_rusher_player_id", "lateral_rusher_player_name")):
    for gid, n in zip(p[idc], p[nmc]):
      if isinstance(gid, str) and gid not in ids:
        ids[gid] = full.get(gid) or (n if isinstance(n, str) else gid)  # full name from the players table
  plist = list(ids.items())
  pi = {gid: i for i, (gid, _) in enumerate(plist)}
  num = lambda c, d=0: pd.to_numeric(p[c], errors="coerce").fillna(d)  # noqa: E731
  scale = lambda c, k, d: np.where(pd.to_numeric(p[c], errors="coerce").isna(), d, (pd.to_numeric(p[c], errors="coerce") * k).round()).astype(int).tolist()  # noqa: E501,E731
  # nflverse files scrambles under play_type "run" (a scramble then a throw is a pass that keeps the qb_scramble flag:
  # owner 2026-10-22 audit, Flacco to S.Smith 80 yds in 2014): a scramble is a run play with the flag
  typ = np.where((num("qb_scramble").astype(int) == 1) & (p.play_type == "run"), 2, np.where(p.play_type == "run", 0, 1))
  pid = lambda c: [pi.get(x, -1) if isinstance(x, str) else -1 for x in p[c]]  # noqa: E731
  cols = {
    "g": [gi[x] for x in p.game_id], "o": [ti[t] for t in p.posteam], "d": [ti[t] for t in p.defteam], "ty": typ.tolist(),
    "q": num("qtr").astype(int).tolist(), "dn": num("down").astype(int).tolist(), "tg": num("ydstogo").astype(int).tolist(),
    "yl": num("yardline_100", 50).astype(int).tolist(), "sd": num("score_differential").astype(int).tolist(),
    "hs": (num("half_seconds_remaining", 1800) // 10).astype(int).tolist(),  # tens of seconds left in the half
    "y": num("yards_gained").astype(int).tolist(), "e": (num("epa") * 100).round().astype(int).tolist(),
    "s": num("success").astype(int).tolist(), "td": num("touchdown").astype(int).tolist(), "fd": num("first_down").astype(int).tolist(),
    "sg": num("shotgun").astype(int).tolist(), "nh": num("no_huddle").astype(int).tolist(), "sk": num("sack").astype(int).tolist(),
    "in": num("interception").astype(int).tolist(), "c": num("complete_pass").astype(int).tolist(), "pa": num("pass_attempt").astype(int).tolist(),
    "ay": num("air_yards", -99).astype(int).tolist(), "yc": num("yards_after_catch", -99).astype(int).tolist(),
    "pl": [LOC.get(x, 0) for x in p.pass_location], "rl": [LOC.get(x, 0) for x in p.run_location], "gp": [GAP.get(x, 0) for x in p.run_gap],
    "fl": num("fumble_lost").astype(int).tolist(), "qh": num("qb_hit").astype(int).tolist(), "tl": num("tackled_for_loss").astype(int).tolist(),
    "wp": scale("wp", 100, -1), "wa": scale("wpa", 1000, 0), "cp": scale("cpoe", 10, -999), "xp": scale("xpass", 100, -1),
    "xy": scale("xyac_mean_yardage", 10, -999),
    "ru": pid("rusher_player_id"), "pp": pid("passer_player_id"), "re": pid("receiver_player_id"),
    # credited, as in the official stats (owner 2026-10-22 audit): yards split at a lateral, and a touchdown only for the
    # player who scored it (not a fumble / interception returned by the defense, not a teammate after a lateral)
    "yru": num("rushing_yards").astype(int).tolist(), "yre": num("receiving_yards").astype(int).tolist(),
    "ypa": num("passing_yards").astype(int).tolist(),
    "tdr": ((num("rush_touchdown") == 1) & (p.td_player_id == p.rusher_player_id)).astype(int).tolist(),
    "tdv": ((num("pass_touchdown") == 1) & (p.td_player_id == p.receiver_player_id)).astype(int).tolist(),
    "tdq": (num("pass_touchdown") == 1).astype(int).tolist(),
    "tdo": ((num("touchdown") == 1) & (p.td_team == p.posteam)).astype(int).tolist(),
    # after a lateral: the player who took it (on a pass play: lr = receiving, else lu = rushing), his credited yards,
    # and whether he scored (official stats credit those to him, not to the original receiver / rusher)
    "lv": pid("lateral_receiver_player_id"), "lvy": num("lateral_receiving_yards").astype(int).tolist(),
    "lu": pid("lateral_rusher_player_id"), "luy": num("lateral_rushing_yards").astype(int).tolist(),
    "ltd": [int(isinstance(t, str) and (t == a or t == b)) for t, a, b in zip(p.td_player_id, p.lateral_receiver_player_id, p.lateral_rusher_player_id)],
  }
  fin = lambda v, k=1: int(round(float(v) * k)) if pd.notna(v) else -999  # noqa: E731
  games = [[r.game_id, int(r.week), 1 if r.season_type == "POST" else 0, ti.get(r.home_team, -1),
            1 if r.roof in ("dome", "closed") else 0, TURF.get(r.surface, 1) if isinstance(r.surface, str) and r.surface.strip() else -1,
            fin(r.temp), fin(r.wind), int(r.div_game or 0) if pd.notna(r.div_game) else 0, fin(r.spread_line, 10), fin(r.total_line, 10),
            ci.get(r.home_coach, -1), ci.get(r.away_coach, -1)] for r in g.itertuples(index=False)]
  return {"v": V, "season": season, "teams": teams, "coaches": coaches, "games": games, "players": plist, "n": len(p),
          "cols": cols}, p[["game_id", "play_id"]].reset_index(drop=True)


def build_st(pbp: pd.DataFrame, doc: dict, full: dict) -> dict:
  """Special-teams plays (kickoffs, punts, field goals, extra points), every column from the KICKING team's side:
  nflverse makes the receiving team the offense on kickoffs (posteam, EPA, score, win probability), so those are
  flipped. k / r = kicking / receiving team; kp = kicker or punter, rp = returner (player idx, -1 none); mk = made
  (FG / XP good); rt = returned (a returner and no touchback / fair catch); e = EPA x100 for the kicking team."""
  p = pbp[pbp.play_type.isin(list(ST_TYPES)) & pbp.posteam.notna() & pbp.defteam.notna() & pbp.game_id.isin(
    [g[0] for g in doc["games"]])].copy()
  for c in ("posteam", "defteam"):
    p[c] = p[c].replace(D.RELOCATED)
  ti = {t: i for i, t in enumerate(doc["teams"])}
  gi = {g[0]: i for i, g in enumerate(doc["games"])}
  ko = (p.play_type == "kickoff").to_numpy()
  kick = np.where(ko, p.defteam, p.posteam)
  recv = np.where(ko, p.posteam, p.defteam)
  num = lambda c, d=0: pd.to_numeric(p[c], errors="coerce").fillna(d)  # noqa: E731
  flip = np.where(ko, -1, 1)
  wp = pd.to_numeric(p.wp, errors="coerce")
  wpk = np.where(wp.isna(), -1, np.round(np.where(ko, 1 - wp, wp) * 100)).astype(int)
  ids = {}
  kid = p.kicker_player_id.fillna(p.punter_player_id)
  knm = p.kicker_player_name.fillna(p.punter_player_name)
  rid = p.kickoff_returner_player_id.fillna(p.punt_returner_player_id)
  rnm = p.kickoff_returner_player_name.fillna(p.punt_returner_player_name)
  for gid, n in list(zip(kid, knm)) + list(zip(rid, rnm)):
    if isinstance(gid, str) and gid not in ids:
      ids[gid] = full.get(gid) or (n if isinstance(n, str) else gid)
  plist = list(ids.items())
  pi = {g: i for i, (g, _) in enumerate(plist)}
  tb, fc = num("touchback").astype(int), num("punt_fair_catch").astype(int)
  ret = (rid.notna() & (tb == 0) & (fc == 0)).astype(int)
  res = np.where(p.play_type == "field_goal", (p.field_goal_result == "made").astype(int),
                 np.where(p.play_type == "extra_point", (p.extra_point_result == "good").astype(int), 0))
  cols = {
    "g": [gi[x] for x in p.game_id], "k": [ti.get(t, -1) for t in kick], "r": [ti.get(t, -1) for t in recv],
    "t": [ST_TYPES[x] for x in p.play_type], "q": num("qtr").astype(int).tolist(),
    "hs": (num("half_seconds_remaining", 1800) // 10).astype(int).tolist(),
    "sd": (num("score_differential").astype(int) * flip).tolist(), "wp": wpk.tolist(),
    "yl": num("yardline_100", 50).astype(int).tolist(), "kd": num("kick_distance", -1).astype(int).tolist(),
    "ry": num("return_yards").astype(int).tolist(), "rt": ret.tolist(), "tb": tb.tolist(), "fc": fc.tolist(),
    "i20": num("punt_inside_twenty").astype(int).tolist(), "bk": num("punt_blocked").astype(int).tolist(),
    "mk": res.astype(int).tolist(), "td": num("return_touchdown").astype(int).tolist(),
    "fl": num("fumble_lost").astype(int).tolist(), "e": (num("epa") * 100 * flip).round().astype(int).tolist(),
    "kp": [pi.get(x, -1) if isinstance(x, str) else -1 for x in kid],
    "rp": [pi.get(x, -1) if isinstance(x, str) else -1 for x in rid],
  }
  return {"v": V, "season": doc["season"], "players": plist, "n": len(p), "cols": cols}


def charting(keys: pd.DataFrame, part: pd.DataFrame | None, ftn: pd.DataFrame | None) -> dict:
  """Participation + FTN columns aligned to the play order in keys (game_id, play_id)."""
  n, cols, voc = len(keys), {}, {}
  k = keys.copy()
  k["play_id"] = pd.to_numeric(k.play_id, errors="coerce")
  if part is not None and len(part):
    pt = part.rename(columns={"nflverse_game_id": "game_id"}).drop_duplicates(["game_id", "play_id"])
    pt["play_id"] = pd.to_numeric(pt.play_id, errors="coerce")
    m = k.merge(pt, on=["game_id", "play_id"], how="left")
    has = m.possession_team.notna()
  else:
    m, has = None, pd.Series(False, index=k.index)
  if ftn is not None and len(ftn):
    ft = ftn.rename(columns={"nflverse_game_id": "game_id", "nflverse_play_id": "play_id"}).drop_duplicates(["game_id", "play_id"])
    ft["play_id"] = pd.to_numeric(ft.play_id, errors="coerce")
    f = k.merge(ft, on=["game_id", "play_id"], how="left")
    fhas = f.ftn_play_id.notna()
  else:
    f, fhas = None, pd.Series(False, index=k.index)

  def ints(src, c, ok, k_=1):
    v = pd.to_numeric(src[c], errors="coerce") * k_
    return np.where(ok & v.notna(), v.round(), -1).astype(int)

  def flag(src, c, ok):
    v = src[c].map(lambda x: -1 if x is None or (isinstance(x, float) and np.isnan(x)) else int(bool(x)))
    return np.where(ok, v, -1).astype(int)

  if m is not None:
    form = [x if h else None for x, h in zip(m.offense_formation, has)]
    pers = [personnel(x) if h else None for x, h in zip(m.offense_personnel, has)]
    route = [x if h else None for x, h in zip(m.route, has)]
    cover = [x if h else None for x, h in zip(m.defense_coverage_type, has)]
    cols["db"] = [dbs(x) if h else -1 for x, h in zip(m.defense_personnel, has)]
    cols["bx"] = ints(m, "defenders_in_box", has)
    cols["pr"] = ints(m, "number_of_pass_rushers", has)
    cols["tt"] = ints(m, "time_to_throw", has, 10)
    cols["pz"] = flag(m, "was_pressure", has)
    cols["mz"] = [1 if x == "MAN_COVERAGE" else 2 if x == "ZONE_COVERAGE" else 0 for x in m.defense_man_zone_type]
  else:
    form, pers, route, cover = [None] * n, [None] * n, [None] * n, [None] * n
  if f is not None:
    for c, src in (("mo", "is_motion"), ("px", "is_play_action"), ("sc", "is_screen_pass"), ("rp", "is_rpo"),
                   ("tr", "is_trick_play"), ("oo", "is_qb_out_of_pocket"), ("iw", "is_interception_worthy"),
                   ("ta", "is_throw_away"), ("cb", "is_catchable_ball"), ("ct", "is_contested_ball"), ("dr", "is_drop"),
                   ("cr", "is_created_reception")):
      cols[c] = flag(f, src, fhas)
    cols["bl"] = ints(f, "n_blitzers", fhas)
    cols["bf"] = ints(f, "n_offense_backfield", fhas)
    rd = [READ.get(str(x)) if h else None for x, h in zip(f.read_thrown, fhas)]
    cols["rd"], voc["rd"] = vocab(rd, None)
    # participation is the primary source; FTN fills alignment / box / rushers where it is missing (the current season)
    form = [a if a else (b if h else None) for a, b, h in zip(form, f.qb_location, fhas)]
    if "bx" not in cols:
      cols["bx"], cols["pr"] = ints(f, "n_defense_box", fhas), ints(f, "n_pass_rushers", fhas)
  if any(form):
    cols["fm"], voc["fm"] = vocab(form, FORM)
  if any(pers):
    cols["op"], voc["op"] = vocab(pers, None)
  if any(route):
    cols["rt"], voc["rt"] = vocab(route, ROUTE)
  if any(cover):
    cols["cv"], voc["cv"] = vocab(cover, COVER)
  cols = {c: (v.tolist() if isinstance(v, np.ndarray) else list(v)) for c, v in cols.items()}
  for c in [c for c, v in cols.items() if all(x in (-1, 0) for x in v)]:  # a column with no data at all is not shipped
    del cols[c]
    voc.pop(c, None)
  return {"cols": cols, "vocab": voc}


GV = 1
DAYS = {"Sunday": 0, "Monday": 1, "Tuesday": 2, "Wednesday": 3, "Thursday": 4, "Friday": 5, "Saturday": 6}
GONE = {"CUT", "RET", "TRD"}  # weekly-roster statuses that mean he wasn't the team's that week


def build_g(doc: dict, sched: pd.DataFrame, snaps: pd.DataFrame | None, rost: pd.DataFrame | None, pfr: dict) -> dict:
  """<season>_g.json, game context for the Game / teammate filters, aligned to doc["games"]:
  x: [home score, away score, home rest days, away rest days, weekday 0 = Sunday, kickoff minutes after midnight ET,
     neutral site 0/1] (-1 missing), from nflverse schedules.
  r: [home, away] per game: the season's ball-carriers / passers / targets (doc player idx i) on that team that week,
     +(i+1) if he played, -(i+1) if he was on the roster (any weekly status but cut / retired / traded) and didn't.
     Played = an offensive snap (snap counts, 2012 on) or a play in the data; on the roster = nflverse weekly
     rosters (2002 on), before that the team's players with a play that season."""
  pi = {g: i for i, (g, _) in enumerate(doc["players"])}
  T, cols, G = doc["teams"], doc["cols"], doc["games"]
  ti = {t: i for i, t in enumerate(T)}
  # who touched the ball, per game and team, and per team over the season
  touched, season_team = {}, {}
  for g, o, *who in zip(cols["g"], cols["o"], cols["ru"], cols["pp"], cols["re"]):
    for p in who:
      if p >= 0:
        touched.setdefault((g, o), set()).add(p)
        season_team.setdefault(o, set()).add(p)
  sc = sched.set_index("game_id")
  gidx = {g[0]: i for i, g in enumerate(G)}
  played = {}
  if snaps is not None and len(snaps):
    s = snaps[(snaps.offense_snaps.fillna(0) > 0) & snaps.game_id.isin(gidx)]
    for gid, team, pid in zip(s.game_id, s.team.replace(D.RELOCATED), s.pfr_player_id):
      i = pi.get(pfr.get(pid))
      if i is not None and team in ti:
        played.setdefault((gidx[gid], ti[team]), set()).add(i)
  on = {}
  if rost is not None and len(rost):
    r = rost[~rost.status.isin(GONE) & rost.gsis_id.notna()]
    for wk, team, gs in zip(r.week, r.team.replace(D.RELOCATED), r.gsis_id):
      i = pi.get(gs)
      if i is not None and team in ti:
        on.setdefault((int(wk), ti[team]), set()).add(i)
  x, rr = [], []
  for gi, g in enumerate(G):
    row = sc.loc[g[0]] if g[0] in sc.index else None
    num = lambda c: int(row[c]) if row is not None and pd.notna(row[c]) else -1  # noqa: E731
    hm = str(row.gametime) if row is not None and isinstance(row.gametime, str) and ":" in row.gametime else ""
    x.append([num("home_score"), num("away_score"), num("home_rest"), num("away_rest"),
              DAYS.get(row.weekday, -1) if row is not None else -1,
              int(hm[:2]) * 60 + int(hm[3:5]) if hm else -1, 1 if row is not None and row.location == "Neutral" else 0])
    home = g[3]
    away = ti.get(D.RELOCATED.get(row.away_team, row.away_team), -1) if row is not None else -1
    sides = []
    for t in (home, away):
      pl = touched.get((gi, t), set()) | played.get((gi, t), set())
      roster = on.get((g[1], t)) if on else season_team.get(t, set())
      sides.append(sorted([i + 1 for i in pl] + [-(i + 1) for i in (roster or set()) - pl]))
    rr.append(sides)
  return {"v": GV, "season": doc["season"], "x": x, "r": rr}


JUCO = re.compile(r"\b(JC|CC|J\.C\.|Junior College|Community College)\b", re.I)


def school(s) -> str | None:
  """'Florida State; Jones County JC' -> 'Florida State' (the four-year school; else the first listed)."""
  if not isinstance(s, str) or not s.strip():
    return None
  parts = [x.strip() for x in s.split(";") if x.strip()]
  return next((x for x in parts if not JUCO.search(x)), parts[0] if parts else None)


def bio(players: pd.DataFrame, contracts: pd.DataFrame | None, out: Path) -> None:
  """bio.json, player facts for the Player filters / breakdowns, for every player in the season files under out:
  {schools: [...], confs: [...], p: {gsis: [school idx (-1), conf idx (-1), draft round (1-7, 7 = 7th or later, 8 undrafted),
  overall pick (-1), contracts [[year signed, years, APY in $10k, APY as % of the cap x 10], ...], birth date YYYYMMDD (-1),
  rookie season (-1)]}}.
  College / draft from nflverse's players table; contracts from its OverTheCap table (the page uses, for a play, the
  latest contract signed by that season and still running)."""
  want = set()
  for f in out.glob("[0-9][0-9][0-9][0-9]*.json"):
    if re.fullmatch(r"\d{4}(_st)?\.json", f.name):
      want |= {g for g, _ in json.loads(f.read_text(encoding="utf-8"))["players"]}
  pl = players[players.gsis_id.isin(want)].drop_duplicates("gsis_id")
  deals = {}
  if contracts is not None and len(contracts):
    c = contracts[contracts.gsis_id.isin(want) & (pd.to_numeric(contracts.year_signed, errors="coerce") > 1900)]
    for g, ys, yrs, apy, cap in zip(c.gsis_id, c.year_signed, c.years, c.apy, c.apy_cap_pct):
      if pd.notna(apy):
        deals.setdefault(g, []).append([int(ys), int(yrs) if pd.notna(yrs) and yrs > 0 else 1, int(round(float(apy) * 100)),
                                        int(round(float(cap) * 1000)) if pd.notna(cap) else -1])
  rows = []
  born = lambda b: int(str(b)[:10].replace("-", "")) if isinstance(b, str) and len(b) >= 10 else -1  # noqa: E731
  for g, col, cf, rnd, pick, bd, rk in zip(pl.gsis_id, pl.college_name, pl.college_conference, pl.draft_round, pl.draft_pick,
                                         pl.birth_date, pl.rookie_season):
    rows.append((g, school(col), cf if isinstance(cf, str) and cf.strip() else None, born(bd), int(rk) if pd.notna(rk) else -1,
                 min(int(rnd), 7) if pd.notna(rnd) else 8, int(pick) if pd.notna(pick) else -1))  # 7 = 7th or later (pre-1994 drafts ran to 12)
  schools, confs = sorted({r[1] for r in rows if r[1]}), sorted({r[2] for r in rows if r[2]})
  si, ci = {x: i for i, x in enumerate(schools)}, {x: i for i, x in enumerate(confs)}
  doc = {"v": 1, "schools": schools, "confs": confs,
         "p": {g: [si.get(sc, -1), ci.get(cf, -1), rnd, pick, sorted(deals.get(g, [])), bd, rk] for g, sc, cf, bd, rk, rnd, pick in rows}}
  (out / "bio.json").write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
  (out / "colleges.json").unlink(missing_ok=True)
  print(f"[plays] bio: {len(rows)} players, {len(schools)} schools, {sum(1 for g in deals)} with contracts", flush=True)


OV = 1
SKILL = {"QB", "RB", "FB", "WR", "TE"}
ON_FIRST = 2016


def build_on(keys: pd.DataFrame, part: pd.DataFrame | None, full: dict, season: int, pos_of: dict) -> dict | None:
  """<season>_on.json (owner 2026-10-22: snap-level with / without, routes run): the offense's skill players on the field
  (QB, RB, FB, WR, TE) for every play in the season file's order, from NGS participation (2016 on; not published for
  the current season). pl: [[gsis, name, position]]; p: per play a sorted list of pl idx, or null without participation.
  Positions come with the participation from 2023; before that only the player ids do, so the players table's
  position stands in (pos_of)."""
  if part is None or not len(part):
    return None
  k = keys.copy()
  k["play_id"] = pd.to_numeric(k.play_id, errors="coerce")
  pt = part.rename(columns={"nflverse_game_id": "game_id"}).drop_duplicates(["game_id", "play_id"])
  pt["play_id"] = pd.to_numeric(pt.play_id, errors="coerce")
  for c in ("offense_positions", "offense_names"):
    if c not in pt:
      pt[c] = None
  m = k.merge(pt[["game_id", "play_id", "offense_players", "offense_positions", "offense_names"]], on=["game_id", "play_id"], how="left")
  pl, pi, plays = [], {}, []
  for ids, pos, nms in zip(m.offense_players, m.offense_positions, m.offense_names):
    if not isinstance(ids, str) or not ids:
      plays.append(None)
      continue
    ids, pos = ids.split(";"), (pos.split(";") if isinstance(pos, str) else [])
    nms = nms.split(";") if isinstance(nms, str) else []
    row = []
    for i, g in enumerate(ids):
      ps = pos[i] if i < len(pos) else pos_of.get(g, "")
      if ps not in SKILL or not g:
        continue
      if g not in pi:
        pi[g] = len(pl)
        pl.append([g, full.get(g) or (nms[i] if i < len(nms) else g), ps])
      row.append(pi[g])
    plays.append(sorted(row))
  if sum(r is not None for r in plays) < 0.5 * len(plays):
    return None
  return {"v": OV, "season": season, "pl": pl, "p": plays}


def coverage(doc: dict, x: dict) -> list:
  """Columns with values on >= COVERED of the plays they apply to (APPLIES), for index.json."""
  c = doc["cols"]
  ty, re_, pa, sk, cm, rl = (np.array(c[k]) for k in ("ty", "re", "pa", "sk", "c", "rl"))
  masks = {"a": np.ones(len(ty), bool), "d": ty == 1, "t": (ty == 1) & (re_ >= 0) & (pa == 1) & (sk == 0),
           "c": (ty == 1) & (cm == 1), "r": ty == 0, "o": (ty == 0) & np.isin(rl, (1, 3))}
  out = []
  for k, kind in APPLIES.items():
    v = c.get(k, x["cols"].get(k))
    if v is None:
      continue
    v, mk = np.array(v), masks[kind]
    if not mk.any():
      continue
    miss = MISSING.get(k, -1)
    if miss is None:
      out.append(k)
      continue
    ok = v[mk] != miss if k not in ("db", "bx", "pr", "tt", "bl", "bf") else v[mk] >= 0
    if ok.mean() >= COVERED:
      out.append(k)
  return sorted(out)


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = Path(opt.get("site", "site"))
  import nflreadpy as nfl
  cfg = load_config()
  current = int(nfl.get_current_season())
  a, _, b = opt.get("seasons", f"{FIRST}-{current}").partition("-")
  out = site / "data" / "plays"
  out.mkdir(parents=True, exist_ok=True)
  kept = ROOT / cfg["data"]["cache_dir"] / "plays_site" / f"v{V}"
  kept.mkdir(parents=True, exist_ok=True)
  players = nfl.load_players().select(["gsis_id", "display_name", "pfr_id", "college_name", "college_conference", "draft_round", "draft_pick", "birth_date", "rookie_season", "position"]).to_pandas()
  full = {g: n for g, n in zip(players.gsis_id, players.display_name) if isinstance(g, str) and isinstance(n, str)}
  pfr = {p: g for p, g in zip(players.pfr_id, players.gsis_id) if isinstance(p, str) and isinstance(g, str)}
  pos_of = {g: ("RB" if p == "FB" else p) for g, p in zip(players.gsis_id, players.position) if isinstance(g, str) and isinstance(p, str)}
  ixf = out / "index.json"
  cov = json.loads(ixf.read_text(encoding="utf-8")).get("cov", {}) if ixf.exists() else {}
  for s in range(int(a), int(b or a) + 1):
    names = (f"{s}.json", f"{s}_x.json", f"{s}_cov.json", f"{s}_st.json")
    on_nm = f"{s}_on.json"
    want_on = ON_FIRST <= s < current
    if s < current and all((kept / nm).exists() for nm in names) and (not want_on or (kept / f"{s}_on{OV}.json").exists()):
      for nm in (names[0], names[1], names[3]):
        shutil.copyfile(kept / nm, out / nm)
      if want_on:
        shutil.copyfile(kept / f"{s}_on{OV}.json", out / on_nm)
      cov[str(s)] = json.loads((kept / names[2]).read_text(encoding="utf-8"))
      continue
    try:
      pbp = nfl.load_pbp([s]).select(COLS).to_pandas()
    except Exception as e:
      print(f"[plays] {s}: unavailable ({e})", flush=True)
      continue
    doc, keys = build(pbp, s, full)
    part = ftn = None
    try:
      part = nfl.load_participation([s]).to_pandas() if s >= 2016 else None
    except Exception:
      pass
    try:
      ftn = nfl.load_ftn_charting([s]).to_pandas() if s >= 2022 else None
    except Exception:
      pass
    x = charting(keys, part, ftn)
    x.update({"v": V, "season": s, "n": doc["n"]})
    cv = coverage(doc, x)
    cov[str(s)] = cv
    st = build_st(pbp, doc, full)
    for nm, d in ((names[0], doc), (names[1], x), (names[2], cv), (names[3], st)):
      (out / nm).write_text(json.dumps(d, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    on = build_on(keys, part, full, s, pos_of) if s >= ON_FIRST else None
    if on:
      (out / on_nm).write_text(json.dumps(on, separators=(",", ":")), encoding="utf-8")
      if s < current:
        shutil.copyfile(out / on_nm, kept / f"{s}_on{OV}.json")
    if s < current:
      for nm in names:
        shutil.copyfile(out / nm, kept / nm)
    (out / names[2]).unlink()
    print(f"[plays] {s}: {doc['n']} plays, {len(doc['players'])} players, {len(x['cols'])} charting cols, "
          f"{(out / names[0]).stat().st_size / 1e6:.1f} + {(out / names[1]).stat().st_size / 1e6:.1f} MB, "
          f"{st['n']} special-teams plays", flush=True)
  # game context + who played (<season>_g.json), from the season files just written; finished seasons cached
  sched = None
  for s in range(int(a), int(b or a) + 1):
    nm, src = f"{s}_g.json", out / f"{s}.json"
    if not src.exists():
      continue
    if s < current and (kept / f"{s}_g{GV}.json").exists():
      shutil.copyfile(kept / f"{s}_g{GV}.json", out / nm)
      continue
    if sched is None:
      sched = nfl.load_schedules().to_pandas()
    snaps = rost = None
    try:
      snaps = nfl.load_snap_counts([s]).to_pandas() if s >= 2012 else None
    except Exception as e:
      print(f"[plays] {s}: no snap counts ({e})", flush=True)
    try:
      rost = nfl.load_rosters_weekly([s]).to_pandas() if s >= 2002 else None
    except Exception as e:
      print(f"[plays] {s}: no weekly rosters ({e})", flush=True)
    gd = build_g(json.loads(src.read_text(encoding="utf-8")), sched[sched.season == s], snaps, rost, pfr)
    (out / nm).write_text(json.dumps(gd, separators=(",", ":")), encoding="utf-8")
    if s < current:
      shutil.copyfile(out / nm, kept / f"{s}_g{GV}.json")
    print(f"[plays] {s}: game context for {len(gd['x'])} games", flush=True)
  # player facts (owner 2026-10-22: "plays that went to u of florida", "contract aav? draft round? draft position?"):
  # college, draft, contracts for every player in the play files; one file, loaded only by those filters / breakdowns
  try:
    contracts = nfl.load_contracts().to_pandas()
  except Exception as e:
    contracts = None
    print(f"[plays] no contracts ({e})", flush=True)
  bio(players, contracts, out)
  seasons = sorted(int(p.stem) for p in out.glob("[0-9][0-9][0-9][0-9].json"))
  ixf.write_text(json.dumps({"v": V, "seasons": seasons, "current": current, "tracked": sorted(APPLIES),
                             "cov": {str(s): cov.get(str(s), []) for s in seasons}}, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
  main()
