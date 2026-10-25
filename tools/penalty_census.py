"""(PA) step 1 of grading accept/decline calls (owner 2026-10-25): a census of every penalty play of the regular
seasons 2022-25, by whether the team that didn't foul had a real choice. Descriptive (no gate): it sizes the population
the rules table (step 2) has to cover. Reads the calculator's play-by-play cache (tools/calc_build.py, pbp_calc_<s>).

  python tools/penalty_census.py [--from=2022] [--to=2025] [--examples=N]

Classes (by the play text; nflfastR's `penalty` flag misses most declined fouls, so the text is the source):
  multi      more than one foul on the play (offsetting included): out of scope at first
  presnap    no action before the foul (false start, delay of game ...): declining replays the down, so no choice
  kick       a kicking play (kickoff, punt, field goal, extra point, two-point try): phase 2
  scrimmage  a foul during a run or pass: the choice the first phase grades, split by
               declined / accepted-no-play (the penalty replaces the play) / accepted-added (the play stands, yards
               added) / between-downs (enforced after the play ended: effectively no choice)
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

FOUL = re.compile(r"(?i)penalty on ([A-Z]{2,3})(?:-[^,]*)?, ([^,.]+?)(?:,|\.|$)")
LEAD = re.compile(r"^(?:\([^)]*\)\s*)*")  # "(7:16) (Shotgun) (No Huddle) " prefixes
ACTION = re.compile(r"\d+-[A-Z][A-Za-z'.-]+")  # a player token ("8-L.Jackson"): the play happened before the foul
KICK = re.compile(r"(?i)\bpunts\b|\bkicks\b|field goal|extra point|two-point|onside")
EVENT = re.compile(r"INTERCEPTED|FUMBLES|TOUCHDOWN|SAFETY")


def classify(desc: str, play_type: str) -> dict:
  n = len(re.findall(r"(?i)penalty on", desc))
  m = FOUL.search(desc)
  team, foul = (m.group(1), m.group(2).strip()) if m else (None, None)
  pre = LEAD.sub("", desc[:re.search(r"(?i)penalty on", desc).start()])
  if n > 1:
    cls = "multi"
  elif not ACTION.search(pre):
    cls = "presnap"
  elif play_type in ("punt", "field_goal", "kickoff", "extra_point") or KICK.search(pre):
    cls = "kick"
  else:
    cls = "scrimmage"
  low = desc.lower()
  if "declined" in low:
    how = "declined"
  elif "between downs" in low:
    how = "between-downs"
  elif "no play" in low:
    how = "accepted-no-play"
  else:
    how = "accepted-added"
  return {"cls": cls, "how": how, "team": team, "foul": foul, "event": bool(EVENT.search(pre))}


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  lo, hi, ex = int(opt.get("from", 2022)), int(opt.get("to", 2025)), int(opt.get("examples", 0))
  d = pd.concat([pd.read_parquet(ROOT / "cache" / f"pbp_calc_{s}.parquet") for s in range(lo, hi + 1)], ignore_index=True)
  d = d[(d.season_type == "REG") & d.desc.str.contains(r"(?i)penalty on", na=False)].copy()
  c = pd.DataFrame([classify(s, t) for s, t in zip(d.desc, d.play_type.fillna(""))], index=d.index)
  d = d.join(c)
  d["side"] = (d.team == d.posteam).map({True: "offense", False: "defense"})
  d["late"] = (d.half_seconds_remaining <= 120) | ((d.qtr == 4) & (d.game_seconds_remaining <= 300))
  seasons = hi - lo + 1
  print(f"[pen] {len(d):,} plays with a foul, regular seasons {lo}-{hi} ({len(d) / seasons:,.0f} a season)\n")
  print("by class (per season):")
  print((d.cls.value_counts() / seasons).round(0).astype(int).to_string(), "\n")
  s = d[d.cls == "scrimmage"]
  print("scrimmage fouls, by how enforced and who fouled (per season):")
  print((pd.crosstab(s.how, s.side, margins=True) / seasons).round(0).astype(int).to_string(), "\n")
  print(f"  with a turnover / score on the play: {s.event.sum() / seasons:.0f} a season; late (last 2:00 of a half or last"
        f" 5:00 of the game): {s.late.sum() / seasons:.0f} a season\n")
  print("scrimmage fouls by type, declined vs accepted (all seasons; 25 most common):")
  t = pd.crosstab(s.foul, s.how == "declined").rename(columns={False: "accepted", True: "declined"})
  t["total"] = t.sum(axis=1)
  print(t.sort_values("total", ascending=False).head(25).to_string(), "\n")
  k = d[d.cls == "kick"]
  print("kicking-play fouls by play type and how enforced (per season):")
  print((pd.crosstab(k.play_type.fillna("?"), k.how) / seasons).round(1).to_string())
  if ex:
    for (cls, how), g in d.groupby(["cls", "how"]):
      print(f"\n-- {cls} / {how}")
      for t_ in g.desc.sample(min(ex, len(g)), random_state=0):
        print("  ", t_[:200])


if __name__ == "__main__":
  main()
