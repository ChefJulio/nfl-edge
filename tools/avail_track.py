"""Model tab > "How accurate is our inactive %?": the availability models' walk-forward track record (owner 2026-10-16:
"general 'our relative accuracy' seems right").

Usage: python tools/avail_track.py [--first=2021] [--last=2025]
Writes data/history/availability_track.json (committed; the build copies it into data/model.json). Rerun and commit
after any change to the availability models (nfledge/tuesday.py, injuries.week_model / tuesday).

Scored like the tests (INSIGHTS (G) / (I2)): each season's predictions come from models trained on seasons before it,
QB / RB / WR / TE, final-report status Out left out (0% by rule). Contents:
  versus: final-report Brier for the public readings of the report (Questionable = 50/50; the official status's real
          play rates; status + Friday practice) and ours
  stages: Tuesday / Wednesday / Thursday / final report: our Brier and how often our lean was wrong
  calib:  predicted-chance bands vs how often those players played
  spots:  common situations: players, how often they played, what we predicted on average
  now:    this season so far (models trained through `last`): the same calibration bands
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge import tuesday as T  # noqa: E402
from nfledge.config import load_config  # noqa: E402

BANDS = [0, .1, .3, .5, .7, .9, 1.0001]


def calib(r: pd.DataFrame) -> list:
  out = []
  for lo, hi in zip(BANDS[:-1], BANDS[1:]):
    g = r[(r.p >= lo) & (r.p < hi)]
    if len(g):
      out.append({"band": f"{round(lo * 100)}-{min(100, round(hi * 100))}%", "n": int(len(g)),
                  "predicted": round(100 * float(g.p.mean()), 1), "played": round(100 * float(g.y.mean()), 1)})
  return out


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  first, last = int(opt.get("first", 2021)), int(opt.get("last", 2025))
  cfg = load_config()
  d = D.load_all(cfg)
  rep, hurt = T.report_rows(d), T.hurt_notes(d, D.Cache(ROOT / cfg["data"]["cache_dir"]))
  w = T.week_rows(d, rep, hurt).dropna(subset=["y"])
  w = w[~((w.stage == 3) & (w.gs_now == "Out"))]
  tue = T.build_rows(d, rep, hurt).dropna(subset=["y"])
  out = []
  newest = int(w.season.max())
  for s in list(range(first, last + 1)) + ([newest] if newest > last else []):
    te = w[(w.season == s) & (w.stage > 0) & (w.on_now == 1)].copy()
    te["p"] = T.week_predict(T.week_model(w, s), te)
    t0 = tue[tue.season == s].copy()
    t0["p"] = T.fit(tue[tue.season < s]).predict_proba(T.features(t0))[:, 1]
    t0["stage"] = 0
    out += [te, t0]
    print(f"[avail track] {s}", flush=True)
  r = pd.concat(out, ignore_index=True)
  r = r[r.pos.isin(["QB", "RB", "WR", "TE"])]
  now, r = r[r.season > last], r[r.season <= last]
  b = lambda g, c="p": round(float(((g[c] - g.y) ** 2).mean()), 4)  # noqa: E731
  f = r[r.stage == 3].copy()
  # public readings of the final report, each fit on the seasons before (like ours)
  parts = []
  for s, g in f.groupby("season"):
    tr = w[(w.season < s) & (w.stage == 3) & (w.on_now == 1) & w.pos.isin(["QB", "RB", "WR", "TE"])]
    g = g.copy()
    g["p_naive"] = g.gs_now.map({"Questionable": 0.5, "Doubtful": 0.25}).fillna(0.95)
    g["p_status"] = g.gs_now.map(tr.groupby("gs_now").y.mean()).fillna(tr.y.mean())
    tab = tr.assign(last=tr.days_now.str[-1].fillna("")).groupby(["gs_now", "last"]).y.mean()
    g["p_table"] = [tab.get((a, l_), np.nan) for a, l_ in zip(g.gs_now, g.days_now.str[-1].fillna(""))]
    g["p_table"] = g.p_table.fillna(g.p_status)
    parts.append(g)
  f = pd.concat(parts)
  versus = [{"label": "\"Questionable = 50/50\" (the common rule of thumb)", "brier": b(f, "p_naive")},
            {"label": "The official game status (each tag's real play rate)", "brier": b(f, "p_status")},
            {"label": "Game status + Friday's practice", "brier": b(f, "p_table")},
            {"label": "Ours", "brier": b(f), "ours": True}]
  names = {0: "Tuesday (before any report)", 1: "Wednesday", 2: "Thursday", 3: "Final report"}
  stages = [{"label": names[s], "n": int(len(g)), "brier": b(g), "wrong": round(100 * float(((g.p >= 0.5) != (g.y == 1)).mean()), 1),
             "predicted": round(100 * float(g.p.mean()), 1), "played": round(100 * float(g.y.mean()), 1)}
            for s, g in r.groupby("stage")]
  m = r[r.stage == 1]
  t0 = r[r.stage == 0]
  spot_defs = [
    ("Final report", "No game status", f[f.gs_now == "None"]),
    ("Final report", "Questionable, full practice Friday", f[(f.gs_now == "Questionable") & (f.days_now.str[-1] == "F")]),
    ("Final report", "Questionable, limited Friday", f[(f.gs_now == "Questionable") & (f.days_now.str[-1] == "L")]),
    ("Final report", "Questionable, no practice Friday", f[(f.gs_now == "Questionable") & (f.days_now.str[-1] == "D")]),
    ("Final report", "Questionable, no practice all week", f[(f.gs_now == "Questionable") & (f.days_now == "DDD")]),
    ("Final report", "Questionable, missed his last game", f[(f.gs_now == "Questionable") & (f.played_last == 0)]),
    ("Final report", "Doubtful", f[f.gs_now == "Doubtful"]),
    ("Wednesday", "Full practice", m[m.days_now == "F"]),
    ("Wednesday", "Limited practice", m[m.days_now == "L"]),
    ("Wednesday", "No practice", m[m.days_now == "D"]),
    ("Wednesday", "No practice, missed his last game", m[(m.days_now == "D") & (m.played_last == 0)]),
    ("Tuesday", "Out last week", t0[t0.status == "Out"]),
    ("Tuesday", "Questionable last week, played", t0[(t0.status == "Questionable") & (t0.played_last == 1)]),
    ("Tuesday", "Hurt in his last game, not on that report", t0[t0["pop"] == "B"]),
  ]
  spots = [{"when": w_, "label": lab, "n": int(len(g)), "played": round(100 * float(g.y.mean()), 1),
            "predicted": round(100 * float(g.p.mean()), 1)} for w_, lab, g in spot_defs if len(g) >= 30]
  doc = {"seasons": f"{first}-{last}", "n": int(len(r)), "versus": versus, "stages": stages, "calib": calib(r), "spots": spots,
         "now": {"season": int(now.season.max()), "weeks": f"{int(now.week.min())}-{int(now.week.max())}", "n": int(len(now)),
                 "calib": calib(now), "brier": b(now)} if len(now) else None}
  path = ROOT / "data" / "history" / "availability_track.json"
  path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
  print(json.dumps(doc, indent=1)[:3000])


if __name__ == "__main__":
  main()
