"""Build the weekly report context and render a single static, mobile-friendly HTML file."""
from __future__ import annotations

import html
import math
from pathlib import Path

import numpy as np
import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .team_model import UNITS, game_lines, team_volume_features

TEMPLATE_DIR = Path(__file__).parent / "templates"
LEAGUE_PASS_SHARE = 0.58  # weight of pass vs rush when combining unit ratings into one number


# ----------------------------------------------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------------------------------------------

def per100(x):
  """EPA/play -> points per 100 plays (the unit shown everywhere)."""
  return 100.0 * x


def sparkline(values, width=90, height=22) -> str:
  v = [x for x in values if pd.notna(x)]
  if len(v) < 2:
    return ""
  lo, hi = min(v), max(v)
  span = (hi - lo) or 1.0
  pts = " ".join(f"{i * width / (len(v) - 1):.1f},{height - 2 - (x - lo) / span * (height - 4):.1f}"
                 for i, x in enumerate(v))
  last = v[-1]
  cy = height - 2 - (last - lo) / span * (height - 4)
  return (f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" height="{height}" aria-hidden="true">'
          f'<polyline points="{pts}" fill="none" stroke="currentColor" stroke-width="1.5"/>'
          f'<circle cx="{width:.1f}" cy="{cy:.1f}" r="2.2" fill="currentColor"/></svg>')


def start_sit(rank: int, pos: str, tiers: dict) -> str:
  t = tiers.get(pos, [5, 12, 18])
  return "Must start" if rank <= t[0] else "Start" if rank <= t[1] else "Flex" if rank <= t[2] else "Sit"


