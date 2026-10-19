"""(AY5) the backup-QB rule names the backup by who dressed, not depth rank (pre-registered 2026-10-19,
docs/INSIGHTS.md).

Usage: python tools/qb2_dressed_eval.py
2019-25 team-weeks (final, inactives published, week 2 on). Starter = last game's QB with the most snaps (30%+).
When he takes no snap this week: did the named QB2 take one? A = depth rank 2 (not the starter), B = the healthy QB
who dressed as the backup last game, best depth rank first. GATE: B's play rate higher, paired 95% CI over team-weeks
excluding 0; when the starter plays, B's relief rate within 5 points of 0.232.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import run as RUN  # noqa: E402
from nfledge.config import load_config, load_scoring  # noqa: E402
from nfledge.data import load_all  # noqa: E402


def main():
  cfg, sc = load_config(), load_scoring()
  data = load_all(cfg)
  eng, _ = RUN.cached_model(data, cfg, sc, data.current_season, RUN.display_week(data))
  im = eng.injury_model
  played, _ = im._played_sets()
  sat_rows, play_rows = [], []
  for s in range(2019, 2026):
    t = im.scratch_table(s)
    q = t[t.is_QB == 1]
    done = set(t[t.final & (t.week <= data.completed_weeks(s)) & t.observable].week)
    for team, g in q.groupby("team"):
      wks = sorted(g.week.unique())
      for i in range(1, len(wks)):
        w = wks[i]
        if w not in done or w < 2:
          continue
        prev, cur = g[g.week == wks[i - 1]], g[g.week == w]
        top = prev.sort_values("snap", ascending=False)
        if not len(top) or not top.snap.fillna(0).iloc[0] > 0.3:
          continue
        st = top.gsis_id.iloc[0]
        a = cur[(cur["rank"] == 2) & (cur.gsis_id != st)]
        healthy = set(cur[~cur.is_out & ~cur.on_report].gsis_id)
        dressed = set(prev[prev.status == "ACT"].gsis_id) - {st}
        b = cur[cur.gsis_id.isin(dressed & healthy)].sort_values("rank")
        if not len(a) or not len(b):
          continue
        pa, pb = (s, w, a.gsis_id.iloc[0]) in played, (s, w, b.gsis_id.iloc[0]) in played
        row = {"season": s, "week": w, "team": team, "A": float(pa), "B": float(pb), "same": a.gsis_id.iloc[0] == b.gsis_id.iloc[0]}
        (play_rows if (s, w, st) in played else sat_rows).append(row)
  S, P = pd.DataFrame(sat_rows), pd.DataFrame(play_rows)
  d = S.B - S.A
  idx = np.random.default_rng(0).integers(0, len(d), (4000, len(d)))
  bt = d.to_numpy()[idx].mean(1)
  lo, hi = np.percentile(bt, [2.5, 97.5])
  print(f"[AY5] starter sat: {len(S)} team-weeks ({(~S.same).sum()} where the two name different QBs)")
  print(f"[AY5]   named QB2 played: depth rank 2 {S.A.mean():.1%}, dressed backup {S.B.mean():.1%}; diff {d.mean():+.3f} [{lo:+.3f}, {hi:+.3f}]")
  dd = S[~S.same]
  print(f"[AY5]   where they differ: depth rank 2 played {dd.A.mean():.1%}, dressed backup {dd.B.mean():.1%}")
  print(f"[AY5] starter played: {len(P)} team-weeks; relief rate depth rank 2 {P.A.mean():.1%}, dressed backup {P.B.mean():.1%}")
  ok = lo > 0 and abs(P.B.mean() - 0.232) <= 0.05
  print("[AY5] GATE:", "PASS" if ok else "FAIL")


if __name__ == "__main__":
  main()
