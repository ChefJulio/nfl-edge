"""Audit of the injury-tag rules (owner 2026-10-21: official tags; InjuryModel.designations) on past seasons: what
happened to the players each rule tags, so every assumption behind a rule is a measured number.

Usage: python tools/tag_audit.py [--first=2022] [--last=2025]

Per (player, team game w) with his team's previous game k, QB / RB / WR / TE, not on a reserve list at k:
  missed   missed k while on k's injury report, listed reason not rest / personal  -> Tuesday Q
  rest     missed k while on k's report for rest / personal                         -> no tag (excluded)
  notback  played k, hurt in it and not back (injury note, no return note after)   -> Tuesday Q
  back     played k, hurt in it and back                                            -> no tag
For each: how often he played game w, whether he was on w's report, and w's final designation. Plus the cleared
case: on w's final report with no designation (the tag shows nothing) and how often those players played.
In-game notes with returns come from nflverse's play-by-play text (fetched here; nfledge/ingame.py).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge import ingame  # noqa: E402
from nfledge import tuesday as T  # noqa: E402
from nfledge.config import load_config  # noqa: E402


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  first, last = int(opt.get("first", 2022)), int(opt.get("last", 2025))
  import nflreadpy as nfl
  cfg = load_config()
  d = D.load_all(cfg)
  cache = D.Cache(ROOT / cfg["data"]["cache_dir"])
  rr = T.report_rows(d)
  ctx = T._Ctx(d, rr, T.hurt_notes(d, cache))
  by_team = {}  # (season, week, team) -> players on its report or noted hurt in its game
  for g, s, w, t in zip(rr.gsis_id, rr.season, rr.week, rr.team):
    by_team.setdefault((int(s), int(w), {"LAR": "LA"}.get(t, t)), set()).add(g)
  hurt_back = {}  # (g, s, k) -> True back / False not back
  with_returns = set()  # seasons whose text carries the return notes (nflverse: 2024 on)
  for s in range(first, last + 1):
    pbp = nfl.load_pbp([s]).select(["game_id", "play_id", "season", "week", "season_type", "qtr", "time", "desc"]).to_pandas()
    rs = cache.get("rosters", s, lambda: nfl.load_rosters_weekly([s]), stale=False)
    n = ingame.link(ingame.notes(pbp), rs)
    n = n[n.season_type == "REG"].dropna(subset=["gsis_id"])
    nb = ingame.not_back(n)
    h = n[n.kind == "hurt"]
    for g, w, t in zip(h.gsis_id, h.week, h.team):
      hurt_back[(g, s, int(w))] = (g, s, int(w)) not in nb
      by_team.setdefault((s, int(w), t), set()).add(g)
    if (n.kind == "back").any():
      with_returns.add(s)
    print(f"[audit] {s}: {int((n.kind == 'hurt').sum())} injury notes, {int((n.kind == 'back').sum())} returns", flush=True)
  ro = d.rosters.dropna(subset=["gsis_id"])
  ro = ro.assign(season=ro.season.astype(int), week=ro.week.astype(int))
  ros_at = {(g, s_, w_): st for g, s_, w_, st in zip(ro.gsis_id, ro.season, ro.week, ro.status)}
  ros_team = {(g, s_, w_): {"LAR": "LA"}.get(t, t) for g, s_, w_, t in zip(ro.gsis_id, ro.season, ro.week, ro.team)}
  rows = []
  for (s, team), weeks in ctx.tw.items():
    if not first <= s <= last:
      continue
    for k, w in zip(weeks, weeks[1:]):
      if (s, w, team) not in ctx.final:
        continue
      for g in by_team.get((s, k, team), set()):
        pos = ctx.pos_of.get(g, "")
        if pos not in ("QB", "RB", "WR", "TE") or (g, s, k) in ctx.res:
          continue
        played_k = (g, s, k) in ctx.on
        if not played_k and (g, s, k) in ctx.rep:
          grp = "rest" if ctx.why.get((s, k, g), "none") in ("rest", "personal") else "missed"
        elif played_k and (g, s, k) in hurt_back and s in with_returns:
          grp = "back" if hurt_back[(g, s, k)] else "notback"
        else:
          continue
        now = ctx.rep.get((g, s, w))
        rst = ros_at.get((g, s, w), "none")
        rows.append({"team": team, "ros_w": rst, "team_w": ros_team.get((g, s, w), ""), "season": s, "week": w, "gsis_id": g, "grp": grp, "y": ctx.label(g, s, team, w),
                     "listed": now is not None, "final": T._gs(now.game_status) if now is not None else "not listed",
                     "res_w": (g, s, w) in ctx.res})
  x = pd.DataFrame(rows).dropna(subset=["y"])
  x = x[~x.res_w]
  print(f"\nrows {len(x)} ({first}-{last}); played the next game overall {x.y.mean():.3f}\n")
  for grp, lab in (("missed", "missed last game hurt (Tuesday Q)"), ("notback", "hurt in last game, not back (Tuesday Q)"),
                   ("back", "hurt in last game, came back (no tag)"), ("rest", "missed last game, rest / personal (no tag)")):
    r = x[x.grp == grp]
    if not len(r):
      continue
    print(f"{lab}: n {len(r)}, played next game {r.y.mean():.3f}, on next week's report {r.listed.mean():.3f}")
    t = r.groupby("final").y.agg(["size", "mean"]).sort_values("size", ascending=False)
    for f_, v in t.iterrows():
      print(f"    final {f_:<12} n {int(v['size']):>5}  played {v['mean']:.3f}")
    nl = r[r.final == "not listed"]
    if len(nl):
      nl = nl.assign(where=[st if tw == "" or tw == tm else "other team" for st, tw, tm in zip(nl.ros_w, nl.team_w, nl.team)])
      print("      not listed, his roster status that week: " + ", ".join(f"{k} {int(v['size'])} (played {v['mean']:.2f})"
            for k, v in nl.groupby("where").y.agg(["size", "mean"]).sort_values("size", ascending=False).iterrows()))
  # the cleared case: on the final report with no designation
  rep = pd.DataFrame([(g, s, w, T._gs(r_.game_status), r_.days) for (g, s, w), r_ in ctx.rep.items() if first <= s <= last],
                     columns=["gsis_id", "season", "week", "gs", "days"])
  rep["pos"] = rep.gsis_id.map(ctx.pos_of)
  rep = rep[rep.pos.isin(["QB", "RB", "WR", "TE"])]
  team = {}
  inj = d.injuries.dropna(subset=["gsis_id"])
  team = {(int(a), int(b), g): t for a, b, g, t in zip(inj.season, inj.week, inj.gsis_id, inj.team)}
  rep["y"] = [ctx.label(g, s, {"LAR": "LA"}.get(team.get((s, w, g), ""), team.get((s, w, g), "")), w) for g, s, w in zip(rep.gsis_id, rep.season, rep.week)]
  rep = rep.dropna(subset=["y"])
  print("\nfinal report designation (QB/RB/WR/TE) -> played:")
  for gs_, v in rep.groupby("gs").y.agg(["size", "mean"]).iterrows():
    print(f"    {gs_:<12} n {int(v['size']):>5}  played {v['mean']:.3f}")
  none = rep[rep.gs == "None"]
  dnp = none.days.fillna("").str.replace("?", "", regex=False)
  print("  no designation, by the week's practice:")
  for lab, m in (("any DNP", dnp.str.contains("D")), ("limited, no DNP", ~dnp.str.contains("D") & dnp.str.contains("L")),
                 ("full every day", ~dnp.str.contains("D") & ~dnp.str.contains("L"))):
    if m.any():
      print(f"    {lab:<16} n {int(m.sum()):>5}  played {none[m].y.mean():.3f}")



if __name__ == "__main__":
  main()
