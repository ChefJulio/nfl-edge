"""Build the weekly report context and render a single static, mobile-friendly HTML file."""
from __future__ import annotations

import html
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import elo
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


def roster_tiers(p: pd.DataFrame, tiers: dict) -> tuple[list, list]:
  """League-size tiers (QB1 = top `teams` QBs, QB2 = the next `teams`, ...) and the roster slot each player fills
  in a standard league: 'start' (within teams x starters at his position), 'flex' (among the best remaining
  flex-eligible players, teams x flex of them, by projection) or 'bench'."""
  n = int(tiers.get("teams", 10))
  starters = tiers.get("starters", {})
  label = [f"{pos}{(r - 1) // n + 1}" for pos, r in zip(p.pos, p.pos_rank)]
  start = p.pos_rank <= p.pos.map(lambda x: n * int(starters.get(x, 0)))
  pool = p[~start & p.pos.isin(tiers.get("flex_positions", ["RB", "WR", "TE"]))]
  flex = p.index.isin(pool.proj.nlargest(n * int(tiers.get("flex", 0))).index)
  slot = ["start" if s else "flex" if f else "bench" for s, f in zip(start, flex)]
  return label, slot


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
  if a.empty:  # week 1: nothing played yet this season
    return pd.DataFrame(columns=["games", "fpg", "fp_total", "last3", "weeks", "week_comps", "snap", "tgt_share",
                                 "carry_share"] + SCORE_KEYS)
  g = a.groupby("gsis_id")
  out = pd.DataFrame({
    "games": g.size(), "fpg": g.actual.mean(), "fp_total": g.actual.sum(),
    "last3": a.sort_values("week").groupby("gsis_id").tail(3).groupby("gsis_id").actual.mean(),
  })
  for c in ("pass_yd", "pass_td", "interception", "rush_yd", "rush_td", "reception", "rec_yd", "rec_td",
            "fumble_lost", "attempts", "completions", "carries", "targets"):
    out[c] = g[c].sum()
  out["weeks"] = g.apply(lambda x: list(zip(x.week.astype(int), x.actual.astype(float))), include_groups=False)
  # Per-week stat lines so the page can re-score past weeks under the viewer's scoring settings.
  out["week_comps"] = g.apply(lambda x: [[int(w)] + [round(float(v), 2) for v in row]
                                         for w, row in zip(x.week, x[SCORE_KEYS].to_numpy())], include_groups=False)
  L = eng.pm.ledger
  L = L[(L.season == season) & (L.week < week)]
  lg = L.groupby("gsis_id")
  out["snap"] = lg.offense_pct.mean()
  out["tgt_share"] = lg.tgt.sum() / lg.team_db.sum()
  out["carry_share"] = lg.carries.sum() / lg.team_rush.sum()
  return out


# Stat order shared with the page's scoring panel (rows carry their stat lines in this order).
SCORE_KEYS = ["pass_yd", "pass_td", "interception", "rush_yd", "rush_td", "reception", "rec_yd", "rec_td",
              "fumble_lost"]


def scoring_settings(scoring, cfg: dict) -> str:
  """Presets + league defaults for the page's scoring panel (JSON). The site is built with `scoring` (default
  half PPR, scoring.toml); the panel re-scores the projected and past stat lines in the browser."""
  half = {"pass_yd": 0.04, "pass_td": 4, "interception": -2, "rush_yd": 0.1, "rush_td": 6, "reception": 0.5,
          "rec_yd": 0.1, "rec_td": 6, "fumble_lost": -2, "te_bonus": 0.0}
  presets = {"Half PPR": half, "PPR": {**half, "reception": 1.0}, "Standard": {**half, "reception": 0.0},
             "6-pt pass TD": {**half, "pass_td": 6}, "TE premium": {**half, "te_bonus": 0.5}}
  built = {**{k: float(v) for k, v in scoring.weights.items()}, "te_bonus": float(scoring.te_reception_bonus)}
  t = cfg["tiers"]
  return json.dumps({"keys": SCORE_KEYS, "presets": presets, "built": built,
                     "league": {"teams": int(t["teams"]), "starters": t["starters"], "flex": int(t["flex"]),
                                "superflex": 0}}, separators=(",", ":"))


def week_actuals(eng, season: int, week: int) -> dict:
  """Actual fantasy points + stat line for this week, for players whose game is final (blank until then)."""
  s = eng.data.schedules
  g = s[(s.season == season) & (s.week == week) & (s.game_type == "REG") & s.home_score.notna()]
  final_teams = set(g.home_team) | set(g.away_team)
  a = eng.actual[(eng.actual.season == season) & (eng.actual.week == week)]
  team_col = "team" if "team" in a else "recent_team"
  a = a[a[team_col].isin(final_teams)] if team_col in a else a
  return {r.gsis_id: {"pts": float(r.actual), "c": [round(float(getattr(r, k, 0) or 0), 2) for k in SCORE_KEYS]}
          for r in a.itertuples()}


def score_data(r, st, act: dict | None = None) -> str:
  """Compact JSON for client-side re-scoring: projected stat line (pj), season totals (ss) and games (g), and
  per-week stat lines (wk). The page re-scores with the viewer's settings; see the scoring panel script."""
  pj = [round(float(getattr(r, k, 0.0) or 0.0), 3) for k in SCORE_KEYS]
  out = {"pj": pj}
  if act:
    out["ac"] = act["c"]
  if st:
    out["ss"] = [round(float(st.get(k, 0.0) or 0.0), 2) for k in SCORE_KEYS]
    out["g"] = int(st.get("games", 0) or 0)
    out["wk"] = st.get("week_comps") or []
  return json.dumps(out, separators=(",", ":"))


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


