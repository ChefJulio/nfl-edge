"""Team defense (D/ST) projections: an expected stat line + points / yards allowed distributions, scored per league.

Owner 2026-10-15 ("wire up defense and kickers"; pre-registered in docs/INSIGHTS.md section 9). From nflverse weekly
team stats and schedules. Each counting stat = league rate x (the defense's rate / league) x (the opponent offense's
rate allowed / league), every rate over the team's last WINDOW games shrunk toward the league (K_COMMON / K_RARE
games of league weight). Points allowed ~ normal around the opponent's implied points; yards allowed ~ normal around
a fit on the opponent's implied points and the defense's yards-allowed rate. Leagues score tiers, per-point and
per-yard settings from those distributions.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

WINDOW, K_COMMON, K_RARE = 16, 8.0, 30.0
# component: (defense column, opponent-offense column allowing it or None, shrink)
COMP = {
  "sack": ("def_sacks", "sacks_suffered", K_COMMON),
  "int": ("def_interceptions", "passing_interceptions", K_COMMON),
  "fum_rec": ("fumble_recovery_opp", "fumbles_lost_total", K_COMMON),
  "ff": ("def_fumbles_forced", "fumbles_total", K_COMMON),
  "def_td": ("def_td_all", None, K_RARE),
  "st_td": ("special_teams_tds", None, K_RARE),
  "safe": ("def_safeties", None, K_RARE),
  "blk": ("blocks", None, K_RARE),
  "pass_def": ("def_pass_defended", "attempts", K_COMMON),
  "tkl_loss": ("def_tackles_for_loss", None, K_COMMON),
  "forced_punts": ("forced_punts", "pt_att", K_COMMON),
  "def_2pt": ("def_2pt_made", None, K_RARE),
}
LINE = list(COMP) + ["pa_mu", "pa_sd", "ya_mu", "ya_sd"]


def load_games(cache, seasons: list[int], schedules: pd.DataFrame) -> pd.DataFrame:
  """One row per (season, week, team) as a DEFENSE: its stats + the opponent's offensive stats (o_*) + points /
  yards allowed."""
  import nflreadpy as nfl
  frames = []
  for s in seasons:
    def get(s=s):
      d = nfl.load_team_stats([s])
      return d.to_pandas() if hasattr(d, "to_pandas") else d
    frames.append(cache.get("tstats", s, get, stale=False))
  t = pd.concat(frames, ignore_index=True)
  t = t[t.season_type == "REG"].fillna(0)
  t["def_td_all"] = t.def_tds + t.fumble_recovery_tds
  t["blocks"] = t.def_punt_blocks + t.def_pat_blocks + t.def_fg_blocks
  t["yards_off"] = t.passing_yards - t.sack_yards_lost + t.rushing_yards
  opp = t[["season", "week", "team", "sacks_suffered", "passing_interceptions", "fumbles_lost_total", "fumbles_total",
           "attempts", "pt_att", "yards_off"]].rename(columns=lambda c: c if c in ("season", "week") else f"o_{c}")
  g = t.merge(opp.rename(columns={"o_team": "opponent_team"}), on=["season", "week", "opponent_team"], how="left")
  g["forced_punts"] = g.o_pt_att
  g["ya"] = g.o_yards_off
  sc = schedules[schedules.game_type == "REG"]
  pa = pd.concat([pd.DataFrame({"season": sc.season, "week": sc.week, "team": sc.home_team, "pa": sc.away_score}),
                  pd.DataFrame({"season": sc.season, "week": sc.week, "team": sc.away_team, "pa": sc.home_score})])
  return g.merge(pa, on=["season", "week", "team"], how="left").sort_values(["season", "week"]).reset_index(drop=True)


def _phi(z: float) -> float:
  return 0.5 * (1 + math.erf(z / math.sqrt(2)))


class DefenseModel:
  def fit(self, g: pd.DataFrame, imp: pd.DataFrame):
    """g: defense-games in the training window (rates are taken per team later from `hist`)."""
    self.hist = g
    self.league = {c: float(g[d].mean()) for c, (d, o, k) in COMP.items()}
    self.league_o = {c: float(g[f"o_{o}"].mean()) for c, (d, o, k) in COMP.items() if o}
    x = g.merge(imp.rename(columns={"team": "opponent_team", "implied": "opp_imp"})[["season", "week", "opponent_team", "opp_imp"]],
                on=["season", "week", "opponent_team"], how="inner").dropna(subset=["pa", "ya"])
    self.pa_sd = float((x.pa - x.opp_imp).std())
    ya_rate = x.groupby("team").ya.transform("mean")
    A = np.column_stack([np.ones(len(x)), x.opp_imp, ya_rate])
    self.ya_coef, *_ = np.linalg.lstsq(A, x.ya.to_numpy(), rcond=None)
    self.ya_sd = float((x.ya - A @ self.ya_coef).std())
    self.ya_league = float(x.ya.mean())
    return self

  def _rate(self, rows: pd.DataFrame, col: str, league: float, k: float) -> float:
    rows = rows.tail(WINDOW)
    return (rows[col].sum() + k * league) / (len(rows) + k)

  def line(self, team: str, opp: str, opp_implied: float, before: tuple[int, int]) -> dict:
    """Expected D/ST line for `team` vs `opp`, using games before (season, week)."""
    s, w = before
    h = self.hist[(self.hist.season < s) | ((self.hist.season == s) & (self.hist.week < w))]
    dt, ot = h[h.team == team], h[h.opponent_team == opp]  # opp's games: rows where it was the opposing offense
    out = {}
    for c, (d, o, k) in COMP.items():
      L = self.league[c] or 1e-9
      dr = self._rate(dt, d, L, k) / L
      orr = self._rate(ot, f"o_{o}", self.league_o[c], k) / (self.league_o[c] or 1e-9) if o else 1.0
      out[c] = L * dr * orr
    out["pa_mu"], out["pa_sd"] = float(opp_implied), self.pa_sd
    yr = self._rate(dt, "ya", self.ya_league, K_COMMON)
    out["ya_mu"] = float(self.ya_coef[0] + self.ya_coef[1] * opp_implied + self.ya_coef[2] * yr)
    out["ya_sd"] = self.ya_sd
    return out


def p_between(mu: float, sd: float, lo: float, hi: float) -> float:
  """P(integer outcome in [lo, hi]) under normal(mu, sd), outcomes below 0 counted as 0."""
  a = -math.inf if lo <= 0 else (lo - 0.5 - mu) / sd
  b = math.inf if hi == math.inf else (hi + 0.5 - mu) / sd
  return _phi(b) - (_phi(a) if a != -math.inf else 0.0)


ESPN_STD = {"sack": 1, "int": 2, "fum_rec": 2, "def_td": 6, "st_td": 6, "safe": 2, "blk": 2,
            "pa_tiers": [(0, 0, 5), (1, 6, 4), (7, 13, 3), (14, 17, 1), (18, 27, 0), (28, 34, -1), (35, 45, -3), (46, math.inf, -5)]}


def score(line: dict, w: dict) -> float:
  """w: per-stat points, optional pa_tiers / ya_tiers [(lo, hi, pts)], pts_allow / yds_allow per point / yard."""
  t = sum(line.get(c, 0.0) * w.get(c, 0.0) for c in COMP)
  for lo, hi, pts in w.get("pa_tiers", []):
    t += pts * p_between(line["pa_mu"], line["pa_sd"], lo, hi)
  for lo, hi, pts in w.get("ya_tiers", []):
    t += pts * p_between(line["ya_mu"], line["ya_sd"], lo, hi)
  t += w.get("pts_allow", 0.0) * line["pa_mu"] + w.get("yds_allow", 0.0) * line["ya_mu"]
  return float(t)


def actual_line(r) -> dict:
  return {**{c: float(getattr(r, d)) for c, (d, o, k) in COMP.items()}, "pa_mu": float(r.pa), "pa_sd": 1e-6,
          "ya_mu": float(r.ya), "ya_sd": 1e-6}
