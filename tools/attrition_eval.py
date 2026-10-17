"""(Y) injury attrition: P(a healthy regular misses week w+j injured), by position and horizon (docs/INSIGHTS.md,
pre-registered 2026-10-17). Reads the career logs tools/player_logs.py writes (<site>/data/players/*.json).

  python tools/attrition_eval.py [--site=scratch/site]
"""
from __future__ import annotations

import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

POS = ["QB", "RB", "WR", "TE"]
# seasons each fit uses: (Y) every earlier one (99); (Y2) the last 3, since absences have risen over the decade
RECENT = next((int(a.split("=", 1)[1]) for a in sys.argv if a.startswith("--recent=")), 99)
J = range(1, 13)
CENSOR = {"Cut", "PS", "FA", "Ret"}


def rows(site: Path):
  """(pos, season, j, out) for every healthy-regular week and horizon."""
  out = []
  for f in glob.glob(str(site / "data" / "players" / "*.json")):
    d = json.loads(Path(f).read_text(encoding="utf-8"))
    if d.get("kind") or d.get("pos") not in POS:
      continue
    eps = defaultdict(set)
    for e in d.get("inj") or []:
      eps[e["s"]].update(range(e["w0"], e["w1"] + 1))
    for S in d["seasons"]:
      s = S["s"]
      if s < 2013:
        continue
      played = {g["w"]: g.get("sn") for g in S["g"]}
      miss = {m["w"]: m for m in S.get("m") or []}
      for w, sn in played.items():
        if sn is None or sn < 50 or w in eps[s]:
          continue
        for j in J:
          k = w + j
          if k in played:
            out.append((d["pos"], s, j, 0))
          elif k in miss:
            m = miss[k]
            if m.get("bye") or m.get("miss") in CENSOR:
              continue
            out.append((d["pos"], s, j, 1 if k in eps[s] else 0))
  return np.array([(POS.index(p), s, j, y) for p, s, j, y in out])


def main():
  site = Path(next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--site=")), "scratch/site"))
  R = rows(site)
  print(f"{len(R)} healthy-regular week x horizon rows, seasons {R[:, 1].min()}-{R[:, 1].max()}")
  # the curve on everything (for reading)
  print("P(out injured) by horizon j (all seasons):")
  for pi, pos in enumerate(POS):
    x = R[R[:, 0] == pi]
    print(f"  {pos}: " + " ".join(f"{x[x[:, 2] == j][:, 3].mean():.3f}" for j in J) + f"   (n {len(x)})")
  print("Walk-forward 2021-25 (fit on seasons before s): Brier of P = 0 / flat rate / curve; curve ECE")
  ok = True
  for s in range(2021, 2027):
    tr, te = R[(R[:, 1] < s) & (R[:, 1] >= s - RECENT)], R[R[:, 1] == s]
    flat = {pi: tr[tr[:, 0] == pi][:, 3].mean() for pi in range(4)}
    curve = {(pi, j): tr[(tr[:, 0] == pi) & (tr[:, 2] == j)][:, 3].mean() for pi in range(4) for j in J}
    y = te[:, 3]
    pf = np.array([flat[p] for p in te[:, 0]])
    pc = np.array([curve[(p, j)] for p, j in zip(te[:, 0], te[:, 2])])
    b0, bf, bc = (y ** 2).mean(), ((pf - y) ** 2).mean(), ((pc - y) ** 2).mean()
    bins = np.minimum((pc * 10).astype(int), 9)
    ece = sum(abs(pc[bins == b].mean() - y[bins == b].mean()) * (bins == b).sum() for b in range(10) if (bins == b).any()) / len(y)
    print(f"  {s}: rows {len(y)}  P=0 {b0:.4f}  flat {bf:.4f}  curve {bc:.4f}  ECE {ece:.4f}  (rate {y.mean():.3f})")
    ok &= bool(bc < b0 and ece < 0.01)
  print(f"GATE: {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
  main()