def _num(r, col: str, nd: int = 2) -> float | None:
  v = getattr(r, col, None)
  return None if v is None or pd.isna(v) else round(float(v), nd)


def espn_ids(rosters: pd.DataFrame | None, season: int) -> dict:
  """gsis_id -> ESPN athlete id (nflverse rosters carry both), so live ESPN box scores map onto our players."""
  if rosters is None or "espn_id" not in rosters:
    return {}
  r = rosters[(rosters.season <= season) & rosters.espn_id.notna() & rosters.gsis_id.notna()]
  r = r.sort_values("season").drop_duplicates("gsis_id", keep="last")
  return {g: str(e).split(".")[0] for g, e in zip(r.gsis_id, r.espn_id)}


# ESPN team codes that differ from nflverse's (everything else matches).
ESPN_TEAM = {"LA": "LAR", "WAS": "WSH"}


def week_data(ctx: dict) -> str:
  """The week's numbers as JSON, written next to the page (<page>.json). The game page and the player card read
  it: projections and stat lines, pregame chances and battle bars, team colors and logos."""
  players = {}
  for pos, block in ctx["players"].items():
    for r in block["rows"]:
      players[r["pid"]] = {
        "name": r["name"], "pos": r["pos"], "team": r["team"], "opp": r["opp"], "home": r["home"], "espn": r["espn"],
        "proj": round(float(r["proj"]), 2), "q": [round(float(r[k]), 2) for k in ("p10", "p25", "p50", "p75", "p90")],
        "rank": r["rank"],
        "tier": r["tier"], "slot": r["slot"], "ecr": None if pd.isna(r["ecr"]) else r["ecr"],
        "status": r["status"] or "", "inactive": r["inactive"], "inactive_why": r["inactive_why"],
        "boost": r["boost"], "boost_from": r["boost_from"], "low_sample": r["low_sample"], "conf": r["conf"],
        "dvp": r["dvp"], "dvp_color": r["dvp_color"], "grade": r["grade"], "mpts": r["mpts"],
        "takeaway": r["takeaway"], "fpg": None if pd.isna(r["fpg"]) else r["fpg"],
        "last3": None if pd.isna(r["last3"]) else r["last3"], "act": r["act"], "sc": json.loads(r["sc"]),
        "ext": r["ext"], "sched": r["sched"] or "",
        "proj_line": {k: v for k, v in r["proj_line"].items() if v}}
  games = []
  for g in ctx["games"]:
    games.append({k: g[k] for k in ("id", "away", "home", "kickoff", "neutral", "fc", "vegas_line", "vegas_total",
                                    "battles", "extras", "plays", "power_rk", "final", "bt_style", "colors",
                                    "gameday", "gametime")})
  out = {"season": ctx["season"], "week": ctx["week"], "generated": ctx["generated"], "archive": ctx["archive"],
         "lookahead": ctx["lookahead"], "tossup_pct": ctx["tossup_pct"], "espn_team": ESPN_TEAM,
         "score": json.loads(ctx["score_cfg"]), "players": players, "games": games}
  return json.dumps(out, separators=(",", ":"), default=lambda o: float(o) if isinstance(o, (np.floating, np.integer))
                    else bool(o) if isinstance(o, np.bool_) else None)


def player_rankings(eng, p: pd.DataFrame, season: int, week: int, cfg: dict) -> dict:
  ts = TeamStyle(eng.data.teams)
  p = p.copy()
  # Everyone with a real role, plus every team's QB1 (so all playing teams have a quarterback listed).
  qb1 = p[p.pos == "QB"].sort_values("db", ascending=False).groupby("team").head(1).index
  # Rows worth listing: 2+ projected points (deep reserves add page weight, not information), plus every team's QB1.
  p = p[(p.proj >= 2.0) | p.index.isin(qb1)].copy()
  p["pos_rank"] = p.groupby("pos").proj.rank(ascending=False, method="first").astype(int)
  p["tier"], p["slot"] = roster_tiers(p, cfg["tiers"])
  # Matchup = the opponent's defense-vs-position rank (1st toughest .. 32nd easiest); grade and meter follow it,
  # so the meter, the rank and the takeaway always tell the same story.
  dvp = defense_vs_position(eng, p, season, week)
  p["dvp_rank"] = [int(dvp[pos][o]) if pos in dvp and o in dvp[pos] else 16 for pos, o in zip(p.pos, p.opp)]
  p["grade"] = pd.cut(p.dvp_rank, [0, 6, 12, 19, 26, 32], labels=["F", "D", "C", "B", "A"]).astype(str)
  p["takeaway"] = [takeaway(r) for _, r in p.iterrows()]
  stats = season_stats(eng, season, week)
  luck = player_luck(eng, p, season, week)
  acts = week_actuals(eng, season, week)
  n_weeks = week - 1
  # Until Friday's expert rankings are out, show last week's rank (display only; never fed to the model).
  e = eng.data.ecr
  prev_ecr = (e[(e.season == season) & (e.week == week - 1)].set_index("gsis_id").ecr
              if e is not None else pd.Series(dtype=float))
  prev_ecr = prev_ecr[~prev_ecr.index.duplicated()]
  espn = espn_ids(eng.data.rosters, season)
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
        "grade": r.grade, "mpts": r.matchup_pts, "tier": r.tier, "slot": r.slot, "takeaway": r.takeaway, "conf": r.confidence,
        "status": r.status, "avail": r.avail, "inactive": 1 - r.avail,
        "inactive_why": inactive_why(r), "boost": r.injury_boost, "boost_from": r.boost_from or "",
        "low_sample": bool(r.low_sample), "line": expected_line(r),
        "fpg": st["fpg"] if st else np.nan, "last3": st["last3"] if st else np.nan,
        "season": season_line(r, st), "usage": usage_line(r, st),
        "bars": week_bars(st["weeks"] if st else [], n_weeks),
        "sc": score_data(r, st, acts.get(r.gsis_id)), "pos": r.pos,
        "act": acts[r.gsis_id]["pts"] if r.gsis_id in acts else None,
        "sched": schedule_note(luck.loc[r.gsis_id] if r.gsis_id in luck.index else None),
        # identity for the player card, live stats (ESPN box scores) and the game page
        "pid": r.gsis_id, "espn": espn.get(r.gsis_id, ""), "team": r.team,
        "ext": ({k: (None if pd.isna(st.get(k)) else round(float(st.get(k)), 3))
                 for k in ("games", "targets", "carries", "attempts", "completions", "snap", "tgt_share", "carry_share")}
                if st else {}),
        "proj_line": {"tgt": _num(r, "tgt"), "car": _num(r, "carries"), "att": _num(r, "attempts"),
                      "rec": _num(r, "reception"), "pass_yd": _num(r, "pass_yd"), "rush_yd": _num(r, "rush_yd"),
                      "rec_yd": _num(r, "rec_yd"), "pass_td": _num(r, "pass_td"), "rush_td": _num(r, "rush_td"),
                      "rec_td": _num(r, "rec_td"), "int": _num(r, "interception")},
      })
    out[pos] = {"rows": rows, "byes": bye_rows(eng, stats, ts, pos, season, week)}
  # FLEX (RB / WR / TE in one list) is assembled in the browser from those three lists, so rows aren't sent twice.
  out["FLEX"] = {"rows": [], "byes": []}
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
           "logo": ts.logo_img(x.team, 16), "pos": pos,
           "sc": json.dumps({"ss": [round(float(getattr(x, k, 0) or 0), 2) for k in SCORE_KEYS],
                             "g": int(x.games)}, separators=(",", ":"))}
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


