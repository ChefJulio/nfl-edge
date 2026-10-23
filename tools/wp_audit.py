"""(CP) a situational audit of the win model (docs/INSIGHTS.md): the engine's wp() with a model fit through 2018 on
2019-25 snaps, sliced by the states the calculator values. A slice is flagged only if it is off the same way in
2019-21 and 2022-25 (95% interval by games excluding zero in both) by 1.5+ points pooled.

  python tools/calc_build.py --through=2018 --out=scratch/calc_val/through_2018.json
  python tools/wp_audit.py export      -> scratch/calc_val/audit_rows.json
  node tools/wp_audit.mjs              -> scratch/calc_val/audit_scored.json
  python tools/wp_audit.py analyze
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

OUT = ROOT / "scratch" / "calc_val"
MIN_N = 300


def export():
  d = pd.concat([pd.read_parquet(ROOT / "cache" / f"pbp_calc_{s}.parquet") for s in range(2019, 2026)], ignore_index=True)
  d = d[(d.season_type == "REG") & (d.qtr <= 4)].sort_values(["game_id", "play_id"]).reset_index(drop=True)
  ko = d[(d.kickoff_attempt == 1) & (d.qtr == 1) & d.posteam.notna()].drop_duplicates("game_id").set_index("game_id").posteam
  # the play before each snap (any play with a team on offense), to label what led to it
  ev = d[d.posteam.notna() & (d.play_type.isin(["run", "pass", "punt", "field_goal", "kickoff", "qb_kneel", "qb_spike"]))].copy()
  prev = ev.groupby("game_id").shift(1)
  snap = ev.play_type.isin(["run", "pass", "qb_kneel", "qb_spike"]) & ev.down.notna()
  same = prev.posteam == ev.posteam
  lost = (prev.interception == 1) | (prev.fumble_lost == 1)
  tags = {
    "after a converted 4th down": (prev.down == 4) & prev.play_type.isin(["run", "pass"]) & (prev.fourth_down_converted == 1) & same & ~lost,
    "after a failed 4th down (theirs)": (prev.down == 4) & prev.play_type.isin(["run", "pass"]) & (prev.fourth_down_failed == 1) & ~same & ~lost,
    "after a punt": (prev.play_type == "punt") & ~same,
    "after a missed field goal": (prev.play_type == "field_goal") & (prev.field_goal_result != "made") & ~same,
    "after an interception / lost fumble": lost & ~same,
    "after a kickoff": prev.play_type == "kickoff",
  }
  x = ev[snap].copy()
  home = x.posteam == x.home_team
  rows = pd.DataFrame({
    "game_id": x.game_id, "season": x.season, "won": np.where(home, x.result > 0, x.result < 0).astype(int),
    "tie": (x.result == 0).astype(int), "diff": x.score_differential.fillna(0), "sec": x.game_seconds_remaining,
    "down": x.down, "togo": x.ydstogo, "yl": x.yardline_100, "to": x.posteam_timeouts_remaining.fillna(3),
    "oppTo": x.defteam_timeouts_remaining.fillna(3), "line": np.where(home, x.spread_line, -x.spread_line),
    "total": x.total_line.fillna(45), "home": home.astype(int), "rec2h": (x.game_id.map(ko) != x.posteam).astype(int)})
  rows["tags"] = [[] for _ in range(len(rows))]
  for k, m in tags.items():
    for i in m[snap][m[snap].fillna(False).astype(bool)].index:
      rows.at[i, "tags"].append(k)
  rows = rows[rows.tie == 0].drop(columns="tie").replace({np.nan: None})
  (OUT / "audit_rows.json").write_text(json.dumps(rows.to_dict("records")), encoding="utf-8")
  print(f"[cp] {len(rows):,} snaps 2019-25; tagged: " + ", ".join(f"{k} {sum(k in t for t in rows.tags)}" for k in tags))


def slices(t: pd.DataFrame) -> dict:
  s = {"all snaps": t.index}
  for k in ["after a converted 4th down", "after a failed 4th down (theirs)", "after a punt", "after a missed field goal",
            "after an interception / lost fumble", "after a kickoff"]:
    s[k] = t.index[t.tags.map(lambda v: k in v)]
  late = (t.sec <= 300) & (t["diff"].abs() <= 8)
  for side, m in (("leading", t["diff"] > 0), ("not leading", t["diff"] <= 0)):
    for n in range(4):
      s[f"last 5:00, within 8, {side} with the ball, defense {n} timeouts"] = t.index[late & m & (t.oppTo == n)]
      s[f"last 5:00, within 8, {side} with the ball, offense {n} timeouts"] = t.index[late & m & (t.to == n)]
  s["4th quarter 2:01-2:40"] = t.index[t.sec.between(121, 160)]
  s["4th quarter 1:20-2:00"] = t.index[t.sec.between(80, 120)]
  return s


def analyze():
  t = pd.DataFrame(json.loads((OUT / "audit_scored.json").read_text(encoding="utf-8")))
  t["err"] = t.won - t.wp
  rng = np.random.default_rng(0)

  def ci(x):
    gm = x.game_id.to_numpy(); e = x.err.to_numpy(); ug, inv = np.unique(gm, return_inverse=True)
    sums, cnts = np.bincount(inv, e), np.bincount(inv)
    b = []
    for _ in range(1000):
      w = np.bincount(rng.integers(0, len(ug), len(ug)), minlength=len(ug))
      b.append((w * sums).sum() / (w * cnts).sum())
    return e.mean(), *np.percentile(b, [2.5, 97.5])

  flagged = []
  print(f"[cp] {len(t):,} snaps; won minus forecast, points (95% by games)")
  print(f"  {'slice':72s} {'2019-21':>28s} {'2022-25':>28s}  pooled")
  for name, ix in slices(t).items():
    x = t.loc[ix]
    a, b = x[x.season <= 2021], x[x.season >= 2022]
    if len(a) == 0 or len(b) == 0:
      continue
    ra, rb = ci(a), ci(b)
    pooled = x.err.mean()
    can = len(a) >= MIN_N and len(b) >= MIN_N
    flag = (can and np.sign(ra[0]) == np.sign(rb[0]) and (ra[1] > 0 or ra[2] < 0) and (rb[1] > 0 or rb[2] < 0)
            and abs(pooled) >= 0.015)
    if flag:
      flagged.append(name)
    f = lambda r, n: f"{100 * r[0]:+5.1f} [{100 * r[1]:+5.1f},{100 * r[2]:+5.1f}] n{n:<6d}"  # noqa: E731
    print(f"  {'FLAG ' if flag else ('     ' if can else 'thin ')}{name:67s} {f(ra, len(a))} {f(rb, len(b))}  {100 * pooled:+5.1f}")
  print(f"\n[cp] flagged: {flagged if flagged else 'none'}")


if __name__ == "__main__":
  {"export": export, "analyze": analyze}[sys.argv[1] if len(sys.argv) > 1 else "analyze"]()
