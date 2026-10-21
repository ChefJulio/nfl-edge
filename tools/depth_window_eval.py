"""Which playing-time window best predicts next game's starters? (pre-registered in docs/INSIGHTS.md, 2026-10-14)

Usage: python tools/depth_window_eval.py
Variants of depth_build's "share of snaps over the team's last 3 games, a missed game counts 0":
  base       the live rule
  skip_inj   a game he missed (0 snaps) while on that week's injury report or a reserve list leaves his average
             (returning starters aren't buried by the games they sat out hurt)
  recency    weights .5 / .3 / .2, newest game first
  both       skip_inj + recency
  last1      the last game only
  healthy3   (owner design) each player's last 3 HEALTHY games that season, newest first .5 / .3 / .2: skips games
             missed hurt and games LEFT hurt (under half his max share of his previous 3 played games, and on the
             report / a reserve list the next team week), reaching back as far as needed
Score per team-game and group: share of the predicted top-N (fixed N per group, depth_build.DEFAULT_N) that were
among the game's top-N snap-getters in the group. Players ruled Out / on a reserve list for the target week are
excluded for every variant (as the site does). 2019-2026 regular season, weeks 4+.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from depth_build import DEFAULT_N, GROUP, GROUPS  # noqa: E402
from nfledge import data as D, ingame  # noqa: E402

SEASONS = range(2019, 2027)
VARIANTS = ["base", "skip_inj", "recency", "both", "last1", "healthy3", "h3_note50", "h3_note80"]
RW = np.array([0.5, 0.3, 0.2])


def main():
  import nflreadpy as nfl
  c = D.Cache(ROOT / "cache")
  players = c.get("players", "all", lambda: nfl.load_players(), stale=False)
  pfr = players.dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates("pfr_id").set_index("pfr_id").gsis_id
  rows = []
  for season in SEASONS:
    sn = c.get("snaps", season, lambda: nfl.load_snap_counts([season]), stale=False)
    inj = c.get("injuries", season, lambda: nfl.load_injuries([season]), stale=False)
    ros = c.get("rosters", season, lambda: nfl.load_rosters_weekly([season]), stale=False)
    if sn is None or inj is None or ros is None:
      print(f"{season}: missing data", flush=True)
      continue
    sn = sn[sn.game_type == "REG"].copy()
    sn["gsis_id"] = sn.pfr_player_id.map(pfr)
    sn["team"] = sn.team.replace(D.RELOCATED)
    sn["grp"] = sn.position.map(GROUP)
    sn["pct"] = sn[["offense_pct", "defense_pct"]].max(axis=1).fillna(0)
    sn = sn.dropna(subset=["gsis_id", "grp"]).drop_duplicates(["gsis_id", "week"])
    listed = set(zip(inj.gsis_id, inj.week))  # on that week's injury report, any status
    out = set(zip(inj[inj.report_status == "Out"].gsis_id, inj[inj.report_status == "Out"].week))
    res = ros[ros.status.isin(["RES", "INA"]) & ros.status_description_abbr.astype(str).str.match(r"^R")]
    reserve = set(zip(res.gsis_id, res.week))
    hurt = listed | reserve
    nt = ingame.load(c, nfl, season, ros)
    nt = ingame.hurt_rows(nt) if nt is not None else nt  # injuries, not returns
    noted = set(zip(nt.gsis_id, nt.week)) if nt is not None and len(nt) else set()
    for team, ts in sn.groupby("team"):
      weeks = sorted(ts.week.unique())
      pct = ts.pivot_table(index="gsis_id", columns="week", values="pct", aggfunc="max").fillna(0.0)
      grp_of = ts.drop_duplicates("gsis_id").set_index("gsis_id").grp
      # injury-affected games per player over the whole season: missed hurt, or left hurt (see healthy3)
      A = pct[weeks].to_numpy()
      gids = pct.index.to_numpy()
      bad = np.zeros_like(A, dtype=bool)
      bad50, bad80 = np.zeros_like(bad), np.zeros_like(bad)  # + injury-note games under 50% / 80% of his usual share
      for r_, g in enumerate(gids):
        played = []
        for j, w in enumerate(weeks):
          v = A[r_, j]
          if v == 0:
            bad[r_, j] = bad50[r_, j] = bad80[r_, j] = (g, w) in hurt
          else:
            ref = max(played[-3:]) if played else None
            nxt = weeks[j + 1] if j + 1 < len(weeks) else None
            heur = bool(ref and v < 0.5 * ref and nxt is not None and (g, nxt) in hurt)
            note = (g, w) in noted
            bad[r_, j] = heur
            bad50[r_, j] = heur or bool(note and ref and v < 0.5 * ref)
            bad80[r_, j] = heur or bool(note and ref and v < 0.8 * ref)
            if not heur:
              played.append(v)
      for i, wk in enumerate(weeks):
        if i < 3 or wk < 4:
          continue
        prior = weeks[i - 3:i][::-1]  # newest first
        game = ts[ts.week == wk]
        P = pct[prior].to_numpy()  # players x 3
        ids = pct.index.to_numpy()
        missed_hurt = np.array([[(g, w) in hurt and P[r, j] == 0 for j, w in enumerate(prior)] for r, g in enumerate(ids)])
        avail = np.array([(g, wk) not in out and (g, wk) not in reserve for g in ids])
        played_any = (P > 0).any(axis=1)
        def score(kind):
          if kind == "base":
            return P.mean(axis=1)
          if kind == "last1":
            return P[:, 0]
          w = np.tile(RW if kind in ("recency", "both") else np.ones(3), (len(ids), 1))
          if kind in ("skip_inj", "both"):
            w = np.where(missed_hurt, 0.0, w)
          tot = w.sum(axis=1)
          return np.where(tot > 0, (P * w).sum(axis=1) / np.where(tot > 0, tot, 1), 0.0)
        def healthy3(B):
          out_ = np.zeros(len(ids))
          for r_ in range(len(ids)):
            vals = [A[r_, j] for j in range(i - 1, -1, -1) if not B[r_, j]][:3]
            if vals:
              w = RW[:len(vals)]
              out_[r_] = float(np.dot(vals, w) / w.sum())
          return out_
        HB = {"healthy3": bad, "h3_note50": bad50, "h3_note80": bad80}
        sc = {v: pd.Series(healthy3(HB[v]) if v in HB else score(v), index=ids) for v in VARIANTS}
        for grp in GROUPS:
          n = DEFAULT_N[grp]
          truth_pool = game[game.grp == grp]
          if len(truth_pool) < n:
            continue
          truth = set(truth_pool.nlargest(n, "pct").gsis_id)
          mask = (grp_of.reindex(ids).to_numpy() == grp) & avail & played_any
          if mask.sum() < n:
            continue
          ret = any(missed_hurt[r].any() for r in np.where(mask)[0] if ids[r] in truth)  # a starter returning from a hurt absence
          row = {"season": season, "week": wk, "team": team, "grp": grp, "n": n, "ret": ret}
          for v in VARIANTS:
            pick = sc[v][mask].nlargest(n).index
            row[v] = sum(g in truth for g in pick) / n
          rows.append(row)
    print(f"{season}: done", flush=True)
  r = pd.DataFrame(rows)
  wavg = lambda d, v: float((d[v] * d.n).sum() / d.n.sum())  # noqa: E731
  print(f"\n{len(r):,} team-game-group cells, {r.season.min()}-{r.season.max()}")
  print("per starter:", "  ".join(f"{v} {wavg(r, v):.4f}" for v in VARIANTS))
  rng = np.random.default_rng(5)
  tg = r.assign(key=r.season.astype(str) + r.team + r.week.astype(str))
  keys = tg.key.unique()
  by = {k: g for k, g in tg.groupby("key")}
  for v, ref in [(x, "base") for x in VARIANTS[1:]] + [("healthy3", "both"), ("h3_note50", "healthy3"), ("h3_note80", "healthy3")]:
    d0 = wavg(r, v) - wavg(r, ref)
    boots = []
    for _ in range(400):
      smp = pd.concat([by[k] for k in rng.choice(keys, len(keys))])
      boots.append(wavg(smp, v) - wavg(smp, ref))
    lo, hi = np.percentile(boots, [2.5, 97.5])
    print(f"  {v:9s} - {ref:4s} {d0:+.4f} [{lo:+.4f}, {hi:+.4f}]")
  sub = r[r.ret]
  print(f"\ncells with a starter returning from a hurt absence ({len(sub):,}):", "  ".join(f"{v} {wavg(sub, v):.3f}" for v in VARIANTS))
  print(r.groupby("grp")[VARIANTS].mean().round(3).to_string())


if __name__ == "__main__":
  main()