def league_volume(eng, season: int, week: int, r) -> dict:
  """Average plays per team-game this season: dropbacks, designed runs (all situations), special-teams plays."""
  tl = eng.team_ledger
  cur = tl[(tl.season == season) & (tl.week < week)]
  if cur.empty:
    cur = tl[tl.season == season - 1]
  return {"pass": float(cur.dropbacks.mean()), "rush": float(cur.rushes.mean()),
          "st": float(r.plays_pg.get("st", 11.0))}


def starters_asof(eng, season: int, week: int) -> dict:
  """Each team's most recent starting QB before (season, week)."""
  tl = eng.team_ledger
  past = tl[((tl.season == season) & (tl.week < week)) | (tl.season < season)].sort_values(["season", "week"])
  return past.dropna(subset=["qb"]).groupby("team").qb.last().to_dict()


def formula_weights(eng) -> dict:
  """The game model's fitted points formula, as unit multipliers on EPA per game: offense and defense count
  b points per EPA; a special-teams EPA edge counts 2c on the margin (c adds to your score, c comes off the
  opponent's). Power uses these so its Net is the model's own margin vs an average team, matching Matchups."""
  pc = dict(zip(eng.gm.points.cols, eng.gm.points.coef[1:]))
  return {"play": float(pc["off_epa_game"]), "st": 2.0 * float(pc["st_net"])}


def unit_points(r, vol: dict, starters: dict, w: dict) -> pd.DataFrame:
  """Model margin per game vs an average opponent on a neutral field, per unit, at league-average volume (so
  units add up): EPA per game x the game model's points-formula weights (formula_weights). Pass O includes the
  starting QB's effect; defense signs flipped so positive is always good."""
  qb = pd.Series({t: r.qb_term(starters.get(t)) for t in r.teams})
  u = pd.DataFrame(index=r.teams)
  u["pass_o"] = (r.off["pass"] + qb) * vol["pass"] * w["play"]
  u["rush_o"] = r.off["rush"] * vol["rush"] * w["play"]
  u["pass_d"] = -r.dfn["pass"] * vol["pass"] * w["play"]
  u["rush_d"] = -r.dfn["rush"] * vol["rush"] * w["play"]
  u["st"] = (r.off["st"] - r.dfn["st"]) * vol["st"] * w["st"]
  u["off"] = u.pass_o + u.rush_o
  u["def"] = u.pass_d + u.rush_d
  u["net"] = u["off"] + u["def"] + u["st"]
  return u