class TeamStyle:
  """Team-colored chips. Text color picked for contrast against the team's primary color."""

  def __init__(self, teams: pd.DataFrame | None):
    self.c = {}
    if teams is not None:
      for _, t in teams.iterrows():
        self.c[t.team_abbr] = (t.team_color or "#666666", t.team_color2 or "#999999")

  def chip(self, team: str) -> str:
    bg, edge = self.c.get(team, ("#666666", "#999999"))
    rgb = [int(bg.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lum = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    fg = "#111" if lum > 0.55 else "#fff"
    return (f'<span class="chip" style="background:{bg};color:{fg};border-left-color:{edge}">'
            f'{html.escape(team)}</span>')


def range_svg(q10, q25, q75, q90, proj, axis_max, width=120, height=16) -> str:
  """Floor-to-ceiling whisker (10th-90th pct), likely box (25th-75th), tick at the projection."""
  if any(pd.isna(x) for x in (q10, q25, q75, q90)):
    return ""
  x = lambda v: 2 + (width - 4) * min(max(v, 0), axis_max) / axis_max
  mid = height / 2
  return (f'<svg class="rng" viewBox="0 0 {width} {height}" width="{width}" height="{height}" aria-hidden="true">'
          f'<line x1="{x(q10):.1f}" y1="{mid}" x2="{x(q90):.1f}" y2="{mid}" class="rng-w"/>'
          f'<rect x="{x(q25):.1f}" y="{mid - 4}" width="{max(x(q75) - x(q25), 1.5):.1f}" height="8" rx="2" '
          f'class="rng-b"/>'
          f'<line x1="{x(proj):.1f}" y1="1" x2="{x(proj):.1f}" y2="{height - 1}" class="rng-p"/></svg>')


def week_bars(weeks: list, n_weeks: int, width=150, height=34) -> str:
  """Weekly fantasy points as mini bars; missed weeks shown as a dash."""
  if n_weeks < 1:
    return ""
  top = max([v for _, v in weeks if v is not None] + [10.0])
  bw = width / n_weeks
  pts = dict(weeks)
  out = []
  for w in range(1, n_weeks + 1):
    v = pts.get(w)
    x0 = (w - 1) * bw + 1
    if v is None:
      out.append(f'<line x1="{x0 + 2:.1f}" y1="{height - 9}" x2="{x0 + bw - 4:.1f}" y2="{height - 9}" '
                 f'class="wb-miss"><title>Wk {w}: did not play</title></line>')
    else:
      h = max(1.0, (height - 10) * max(v, 0) / top)
      out.append(f'<rect x="{x0:.1f}" y="{height - 8 - h:.1f}" width="{bw - 3:.1f}" height="{h:.1f}" rx="1.5" '
                 f'class="wb"><title>Wk {w}: {v:.1f} pts</title></rect>')
    out.append(f'<text x="{x0 + (bw - 3) / 2:.1f}" y="{height - 0.5}" class="wb-l">{w}</text>')
  body = "".join(out)
  return f'<svg class="wbars" viewBox="0 0 {width} {height}" width="{width}" height="{height}">{body}</svg>'


def stat(v, unit, digits=0) -> str:
  return f'<span class="st"><b>{v:.{digits}f}</b><small>{unit}</small></span>'


def td_odds(lam: float, label: str = "TD") -> str:
  """Expected TDs -> chance of exactly 1, exactly 2, 3+ (Poisson; calibrated against backtest outcomes)."""
  lam = max(float(lam), 0.0)
  p0 = math.exp(-lam)
  p1 = lam * p0
  p2 = lam ** 2 / 2 * p0
  p3 = max(1 - p0 - p1 - p2, 0.0)
  tip = f"Anytime {label}: {1 - p0:.0%} (average {lam:.2f} per game)"
  cells = "".join(f'<span class="tdo"><small>{k}</small><b>{v:.0%}</b></span>'
                  for k, v in (("1", p1), ("2", p2), ("3+", p3)))
  return f'<span class="tds" title="{tip}"><small class="tdl">{label}</small>{cells}</span>'


# ----------------------------------------------------------------------------------------------------------------
# Sections
# ----------------------------------------------------------------------------------------------------------------

def season_stats(eng, season: int, week: int) -> pd.DataFrame:
  """Season-to-date per player: games, FP/G, last-3 FP/G, totals, usage shares, weekly points."""
  a = eng.actual[(eng.actual.season == season) & (eng.actual.week < week)]
  g = a.groupby("gsis_id")
  out = pd.DataFrame({
    "games": g.size(), "fpg": g.actual.mean(), "fp_total": g.actual.sum(),
    "last3": a.sort_values("week").groupby("gsis_id").tail(3).groupby("gsis_id").actual.mean(),
  })
  for c in ("pass_yd", "pass_td", "interception", "rush_yd", "rush_td", "reception", "rec_yd", "rec_td",
            "attempts", "completions", "carries", "targets"):
    out[c] = g[c].sum()
  out["weeks"] = g.apply(lambda x: list(zip(x.week.astype(int), x.actual.astype(float))), include_groups=False)
  L = eng.pm.ledger
  L = L[(L.season == season) & (L.week < week)]
  lg = L.groupby("gsis_id")
  out["snap"] = lg.offense_pct.mean()
  out["tgt_share"] = lg.tgt.sum() / lg.team_db.sum()
  out["carry_share"] = lg.carries.sum() / lg.team_rush.sum()
  return out


def expected_line(r) -> str:
  if r.pos == "QB":
    return (stat(r.pass_yd, "pass yd") + stat(r.interception, "INT", 1) + stat(r.rush_yd, "rush yd")
            + td_odds(r.pass_td, "pass TD") + (td_odds(r.rush_td, "rush TD") if r.rush_td >= 0.15 else ""))
  if r.pos == "RB":
    return (stat(r.carries, "car") + stat(r.rush_yd, "rush yd") + stat(r.reception, "rec", 1)
            + stat(r.rec_yd, "rec yd") + td_odds(r.rush_td + r.rec_td))
  return stat(r.tgt, "tgt", 1) + stat(r.reception, "rec", 1) + stat(r.rec_yd, "yd") + td_odds(r.rec_td + r.rush_td)


def season_line(r, st) -> str:
  if st is None or pd.isna(st.get("games")):
    return "No games this season."
  g = int(st["games"])
  if r.pos == "QB":
    body = (stat(st["completions"], "/") + stat(st["attempts"], "att") + stat(st["pass_yd"], "pass yd")
            + stat(st["pass_td"], "TD") + stat(st["interception"], "INT") + stat(st["rush_yd"], "rush yd")
            + stat(st["rush_td"], "rush TD"))
  elif r.pos == "RB":
    body = (stat(st["carries"], "car") + stat(st["rush_yd"], "rush yd") + stat(st["rush_td"], "rush TD")
            + stat(st["targets"], "tgt") + stat(st["reception"], "rec") + stat(st["rec_yd"], "rec yd")
            + stat(st["rec_td"], "rec TD"))
  else:
    body = (stat(st["targets"], "tgt") + stat(st["reception"], "rec") + stat(st["rec_yd"], "yd")
            + stat(st["rec_td"], "TD"))
  return f'<span class="st"><b>{g}</b><small>G</small></span>' + body


def usage_line(r, st) -> str:
  if st is None:
    return ""
  bits = []
  if pd.notna(st.get("snap")):
    bits.append(stat(100 * st["snap"], "% snaps"))
  if r.pos == "RB" and pd.notna(st.get("carry_share")):
    bits.append(stat(100 * st["carry_share"], "% of carries"))
  if r.pos != "QB" and pd.notna(st.get("tgt_share")):
    bits.append(stat(100 * st["tgt_share"], "% target share"))
  return "".join(bits)


def player_rankings(eng, p: pd.DataFrame, season: int, week: int, cfg: dict) -> dict:
  ts = TeamStyle(eng.data.teams)
  p = p.copy()
  # Everyone with a real role, plus every team's QB1 (so all playing teams have a quarterback listed).
  qb1 = p[p.pos == "QB"].sort_values("db", ascending=False).groupby("team").head(1).index
  p = p[(p.proj >= 0.5) | p.index.isin(qb1)].copy()
  p["pos_rank"] = p.groupby("pos").proj.rank(ascending=False, method="first").astype(int)
  p["tier"] = [start_sit(r, pos, cfg["tiers"]) for r, pos in zip(p.pos_rank, p.pos)]
  # Grade relative to this week's spread of matchups at the position (opponent effects are modest in size).
  pct = p.groupby("pos").matchup_pct.rank(pct=True)
  p["grade"] = np.select([pct >= 0.85, pct >= 0.65, pct > 0.35, pct > 0.15], ["A", "B", "C", "D"], "F")
  p["takeaway"] = [takeaway(r) for _, r in p.iterrows()]
  stats = season_stats(eng, season, week)
  n_weeks = week - 1
  out = {}
  for pos in ("QB", "RB", "WR", "TE"):
    g = p[p.pos == pos].sort_values("proj", ascending=False)
    axis = max(float(np.nanpercentile(g.p90, 95)) if g.p90.notna().any() else 20.0, 10.0)
    rows = []
    for _, r in g.iterrows():
      st = stats.loc[r.gsis_id].to_dict() if r.gsis_id in stats.index else None
      rows.append({
        "rank": int(r.pos_rank), "ecr": r.ecr, "name": r.full_name, "team_chip": ts.chip(r.team),
        "opp_chip": ts.chip(r.opp), "home": "vs" if r.home >= 0 else "@", "proj": r.proj,
        "p10": r.p10, "p25": r.p25, "p50": r.p50, "p75": r.p75, "p90": r.p90,
        "range": range_svg(r.p10, r.p25, r.p75, r.p90, r.proj, axis),
        "grade": r.grade, "mpts": r.matchup_pts, "tier": r.tier, "takeaway": r.takeaway, "conf": r.confidence,
        "status": r.status, "avail": r.avail, "inactive": 1 - r.avail,
        "inactive_why": inactive_why(r), "boost": r.injury_boost, "boost_from": r.boost_from or "",
        "low_sample": bool(r.low_sample), "line": expected_line(r),
        "fpg": st["fpg"] if st else np.nan, "last3": st["last3"] if st else np.nan,
        "season": season_line(r, st), "usage": usage_line(r, st),
        "bars": week_bars(st["weeks"] if st else [], n_weeks),
      })
    out[pos] = {"rows": rows, "byes": bye_rows(eng, stats, ts, pos, season, week)}
  return out


def bye_rows(eng, stats, ts, pos, season, week) -> list:
  """Top players at the position whose teams are on bye (QB: every bye team's starter)."""
  g = eng.games(season, week)
  bye = sorted(set(eng.tm.teams) - set(g.home_team) - set(g.away_team))
  if not bye:
    return []
  r = eng.data.rosters
  r = r[(r.season == season) & (r.week <= week) & r.gsis_id.notna()].copy()
  r = r[(r.week == r.groupby("team").week.transform("max")) & r.status.isin(["ACT", "INA"]) & r.team.isin(bye)]
  r = r[r.position.replace({"FB": "RB"}) == pos].join(stats, on="gsis_id")
  r = r[r.fpg.notna()].sort_values("fp_total", ascending=False)
  r = r.groupby("team").head(1 if pos == "QB" else 2 if pos in ("RB", "TE") else 3)
  if pos != "QB":
    r = r[r.fpg >= 6]
  return [{"name": x.full_name, "team_chip": ts.chip(x.team), "fpg": x.fpg, "games": int(x.games)}
          for x in r.itertuples()]


def inactive_why(r) -> str:
  if r.status:
    return "Injury report + practice pattern: " + r.status
  if r.avail < 0.9:
    return "Healthy-scratch risk from his recent active/inactive history, depth chart spot and who is out ahead of him"
  return "Not on the injury report; regular role"


def takeaway(r) -> str:
  bits = []
  if r.avail < 0.5:
    return f"Likely inactive ({r.status or 'healthy scratch risk'})"
  if r.avail < 0.9:
    bits.append(f"{1 - r.avail:.0%} chance inactive" + (f" ({r.status})" if r.status else " (scratch risk)"))
  if r.injury_boost >= 1.0:
    bits.append(f"+{r.injury_boost:.1f} pts from vacated volume ({r.boost_from})")
  if r.if_sits_gain >= 1.0:
    bits.append(f"+{r.if_sits_gain:.1f} more if {r.if_sits_name} sits")
  if r.grade == "A" and r.matchup_pts >= 0.8:
    bits.append(f"soft matchup ({r.matchup_pts:+.1f} pts vs avg D)")
  elif r.grade == "F" and r.matchup_pts <= -0.8:
    bits.append(f"tough matchup ({r.matchup_pts:+.1f} pts vs avg D)")
  if r.wind_penalty >= 0.05:
    bits.append(f"wind trims passing {r.wind_penalty:.0%}")
  if r.low_sample:
    bits.append("little data: leans on draft-tier prior")
  if not bits:
    if r.pos == "QB":
      bits.append(f"{r.db:.0f} dropbacks" + (f", {r.rush:.1f} rushes add a floor" if r.rush >= 4 else ""))
    elif r.pos == "RB":
      bits.append(f"workload: {r.carries:.0f} carries + {r.tgt:.1f} targets")
    else:
      bits.append(f"{r.tgt:.1f} targets ({r.tgt_share_hat:.0%} of dropbacks)")
    if r.confidence == "Low":
      bits.append("boom/bust")
  return "; ".join(bits)


def team_tables(eng, season: int, week: int, cfg: dict) -> tuple[list, list]:
  rb = eng.tm.fit(season, week, bootstrap=cfg["team_model"]["bootstrap_samples"])
  history = {}
  for w in range(2, week + 1):
    r = eng.tm.fit(season, w)
    history[w] = net_rating(r)
  hist = pd.DataFrame(history)
  rows = []
  net = net_rating(rb)
  for team in rb.teams:
    off = LEAGUE_PASS_SHARE * rb.off.at[team, "pass"] + (1 - LEAGUE_PASS_SHARE) * rb.off.at[team, "rush"]
    dfn = LEAGUE_PASS_SHARE * rb.dfn.at[team, "pass"] + (1 - LEAGUE_PASS_SHARE) * rb.dfn.at[team, "rush"]
    se = np.sqrt((LEAGUE_PASS_SHARE * rb.se_off.at[team, "pass"]) ** 2 + (LEAGUE_PASS_SHARE * rb.se_def.at[team, "pass"]) ** 2)
    rows.append({
      "team": team, "net": per100(net[team]), "off": per100(off), "def": per100(-dfn),
      "off_pass": per100(rb.off.at[team, "pass"]), "off_rush": per100(rb.off.at[team, "rush"]),
      "def_pass": per100(-rb.dfn.at[team, "pass"]), "def_rush": per100(-rb.dfn.at[team, "rush"]),
      "st": per100(rb.off.at[team, "st"] - rb.dfn.at[team, "st"]), "se": per100(se),
      "spark": sparkline(hist.loc[team].tolist()) if team in hist.index else "",
    })
  power = sorted(rows, key=lambda x: -x["net"])
  for i, r in enumerate(power, 1):
    r["rank"] = i
    r["certainty"] = "Solid" if r["se"] < 2.5 else "Likely" if r["se"] < 4.0 else "Uncertain"
  # Schedule luck (teams): average strength of opponents actually faced this season, from the ridge
  # coefficients (not raw minus adjusted, which would mostly measure ridge shrinkage).
  luck = []
  if rb.raw_off is not None:
    w = {"pass": LEAGUE_PASS_SHARE, "rush": 1 - LEAGUE_PASS_SHARE}
    faced_def, faced_off = 0.0, 0.0
    for u in ("pass", "rush"):
      pl = eng.tm.plays[u]
      pl = pl[(pl.season == season) & (pl.week < week)]
      faced_def = faced_def + w[u] * pl.defteam.map(rb.dfn[u]).groupby(pl.posteam).mean()
      faced_off = faced_off + w[u] * pl.posteam.map(rb.off[u]).groupby(pl.defteam).mean()
    for team in rb.teams:
      if team not in faced_def.index:
        continue
      ro = sum(w[u] * rb.raw_off.at[team, u] for u in w)
      rd = sum(w[u] * rb.raw_def.at[team, u] for u in w)
      luck.append({"team": team, "off_raw": per100(ro), "off_gap": per100(faced_def[team]),
                   "off_adj": per100(ro - faced_def[team]), "def_raw": per100(-rd),
                   "def_gap": per100(-faced_off[team]), "def_adj": per100(-(rd - faced_off[team]))})
  for r in luck:
    r["total_gap"] = r["off_gap"] + r["def_gap"]
  luck.sort(key=lambda x: -x["total_gap"])
  return power, luck


def net_rating(r) -> pd.Series:
  off = LEAGUE_PASS_SHARE * r.off["pass"] + (1 - LEAGUE_PASS_SHARE) * r.off["rush"]
  dfn = LEAGUE_PASS_SHARE * r.dfn["pass"] + (1 - LEAGUE_PASS_SHARE) * r.dfn["rush"]
  return off - dfn + (r.off["st"] - r.dfn["st"]) * 0.18  # ST plays are ~18% as frequent as scrimmage plays


def matchups(eng, season: int, week: int, cfg: dict) -> list:
  r = eng.tm.fit(season, week)
  vf = team_volume_features(eng.team_ledger, season, week, eng.cfg)
  games = eng.games(season, week)
  tp = eng.gm.predict(games, r, vf, use_vegas=False)
  gl = game_lines(tp, games)
  out = []
  for _, g in gl.iterrows():
    side = lambda t: {
      "team": t, "off_pass": per100(r.off.at[t, "pass"]), "off_rush": per100(r.off.at[t, "rush"]),
      "def_pass": per100(-r.dfn.at[t, "pass"]), "def_rush": per100(-r.dfn.at[t, "rush"]),
      "st": per100(r.off.at[t, "st"] - r.dfn.at[t, "st"])}
    vm, vt = g.spread_line, g.total_line
    dm = g.model_margin - vm if pd.notna(vm) else np.nan
    dt = g.model_total - vt if pd.notna(vt) else np.nan
    flag_m = pd.notna(dm) and abs(dm) >= cfg["report"]["margin_disagree"]
    flag_t = pd.notna(dt) and abs(dt) >= cfg["report"]["total_disagree"]
    fav = g.home_team if g.model_margin >= 0 else g.away_team
    take = f"Model: {fav} by {abs(g.model_margin):.1f}, total {g.model_total:.1f}."
    if flag_m:
      take += f" Leans {g.home_team if dm > 0 else g.away_team} vs the spread ({dm:+.1f})."
    if flag_t:
      take += f" Leans {'over' if dt > 0 else 'under'} ({dt:+.1f})."
    out.append({"away": side(g.away_team), "home": side(g.home_team), "gameday": g.gameday,
                "neutral": g.location == "Neutral", "model_margin": g.model_margin, "model_total": g.model_total,
                "vegas_margin": vm, "vegas_total": vt, "d_margin": dm, "d_total": dt, "flag_m": flag_m,
                "flag_t": flag_t, "takeaway": take})
  return out


def player_luck(eng, p: pd.DataFrame, season: int, week: int) -> list:
  """Raw fantasy points/game vs schedule-adjusted: each past game is divided by how favorable that opponent
  was for this player's current profile (projection vs that defense / projection vs average defense)."""
  r = eng.tm.fit(season, week)
  a = eng.actual[(eng.actual.season == season) & (eng.actual.week < week)]
  a = a[a.gsis_id.isin(p.gsis_id)][["gsis_id", "week", "opponent_team", "actual"]]
  if a.empty:
    return []
  base = p.set_index("gsis_id")
  rows = base.loc[a.gsis_id].reset_index()
  rows["opp"] = a.opponent_team.to_numpy()
  rows["def_pass"] = rows.opp.map(r.dfn["pass"]).fillna(0).to_numpy()
  rows["def_rush"] = rows.opp.map(r.dfn["rush"]).fillna(0).to_numpy()
  rows["home"] = 0
  # Standard starter workload per position so the factor reflects the player's rates, not his role size.
  vol = {"QB": dict(db=35, rush=4, carries=2, tgt=0), "RB": dict(db=0, rush=15, carries=15, tgt=3.5),
         "WR": dict(db=0, rush=0.3, carries=0.3, tgt=7), "TE": dict(db=0, rush=0, carries=0, tgt=5)}
  for c in ("db", "rush", "carries", "tgt"):
    rows[c] = rows.pos.map(lambda x: vol.get(x, vol["WR"])[c])
  vs_opp = eng.pm.stats_from_volume(rows).proj.to_numpy()
  neutral = eng.pm.stats_from_volume(rows, neutral=True).proj.to_numpy()
  factor = np.clip(vs_opp / np.maximum(neutral, 1.0), 0.7, 1.4)
  a = a.assign(adj=a.actual.to_numpy() / factor)
  g = a.groupby("gsis_id").agg(games=("actual", "size"), raw=("actual", "mean"), adj=("adj", "mean"))
  g = g[g.games >= 3]
  g["gap"] = g.raw - g.adj
  g = g.join(base[["full_name", "pos", "team", "proj"]])
  g = g[g.raw >= 8]
  g = g.reindex(g.gap.abs().sort_values(ascending=False).index).head(40)
  return [{"name": x.full_name, "pos": x.pos, "team": x.team, "games": int(x.games), "raw": x.raw, "adj": x.adj,
           "gap": x.gap, "takeaway": ("Stats inflated by soft schedule - sell high" if x.gap >= 1 else
                                      "Better than his stats - tough schedule so far, buy low" if x.gap <= -1
                                      else "Schedule-neutral production")}
          for x in g.itertuples()]


def role_changes(eng, season: int, week: int, cfg: dict) -> list:
  L = eng.pm.ledger
  L = L[(L.season == season) & (L.week < week) & L.pos.isin(["RB", "WR", "TE", "QB"])].copy()
  if L.empty:
    return []
  L["opp_share"] = (L.carries + L.tgt) / (L.team_rush + L.team_db).replace(0, np.nan)
  last_team_week = L.groupby("team").week.max()
  out = []
  thr_s, thr_o = cfg["player_model"]["role_change_snap_jump"], cfg["player_model"]["role_change_opp_jump"]
  for gid, g in L.sort_values("week").groupby("gsis_id"):
    last = g.iloc[-1]
    if last.week != last_team_week.get(last.team):
      continue
    prev = g.iloc[:-1].tail(3)
    prev_snap = prev.offense_pct.mean() if len(prev) else 0.0
    prev_opp = prev.opp_share.mean() if len(prev) else 0.0
    ds = (last.offense_pct or 0) - (prev_snap if pd.notna(prev_snap) else 0)
    do = (last.opp_share or 0) - (prev_opp if pd.notna(prev_opp) else 0)
    if (pd.notna(ds) and ds >= thr_s) or (pd.notna(do) and do >= thr_o):
      name = eng.pm.info.full_name.get(gid, gid)
      out.append({"name": name, "pos": last.pos, "team": last.team, "week": int(last.week),
                  "snap_now": last.offense_pct, "snap_prev": prev_snap, "opp_now": last.opp_share,
                  "opp_prev": prev_opp, "touches": int(last.carries + last.tgt), "score": (ds or 0) + 2 * (do or 0),
                  "takeaway": ("New full-time role" if (last.offense_pct or 0) >= 0.7 else "Expanding role")
                  + (" - waiver add" if (last.offense_pct or 0) >= 0.5 else " - watch list")})
  out.sort(key=lambda x: -x["score"])
  return out[:30]


def backtest_summary(ev: pd.DataFrame | None) -> list:
  if ev is None or ev.empty:
    return []
  ev = ev[ev.subset == "relevant"]
  rows = []
  for _, r in ev.iterrows():
    rows.append({k: r.get(k) for k in ["pos", "n", "mae_model", "mae_ecr", "mae_vegas", "mae_raw", "rank_model",
                                        "rank_ecr", "rank_vegas", "rank_raw"]})
  return rows


# ----------------------------------------------------------------------------------------------------------------
# Render
# ----------------------------------------------------------------------------------------------------------------

def render(ctx: dict, out_path: Path) -> Path:
  env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html", "j2"]))
  env.filters["f0"] = lambda x: "" if x is None or pd.isna(x) else f"{x:.0f}"
  env.filters["f1"] = lambda x: "" if x is None or pd.isna(x) else f"{x:.1f}"
  env.filters["f2"] = lambda x: "" if x is None or pd.isna(x) else f"{x:.2f}"
  env.filters["f3"] = lambda x: "" if x is None or pd.isna(x) else f"{x:.3f}"
  env.filters["sgn"] = lambda x: "" if x is None or pd.isna(x) else f"{x:+.1f}"
  env.filters["pct"] = lambda x: "" if x is None or pd.isna(x) else f"{x:.0%}"
  html_out = env.get_template("report.html.j2").render(**ctx)
  out_path.parent.mkdir(parents=True, exist_ok=True)
  out_path.write_text(html_out, encoding="utf-8")
  return out_path
