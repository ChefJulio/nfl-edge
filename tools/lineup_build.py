"""(BO) Lineup value per team-game: who's missing (or back) beyond the QB (pre-registered 2026-10-20, docs/INSIGHTS.md (BO)).

Usage: python tools/lineup_build.py [first] [last]      (default 2021 to this season)
For each team-game and each non-QB player with this team in its previous 8 games (weights 0.5^(games ago / 3)):
  recent = weighted mean snap share (0 when he missed), role = weighted mean share in the games he played; kept if
  role >= 0.3. delta = (role if available else 0) - recent, under three availability definitions:
    report     on the team's roster that week (ACT or INA) and not Out / Doubtful on the final injury report
    inactives  report, and not on the game-day inactive list (roster status ACT)
    actual     played (any snaps) - hindsight, a ceiling
  q = cap-share percentile within his position group that season (contracts; none on file = 0.5).
Writes cache/lineup_rows.parquet: one row per team-game with per-group sums of delta (snap) and delta x q (cap) for
each definition, plus OFF / DEF totals.
"""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge.lineup import DEF, OFF, Lineups, Values, shares  # noqa: E402

OUT = ROOT / "cache" / "lineup_rows.parquet"
KINDS = ("snap", "cap", "rapm")  # rapm (BP): on-field value, tools/rapm_build.py
DEFS = ("report", "inactives", "actual")


def load(first: int, last: int):
  c = ROOT / "cache"
  players = pd.read_parquet(c / "players_all.parquet").dropna(subset=["pfr_id", "gsis_id"])
  pid = dict(zip(players.pfr_id, players.gsis_id))
  sn = pd.concat([pd.read_parquet(c / f"snaps_{y}.parquet") for y in range(first - 1, last + 1)], ignore_index=True)
  sn["gsis_id"] = sn.pfr_player_id.map(pid)
  sn = shares(sn)
  ro = pd.concat([pd.read_parquet(c / f"rosters_{y}.parquet") for y in range(first, last + 1)], ignore_index=True)
  ro = ro[ro.game_type == "REG"][["season", "week", "team", "gsis_id", "status"]].dropna(subset=["gsis_id"])
  inj = pd.concat([pd.read_parquet(c / f"injuries_{y}.parquet") for y in range(first, last + 1) if (c / f"injuries_{y}.parquet").exists()],
                  ignore_index=True)
  inj = inj[(inj.game_type == "REG") & inj.report_status.isin(["Out", "Doubtful"])][["season", "week", "team", "gsis_id"]]
  return sn, ro, inj


def contracts_q(seasons) -> dict:
  """(season, gsis_id) -> cap-share percentile within position group (the group from his most common snap position)."""
  k = pd.read_parquet(ROOT / "cache" / "contracts_all.parquet").dropna(subset=["gsis_id", "apy_cap_pct", "year_signed"])
  out = {}
  for s in seasons:
    a = k[(k.year_signed <= s) & (k.last_year.fillna(9999) >= s)].sort_values("year_signed").drop_duplicates("gsis_id", keep="last")
    out[s] = a.set_index("gsis_id").apy_cap_pct
  return out


def main():
  a = [int(x) for x in sys.argv[1:3]]
  first, last = a if len(a) == 2 else (2021, date.today().year)
  sn, ro, inj = load(first, last)
  cap = contracts_q(range(first, last + 1))
  main_grp = sn.groupby("gsis_id").grp.agg(lambda x: x.value_counts().index[0])
  val = Values()
  # cap percentile within group per season, among players who played that season
  q = {}
  for s in range(first, last + 1):
    ids = sn[sn.season == s].gsis_id.unique()
    t = pd.DataFrame({"gsis_id": ids, "grp": main_grp.reindex(ids).to_numpy(), "cap": cap[s].reindex(ids).to_numpy()})
    t["q"] = t.groupby("grp").cap.rank(pct=True)
    q.update({(s, g): (v if v == v else 0.5) for g, v in zip(t.gsis_id, t.q)})
  L = Lineups(sn)  # the same regulars / role / recent as the live win chance (nfledge/lineup.py)
  played = set(zip(sn.game_id, sn.gsis_id))
  status = ro.drop_duplicates(["season", "week", "team", "gsis_id"], keep="last").set_index(["season", "week", "team", "gsis_id"]).status
  outrep = set(map(tuple, inj[["season", "week", "team", "gsis_id"]].itertuples(index=False)))
  roster_status = {}
  for k, stt in status.items():
    roster_status.setdefault(k[:3], {})[k] = stt
  rows = []
  games = sn[sn.season >= first][["season", "week", "team", "game_id"]].drop_duplicates().sort_values(["team", "season", "week"])
  for x in games.itertuples():
    regs = L.regulars(x.team, int(x.season), int(x.week))
    if not regs:
      continue
    rec = {f"{d}_{k}_{grp}": 0.0 for d in DEFS for k in KINDS for grp in OFF + DEF + ["QB"]}
    for p, grp, role, recent in regs:
      st = status.get((x.season, x.week, x.team, p))
      rep_out = (x.season, x.week, x.team, p) in outrep
      avail = {"report": st in ("ACT", "INA") and not rep_out,
               "inactives": st == "ACT" and not rep_out,
               "actual": (x.game_id, p) in played}
      qq = q.get((x.season, p), 0.5)
      rq = val(int(x.season), p, grp)
      for d in DEFS:
        delta = (role if avail[d] else 0.0) - recent
        rec[f"{d}_snap_{grp}"] += delta
        rec[f"{d}_cap_{grp}"] += delta * qq
        rec[f"{d}_rapm_{grp}"] += delta * rq
    for d in DEFS:
      for k in KINDS:
        rec[f"{d}_{k}_OFF"] = sum(rec[f"{d}_{k}_{gp}"] for gp in OFF)
        rec[f"{d}_{k}_DEF"] = sum(rec[f"{d}_{k}_{gp}"] for gp in DEF)
    # (BR) arrivals: regulars elsewhere now on this team's roster (report availability, offense, on-field value)
    ros = {p for (se, wk, tm, p), stt in roster_status.get((x.season, x.week, x.team), {}).items() if stt in ("ACT", "INA")}
    arr = L.arrivals(x.team, int(x.season), int(x.week), ros, {r[0] for r in regs})
    extra = sum(r[2] * val(int(x.season), r[0], r[1]) for r in arr
                if r[1] in OFF and (x.season, x.week, x.team, r[0]) not in outrep)
    rec["report_rapmarr_OFF"] = rec["report_rapm_OFF"] + extra
    rec["n_arrivals"] = sum(1 for r in arr if r[1] in OFF)
    rows.append({"season": int(x.season), "week": int(x.week), "team": x.team, "game_id": x.game_id, **rec})
  df = pd.DataFrame(rows)
  df.to_parquet(OUT, index=False)
  print(f"wrote {OUT.relative_to(ROOT)}: {len(df)} team-games")
  print(df.groupby("season")[["report_cap_OFF", "report_cap_DEF", "actual_snap_OFF"]].describe().round(2).T.to_string())


if __name__ == "__main__":
  main()