def schedule_faced(eng, season: int, week: int, r, starters: dict) -> pd.DataFrame:
  """Strength of schedule in points per game, unit by unit and weighted by the plays actually involved.
  Played: every offensive play is charged with the opposing unit it faced (dropbacks vs that pass defense,
  runs vs that run defense) and every defensive play with the opposing offense (incl. its passer); summed and
  divided by games. Remaining: each future opponent's units at the team's own average volume.
  Positive = tougher than average (points the opponents took away / would take away)."""
  P, R = eng.tm.plays["pass"], eng.tm.plays["rush"]
  P = P[(P.season == season) & (P.week < week)]
  R = R[(R.season == season) & (R.week < week)]
  tl = eng.team_ledger
  cur = tl[(tl.season == season) & (tl.week < week)]
  games = cur.groupby("team").size()
  off_faced = -(P.defteam.map(r.dfn["pass"]).groupby(P.posteam).sum()
                + R.defteam.map(r.dfn["rush"]).groupby(R.posteam).sum())
  qbt = P.qb.map(lambda q: r.qb_term(q)).astype(float)  # float even when no games are played yet (week 1)
  def_faced = ((P.posteam.map(r.off["pass"]) + qbt).groupby(P.defteam).sum()
               + R.posteam.map(r.off["rush"]).groupby(R.defteam).sum())
  out = pd.DataFrame({"off_past": off_faced / games, "def_past": def_faced / games})
  # remaining schedule at each team's own average volume
  db_pg, ru_pg = cur.groupby("team").dropbacks.mean(), cur.groupby("team").rushes.mean()
  s = eng.data.schedules
  fut = s[(s.season == season) & (s.game_type == "REG") & s.home_score.isna() & (s.week >= week)]
  rows = []
  for g in fut.itertuples():
    for t, o in ((g.home_team, g.away_team), (g.away_team, g.home_team)):
      t, o = t.replace("LAR", "LA") if t == "LAR" else t, o.replace("LAR", "LA") if o == "LAR" else o
      if t not in r.teams or o not in r.teams:
        continue
      rows.append({"team": t,
                   "off_next": -(r.dfn.at[o, "pass"] * db_pg.get(t, np.nan) + r.dfn.at[o, "rush"] * ru_pg.get(t, np.nan)),
                   "def_next": ((r.off.at[o, "pass"] + r.qb_term(starters.get(o))) * db_pg.get(o, np.nan)
                                + r.off.at[o, "rush"] * ru_pg.get(o, np.nan))})
  if rows:
    out = out.join(pd.DataFrame(rows).groupby("team")[["off_next", "def_next"]].mean(), how="outer")
  out["past"] = out.off_past + out.def_past
  out["next"] = out.get("off_next", np.nan) + out.get("def_next", np.nan)
  # raw offense / defense EPA per game this season (for the luck tab's raw vs adjusted)
  out["raw_off"] = (P.groupby("posteam").epa.sum() + R.groupby("posteam").epa.sum()) / games
  out["raw_def"] = -(P.groupby("defteam").epa.sum() + R.groupby("defteam").epa.sum()) / games
  return out


def records(eng, season: int, week: int) -> dict:
  s = eng.data.schedules
  s = s[(s.season == season) & (s.game_type == "REG") & s.home_score.notna() & (s.week < week)]
  rec = {}
  for g in s.itertuples():
    for t, pf, pa in ((g.home_team, g.home_score, g.away_score), (g.away_team, g.away_score, g.home_score)):
      w, l, tie = rec.get(t, (0, 0, 0))
      rec[t] = (w + (pf > pa), l + (pf < pa), tie + (pf == pa))
  return {t.replace("LAR", "LA") if t == "LAR" else t: f"{w}-{l}" + (f"-{tie}" if tie else "")
          for t, (w, l, tie) in rec.items()}


def team_tables(eng, season: int, week: int, cfg: dict, proj: pd.DataFrame | None = None) -> tuple[list, list]:
  rb = eng.tm.fit(season, week, bootstrap=cfg["team_model"]["bootstrap_samples"])
  vol = league_volume(eng, season, week, rb)
  starters = starters_asof(eng, season, week)
  if proj is not None:  # this week's projected starters (injury-aware) override
    qbs = proj[(proj.pos == "QB") & ~proj.sits].sort_values("db").groupby("team").tail(1)
    starters.update(dict(zip(qbs.team, qbs.gsis_id)))
  fw = formula_weights(eng)
  u = unit_points(rb, vol, starters, fw)
  history = {}
  for w in range(2, week + 1):
    rw = eng.tm.fit(season, w)
    history[w] = unit_points(rw, league_volume(eng, season, w, rw), starters_asof(eng, season, w), fw).net
  hist = pd.DataFrame(history)
  ts = TeamStyle(eng.data.teams)
  # Rank range: resample each unit within its bootstrap uncertainty (in points per game), rank the nets.
  qb = pd.Series({t: rb.qb_term(starters.get(t)) for t in rb.teams})
  se_net = fw["play"] * np.sqrt((vol["pass"] ** 2) * (rb.se_off["pass"] ** 2 + rb.se_def["pass"] ** 2)
                                + (vol["rush"] ** 2) * (rb.se_off["rush"] ** 2 + rb.se_def["rush"] ** 2))
  rng = np.random.default_rng(cfg["team_model"]["seed"])
  sims = rng.normal(u.net.to_numpy(), se_net.reindex(u.index).to_numpy(), size=(4000, len(u)))
  sim_rank = (-sims).argsort(axis=1).argsort(axis=1) + 1
  lo = pd.Series(np.percentile(sim_rank, 10, axis=0), index=u.index).round().astype(int)
  hi = pd.Series(np.percentile(sim_rank, 90, axis=0), index=u.index).round().astype(int)
  prev_rank = hist[week - 1].rank(ascending=False) if (week - 1) in hist else None
  rk = lambda s: s.rank(ascending=False, method="min").astype(int)
  ranks = {c: rk(u[c]) for c in u.columns}
  sos = schedule_faced(eng, season, week, rb, starters)
  for c in ("off_past", "def_past", "off_next", "def_next", "past", "next"):  # same points scale as the units
    if c in sos:
      sos[c] = sos[c] * fw["play"]
  sos_rk = {c: rk(sos[c].dropna()) for c in ("past", "next")}
  rec = records(eng, season, week)
  rows = []
  for team in rb.teams:
    move = int(prev_rank[team] - ranks["net"][team]) if prev_rank is not None and team in prev_rank else 0
    sp = sos.loc[team] if team in sos.index else pd.Series(dtype=float)
    rows.append({
      "team": team, "nick": ts.nick.get(team, ""), "logo": ts.logo_img(team, 26), "row_style": ts.row_style(team),
      "record": rec.get(team, ""), "rank": int(ranks["net"][team]), "move": move,
      "range": f"{lo[team]}-{hi[team]}" if lo[team] != hi[team] else f"{lo[team]}",
      **{c: float(u.at[team, c]) for c in u.columns},
      **{f"{c}_rk": int(ranks[c][team]) for c in u.columns},
      "pass_o_pp": per100(rb.off.at[team, "pass"] + qb[team]), "rush_o_pp": per100(rb.off.at[team, "rush"]),
      "pass_d_pp": per100(-rb.dfn.at[team, "pass"]), "rush_d_pp": per100(-rb.dfn.at[team, "rush"]),
      "sos_past": float(sp.get("past", np.nan)), "sos_past_rk": int(sos_rk["past"].get(team, 0)),
      "sos_next": float(sp.get("next", np.nan)), "sos_next_rk": int(sos_rk["next"].get(team, 0)),
      "sos_past_o": float(sp.get("off_past", np.nan)), "sos_past_d": float(sp.get("def_past", np.nan)),
      "sos_next_o": float(sp.get("off_next", np.nan)), "sos_next_d": float(sp.get("def_next", np.nan)),
      "spark": sparkline(hist.loc[team].tolist(), width=84, height=22) if team in hist.index else "",
    })
  return sorted(rows, key=lambda x: x["rank"])


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


