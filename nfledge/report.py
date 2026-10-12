"""Build the weekly report context and render a single static, mobile-friendly HTML file."""
from __future__ import annotations

import html
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import ROOT
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


def _lum(hexcolor: str) -> float:
  """WCAG relative luminance."""
  h = hexcolor.lstrip("#")
  ch = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
  ch = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]


def contrast(a: str, b: str) -> float:
  la, lb = sorted((_lum(a), _lum(b)), reverse=True)
  return (la + 0.05) / (lb + 0.05)


class TeamStyle:
  """Team colors for chips and full-row backgrounds, with text colors chosen for WCAG contrast: the team's
  secondary color when it reaches 4.5:1 on the primary, otherwise white or black (whichever contrasts more)."""

  def __init__(self, teams: pd.DataFrame | None):
    self.c, self.logo, self.nick = {}, {}, {}
    if teams is not None:
      for _, t in teams.iterrows():
        self.c[t.team_abbr] = (t.team_color or "#666666", t.team_color2 or "#999999")
        self.logo[t.team_abbr] = t.get("team_logo_espn")
        self.nick[t.team_abbr] = t.get("team_nick") or ""

  def colors(self, team: str) -> tuple[str, str, str]:
    """(background, accent, text)."""
    bg, sec = self.c.get(team, ("#666666", "#999999"))
    bw = "#ffffff" if contrast("#ffffff", bg) >= contrast("#111111", bg) else "#111111"
    text = sec if contrast(sec, bg) >= 4.5 else bw
    return bg, sec, text

  def chip(self, team: str) -> str:
    bg, sec, fg = self.colors(team)
    return (f'<span class="chip" style="background:{bg};color:{fg};border-left-color:{sec}">'
            f'{html.escape(team)}</span>')

  TILE = "#171a20"

  def visible(self, color: str) -> str:
    """Lighten a team color just enough to show against the dark tile (e.g. black, deep navy)."""
    c = color
    for t in (0.0, 0.2, 0.35, 0.5, 0.65):
      rgb = [int(color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
      mixed = "#" + "".join(f"{round(v + (255 - v) * t):02x}" for v in rgb)
      if contrast(mixed, self.TILE) >= 2.0:
        return mixed
      c = mixed
    return c

  def row_style(self, team: str) -> str:
    """Dark tile with a thin border traced from the team's primary (left) into its secondary (right)."""
    bg, sec = self.c.get(team, ("#666666", "#999999"))
    return f"--tc:{self.visible(bg)};--tc2:{self.visible(sec)};--tfg:#ffffff"

  def logo_bg(self, team: str) -> str:
    """Team primary or secondary - whichever leaves more of the logo visible (measured from its pixels)."""
    return self._logo_bgs().get(team, self.c.get(team, ("#666666", "#999999"))[1])

  def _logo_bgs(self) -> dict:
    if hasattr(self, "_bg_cache"):
      return self._bg_cache
    path = ROOT / "cache" / "logo_bg.json"
    known = json.loads(path.read_text()) if path.exists() else {}
    for team, url in self.logo.items():
      if team in known or not url or team not in self.c:
        continue
      try:
        known[team] = pick_logo_bg(url, *self.c[team])
      except Exception:
        continue
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(known, indent=1))
    self._bg_cache = known
    return known

  def logo_img(self, team: str, size: int = 18) -> str:
    url = self.logo.get(team)
    if not url:
      return ""
    return (f'<span class="logo" style="background:{self.logo_bg(team)}"><img src="{html.escape(url)}" alt="{html.escape(team)}" '
            f'width="{size}" height="{size}" loading="lazy"></span>')


def pick_logo_bg(url: str, primary: str, secondary: str) -> str:
  """Fraction of the logo's opaque pixels that would blend into each candidate background (contrast < 1.6);
  choose the background that hides less of the logo."""
  import io
  import urllib.request

  from PIL import Image
  with urllib.request.urlopen(url, timeout=15) as resp:
    img = Image.open(io.BytesIO(resp.read())).convert("RGBA").resize((96, 96))
  px = [p for p in img.getdata() if p[3] > 128]
  if not px:
    return secondary

  def hidden(bg: str) -> float:
    lb = _lum(bg)
    lost = 0
    for r, g, b, _ in px:
      lp = _lum(f"#{r:02x}{g:02x}{b:02x}")
      hi, lo = max(lp, lb), min(lp, lb)
      lost += (hi + 0.05) / (lo + 0.05) < 1.6
    return lost / len(px)

  return primary if hidden(primary) < hidden(secondary) else secondary


def range_svg(q10, q25, q75, q90, proj, axis_max, width=100, height=16) -> str:
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


POSITIONS_ALL = ("QB", "RB", "WR", "TE")


def pos_badge(pos: str) -> str:
  """Position badge, one color per position across the site."""
  return f'<span class="posb posb-{pos}">{pos}</span>' if pos in POSITIONS_ALL else str(pos)


def stat(v, unit, digits=0) -> str:
  return f'<span class="st"><b>{v:.{digits}f}</b><small>{unit}</small></span>'


def td_donut(lam: float, label: str = "TD") -> str:
  """Touchdown odds as a small donut: ring segments for 0 / 1 / 2 / 3+ TDs (darker = more), anytime % in the
  middle. Poisson from the expected-TD rate (backtest: well calibrated)."""
  lam = max(float(lam), 0.0)
  p0 = math.exp(-lam)
  probs = [p0, lam * p0, lam ** 2 / 2 * p0]
  probs.append(max(1 - sum(probs), 0.0))
  r, sw, size = 13.0, 6.0, 34
  circ = 2 * math.pi * r
  segs, start = [], 0.0
  for k, p in enumerate(probs):
    if p <= 0.002:
      continue
    seg = p * circ
    segs.append(f'<circle r="{r}" cx="{size / 2}" cy="{size / 2}" class="td{k}" stroke-width="{sw}" fill="none" '
                f'stroke-dasharray="{seg:.2f} {circ - seg:.2f}" stroke-dashoffset="{-start:.2f}" '
                f'transform="rotate(-90 {size / 2} {size / 2})"/>')
    start += seg
  tip = (f"{label}: anytime {1 - p0:.0%} | exactly 1: {probs[1]:.0%} | 2: {probs[2]:.0%} | 3+: {probs[3]:.0%} "
         f"(avg {lam:.2f})")
  return (f'<span class="tdd" title="{tip}"><svg viewBox="0 0 {size} {size}" width="{size}" height="{size}">'
          f'{"".join(segs)}<text x="{size / 2}" y="{size / 2 + 3.5}" class="tdc">{1 - p0:.0%}</text></svg>'
          f'<small>{label}</small></span>')


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
    stats = stat(r.pass_yd, "pass yd") + stat(r.interception, "INT", 1) + stat(r.rush_yd, "rush yd")
    tds = td_donut(r.pass_td, "pass TD") + (td_donut(r.rush_td, "rush TD") if r.rush_td >= 0.15 else "")
  elif r.pos == "RB":
    stats = (stat(r.carries, "car") + stat(r.rush_yd, "rush yd") + stat(r.reception, "rec", 1)
             + stat(r.rec_yd, "rec yd"))
    tds = td_donut(r.rush_td + r.rec_td)
  else:
    stats = stat(r.tgt, "tgt", 1) + stat(r.reception, "rec", 1) + stat(r.rec_yd, "yd")
    tds = td_donut(r.rec_td + r.rush_td)
  return f'<div class="xl"><div class="xl-st">{stats}</div><div class="xl-td">{tds}</div></div>'


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


STARTERS = {"QB": 12, "RB": 24, "WR": 36, "TE": 12}


def defense_vs_position(eng, p: pd.DataFrame, season: int, week: int) -> dict:
  """Opponent-adjusted 'defense vs position' ranks: each position's fantasy starters projected against every
  defense (that defense's ratings in place of this week's opponent, home field neutral); defenses ranked by
  points allowed. 1st = toughest, 32nd = most generous. Unlike raw fantasy-points-allowed ranks, this is not
  skewed by which offenses a defense happened to face."""
  r = eng.game_ratings(season, week)
  out = {}
  for pos, n in STARTERS.items():
    base = p[(p.pos == pos) & (p.avail >= 0.5)].sort_values("proj", ascending=False).head(n)
    if base.empty:
      continue
    allowed = {}
    for d in r.teams:
      x = base.assign(def_pass=r.dfn.at[d, "pass"], def_rush=r.dfn.at[d, "rush"], home=0)
      allowed[d] = float(eng.pm.stats_from_volume(x).proj.mean())
    s = pd.Series(allowed)
    out[pos] = s.rank(ascending=True, method="min").astype(int)  # fewest points allowed = 1st (toughest)
  return out


def rank_color(rank: int, n: int = 32) -> str:
  """1st (toughest) red -> mid neutral -> 32nd (easiest) green."""
  t = (rank - 1) / max(n - 1, 1)
  red, mid, green = (255, 131, 120), (214, 218, 224), (84, 209, 122)
  a, b, u = (red, mid, t / 0.5) if t < 0.5 else (mid, green, (t - 0.5) / 0.5)
  return "#" + "".join(f"{round(x + (y - x) * u):02x}" for x, y in zip(a, b))


def ordinal(n: int) -> str:
  return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def player_rankings(eng, p: pd.DataFrame, season: int, week: int, cfg: dict) -> dict:
  ts = TeamStyle(eng.data.teams)
  p = p.copy()
  # Everyone with a real role, plus every team's QB1 (so all playing teams have a quarterback listed).
  qb1 = p[p.pos == "QB"].sort_values("db", ascending=False).groupby("team").head(1).index
  p = p[(p.proj >= 0.5) | p.index.isin(qb1)].copy()
  p["pos_rank"] = p.groupby("pos").proj.rank(ascending=False, method="first").astype(int)
  p["tier"] = [start_sit(r, pos, cfg["tiers"]) for r, pos in zip(p.pos_rank, p.pos)]
  # Matchup = the opponent's defense-vs-position rank (1st toughest .. 32nd easiest); grade and meter follow it,
  # so the meter, the rank and the takeaway always tell the same story.
  dvp = defense_vs_position(eng, p, season, week)
  p["dvp_rank"] = [int(dvp[pos][o]) if pos in dvp and o in dvp[pos] else 16 for pos, o in zip(p.pos, p.opp)]
  p["grade"] = pd.cut(p.dvp_rank, [0, 6, 12, 19, 26, 32], labels=["F", "D", "C", "B", "A"]).astype(str)
  p["takeaway"] = [takeaway(r) for _, r in p.iterrows()]
  stats = season_stats(eng, season, week)
  n_weeks = week - 1
  # Until Friday's expert rankings are out, show last week's rank (display only; never fed to the model).
  e = eng.data.ecr
  prev_ecr = (e[(e.season == season) & (e.week == week - 1)].set_index("gsis_id").ecr
              if e is not None else pd.Series(dtype=float))
  prev_ecr = prev_ecr[~prev_ecr.index.duplicated()]
  out = {}
  for pos in ("QB", "RB", "WR", "TE"):
    g = p[p.pos == pos].sort_values("proj", ascending=False)
    axis = max(float(np.nanpercentile(g.p90, 95)) if g.p90.notna().any() else 20.0, 10.0)
    rows = []
    for _, r in g.iterrows():
      st = stats.loc[r.gsis_id].to_dict() if r.gsis_id in stats.index else None
      rows.append({
        "row_style": ts.row_style(r.team), "logo": ts.logo_img(r.team),
        "rank": int(r.pos_rank), "ecr": r.ecr if pd.notna(r.ecr) else prev_ecr.get(r.gsis_id, np.nan),
        "ecr_stale": pd.isna(r.ecr) and r.gsis_id in prev_ecr.index, "name": r.full_name, "team_chip": ts.chip(r.team),
        "opp_chip": ts.chip(r.opp), "opp": r.opp, "opp_logo": ts.logo_img(r.opp, 18),
        "dvp": ordinal(int(dvp[r.pos][r.opp])) if r.pos in dvp and r.opp in dvp[r.pos] else "",
        "dvp_rank": int(r.dvp_rank),
        "dvp_color": rank_color(int(dvp[r.pos][r.opp])) if r.pos in dvp and r.opp in dvp[r.pos] else "",
        "home": "vs" if r.home >= 0 else "@", "proj": r.proj,
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
  return [{"name": x.full_name, "team_chip": ts.chip(x.team), "fpg": x.fpg, "games": int(x.games),
           "logo": ts.logo_img(x.team, 16)}
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
  if r.grade == "A":
    bits.append(f"soft matchup ({r.opp} {ordinal(r.dvp_rank)} vs {r.pos}s)")
  elif r.grade == "F":
    bits.append(f"tough matchup ({r.opp} {ordinal(r.dvp_rank)} vs {r.pos}s)")
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
  ts = TeamStyle(eng.data.teams)
  net = net_rating(rb)
  # Net-rating uncertainty from the bootstrap (pass/rush offense and defense SEs, weighted like the net).
  w_p, w_r = LEAGUE_PASS_SHARE, 1 - LEAGUE_PASS_SHARE
  se_net = np.sqrt(w_p ** 2 * (rb.se_off["pass"] ** 2 + rb.se_def["pass"] ** 2)
                   + w_r ** 2 * (rb.se_off["rush"] ** 2 + rb.se_def["rush"] ** 2))
  # Likely rank range: simulate ratings within their uncertainty, take the 10th-90th percentile rank.
  rng = np.random.default_rng(cfg["team_model"]["seed"])
  sims = rng.normal(net.to_numpy(), se_net.reindex(net.index).to_numpy(), size=(4000, len(net)))
  sim_rank = (-sims).argsort(axis=1).argsort(axis=1) + 1
  lo = pd.Series(np.percentile(sim_rank, 10, axis=0), index=net.index).round().astype(int)
  hi = pd.Series(np.percentile(sim_rank, 90, axis=0), index=net.index).round().astype(int)
  prev_rank = hist[week - 1].rank(ascending=False) if (week - 1) in hist else None
  off = w_p * rb.off["pass"] + w_r * rb.off["rush"]
  dfn = -(w_p * rb.dfn["pass"] + w_r * rb.dfn["rush"])
  st = rb.off["st"] - rb.dfn["st"]
  rk = lambda s: s.rank(ascending=False, method="min").astype(int)
  ranks = {"net": rk(net), "off": rk(off), "def": rk(dfn), "st": rk(st),
           "off_pass": rk(rb.off["pass"]), "off_rush": rk(rb.off["rush"]),
           "def_pass": rk(-rb.dfn["pass"]), "def_rush": rk(-rb.dfn["rush"])}
  rec, sos_p, sos_f = schedule_strength(eng, season, week, net)
  sos_p_rk, sos_f_rk = rk(sos_p), rk(sos_f)
  rows = []
  for team in rb.teams:
    move = int(prev_rank[team] - ranks["net"][team]) if prev_rank is not None and team in prev_rank else 0
    rows.append({
      "team": team, "nick": ts.nick.get(team, ""), "logo": ts.logo_img(team, 26), "row_style": ts.row_style(team),
      "record": rec.get(team, ""), "rank": int(ranks["net"][team]), "move": move,
      "net": per100(net[team]), "range": f"{lo[team]}-{hi[team]}" if lo[team] != hi[team] else f"{lo[team]}",
      "off": per100(off[team]), "off_rk": int(ranks["off"][team]),
      "off_pass": per100(rb.off.at[team, "pass"]), "off_rush": per100(rb.off.at[team, "rush"]),
      "def": per100(dfn[team]), "def_rk": int(ranks["def"][team]),
      "def_pass": per100(-rb.dfn.at[team, "pass"]), "def_rush": per100(-rb.dfn.at[team, "rush"]),
      "st": per100(st[team]), "st_rk": int(ranks["st"][team]),
      "off_pass_rk": int(ranks["off_pass"][team]), "off_rush_rk": int(ranks["off_rush"][team]),
      "def_pass_rk": int(ranks["def_pass"][team]), "def_rush_rk": int(ranks["def_rush"][team]),
      "sos_past": per100(sos_p.get(team, np.nan)), "sos_past_rk": int(sos_p_rk.get(team, 0)),
      "sos_next": per100(sos_f.get(team, np.nan)), "sos_next_rk": int(sos_f_rk.get(team, 0)),
      "spark": sparkline(hist.loc[team].tolist(), width=84, height=22) if team in hist.index else "",
    })
  power = sorted(rows, key=lambda x: x["rank"])
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
      luck.append({"team": team, "row_style": ts.row_style(team), "logo": ts.logo_img(team), "off_raw": per100(ro), "off_gap": per100(faced_def[team]),
                   "off_adj": per100(ro - faced_def[team]), "def_raw": per100(-rd),
                   "def_gap": per100(-faced_off[team]), "def_adj": per100(-(rd - faced_off[team]))})
  for r in luck:
    r["total_gap"] = r["off_gap"] + r["def_gap"]
  luck.sort(key=lambda x: -x["total_gap"])
  return power, luck


def schedule_strength(eng, season: int, week: int, net: pd.Series):
  """Records, plus strength of schedule played and remaining: the average current net rating of opponents
  (positive = tougher than an average schedule)."""
  s = eng.data.schedules
  s = s[(s.season == season) & (s.game_type == "REG")]
  rows = []
  for g in s.itertuples():
    for team, opp, pts, opp_pts in ((g.home_team, g.away_team, g.home_score, g.away_score),
                                    (g.away_team, g.home_team, g.away_score, g.home_score)):
      rows.append({"team": team, "opp": opp, "week": g.week, "played": pd.notna(pts), "pf": pts, "pa": opp_pts})
  x = pd.DataFrame(rows)
  x["team"] = x.team.replace({"LAR": "LA"})
  x["opp"] = x.opp.replace({"LAR": "LA"})
  x["opp_net"] = x.opp.map(net)
  past = x[x.played & (x.week < week)]
  future = x[~x.played & (x.week >= week)]
  rec = {}
  for team, g in past.groupby("team"):
    w, l, t = int((g.pf > g.pa).sum()), int((g.pf < g.pa).sum()), int((g.pf == g.pa).sum())
    rec[team] = f"{w}-{l}" + (f"-{t}" if t else "")
  return rec, past.groupby("team").opp_net.mean(), future.groupby("team").opp_net.mean()


def net_rating(r) -> pd.Series:
  off = LEAGUE_PASS_SHARE * r.off["pass"] + (1 - LEAGUE_PASS_SHARE) * r.off["rush"]
  dfn = LEAGUE_PASS_SHARE * r.dfn["pass"] + (1 - LEAGUE_PASS_SHARE) * r.dfn["rush"]
  return off - dfn + (r.off["st"] - r.dfn["st"]) * 0.18  # ST plays are ~18% as frequent as scrimmage plays


def spread_text(fav: str, margin: float) -> str:
  """Betting notation: favorite minus points ('SEA -4.1'); 'PK' when within half a point."""
  if pd.isna(margin):
    return "n/a"
  return "PK" if abs(margin) < 0.5 else f"{fav} -{abs(margin):.1f}"


def kickoff_text(gameday, gametime) -> str:
  try:
    d = pd.Timestamp(gameday)
    t = pd.Timestamp(f"2000-01-01 {gametime}") if isinstance(gametime, str) and gametime else None
    return d.strftime("%a %b %-d") + (t.strftime(" · %-I:%M %p ET") if t is not None else "")
  except (ValueError, TypeError):
    try:  # Windows strftime has no %-d
      d = pd.Timestamp(gameday)
      t = pd.Timestamp(f"2000-01-01 {gametime}") if isinstance(gametime, str) and gametime else None
      return f"{d:%a %b} {d.day}" + (f" · {t.hour % 12 or 12}:{t:%M} {'PM' if t.hour >= 12 else 'AM'} ET"
                                     if t is not None else "")
    except (ValueError, TypeError):
      return str(gameday)


def diverging_bar(v: float, scale: float, width: int = 120) -> str:
  """Centered bar: right/green for positive, left/red for negative, clipped at +/-scale."""
  if v is None or pd.isna(v) or not scale:
    return ""
  frac = max(-1.0, min(1.0, v / scale)) * 0.5
  left = 50 if frac >= 0 else 50 + frac * 100
  cls = "pos" if v >= 0 else "neg"
  return (f'<span class="dbar" style="width:{width}px"><span class="dbar-mid"></span>'
          f'<span class="dbar-fill {cls}" style="left:{left:.1f}%;width:{abs(frac) * 100:.1f}%"></span></span>')


def matchups(eng, season: int, week: int, cfg: dict, proj: pd.DataFrame | None = None) -> list:
  """Per game: the headline lines (model vs Vegas, in betting notation), edges where they disagree, and
  where each side's offense has the advantage over the other's defense."""
  r = eng.game_ratings(season, week)
  vf = team_volume_features(eng.team_ledger, season, week, eng.cfg)
  games = eng.games(season, week)
  starters = {}
  if proj is not None:
    qbs = proj[(proj.pos == "QB") & ~proj.sits].sort_values("db").groupby("team").tail(1)
    starters = dict(zip(qbs.team, qbs.gsis_id))
  qb_name = dict(zip(proj.gsis_id, proj.full_name)) if proj is not None else {}
  tp = eng.gm.predict(games, r, vf, use_vegas=False, starters=starters)
  gl = game_lines(tp, games).merge(games[["game_id", "gametime"]], on="game_id", how="left")
  ts = TeamStyle(eng.data.teams)
  names = ({t.team_abbr: t.team_nick for t in eng.data.teams.itertuples()} if eng.data.teams is not None else {})
  out = []
  for _, g in gl.iterrows():
    def side(t):
      return {"team": t, "nick": names.get(t, t), "row_style": ts.row_style(t), "logo": ts.logo_img(t, 28),
              "qb": qb_name.get(starters.get(t), ""),
              "off_pass": per100(r.off.at[t, "pass"] + r.qb_term(starters.get(t))),
              "off_rush": per100(r.off.at[t, "rush"]), "def_pass": per100(-r.dfn.at[t, "pass"]),
              "def_rush": per100(-r.dfn.at[t, "rush"]), "st": per100(r.off.at[t, "st"] - r.dfn.at[t, "st"])}
    away, home = side(g.away_team), side(g.home_team)
    vm, vt = g.spread_line, g.total_line
    dm = g.model_margin - vm if pd.notna(vm) else np.nan
    dt = g.model_total - vt if pd.notna(vt) else np.nan
    m_fav = g.home_team if g.model_margin >= 0 else g.away_team
    v_fav = g.home_team if (pd.notna(vm) and vm >= 0) else g.away_team
    edges = []
    if pd.notna(dm) and abs(dm) >= 1.0:
      edges.append({"label": f"Spread lean {g.home_team if dm > 0 else g.away_team}", "value": f"{abs(dm):.1f}",
                    "strong": abs(dm) >= cfg["report"]["margin_disagree"]})
    if pd.notna(dt) and abs(dt) >= 1.5:
      edges.append({"label": "Lean " + ("Over" if dt > 0 else "Under"), "value": f"{abs(dt):.1f}",
                    "strong": abs(dt) >= cfg["report"]["total_disagree"]})
    facets = []
    for o, d in ((away, home), (home, away)):
      for unit, label in (("pass", "Pass"), ("rush", "Run")):
        edge = o[f"off_{unit}"] - d[f"def_{unit}"]
        facets.append({"label": f"{o['team']} {label} O vs {d['team']} {label} D", "edge": edge,
                       "bar": diverging_bar(edge, 12.0), "row_style": o["row_style"], "team": o["team"]})
    out.append({"away": away, "home": home, "kickoff": kickoff_text(g.gameday, g.gametime),
                "neutral": g.location == "Neutral", "model_line": spread_text(m_fav, g.model_margin),
                "model_total": g.model_total, "vegas_line": spread_text(v_fav, vm) if pd.notna(vm) else "n/a",
                "vegas_total": vt, "edges": edges, "facets": facets,
                "score": f"{g.away_team} {g.away_pts:.0f} - {g.home_team} {g.home_pts:.0f}"})
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
  ts = TeamStyle(eng.data.teams)
  return [{"name": x.full_name, "pos": x.pos, "team": x.team, "games": int(x.games), "raw": x.raw, "adj": x.adj,
           "row_style": ts.row_style(x.team), "logo": ts.logo_img(x.team),
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
  ts = TeamStyle(eng.data.teams)
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
                  "row_style": ts.row_style(last.team), "logo": ts.logo_img(last.team),
                  "snap_now": last.offense_pct, "snap_prev": prev_snap, "opp_now": last.opp_share,
                  "opp_prev": prev_opp, "touches": int(last.carries + last.tgt), "score": (ds or 0) + 2 * (do or 0),
                  "takeaway": role_takeaway(last.offense_pct or 0, last.opp_share or 0, int(last.carries + last.tgt))})
  out.sort(key=lambda x: -x["score"])
  return out[:30]


def role_takeaway(snap: float, opp: float, touches: int) -> str:
  """Waiver advice needs real usage, not just snaps."""
  used = touches >= 8 or opp >= 0.10
  if snap >= 0.7 and used:
    return "Full-time role with real touches: waiver add"
  if used:
    return "Growing workload: waiver add"
  return "Snaps up, touches not yet: watch"


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
  env.filters["dbar"] = lambda v, scale=10.0, width=120: diverging_bar(v, scale, width)
  env.filters["abs"] = lambda v: abs(v) if v is not None and not pd.isna(v) else 0
  env.filters["ord"] = lambda n: "" if not n else f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"
  env.filters["rkc"] = lambda n: "rk1" if n <= 8 else "rk2" if n <= 16 else "rk3" if n <= 24 else "rk4"
  env.filters["posb"] = pos_badge
  env.filters["pct"] = lambda x: "" if x is None or pd.isna(x) else f"{x:.0%}"
  html_out = env.get_template("report.html.j2").render(**ctx)
  out_path.parent.mkdir(parents=True, exist_ok=True)
  out_path.write_text(html_out, encoding="utf-8")
  return out_path
