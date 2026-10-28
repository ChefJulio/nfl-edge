"""Audit: our Pro Bowl and first-team All-Pro seasons (data/history/honors.json) against each player's Wikipedia infobox
"highlights" (an independent listing). Players with 3+ Pro Bowls or a first-team All-Pro in our data, seasons 1999-2025.

  python tools/honors_audit.py   -> scratch/honors_audit.csv and a summary
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import pandas as pd  # noqa: E402

from honors_build import wiki  # noqa: E402

LO, HI = 1999, 2025


def years(line: str) -> set:
  """'([[2015 Pro Bowl|2014]]–[[2022 Pro Bowl|2021]], [[2024 Pro Bowl Games|2023]])' -> seasons, ranges expanded (the
  link's shown text is the season)."""
  t = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", line)
  t = re.sub(r"\[\[([^\]]*)\]\]", r"\1", t)
  t = re.sub(r"\{\{(?:nowrap|nobr|small)\|([^{}]*)\}\}", r"\1", t, flags=re.I)  # keep what these wrap (years)
  t = re.sub(r"<ref.*?(</ref>|/>)|\{\{[^}]*\}\}", "", t)
  inner = t[t.find("(") + 1:] if "(" in t else ""
  out = set()
  for a, b in re.findall(r"(\d{4})\s*[–—-]\s*(\d{4})", inner):
    out |= set(range(int(a), int(b) + 1))
  inner = re.sub(r"(\d{4})\s*[–—-]\s*(\d{4})", "", inner)
  out |= {int(y) for y in re.findall(r"\b(19\d\d|20\d\d)\b", inner)}
  return out


def infobox(name: str):
  for title in (name, f"{name} (American football)"):
    t = wiki(title)
    if t and "highlights" in t and ("NFL" in t or "National Football League" in t):
      i = t.find("highlights")
      return t[i:i + 4000].split("\n| ")[0]
  return None


def main():
  import nflreadpy as nfl
  pl = nfl.load_players().to_pandas().set_index("gsis_id").display_name
  hist = json.loads((ROOT / "data" / "history" / "honors.json").read_text(encoding="utf-8"))["seasons"]
  ours = {}
  for s, rows in hist.items():
    for code, g, *_ in rows:
      if code in ("PB", "AP1"):
        ours.setdefault(g, {"PB": set(), "AP1": set()})[code].add(int(s))
  todo = [g for g, v in ours.items() if len(v["PB"]) >= 3 or v["AP1"]]
  rows = []
  for g in todo:
    name = pl.get(g)
    ib = infobox(name) if isinstance(name, str) else None
    if not ib:
      rows.append((g, name, None, None, None, None))
      continue
    pb, ap = set(), set()
    for ln in ib.split("\n"):
      if re.search(r"Pro Bowl", ln) and not re.search(r"MVP|Games MVP", ln):
        pb |= years(ln)
      if re.search(r"First-team\s*(\[\[)?All-Pro", ln, re.I) or re.search(r"^\*\s*(\d+\S\s*)?\[\[All-Pro\]\]", ln):
        ap |= years(ln)
    pb, ap = {y for y in pb if LO <= y <= HI}, {y for y in ap if LO <= y <= HI}
    rows.append((g, name, sorted(ours[g]["PB"]), sorted(pb), sorted(ours[g]["AP1"]), sorted(ap)))
  d = pd.DataFrame(rows, columns=["gsis", "name", "pb_ours", "pb_wiki", "ap_ours", "ap_wiki"])
  d.to_csv(ROOT / "scratch" / "honors_audit.csv", index=False)
  ok = d.dropna(subset=["pb_wiki"])
  miss_pb = sum(len(set(w) - set(o)) for o, w in zip(ok.pb_ours, ok.pb_wiki))
  extra_pb = sum(len(set(o) - set(w)) for o, w in zip(ok.pb_ours, ok.pb_wiki))
  miss_ap = sum(len(set(w) - set(o)) for o, w in zip(ok.ap_ours, ok.ap_wiki))
  extra_ap = sum(len(set(o) - set(w)) for o, w in zip(ok.ap_ours, ok.ap_wiki))
  tot_pb, tot_ap = sum(len(w) for w in ok.pb_wiki), sum(len(w) for w in ok.ap_wiki)
  print(f"{len(d)} players audited, {len(ok)} with an infobox found")
  print(f"Pro Bowl seasons: Wikipedia {tot_pb}; ours missing {miss_pb}, ours extra {extra_pb}")
  print(f"First-team All-Pro seasons: Wikipedia {tot_ap}; ours missing {miss_ap}, ours extra {extra_ap}")
  from collections import Counter
  print("missing Pro Bowls by season:", sorted(Counter(y for o, w in zip(ok.pb_ours, ok.pb_wiki) for y in set(w) - set(o)).items()))
  print("extra Pro Bowls by season:", sorted(Counter(y for o, w in zip(ok.pb_ours, ok.pb_wiki) for y in set(o) - set(w)).items()))
  print("missing All-Pros by season:", sorted(Counter(y for o, w in zip(ok.ap_ours, ok.ap_wiki) for y in set(w) - set(o)).items()))
  print("extra All-Pros by season:", sorted(Counter(y for o, w in zip(ok.ap_ours, ok.ap_wiki) for y in set(o) - set(w)).items()))


if __name__ == "__main__":
  main()