UNIT_NAME = {"pass": "Pass", "rush": "Run"}


def tug(label: str, away_edge: float, scale: float, away_rk, home_rk, away_what: str, home_what: str,
        title: str, impact: float | None = None) -> dict:
  """One tug-of-war bar: away team on the left, home on the right. away_edge = the number shown, in the away
  team's favor, on the winner's side ('even' under 0.5). The split moves past the middle toward the loser by
  impact / scale (impact defaults to away_edge), clipped at 90% of the bar."""
  return {"label": label, "edge": away_edge, "pts": abs(away_edge),
          "split": 50 + 50 * max(-0.9, min(0.9, (away_edge if impact is None else impact) / scale)),
          "side": "even" if abs(away_edge) < 0.5 else "away" if away_edge > 0 else "home",
          "away_rk": away_rk, "home_rk": home_rk, "away_what": away_what, "home_what": home_what, "title": title}


def _rgb_dist(a: str, b: str) -> float:
  ra, rb = ([int(c.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)] for c in (a, b))
  return sum((x - y) ** 2 for x, y in zip(ra, rb)) ** 0.5


def battle_colors(ts: "TeamStyle", away: str, home: str) -> dict:
  """One bar color per team for a game, visible on the dark card and distinct from each other: the primary
  colors, falling back to a secondary when the two teams' primaries look alike (e.g. two navy teams)."""
  ap, asec = (ts.visible(c) for c in ts.c.get(away, ("#666666", "#999999")))
  hp, hsec = (ts.visible(c) for c in ts.c.get(home, ("#666666", "#999999")))
  for a, h in ((ap, hp), (ap, hsec), (asec, hp), (asec, hsec)):
    if _rgb_dist(a, h) >= 110:
      return {away: a, home: h}
  return {away: ap, home: "#9aa3b2"}


def logistic(x):
  return 1 / (1 + np.exp(-x))


def fit_win_k(margin: np.ndarray, won: np.ndarray) -> float:
  """Maximum-likelihood k in P(home wins) = logistic(k x margin) (no intercept: a margin of 0 is 50%)."""
  ks = np.linspace(0.02, 0.4, 381)
  p = logistic(np.outer(ks, margin)).clip(1e-9, 1 - 1e-9)
  return float(ks[int(np.argmax((won * np.log(p) + (1 - won) * np.log(1 - p)).sum(axis=1)))])


def _decided(schedules: pd.DataFrame, season: int, week: int) -> pd.DataFrame:
  """Games finished before this week that had a closing line and a winner."""
  s = schedules[schedules.home_score.notna() & schedules.spread_line.notna()
                & (schedules.home_score != schedules.away_score)]
  return s[(s.season < season) | ((s.season == season) & (s.week < week))]


def vegas_win_k(schedules: pd.DataFrame, season: int, week: int) -> float:
  s = _decided(schedules, season, week)
  return fit_win_k(s.spread_line.to_numpy(float), (s.home_score > s.away_score).to_numpy(float))


def track_record(schedules: pd.DataFrame, season: int, week: int, tossup: float) -> dict:
  """How often the market's favorites won, by how confident it was. Each season's chances use a k fit only on
  the seasons before it (the first loaded season only trains), so every row is an honest out-of-sample record."""
  s = _decided(schedules, season, week)
  yrs = sorted(s.season.unique())
  parts = []
  for yr in yrs[1:]:
    tr, te = s[s.season < yr], s[s.season == yr]
    p = logistic(fit_win_k(tr.spread_line.to_numpy(float), (tr.home_score > tr.away_score).to_numpy(float))
                 * te.spread_line.to_numpy(float))
    home_won = (te.home_score > te.away_score).to_numpy()
    parts.append(pd.DataFrame({"season": yr, "fav": np.maximum(p, 1 - p), "won": np.where(p >= .5, home_won, ~home_won)}))
  if not parts:
    return {}
  t = pd.concat(parts)
  t["pct"] = (t.fav * 100).round()
  cut = round(tossup * 100)
  rows = []
  for lo, hi, label in ((50, cut, f"Tossup (under {cut}%)"), (cut, 65, f"{cut}-64%"), (65, 75, "65-74%"),
                        (75, 101, "75% or more")):
    b = t[(t.pct >= lo) & (t.pct < hi)]
    now = b[b.season == season]
    rows.append({"label": label, "tossup": lo == 50, "n": len(b), "expected": b.fav.mean() * 100,
                 "actual": b.won.mean() * 100, "n_now": len(now),
                 "actual_now": now.won.mean() * 100 if len(now) else None})
  return {"since": int(yrs[1]), "rows": rows, "n": len(t), "season": season}


