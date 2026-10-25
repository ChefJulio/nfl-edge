"""Accept / decline: rebuilding the branch a game didn't take ((PB) in docs/INSIGHTS.md; owner 2026-10-25: "when a
team gets penalized, the other team can decide to accept or decline ... can we fold them into our graded calls list?").

A foul during a run or pass gives the team that didn't foul a choice: the play's result, or the penalty. The next
snap shows only the branch taken. This module rebuilds either one from the snap's state, the play text and the foul:
  parse(desc)                      - the foul (type, team, declined?) and the play (kind, yards) from nflfastR's text
  penalty_branch(st, foul, play)   - the state after the penalty is enforced (None: the text can't give the spot)
  play_branch(st, play)            - the state after the play, as if no foul
  choice_rows(pbp)                 - (PC) every gradeable choice: the team that chose, both branches as engine states
States are from the side of the team with the ball at the snap: {down, togo, yl (yards to the end zone)}; a branch
also says who has the ball next ("same" / "other": a turnover on downs, the new team's yl).

Rules: the 2026 Official Playing Rules (scratch/rulebook/review.md; Rule 14 enforcement, 14-1-2 automatic first
downs, 14-2-1 half the distance, 14-3-6 three-and-one, 14-4-5 pass plays). Scope: single fouls during scrimmage
plays; kicking plays, pre-snap fouls, multiple fouls, turnovers and scores on the play are left out.
"""
from __future__ import annotations

import re

import pandas as pd

# foul -> (yards, category). Categories:
#   snap5    5 yards from the previous spot, no automatic first down (fouls at the snap: offside, encroachment, ...)
#   pass     from the previous spot (fouls during the pass: illegal contact, pass interference by the offense, ...)
#   general  "G": pass plays from the previous spot; runs: the defense from the end of the run (past the line), the
#            offense three-and-one (the spot of the foul if the run gained: unknown here)
#   personal 15-yard personal fouls: as general, and the defense's after a completion: the better of previous spot and
#            end of the play (14-4-5(d))
#   after    after the play (taunting, unsportsmanlike): the play stands, enforced from where it ended
#   spot     the spot of the foul (defensive pass interference): unknown here
#   ground   intentional grounding: 10 from the previous spot, loss of down
#   ifp      illegal forward pass: 5 from the spot of the pass (taken as the previous spot), loss of down
#   lod      loss of down only
FOULS = {
  "Defensive Offside": (5, "snap5"), "Neutral Zone Infraction": (5, "snap5"), "Encroachment": (5, "snap5"),
  "Defensive Too Many Men on Field": (5, "snap5"), "Offensive Offside": (5, "snap5"), "Illegal Formation": (5, "snap5"),
  "Illegal Shift": (5, "snap5"), "Illegal Motion": (5, "snap5"), "Offensive Too Many Men on Field": (5, "snap5"),
  "Illegal Substitution": (5, "snap5"), "False Start": (5, "snap5"),
  # (PB, 2022-23 look) with a play before them these are dead-ball fouls after it (succeeding spot, 14-4-9)
  "Delay of Game": (5, "after"), "Defensive Delay of Game": (5, "after"),
  "Ineligible Downfield Pass": (5, "pass"), "Illegal Contact": (5, "pass"),
  "Illegal Touch Pass": (0, "lod"),  # (PB) the receiver out and back in: loss of down, no yards (8-1-8)
  "Offensive Pass Interference": (10, "pass"),
  "Defensive Holding": (5, "general"), "Illegal Use of Hands": (5, "general"),
  "Offensive Holding": (10, "general"), "Illegal Block Above the Waist": (10, "general"),
  # (PB, 2022-23 look) mostly late hits: a dead-ball foul from where the play ended, which stands (14-2-4, 14-4-9)
  "Unnecessary Roughness": (15, "after"), "Face Mask": (15, "personal"), "Face Mask (15 Yards)": (15, "personal"),
  "Roughing the Passer": (15, "personal"), "Horse Collar Tackle": (15, "personal"), "Tripping": (15, "personal"),
  "Lowering the Head to Make Forcible Contact": (15, "personal"), "Lowering the Head to Initiate Contact": (15, "personal"),
  "Illegal Blindside Block": (15, "personal"), "Low Block": (15, "personal"), "Chop Block": (15, "personal"),
  "Clipping": (15, "personal"), "Illegal Crackback": (15, "personal"), "Illegal Peelback": (15, "personal"),
  "Hip-Drop Tackle": (15, "personal"), "Illegal Hip-Drop Tackle": (15, "personal"), "Use of Helmet": (15, "personal"),
  "Taunting": (15, "after"), "Unsportsmanlike Conduct": (15, "after"),
  "Defensive Pass Interference": (None, "spot"),
  "Intentional Grounding": (10, "ground"), "Illegal Forward Pass": (5, "ifp"),
}
# 14-1-2 Item 5: the defense's fouls WITHOUT an automatic first down (of the categories above: the snap5 ones)
NO_AFD = {"Defensive Offside", "Neutral Zone Infraction", "Encroachment", "Defensive Too Many Men on Field",
          "Illegal Substitution", "Defensive Delay of Game", "Delay of Game"}

