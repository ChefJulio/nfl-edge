"""(EE) ESPN's game-day notes in the chance to play (pre-registered 2026-11-01, docs/INSIGHTS.md).

Usage: python tools/notes_eval.py      (reads the archive branch's git history: run `git fetch origin archive` first)

Notes come from the intraday ESPN snapshots each build writes to the archive branch (data/espn_injuries/<date>.csv,
one version per build); the model's chance from the per-build live inputs (data/live_inputs/<season>_<week>_<time>.json).
"""
import io
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

REF = "origin/archive"
SEASON = 2026
# The note parser (nfledge/espn_notes.py, negation-aware) replaced the pre-registered regexes on 2026-11-01 after the
# interim run (owner: "isn't expected to play" vs "is expected to play"); see the (EE) entry in docs/INSIGHTS.md.
from nfledge.espn_notes import classify  # noqa: E402


def git(*a, text=True):
  return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=text, encoding="utf-8" if text else None,
                        errors="replace" if text else None).stdout


def notes() -> pd.DataFrame:
  rows = []
  for f in [x for x in git("ls-tree", "--name-only", REF, "data/espn_injuries/").split() if x.endswith(".csv")]:
    for sha in git("log", "--format=%H", REF, "--", f).split():
      try:
        d = pd.read_csv(io.StringIO(git("show", f"{sha}:{f}")))
      except Exception:
        continue
      if "comment" in d:
        rows.append(d[["espn_id", "name", "team", "status", "updated", "comment"]])
  n = pd.concat(rows, ignore_index=True).dropna(subset=["espn_id", "updated"])
  n["espn_id"] = n.espn_id.astype(str).str.replace(r"\.0$", "", regex=True)
  n = n.drop_duplicates(["espn_id", "updated"])
  n["t"] = pd.to_datetime(n.updated, utc=True, errors="coerce")
  return n.dropna(subset=["t"])


def snapshots() -> list:
  """[(built time, week, {gsis: avail})] from the live-inputs files on the archive branch."""
  out = []
  for f in git("ls-tree", "--name-only", REF, "data/live_inputs/").split():
    m = re.search(rf"/{SEASON}_(\d\d)_(\d{{8}}T\d{{4}})\.json$", f)
    if not m:
      continue
    d = json.loads(git("show", f"{REF}:{f}") or "{}")
    cols = d.get("stats") or []
    if "avail" not in cols:
      continue
    i = cols.index("avail")
    out.append((datetime.fromisoformat(d["built"]), int(m.group(1)), {g: v[i] for g, v in (d.get("p") or {}).items() if v[i] is not None}))
  return sorted(out, key=lambda x: x[0])


def main():
  import nflreadpy as nfl
  from nfledge.data import RELOCATED
  sched = nfl.load_schedules([SEASON]).to_pandas()
  sched = sched[(sched.game_type == "REG")]
  ros = nfl.load_rosters_weekly([SEASON]).to_pandas()
  players = nfl.load_players().to_pandas()
  e2g = {str(e).replace(".0", ""): g for e, g in zip(players.espn_id, players.gsis_id) if pd.notna(e) and isinstance(g, str)}
  team_of = dict(zip(players.gsis_id, players.latest_team))
  n = notes()
  snaps = snapshots()
  print(f"(EE) {len(n)} distinct ESPN notes; {len(snaps)} live-input snapshots")

  # each finished game's kickoff (UTC) by team and week
  kick, done = {}, set()
  for g in sched.itertuples():
    if pd.isna(g.gameday) or pd.isna(g.gametime):
      continue
    k = pd.Timestamp(f"{g.gameday} {g.gametime}", tz="America/New_York").tz_convert("UTC")
    for t in (g.home_team, g.away_team):
      kick[(RELOCATED.get(t, t), int(g.week))] = k
      if pd.notna(g.home_score):
        done.add((RELOCATED.get(t, t), int(g.week)))
  st = ros.assign(team=ros.team.map(lambda t: RELOCATED.get(t, t))).set_index(["gsis_id", "week"])
  cases = []
  n["gsis"] = n.espn_id.map(e2g)
  n = n.dropna(subset=["gsis"])
  for (g, ), x in n.groupby(["gsis"]):
    for wk in sorted({w for (t, w) in kick if True}):
      if (g, wk) not in st.index:
        continue
      r = st.loc[(g, wk)]
      r = r.iloc[0] if isinstance(r, pd.DataFrame) else r
      tm = r.team
      if (tm, wk) not in done:
        continue
      ko = kick[(tm, wk)]
      ina = ko - timedelta(minutes=90)
      w = x[(x.t >= ko - timedelta(hours=48)) & (x.t < ina)]
      if not len(w):
        continue
      last = w.sort_values("t").iloc[-1]
      if last.status not in ("Questionable", "Doubtful"):
        continue
      # the model's chance: the last snapshot of this week built before inactives
      prior = [s for s in snaps if s[1] == wk and s[0] < ina.to_pydatetime() and g in s[2]]
      if not prior:
        continue
      active = 0 if str(r.status) in ("INA", "RES") or str(getattr(r, "status_description_abbr", "")).startswith("R") else 1
      cases.append({"gsis": g, "name": last["name"], "week": wk, "status": last.status, "cls": classify(str(last.comment)),
                    "note": str(last.comment)[:110], "model": float(prior[-1][2][g]), "y": active})
  c = pd.DataFrame(cases)
  print(f"  cases (Q / D with a note in the 48 hours before kickoff, finished games): {len(c)}; by week {c.week.value_counts().sort_index().to_dict()}")
  print("  by class: n, active rate, model's mean chance")
  for k, x in c.groupby("cls"):
    print(f"    {k:5s} {len(x):4d}  active {x.y.mean():.2f}  model {x.model.mean():.2f}")
  # note-adjusted chance: the class's active rate in the other weeks (+1 / +1)
  c["adj"] = c.model
  for i, r in c[c.cls != "NONE"].iterrows():
    o = c[(c.week != r.week) & (c.cls == r.cls)]
    c.at[i, "adj"] = (o.y.sum() + 1) / (len(o) + 2)
  t = c[c.cls != "NONE"]
  d = ((t.adj - t.y) ** 2 - (t.model - t.y) ** 2).to_numpy()
  rng = np.random.default_rng(0)
  bt = d[rng.integers(0, len(d), (2000, len(d)))].mean(1)
  lo, hi = np.percentile(bt, [2.5, 97.5])
  per = t.groupby("week").apply(lambda x: (((x.adj - x.y) ** 2).mean(), ((x.model - x.y) ** 2).mean(), len(x)))
  print(f"  OUT / GTD / IN cases: {len(t)}; Brier model {((t.model - t.y) ** 2).mean():.4f} -> with notes {((t.adj - t.y) ** 2).mean():.4f}, "
        f"difference {d.mean():+.4f} [{lo:+.4f}, {hi:+.4f}]")
  for wk, (a, m, k) in per.items():
    print(f"    week {wk}: {k} cases, model {m:.4f} -> notes {a:.4f}")
  every = all(a < m for (a, m, k) in per.values if k >= 5)
  print(f"  GATE: {'PASS' if d.mean() < 0 and hi < 0 and every else 'FAIL'}")
  print("  the cases (class, model chance, active):")
  for r in t.sort_values(["cls", "week"]).itertuples():
    print(f"    {r.cls:4s} wk {r.week} {r.name[:20]:20s} model {r.model:.2f} {'ACTIVE' if r.y else 'out'}  | {r.note}")


if __name__ == "__main__":
  main()