def forecast(g, p_model: float, k_vegas: float, tossup: float, names: dict, ts: "TeamStyle") -> dict:
  """The game's win chances: the market's when a Vegas line exists (it has been the more accurate forecast, and
  blending the model in never helped), else the model's. Under the tossup line we name no favorite."""
  vm = g.spread_line
  p = float(logistic(k_vegas * vm)) if pd.notna(vm) else p_model  # P(home wins)
  fav = g.home_team if p >= .5 else g.away_team
  pct = round(max(p, 1 - p) * 100)
  m_fav = g.home_team if p_model >= .5 else g.away_team
  m_pct = round(max(p_model, 1 - p_model) * 100)
  return {"src": "Vegas" if pd.notna(vm) else "Model", "fav": fav, "nick": names.get(fav, fav),
          "logo": ts.logo_img(fav, 24), "pct": pct, "tossup": pct < round(tossup * 100),
          "p_away": round((1 - p) * 100), "p_home": round(p * 100),
          "model_fav": m_fav, "model_nick": names.get(m_fav, m_fav), "model_pct": m_pct, "model_tossup": m_pct < round(tossup * 100)}


def final_result(games: pd.DataFrame, g, fc: dict) -> dict | None:
  """Final score once the game is over, and how the forecast fared: a favorite winning or an upset (a 65%
  favorite should lose about 1 time in 3), or, for a tossup, simply who won."""
  row = games[games.game_id == g.game_id]
  if row.empty or pd.isna(row.home_score.iloc[0]):
    return None
  hs, as_ = int(row.home_score.iloc[0]), int(row.away_score.iloc[0])
  winner = g.home_team if hs > as_ else g.away_team if as_ > hs else None
  return {"home": hs, "away": as_, "winner": winner,
          "fav_won": None if fc["tossup"] or winner is None else fc["fav"] == winner}