FOUL_RE = re.compile(r"(?i)penalty on ([A-Z]{2,3})(?:-[^,]*)?, ([^,.]+?)(?:,|\.|$)")
LEAD = re.compile(r"^(?:\([^)]*\)\s*)*")
KICK = re.compile(r"(?i)\bpunts\b|\bkicks\b|field goal|extra point|two-point|onside")  # kicking plays: out of scope
YARDS = re.compile(r"for (-?\d+) yards?|for (no gain)")


def parse(desc: str) -> dict | None:
  """The single foul and the play before it; None when the text has no foul or more than one."""
  if not isinstance(desc, str) or len(re.findall(r"(?i)penalty on", desc)) != 1:
    return None
  m = FOUL_RE.search(desc)
  if not m:
    return None
  pre = LEAD.sub("", desc[:re.search(r"(?i)penalty on", desc).start()])
  low = pre.lower()
  kind, gain = None, None
  if "kneels" in low or "spiked" in low or "aborted" in low or KICK.search(pre):
    kind = None
  elif "sacked" in low:
    kind = "sack"
  elif "incomplete" in low:
    kind, gain = "incomplete", 0
  elif re.search(r"\bpass\b", low):
    kind = "complete"
  elif re.search(r"\d+-[A-Z]", pre):
    kind = "run"
  if kind and gain is None:
    y = YARDS.search(pre)
    gain = (0 if y.group(2) else int(y.group(1))) if y else None
  return {"team": m.group(1), "foul": m.group(2).strip(), "declined": "declined" in desc.lower(),
          "kind": kind if gain is not None else None, "gain": gain}


def _first_down(yl: float) -> dict:
  return {"down": 1, "togo": min(10, yl), "yl": yl, "ball": "same"}


def _after_downs(st: dict, yl: float, down: int, line: float) -> dict:
  """A down at `yl` with the line to gain at `line` (yards to the end zone); past 4th: a turnover on downs."""
  if yl <= line:
    return _first_down(yl)
  if down > 4:
    return {"down": 1, "togo": 10, "yl": 100 - yl, "ball": "other"}
  return {"down": down, "togo": yl - max(line, 0), "yl": yl, "ball": "same"}  # line <= 0: goal to go


def play_branch(st: dict, play: dict) -> dict:
  """The play's own result (the foul declined)."""
  yl = st["yl"] - play["gain"]
  return _after_downs(st, yl, st["down"] + 1, st["yl"] - st["togo"])


def unit(foul: str, side: str, play: dict) -> str:
  """The scope unit a foul is checked in, as pre-registered: foul x side x play kind (runs split by gain for the
  offense's G fouls)."""
  k = play["kind"]
  if k == "run" and side == "offense" and FOULS.get(foul, (0, ""))[1] in ("general", "personal"):
    k = "run+" if play["gain"] > 0 else "run-"
  return f"{foul} | {side} | {k}"


def path_unit(st: dict, foul: str, side: str, play: dict) -> str:
  """(PB amendment, 2026-10-25, before the gate) foul x side x how it's enforced: from the previous spot (the play
  wiped) or from the end of the play (it stands); "unknown" when the text can't give the spot."""
  e = enforcement(st, foul, side, play)
  return f"{foul} | {side} | {'unknown' if e is None else 'end' if e[1] else 'previous'}"


