"""Every flagged play, archived and sorted before any parsing (owner 2026-10-17: "archive all penalty plays ... separate
the ones with negated play text before trying to parse"). Groundwork for (AB) penalties in team ratings
(docs/handset_audit.md).

Usage: python tools/penalty_archive.py [--seasons=2012-2026] [--show=N]
Writes <cache_dir>/penalty_plays/<season>.parquet (finished seasons cached) and prints a breakdown.

One row per regular-season play with a flag (nflverse records the main penalty of each play). kind:
  stood       the play counts (play_type is not no_play): the flag's yards are inside its EPA already (declined, offset,
              or enforced after the play, e.g. a facemask on a completed pass)
  called_back the play was run and wiped out (no_play whose text before "PENALTY" has action: a pass, run, sack, kick):
              its result exists only in the text; AB-b parses it
  pre_snap    no_play with no action: false start, delay of game, encroachment, a dead-ball foul
unit: off / st (special teams: punt, kick, field goal, extra point text or special_teams_play). Parsed for called_back
scrimmage plays (AB-b): wb_yards (the would-be gain), wb_inc / wb_int / wb_sack / wb_td / wb_fum, wb_ok (an outcome was
read: yards, or incomplete / intercepted).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402

V = 2
COLS = ["game_id", "play_id", "season", "week", "season_type", "posteam", "defteam", "qtr", "down", "ydstogo",
        "yardline_100", "play_type", "desc", "penalty", "penalty_team", "penalty_type", "penalty_yards", "epa",
        "yards_gained", "pass", "rush", "special_teams_play", "first_down_penalty"]
ACTION = re.compile(r"\bpass\b|\bsacked\b|\bscrambles\b|\bup the middle\b|\b(?:left|right) (?:end|tackle|guard)\b"
                    r"|\bkneels\b|\bspiked\b|\bpunts\b|\bkicks\b|\bextra point\b|\bfield goal\b|\bFUMBLES\b"
                    r"|\bINTERCEPTED\b|\bfor (?:-?\d+ yards?|no gain)\b|\bAborted\b", re.I)
ST = re.compile(r"\bpunts\b|\bkicks\b|\bextra point\b|\bfield goal\b|\bonside\b", re.I)
YDS = re.compile(r"\bfor (-?\d+) yards?\b", re.I)


def before_flag(desc: str) -> str:
  """The play's own text, before the first PENALTY clause, without parenthetical notes ("(Pass formation)", the clock,
  "(Shotgun)"), which would read as action."""
  d = str(desc or "")
  i = d.upper().find("PENALTY")
  return re.sub(r"\([^)]*\)", " ", d[:i] if i >= 0 else d)


def classify(p: pd.DataFrame) -> pd.DataFrame:
  f = p[(p.season_type == "REG") & (p.penalty == 1)].drop_duplicates(["game_id", "play_id"]).copy()
  for c in ("posteam", "defteam", "penalty_team"):
    f[c] = f[c].replace(D.RELOCATED)
  f["pre"] = f["desc"].map(before_flag)
  act = f.pre.str.contains(ACTION)
  f["kind"] = "stood"
  f.loc[(f.play_type == "no_play") & act, "kind"] = "called_back"
  f.loc[(f.play_type == "no_play") & ~act, "kind"] = "pre_snap"
  f["unit"] = (f.pre.str.contains(ST) | (f.special_teams_play == 1)).map({True: "st", False: "off"})
  f["on_off"] = f.penalty_team == f.posteam  # the flag is on the offense (possession team)
  # would-be result of a called-back scrimmage play (AB-b)
  cb = (f.kind == "called_back") & (f.unit == "off")
  pre = f.pre.where(cb, "")
  f["wb_inc"] = cb & pre.str.contains(r"\bincomplete\b", case=False)
  f["wb_int"] = cb & pre.str.contains(r"\bINTERCEPTED\b", case=False)
  f["wb_sack"] = cb & pre.str.contains(r"\bsacked\b", case=False)
  f["wb_td"] = cb & pre.str.contains(r"\bTOUCHDOWN\b")
  f["wb_fum"] = cb & pre.str.contains(r"\bFUMBLES\b")
  y = pre.str.extract(YDS, expand=False).astype(float)
  y = y.where(~pre.str.contains(r"\bfor no gain\b", case=False), 0.0)
  f["wb_yards"] = y.where(cb)
  f["wb_ok"] = cb & (f.wb_yards.notna() | f.wb_inc | f.wb_int)
  return f.drop(columns=["pre"])


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  import nflreadpy as nfl
  cfg = load_config()
  current = int(nfl.get_current_season())
  a, _, b = opt.get("seasons", f"2012-{current}").partition("-")
  kept = ROOT / cfg["data"]["cache_dir"] / "penalty_plays" / f"v{V}"
  kept.mkdir(parents=True, exist_ok=True)
  frames = []
  for s in range(int(a), int(b or a) + 1):
    k = kept / f"{s}.parquet"
    if s < current and k.exists():
      frames.append(pd.read_parquet(k))
      continue
    f = classify(nfl.load_pbp([s]).select(COLS).to_pandas())
    f.to_parquet(k, index=False)
    frames.append(f)
    print(f"[penalty-archive] {s}: {len(f)} flagged plays", flush=True)
  f = pd.concat(frames, ignore_index=True)
  print("\nflagged plays by kind and season (unit: off / st)")
  t = f.assign(c=f.kind + "/" + f.unit).pivot_table(index="season", columns="c", values="play_id", aggfunc="size", fill_value=0)
  print(t.to_string())
  cb = f[(f.kind == "called_back") & (f.unit == "off")]
  print(f"\ncalled-back scrimmage plays: {len(cb)}; would-be outcome read: {cb.wb_ok.mean():.1%}"
        f" (yards {cb.wb_yards.notna().mean():.1%}, incomplete {cb.wb_inc.mean():.1%}, int {cb.wb_int.mean():.1%},"
        f" sack {cb.wb_sack.mean():.1%}, TD {cb.wb_td.mean():.1%})")
  print("  flag on offense / defense:", cb.on_off.value_counts().to_dict())
  for k in ("called_back", "pre_snap", "stood"):
    t = f[f.kind == k].penalty_type.fillna("?").value_counts().head(10)
    print(f"\n{k}: top penalty types\n" + "\n".join(f"  {n:6d}  {ty}" for ty, n in t.items()))
  n = int(opt.get("show", 6))
  bad = cb[~cb.wb_ok]
  print(f"\nunparsed called-back plays ({len(bad)}), sample:")
  for d in bad.sample(min(n, len(bad)), random_state=1)["desc"]:
    print("  ", str(d)[:220])
  ps = f[(f.kind == "pre_snap")]
  odd = ps[~ps.penalty_type.fillna("").str.contains("False Start|Delay of Game|Encroachment|Neutral Zone|Offside|Too Many|Illegal Substitution|Illegal Shift|Illegal Formation|Unsportsmanlike|Personal Foul|Taunting|Unnecessary", case=False)]
  print(f"\npre_snap plays of a type that usually happens during a play ({len(odd)} of {len(ps)}), sample:")
  for d in odd.sample(min(n, len(odd)), random_state=1)["desc"]:
    print("  ", str(d)[:220])


if __name__ == "__main__":
  main()