def matchups(eng, season: int, week: int, cfg: dict, proj: pd.DataFrame | None = None,
             power: list | None = None) -> list:
  """Per game: the win chances (the market's when a line exists, the model's as a second opinion; close games are
  tossups), and where each side's offense has the advantage over the other's defense."""
  r = eng.game_ratings(season, week)
  tossup, wm = cfg["report"]["tossup_below"], cfg["report"]["win_model"]
  k_vegas = vegas_win_k(eng.data.schedules, season, week)
  elo_now = elo.ratings_before(eng.data.schedules, season, week, wm)
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
  # League ranks per unit, taken from the Power tab so both tabs always agree.
  rk = {p["team"]: p for p in power or []}
  unit_rk = {("pass", "off"): "pass_o_rk", ("rush", "off"): "rush_o_rk", ("pass", "def"): "pass_d_rk",
             ("rush", "def"): "rush_d_rk"}

  def rank_of(team, key):
    return int(rk[team][key]) if team in rk else None

  # The points formula: points = a + b x (dropbacks x E[pass EPA] + rushes x E[rush EPA]) + c x special-teams net,
  # E[EPA] = league average + offense + defense (+ QB) + home field. It sets each battle bar's length (below).
  pc = dict(zip(eng.gm.points.cols, eng.gm.points.coef[1:]))
  b, c_st = float(pc["off_epa_game"]), float(pc["st_net"])
  # One bar scale for every row of every game: a full bar (90%) is the 95th percentile of offense-vs-defense impact
  # over every possible pairing of this week's ratings at league-average play counts.
  pp = r.plays_pg
  o_imp = {t: pp.get("pass", 34.0) * (r.off.at[t, "pass"] + r.qb_term(starters.get(t)))
           + pp.get("rush", 25.0) * r.off.at[t, "rush"] for t in r.off.index}
  d_imp = {t: pp.get("pass", 34.0) * r.dfn.at[t, "pass"] + pp.get("rush", 25.0) * r.dfn.at[t, "rush"]
           for t in r.dfn.index}
  pair = [abs(b * (o_imp[o] + d_imp[d])) for o in o_imp for d in d_imp if o != d]
  bar_scale = float(np.percentile(pair, 95)) / 0.9 if pair else 8.0  # tug() clips at 0.9 x scale

  out = []
  for _, g in gl.iterrows():
    def side(t):
      return {"team": t, "nick": names.get(t, t), "row_style": ts.row_style(t), "logo": ts.logo_img(t, 28),
              "logo_sm": ts.logo_img(t, 16), "logo_url": ts.logo.get(t) or "", "logo_bg": ts.logo_bg(t),
              "qb": qb_name.get(starters.get(t), ""),
              "off_pass": per100(r.off.at[t, "pass"] + r.qb_term(starters.get(t))),
              "off_rush": per100(r.off.at[t, "rush"]), "def_pass": per100(-r.dfn.at[t, "pass"]),
              "def_rush": per100(-r.dfn.at[t, "rush"]), "st": per100(r.off.at[t, "st"] - r.dfn.at[t, "st"])}
    away, home = side(g.away_team), side(g.home_team)
    vm, vt = g.spread_line, g.total_line
    v_fav = g.home_team if (pd.notna(vm) and vm >= 0) else g.away_team
    # Our model's win chance: power-rank gap + Elo + home field (fit by tools/elo_eval.py; beat the model margin
    # alone walk-forward). The margin itself is never published.
    rk_a, rk_h = rank_of(g.away_team, "rank"), rank_of(g.home_team, "rank")
    e_a, e_h = elo_now.get(g.away_team, elo.MEAN), elo_now.get(g.home_team, elo.MEAN)
    x = (wm["home"] * (g.location != "Neutral") + wm["elo_per_100"] * (e_h - e_a) / 100
         + (wm["rank_gap"] * (rk_a - rk_h) if rk_a and rk_h else 0.0))
    fc = forecast(g, float(logistic(x)), k_vegas, tossup, names, ts)
    fc["model_why"] = (f"Our model: power rank {g.away_team} {rk_a} vs {g.home_team} {rk_h}, Elo {e_a:.0f} vs "
                       f"{e_h:.0f}{'' if g.location == 'Neutral' else ', plus home field'}")
    # Who wins each battle. Every bar is a tug of war, away team on the left and home team on the right. The
    # model margin = both offense-vs-defense matchups + special teams + home field + play volume (never shown).
    vol_of = tp[tp.game_id == g.game_id].set_index("team")
    col = battle_colors(ts, g.away_team, g.home_team)
    a_t, h_t = g.away_team, g.home_team
    # Numbers are EPA per 100 plays (efficiency edges, never the model's points: the model publishes only win
    # chances). Bar LENGTH is the edge's impact on this game through the fitted points formula (per-play edge x
    # projected plays x points per EPA), on one scale for every row, so a special-teams edge over ~11 plays reads
    # smaller than an offense edge of the same size over ~60. The impacts also check the parts against the margin.
    battles, off_pts = [], 0.0
    for o, d in ((away, home), (home, away)):
      a_role, h_role = ("off", "def") if o is away else ("def", "off")
      sign = 1 if o is away else -1  # offense edge -> away team's edge
      rows, pts_sum, plays_sum = [], 0.0, 0.0
      for unit, label, vcol in (("pass", "Passing", "dropbacks_hat"), ("rush", "Running", "rushes_hat")):
        edge100 = o[f"off_{unit}"] - d[f"def_{unit}"]
        plays = float(vol_of.at[o["team"], vcol])
        pts = b * edge100 / 100 * plays
        pts_sum += pts
        plays_sum += plays
        rows.append(tug(label, sign * edge100, bar_scale,
                        rank_of(a_t, unit_rk[(unit, a_role)]), rank_of(h_t, unit_rk[(unit, h_role)]),
                        f"{a_t} {UNIT_NAME[unit]} {a_role[0].upper()}", f"{h_t} {UNIT_NAME[unit]} {h_role[0].upper()}",
                        f"{o['team']} {label.lower()} offense {o[f'off_{unit}']:+.1f} vs {d['team']} {label.lower()} "
                        f"defense {d[f'def_{unit}']:+.1f} EPA per 100 plays (vs league average): a {edge100:+.1f} "
                        f"edge for the offense on about {plays:.0f} projected {'dropbacks' if unit == 'pass' else 'runs'}",
                        impact=sign * pts))
      off_pts += sign * pts_sum
      total100 = pts_sum / (b * plays_sum) * 100  # the pass and run edges weighted by projected plays
      head = tug(f"{o['team']} offense", sign * total100, bar_scale, rank_of(a_t, f"{a_role}_rk"),
                 rank_of(h_t, f"{h_role}_rk"),
                 f"{a_t} {'offense' if a_role == 'off' else 'defense'}",
                 f"{h_t} {'offense' if h_role == 'off' else 'defense'}",
                 f"{o['team']} offense vs {d['team']} defense: {total100:+.1f} EPA per 100 plays for the offense, "
                 f"the passing and running edges weighted by its projected dropbacks and runs",
                 impact=sign * pts_sum)
      head["left"] = f"{a_t} {'offense' if a_role == 'off' else 'defense'}"
      head["right"] = f"{h_t} {'offense' if h_role == 'off' else 'defense'}"
      battles.append({"head": head, "rows": rows})
    # The rest of the margin, in the away team's favor (positive) or the home team's (negative).
    va, vh = vol_of.loc[a_t], vol_of.loc[h_t]
    st = c_st * (float(va.st_net) - float(vh.st_net))

    def base_pts(v):  # league-average EPA on this team's projected play mix
      return b * (v.dropbacks_hat * r.intercept["pass"] + v.rushes_hat * r.intercept["rush"])

    def home_pts(v):  # home-field EPA on this team's plays (+ for the home team, - for the visitor)
      return b * v.home * sum(v[col_] * (r.home[u] + r.home_div.get(u, 0.0) * v["div"])
                              for u, col_ in (("pass", "dropbacks_hat"), ("rush", "rushes_hat")))
    volume = float(base_pts(va) - base_pts(vh))
    hfa_scrim = float(home_pts(va) - home_pts(vh))
    scrim_plays = float(va.dropbacks_hat + va.rushes_hat + vh.dropbacks_hat + vh.rushes_hat)
    # Special teams per 100 special-teams plays = the Power tab's ST difference; its weight in the points formula
    # (field position from returns and coverage) is documented on the Model tab, not printed per game.
    st100 = away["st"] - home["st"]
    n_st = float(r.plays_pg.get("st", 11.0))
    st_row = tug("Special teams", st100, bar_scale, rank_of(a_t, "st_rk"), rank_of(h_t, "st_rk"),
                 f"{a_t} special teams", f"{h_t} special teams",
                 f"Special teams {a_t} {away['st']:+.1f} vs {h_t} {home['st']:+.1f} EPA per 100 special-teams plays "
                 f"(about {n_st:.0f} per team per game)", impact=2 * c_st * n_st * st100 / 100)
    home100 = hfa_scrim / (b * scrim_plays) * 100 if scrim_plays else 0.0  # per-play home edge across both offenses
    home_row = tug("Home field", home100, bar_scale, None, None, "", "",
                   "Neutral site: no home field" if g.location == "Neutral" else
                   f"Home field: {abs(home100):+.1f} EPA per 100 plays for {h_t if home100 < 0 else a_t}, "
                   f"averaged over both teams' plays (fitted from every game in the training window)",
                   impact=hfa_scrim)
    # Pace has no per-play (EPA) form, so it is shown as projected plays and pass rate instead of a bar.
    plays = [{"team": t, "n": float(v.dropbacks_hat + v.rushes_hat),
              "pass": float(v.dropbacks_hat / (v.dropbacks_hat + v.rushes_hat))} for t, v in ((a_t, va), (h_t, vh))]
    check = off_pts + st + hfa_scrim + volume
    if abs(check + g.model_margin) > 0.05:  # the bars must sum to the model line; flag it if the formula changes
      print(f"[report] warning: {g.game_id} matchup bars sum to {-check:+.2f}, model margin {g.model_margin:+.2f}",
            flush=True)
    out.append({"id": g.game_id, "gameday": str(g.gameday), "gametime": str(g.gametime),
                "colors": {g.away_team: col[g.away_team], g.home_team: col[g.home_team]},
                "away": away, "home": home, "kickoff": kickoff_text(g.gameday, g.gametime),
                "neutral": g.location == "Neutral", "fc": fc,
                "vegas_line": spread_text(v_fav, vm) if pd.notna(vm) else None,
                "vegas_total": vt if pd.notna(vt) else None, "battles": battles, "extras": [st_row, home_row],
                "plays": plays, "bt_style": f"--ac:{col[g.away_team]};--hc:{col[g.home_team]}",
                "power_rk": (rank_of(a_t, "rank"), rank_of(h_t, "rank")),
                "final": final_result(games, g, fc)})
  return out