def enforcement(st: dict, foul: str, side: str, play: dict) -> tuple | None:
  """Where the penalty is enforced and whether the play stands: (spot, stands); None when the text can't give the
  spot (the spot of the foul) or the foul isn't in the table."""
  if foul not in FOULS or FOULS[foul][1] == "spot":
    return None
  cat = FOULS[foul][1]
  y, end, kind = st["yl"], st["yl"] - play["gain"], play["kind"]
  stands = False
  if cat == "after":
    spot, stands = end, True
  elif cat == "pass" and kind == "run" and side == "defense":
    spot, stands = (end, True) if end < y else (y, False)  # (PB) a scramble: a run's basic spot (14-3-6)
  elif cat in ("snap5", "pass", "ground", "ifp", "lod"):
    spot = y
  elif kind in ("incomplete", "sack"):
    spot = y
  elif kind == "complete":
    if side == "defense" and cat == "personal" and end < y:
      spot, stands = end, True  # better of previous spot and end of the play
    elif side == "offense" and cat in ("general", "personal") and play["gain"] > 0:
      return None  # (PB) may come after the catch (the run that follows: three-and-one, the spot of the foul)
    else:
      spot = y
  else:  # run
    if side == "defense":
      spot, stands = (end, True) if end < y else (y, False)
    elif play["gain"] > 0:
      return None  # three-and-one: the spot of the foul
    else:
      spot = y
  return spot, stands


def penalty_branch(st: dict, foul: str, side: str, play: dict) -> dict | None:
  """The state after the penalty is enforced (accepted); None when the text can't give the spot."""
  e = enforcement(st, foul, side, play)
  if e is None:
    return None
  spot, stands = e
  yds, cat = FOULS[foul]
  y = st["yl"]
  line = y - st["togo"]
  if side == "defense":
    yl = spot - min(yds, spot / 2)
    if stands:
      after = play_branch(st, play)  # the play's down and line, then the yardage
      if foul not in NO_AFD or after["down"] == 1:
        return _first_down(yl)
      return _after_downs(st, yl, after["down"], after["yl"] - after["togo"])
    if foul not in NO_AFD:
      return _first_down(yl)
    return _after_downs(st, yl, st["down"], line)
  # the offense's foul: toward its own goal (half the distance from there)
  yl = spot + min(yds, (100 - spot) / 2)
  if stands:
    after = play_branch(st, play)
    if after["ball"] == "other":
      return {**after, "yl": 100 - yl}
    if after["down"] == 1:  # (PB) a dead-ball foul after earning a first down: 1st & 10 from the new spot (14-4-9)
      return _first_down(yl)
    return _after_downs(st, yl, after["down"], after["yl"] - after["togo"])
  down = st["down"] + 1 if cat in ("ground", "ifp", "lod") else st["down"]
  return _after_downs(st, yl, down, line)


def near_line(st: dict, foul: str, side: str) -> bool:
  """(PB, 2022-23 look) play-by-play rounds spots to whole yards: a foul without an automatic first down whose yards
  are within 1 of the yards to go may land either side of the line (3rd & 5, offside: 1st & 10 or 3rd & 0.5). Both
  outcomes are rebuilt (penalty_branches); a call is graded only when both give the same verdict."""
  yds = FOULS.get(foul, (None, ""))[0]
  return side == "defense" and foul in NO_AFD and yds is not None and abs(yds - st["togo"]) <= 1


def penalty_branches(st: dict, foul: str, side: str, play: dict) -> list:
  """penalty_branch, plus the other side of the line when the spot rounding makes it ambiguous (near_line)."""
  b = penalty_branch(st, foul, side, play)
  if b is None or b["ball"] != "same" or not near_line(st, foul, side):
    return [b] if b else []
  short = {"down": st["down"], "togo": max(st["togo"] - FOULS[foul][0], 1), "yl": b["yl"], "ball": "same"}
  return [b, short] if b["down"] == 1 else [b, _first_down(b["yl"])]


# (PB, {#penalty-rules}) the rebuild paths that matched 95%+ on 20+ accepted fouls in 2024-25 (tools/penalty_check.py
# --gate, amended units): a DECLINED foul is graded only on one of these (an accepted one needs only the play branch)
IN_SCOPE = {
  "Defensive Offside | defense | previous", "Defensive Holding | defense | previous",
  "Unnecessary Roughness | defense | end", "Offensive Holding | offense | previous",
  "Illegal Formation | offense | previous", "Illegal Contact | defense | previous",
  "Offensive Pass Interference | offense | previous", "Ineligible Downfield Pass | offense | previous",
  "Defensive Holding | defense | end", "Roughing the Passer | defense | previous", "Illegal Shift | offense | previous",
  "Face Mask | defense | end", "Roughing the Passer | defense | end", "Illegal Use of Hands | defense | previous",
  "Face Mask | defense | previous", "Illegal Use of Hands | defense | end",
  "Defensive Too Many Men on Field | defense | previous", "Offensive Offside | offense | previous",
  "Illegal Motion | offense | previous"}
