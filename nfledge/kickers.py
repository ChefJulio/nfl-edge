"""Kicker projections: an expected kicking stat line per game, re-scored by any league's settings.

Owner 2026-10-15 ("wire up defense and kickers"; pre-registered in docs/INSIGHTS.md section 9). From nflverse
player stats (FG made / missed by distance band, PAT made / missed):
  team FG and PAT attempts per game ~ its Vegas implied total (league-wide linear fit on the training window)
  the team's distance-band mix of FG attempts, shrunk toward the league mix (K_MIX attempts of league weight)
  the kicker's make rate per band and on PATs, shrunk toward the league rate (K_RATE / K_PAT attempts)
Expected line = attempts x mix x make rate per band (+ misses), PATs likewise. Fit on the two prior seasons and the
season so far, like the rest of the model.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BANDS = ["0_19", "20_29", "30_39", "40_49", "50_59", "60_"]
LINE = [f"fgm_{b}" for b in BANDS] + [f"fgmiss_{b}" for b in BANDS] + ["xpm", "xpmiss"]
K_MIX, K_RATE, K_PAT = 30.0, 10.0, 20.0
STANDARD = {**{f"fgm_{b}": 3.0 for b in ("0_19", "20_29", "30_39")}, "fgm_40_49": 4.0, "fgm_50_59": 5.0, "fgm_60_": 5.0,
            **{f"fgmiss_{b}": -1.0 for b in BANDS}, "xpm": 1.0, "xpmiss": -1.0}


def load_kicks(cache, seasons: list[int]) -> pd.DataFrame:
  """Kicker-games (regular season) with made / missed per band and PATs."""
  import nflreadpy as nfl
  frames = []
  for s in seasons:
    def get(s=s):
      d = nfl.load_player_stats([s])
      d = d.to_pandas() if hasattr(d, "to_pandas") else d
      cols = ["player_id", "player_display_name", "position", "season", "week", "season_type", "team", "opponent_team",
              "fg_att", "pat_att", "pat_made", "pat_missed"] + [f"fg_made_{b}" for b in BANDS] + [f"fg_missed_{b}" for b in BANDS]
      return d[(d.position == "K")][[c for c in cols if c in d.columns]]
    frames.append(cache.get("kstats", s, get, stale=False))
  k = pd.concat(frames, ignore_index=True)
  k = k[k.season_type == "REG"].fillna(0)
  for b in BANDS:
    k[f"fgm_{b}"], k[f"fgmiss_{b}"] = k[f"fg_made_{b}"], k[f"fg_missed_{b}"]
  k["xpm"], k["xpmiss"] = k.pat_made, k.pat_missed
  return k


def implied_points(schedules: pd.DataFrame) -> pd.DataFrame:
  """(season, week, team) -> Vegas implied team total (spread_line > 0 = home favored)."""
  s = schedules[(schedules.game_type == "REG") & schedules.total_line.notna() & schedules.spread_line.notna()]
  home = pd.DataFrame({"season": s.season, "week": s.week, "team": s.home_team, "implied": s.total_line / 2 + s.spread_line / 2,
                       "roof": s.roof})
  away = pd.DataFrame({"season": s.season, "week": s.week, "team": s.away_team, "implied": s.total_line / 2 - s.spread_line / 2,
                       "roof": s.roof})
  return pd.concat([home, away], ignore_index=True)


class KickerModel:
  def fit(self, k: pd.DataFrame, imp: pd.DataFrame):
    """k: kicker-games in the training window."""
    tg = k.groupby(["season", "week", "team"])[["fg_att", "pat_att"] + [f"fg_{x}_{b}" for x in ("made", "missed") for b in BANDS]].sum().reset_index()
    tg = tg.merge(imp, on=["season", "week", "team"], how="inner")
    self.fga = np.polyfit(tg.implied, tg.fg_att, 1)
    self.pat = np.polyfit(tg.implied, tg.pat_att, 1)
    att_b = {b: tg[f"fg_made_{b}"] + tg[f"fg_missed_{b}"] for b in BANDS}
    tot = sum(att_b[b].sum() for b in BANDS)
    self.mix_league = {b: att_b[b].sum() / tot for b in BANDS}
    tt = tg.assign(**{f"a_{b}": att_b[b] for b in BANDS}).groupby("team")[[f"a_{b}" for b in BANDS]].sum()
    self.mix_team = {t: {b: (r[f"a_{b}"] + K_MIX * self.mix_league[b]) / (r.sum() + K_MIX) for b in BANDS} for t, r in tt.iterrows()}
    made = {b: k[f"fg_made_{b}"].sum() for b in BANDS}
    att = {b: made[b] + k[f"fg_missed_{b}"].sum() for b in BANDS}
    self.rate_league = {b: (made[b] / att[b]) if att[b] else 0.5 for b in BANDS}
    self.pat_league = k.pat_made.sum() / max(k.pat_att.sum(), 1)
    kk = k.groupby("player_id")[[f"fg_made_{b}" for b in BANDS] + [f"fg_missed_{b}" for b in BANDS] + ["pat_made", "pat_att"]].sum()
    self.rate_k = {}
    for pid, r in kk.iterrows():
      rates = {b: (r[f"fg_made_{b}"] + K_RATE * self.rate_league[b]) / (r[f"fg_made_{b}"] + r[f"fg_missed_{b}"] + K_RATE) for b in BANDS}
      rates["pat"] = (r.pat_made + K_PAT * self.pat_league) / (r.pat_att + K_PAT)
      self.rate_k[pid] = rates
    return self

  def line(self, kicker: str, team: str, implied: float) -> dict:
    """Expected kicking stat line for one game."""
    fga = max(0.0, float(np.polyval(self.fga, implied)))
    pat = max(0.0, float(np.polyval(self.pat, implied)))
    mix = self.mix_team.get(team, self.mix_league)
    rk = self.rate_k.get(kicker, {**self.rate_league, "pat": self.pat_league})
    out = {}
    for b in BANDS:
      a = fga * mix[b]
      out[f"fgm_{b}"], out[f"fgmiss_{b}"] = a * rk[b], a * (1 - rk[b])
    out["xpm"], out["xpmiss"] = pat * rk["pat"], pat * (1 - rk["pat"])
    return out


def score(line: dict, w: dict) -> float:
  return float(sum(line.get(k, 0.0) * w.get(k, 0.0) for k in LINE))