def player_luck(eng, p: pd.DataFrame, season: int, week: int) -> pd.DataFrame:
  """Raw fantasy points/game vs schedule-adjusted: each past game is divided by how favorable that opponent
  was for this player's current profile (projection vs that defense / projection vs average defense)."""
  r = eng.tm.fit(season, week)
  a = eng.actual[(eng.actual.season == season) & (eng.actual.week < week)]
  a = a[a.gsis_id.isin(p.gsis_id)][["gsis_id", "week", "opponent_team", "actual"]]
  if a.empty:
    return pd.DataFrame(columns=["games", "raw", "adj", "gap"])
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
  return g


def schedule_note(x) -> str:
  """One line for the Rankings detail row: season FP/G with the defenses faced taken out."""
  if x is None:
    return ""
  verdict = ("soft schedule so far: stats a bit inflated" if x.gap >= 1 else
             "tough schedule so far: better than his stats" if x.gap <= -1 else "schedule-neutral so far")
  return f"Schedule-adjusted {x.adj:.1f} FP/G ({verdict})"


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

def short_name(name: str) -> str:
  """'Josh Allen' -> 'Allen', 'Amon-Ra St. Brown' -> 'St. Brown' (the compact pinned column; the team logo beside
  it tells same-name players apart)."""
  parts = str(name).split(" ", 1)
  return parts[1] if len(parts) == 2 and parts[1] else str(name)


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
  env.filters["short"] = short_name
  # Site root relative to this page ("" for index.html, "../" for <season>/week-NN.html): shared assets, the game
  # page and this week's data file are addressed from there.
  root = ctx["nav"]["current_href"][:-len("index.html")]
  out_path.parent.mkdir(parents=True, exist_ok=True)
  root_dir = (out_path.parent / root).resolve()
  data_rel = out_path.resolve().relative_to(root_dir).with_suffix(".json").as_posix()
  html_out = env.get_template("report.html.j2").render(**ctx, root=root, data_rel=data_rel, asset_v=asset_version())
  out_path.write_text(html_out, encoding="utf-8")
  out_path.with_suffix(".json").write_text(week_data(ctx), encoding="utf-8")
  write_site_assets(root_dir, env)
  return out_path


STATIC_DIR = Path(__file__).resolve().parent / "static"


def asset_version() -> str:
  """Short content hash of the shared assets, added to their links (?v=) so a deploy reaches phones at once
  instead of after the browser's cache lifetime (GitHub Pages: 10 minutes)."""
  import hashlib
  h = hashlib.sha1()
  for f in sorted(STATIC_DIR.iterdir()):
    if f.is_file():
      h.update(f.read_bytes())
  return h.hexdigest()[:10]


def write_site_assets(root_dir: Path, env) -> None:
  """Shared files at the site root: the game page and the live / player-card / gamecast script and styles. Every
  week page (current, lookahead and archived) links to these, so improvements reach old pages without rebuilding
  them."""
  (root_dir / "assets").mkdir(parents=True, exist_ok=True)
  for f in STATIC_DIR.iterdir():
    if f.is_file():
      (root_dir / "assets" / f.name).write_bytes(f.read_bytes())
  (root_dir / "game.html").write_text(env.get_template("game.html.j2").render(asset_v=asset_version()), encoding="utf-8")