EVENT = r"INTERCEPTED|FUMBLES|TOUCHDOWN|SAFETY|BLOCKED|recovered"


def choice_rows(pbp: pd.DataFrame) -> pd.DataFrame:
  """(PC) every gradeable accept / decline choice in regular-season play-by-play: single fouls on runs and passes, no
  score or turnover on the play, not at a half's end, a declined foul on an IN_SCOPE path. Both branches are engine
  states at the NEXT snap's clock and timeouts (4-3-2(e): the clock runs as if there had been no foul), from the side
  of the team with the ball at the snap; own = False: the other team has it (a turnover on downs), the state is from
  its side. `took` is the real next snap; `alt` the rebuilt branch (two states when the spot rounding is ambiguous)."""
  d = pbp[pbp.season_type == "REG"].sort_values(["game_id", "play_id"]).reset_index(drop=True)
  ko = d[(d.kickoff_attempt == 1) & (d.qtr == 1) & d.posteam.notna()].drop_duplicates("game_id").set_index("game_id").posteam
  snap = d[d.down.notna() & d.posteam.notna() & (d.timeout != 1)].copy()
  cols = ["posteam", "down", "ydstogo", "yardline_100", "qtr", "game_seconds_remaining", "posteam_timeouts_remaining",
          "defteam_timeouts_remaining"]
  snap = snap.join(snap.groupby("game_id")[cols].shift(-1).add_prefix("n_"))
  x = snap[snap.desc.str.contains(r"(?i)penalty on", na=False) & ~snap.desc.str.contains(EVENT, na=False)
           & (snap.qtr <= 4) & snap.n_down.notna() & ~((snap.n_qtr != snap.qtr) & snap.qtr.isin([2, 4]))]
  out = []
  for r in x.itertuples():
    p = parse(r.desc)
    if not p or p["kind"] is None or p["foul"] not in FOULS:
      continue
    side = "offense" if p["team"] == r.posteam else "defense" if p["team"] == r.defteam else None
    if side is None:
      continue
    st, play = {"down": int(r.down), "togo": float(r.ydstogo), "yl": float(r.yardline_100)}, {"kind": p["kind"], "gain": p["gain"]}
    if p["declined"]:
      if path_unit(st, p["foul"], side, play) not in IN_SCOPE:
        continue
      alt = penalty_branches(st, p["foul"], side, play)
    else:
      alt = [play_branch(st, play)]
    if not alt:
      continue
    same = r.n_posteam == r.posteam
    to, opp_to = ((r.n_posteam_timeouts_remaining, r.n_defteam_timeouts_remaining) if same
                  else (r.n_defteam_timeouts_remaining, r.n_posteam_timeouts_remaining))
    home = int(r.posteam == r.home_team)
    line = float(r.spread_line if home else -r.spread_line) if pd.notna(r.spread_line) else 0.0
    base = {"diff": float(r.score_differential or 0), "sec": float(r.n_game_seconds_remaining),
            "to": float(to), "oppTo": float(opp_to), "line": line, "home": home,
            "rec2h": int(ko.get(r.game_id) != r.posteam)}

    def state(b):
      s = {**base, "down": b["down"], "togo": b["togo"], "yl": b["yl"], "own": b["ball"] == "same"}
      if not s["own"]:
        s.update(diff=-base["diff"], to=base["oppTo"], oppTo=base["to"], line=-line, home=1 - home, rec2h=1 - base["rec2h"])
      return s
    took = state({"down": int(r.n_down), "togo": float(r.n_ydstogo), "yl": float(r.n_yardline_100), "ball": "same" if same else "other"})
    decider = r.defteam if side == "offense" else r.posteam
    out.append({"game_id": r.game_id, "play_id": float(r.play_id), "season": int(r.season), "week": int(r.week),
                "qtr": int(r.qtr), "sec": float(r.game_seconds_remaining), "team": decider,
                "opp": r.posteam if side == "offense" else r.defteam, "chooser": "defense" if side == "offense" else "offense",
                "foul": p["foul"], "fouler": side, "kind": p["kind"], "choice": "decline" if p["declined"] else "accept",
                "down": st["down"], "togo": st["togo"], "yl": st["yl"], "diff": base["diff"],
                "took": took, "alt": [state(b) for b in alt], "desc": r.desc[:200]})
  return pd.DataFrame(out)
