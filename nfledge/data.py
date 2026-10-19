"""Data loading, local caching, and play-level preprocessing.

Caching policy:
- Completed seasons are fetched once and kept forever.
- Current-season play-level datasets (pbp, player stats, snaps, participation) are refetched only when the
  schedule shows a newly completed week. nflverse publishes these per season, so "refetch only new weeks"
  means "re-download the season file only when it contains a week we have not cached yet".
- Current-season live datasets (injuries, depth charts, weekly rosters) change daily, so they are refetched
  when older than LIVE_TTL_HOURS.
- Schedules (scores + Vegas lines) are tiny and refetched every run, falling back to cache when offline.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .config import ROOT

LIVE_TTL_HOURS = 6
LAG_RETRY_HOURS = 1  # how often to retry while a final game is still missing from nflverse's published data
POSITIONS = ("QB", "RB", "WR", "TE")

PBP_COLS = [
  "play_id", "game_id", "season", "week", "season_type", "home_team", "away_team", "posteam", "defteam",
  "location", "yardline_100", "down", "ydstogo", "goal_to_go", "qtr", "game_seconds_remaining", "wp", "epa",
  "pass", "rush", "qb_dropback", "qb_kneel", "qb_spike", "qb_scramble", "sack", "pass_attempt", "complete_pass",
  "interception", "air_yards", "passing_yards", "receiving_yards", "rushing_yards", "yards_gained",
  "pass_touchdown", "rush_touchdown", "touchdown", "td_team", "passer_player_id", "receiver_player_id",
  "rusher_player_id", "passer_player_name", "receiver_player_name", "rusher_player_name", "fumble_lost",
  "fumbled_1_player_id", "special_teams_play", "play_type", "two_point_attempt", "pass_oe", "xpass", "roof",
  "wind", "weather", "score_differential", "posteam_score", "defteam_score", "total_home_score",
  "total_away_score",
  # nflverse model outputs for the charting experiments (experiments.croe / yacoe / cpoe): completion probability
  # (cp), CPOE, YAC and expected YAC (2006 on, live every week).
  "cp", "cpoe", "yards_after_catch", "xyac_mean_yardage",
  # YAC EPA and its expectation: the receiver's share of a target's value (tools/grade_build.py, Edge grade)
  "yac_epa", "xyac_epa",
]

STAT_COLS = [
  "player_id", "player_display_name", "position", "season", "week", "season_type", "team", "opponent_team",
  "completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions", "sack_fumbles_lost",
  "carries", "rushing_yards", "rushing_tds", "rushing_fumbles_lost", "receptions", "targets", "receiving_yards",
  "receiving_tds", "receiving_fumbles_lost",
]

# Home stadium coordinates for wind forecasts (outdoor / retractable venues matter; domes are skipped).
STADIUMS = {
  "ARI": (33.5276, -112.2626), "ATL": (33.7554, -84.4008), "BAL": (39.2780, -76.6227),
  "BUF": (42.7738, -78.7870), "CAR": (35.2258, -80.8528), "CHI": (41.8623, -87.6167),
  "CIN": (39.0955, -84.5161), "CLE": (41.5061, -81.6995), "DAL": (32.7473, -97.0945),
  "DEN": (39.7439, -105.0201), "DET": (42.3400, -83.0456), "GB": (44.5013, -88.0622),
  "HOU": (29.6847, -95.4107), "IND": (39.7601, -86.1639), "JAX": (30.3239, -81.6373),
  "KC": (39.0489, -94.4839), "LV": (36.0908, -115.1833), "LAC": (33.9535, -118.3392),
  "LA": (33.9535, -118.3392), "MIA": (25.9580, -80.2389), "MIN": (44.9737, -93.2577),
  "NE": (42.0909, -71.2643), "NO": (29.9511, -90.0812), "NYG": (40.8135, -74.0745),
  "NYJ": (40.8135, -74.0745), "PHI": (39.9008, -75.1675), "PIT": (40.4468, -80.0158),
  "SF": (37.4030, -121.9700), "SEA": (47.5952, -122.3316), "TB": (27.9759, -82.5033),
  "TEN": (36.1665, -86.7713), "WAS": (38.9078, -76.8645),
}
INDOOR_ROOFS = {"dome", "closed"}


def _log(msg: str):
  print(f"[data] {msg}", flush=True)


class Cache:
  def __init__(self, cache_dir: Path):
    self.dir = cache_dir
    self.dir.mkdir(parents=True, exist_ok=True)
    self.meta_path = self.dir / "meta.json"
    self.meta = json.loads(self.meta_path.read_text()) if self.meta_path.exists() else {}

  def save_meta(self):
    self.meta_path.write_text(json.dumps(self.meta, indent=2))

  def path(self, name: str, season) -> Path:
    return self.dir / f"{name}_{season}.parquet"

  def get(self, name: str, season, fetch, *, stale: bool) -> pd.DataFrame | None:
    p = self.path(name, season)
    if p.exists() and not stale:
      return pd.read_parquet(p)
    try:
      df = fetch()
    except Exception as e:  # offline or dataset not published for this season
      if p.exists():
        _log(f"{name} {season}: fetch failed ({type(e).__name__}); using cached copy")
        return pd.read_parquet(p)
      _log(f"{name} {season}: unavailable ({str(e)[:80]})")
      return None
    if df is None:
      return None
    if not isinstance(df, pd.DataFrame):
      df = df.to_pandas()
    # Atomic: write a temp file, then rename over the old one. Parallel processes (experiments workers, tools) read
    # these files; a reader that caught a half-written parquet crashed an A/B run (2026-10-14).
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    df.to_parquet(tmp, index=False)
    # Windows refuses the rename while another process has the file open (two experiment workers refreshing the same
    # file crashed a run, 2026-10-16): retry briefly, then keep the other process's copy (same data).
    for i in range(10):
      try:
        os.replace(tmp, p)
        break
      except PermissionError:
        time.sleep(0.2 * (i + 1))
    else:
      try:
        os.remove(tmp)
      except OSError:
        pass
    self.meta.setdefault("fetched", {})[f"{name}_{season}"] = time.time()
    return df

  def lacks(self, name: str, season, cols) -> bool:
    """True if the cached file exists but is missing any of cols (schema only; no data read)."""
    p = self.path(name, season)
    if not p.exists():
      return False
    import pyarrow.parquet as pq
    return not set(cols) <= set(pq.read_schema(p).names)

  def age_hours(self, name: str, season) -> float:
    ts = self.meta.get("fetched", {}).get(f"{name}_{season}")
    return float("inf") if ts is None else (time.time() - ts) / 3600


# Relocated franchises, plus LAR (rosters/depth/draft) vs LA (play-by-play) for the Rams.
RELOCATED = {"OAK": "LV", "SD": "LAC", "STL": "LA", "LAR": "LA"}
TEAM_COLS = {"posteam", "defteam", "home_team", "away_team", "team", "opp", "recent_team", "opponent_team",
             "opponent", "club_code", "draft_club", "possession_team", "return_team", "td_team", "timeout_team",
             "penalty_team"}


@dataclass
class Data:
  current_season: int
  latest_week: int  # latest regular-season week of current_season with ANY game final (the live week counts from its
  # first final game; consumers filter to final games). Which week the site is in: nfledge/week_clock.py
  seasons: list[int]
  pbp: pd.DataFrame  # processed regular-season plays
  schedules: pd.DataFrame
  stats: pd.DataFrame  # official weekly player stats (actual fantasy components)
  rosters: pd.DataFrame  # weekly rosters
  snaps: pd.DataFrame
  injuries: pd.DataFrame
  depth: dict = field(default_factory=dict)  # season -> raw depth chart frame
  draft: pd.DataFrame | None = None
  routes: pd.DataFrame | None = None  # player-game dropbacks on field (participation), where published
  exclusions: pd.DataFrame | None = None
  pending_games: int = 0
  practice: pd.DataFrame | None = None  # daily practice participation (NFL.com API), where enabled
  avail_hist: pd.DataFrame | None = None  # labelled practice weeks (did he play?) for completed seasons
  ecr: pd.DataFrame | None = None  # FantasyPros weekly positional expert consensus ranks (pre-game only)
  teams: pd.DataFrame | None = None  # team names + colors
  qb_career: pd.Series | None = None  # career pass attempts before the loaded window, by gsis_id
  pfr_def: pd.DataFrame | None = None  # PFR weekly advanced defensive stats (pressures, coverage, tackling)
  depth_per_team: bool = False  # EXPERIMENT (AR, experiments.depth_per_team): each team's depth chart as of its own game

  def __post_init__(self):
    """One code per franchise across seasons and sources: older nflverse seasons use the codes of the time (OAK
    before 2020, SD before 2017, STL before 2016), which would split a franchise in two once older history is
    loaded, and some sources call the Rams LAR.
    game_id strings keep their original codes (they are only ever joined to each other)."""
    for name, val in vars(self).items():
      if name == "teams":
        continue
      frames = val.values() if isinstance(val, dict) else [val]
      for f in frames:
        if isinstance(f, pd.DataFrame):
          for col in TEAM_COLS.intersection(f.columns):
            f[col] = f[col].replace(RELOCATED)

  def completed_weeks(self, season: int) -> int:
    """Last week with any final game (current season, see latest_week; may be the live week), else the season's last."""
    if season == self.current_season:
      return self.latest_week
    return int(self.schedules.loc[(self.schedules.season == season) & (self.schedules.game_type == "REG"),
                                  "week"].max())


def _to_pd(df):
  return df if isinstance(df, pd.DataFrame) else df.to_pandas()


def behind_finals(cache: Cache, name: str, season: int, schedules: pd.DataFrame | None) -> bool:
  """A cached per-week frame (week, team columns) that lacks a team of a final regular-season game and wasn't fetched
  in the last LAG_RETRY_HOURS: refetch it. For loaders outside load_all (kicker and team stats, kickers.py /
  defenses.py), which read their cache with stale=False and so kept the first copy all season (2026-10-18: both
  stopped at week 5). No schedule: only a missing file counts."""
  p = cache.path(name, season)
  if not p.exists():
    return True
  if schedules is None or cache.age_hours(name, season) < LAG_RETRY_HOURS:
    return False
  fin = schedules[(schedules.season == season) & (schedules.game_type == "REG") & schedules.home_score.notna()]
  if not len(fin):
    return False
  st = pd.read_parquet(p, columns=["week", "team"])
  have = set(zip(st.week.astype(int), st.team.replace(RELOCATED)))
  need = {(int(w), RELOCATED.get(t, t)) for w, h, a in zip(fin.week, fin.home_team, fin.away_team) for t in (h, a)}
  return not need <= have


def missing_finals(cache: Cache, season: int, reg: pd.DataFrame) -> set[str]:
  """Final regular-season games absent from the cached play-by-play, snaps, or player stats (a game counts as
  present in stats once both teams have rows for that week)."""
  final = reg[reg.home_score.notna()]
  want = set(final.game_id)
  missing = set()
  for name in ("pbp", "snaps"):
    p = cache.path(name, season)
    have = set(pd.read_parquet(p, columns=["game_id"]).game_id) if p.exists() else set()
    missing |= want - have
  p = cache.path("stats", season)
  if p.exists():
    st = pd.read_parquet(p, columns=["week", "team"])
    have = set(zip(st.week, st.team.replace(RELOCATED)))
    for g in final.itertuples():
      if (g.week, RELOCATED.get(g.home_team, g.home_team)) not in have or \
         (g.week, RELOCATED.get(g.away_team, g.away_team)) not in have:
        missing.add(g.game_id)
  else:
    missing |= want
  return missing


def load_all(cfg: dict, force_week: int | None = None) -> Data:
  import nflreadpy as nfl

  cache = Cache(ROOT / cfg["data"]["cache_dir"])
  current = int(nfl.get_current_season())
  seasons = list(range(current - int(cfg["data"]["history_seasons"]), current + 1))

  sched = cache.get("schedules", "all", lambda: nfl.load_schedules(seasons), stale=True)
  sched = sched[sched.season.isin(seasons)].copy()
  reg = sched[(sched.season == current) & (sched.game_type == "REG")]
  # Target = first week with no final games; data runs through the week before it (which may still have a
  # pending Monday game - every final game is used).
  started = reg.groupby("week").home_score.apply(lambda s: s.notna().any())
  latest = int(started[started].index.max()) if started.any() else 0
  if force_week is not None:
    latest = min(latest, force_week - 1)
  n_final = int(reg.home_score.notna().sum())
  pending = int(reg[(reg.week == latest)].home_score.isna().sum())

  cached_final = cache.meta.get("final_games", {}).get(str(current), -1)
  new_weeks = n_final != cached_final
  if new_weeks:
    _log(f"new final games for {current}: cached {cached_final}, schedule shows {n_final}")
  elif cache.age_hours("pbp", current) >= LAG_RETRY_HOURS and (lagging := missing_finals(cache, current, reg)):
    # The schedule marks a game final hours before nflverse publishes its plays/stats/snaps (a Monday night
    # game typically lands Tuesday afternoon). The final-count trigger above has already fired by then, so
    # keep retrying until every final game is covered.
    _log(f"{len(lagging)} final game(s) not yet in cached data ({', '.join(sorted(lagging)[:4])}); refetching")
    new_weeks = True

  frames = {k: [] for k in ("pbp", "stats", "snaps", "rosters", "injuries", "routes", "pfr_def")}
  depth = {}
  for s in seasons:
    is_cur = s == current
    pbp_stale = is_cur and new_weeks
    live_stale = is_cur and cache.age_hours("injuries", s) > LIVE_TTL_HOURS
    # A cached season missing a column PBP_COLS now asks for is refetched (adding a column never yields silent NaN).
    frames["pbp"].append(cache.get("pbp", s, lambda: nfl.load_pbp([s]).select(PBP_COLS),
                                   stale=pbp_stale or cache.lacks("pbp", s, PBP_COLS)))
    frames["stats"].append(cache.get("stats", s, lambda: nfl.load_player_stats([s]).select(STAT_COLS),
                                     stale=pbp_stale))
    frames["snaps"].append(cache.get("snaps", s, lambda: nfl.load_snap_counts([s]), stale=pbp_stale))
    frames["pfr_def"].append(cache.get("pfrdef", s, lambda: nfl.load_pfr_advstats([s], stat_type="def",
                                                                                  summary_level="week"),
                                       stale=pbp_stale))
    frames["routes"].append(cache.get("routes", s, lambda: _routes_from_participation(nfl, s),
                                      stale=pbp_stale and s <= 2025))
    frames["rosters"].append(cache.get("rosters", s, lambda: nfl.load_rosters_weekly([s]), stale=live_stale))
    frames["injuries"].append(cache.get("injuries", s, lambda: nfl.load_injuries([s]), stale=live_stale))
    if is_cur and live_stale and frames["injuries"][-1] is not None:
      archive_injury_snapshot(cache.dir, frames["injuries"][-1])
    depth[s] = cache.get("depth", s, lambda: nfl.load_depth_charts([s]), stale=live_stale)
  practice = avail_hist = None
  if cfg["data"].get("nfl_api_practice", False):
    pr = [cache.get("practice", s, lambda: fetch_practice_days(s), stale=(s == current) and
                    cache.age_hours("practice", s) > LIVE_TTL_HOURS) for s in seasons]
    pr = [p for p in pr if p is not None and len(p)]
    practice = pd.concat(pr, ignore_index=True) if pr else None
    # Longer labelled history (practice week -> did he play) for the availability model.
    first = int(cfg["data"].get("practice_history_start", 2018))
    ah = [cache.get("availhist", s, lambda: availability_history(nfl, s), stale=False) for s in range(first, current)]
    ah = [a for a in ah if a is not None and len(a)]
    avail_hist = pd.concat(ah, ignore_index=True) if ah else None
  ecr_path = cache.path("ecr", "all")
  ecr_old = ecr_path.exists() and "ecr_flex" not in pq.read_schema(ecr_path).names  # cached before ecr_flex existed
  ecr = cache.get("ecr", "all", lambda: load_ecr(nfl, sched),
                  stale=ecr_old or cache.age_hours("ecr", "all") > LIVE_TTL_HOURS)
  teams = cache.get("teams", "all", lambda: nfl.load_teams(), stale=cache.age_hours("teams", "all") > 24 * 90)
  first = seasons[0]
  qbc = cache.get("qbcareer", first, lambda: qb_career_before(nfl, first), stale=False)
  qb_career = qbc.set_index("gsis_id").attempts if qbc is not None else None
  draft = cache.get("draft", "all", lambda: nfl.load_draft_picks(), stale=cache.age_hours("draft", "all") > 24 * 30)
  if new_weeks:
    cache.meta.setdefault("final_games", {})[str(current)] = n_final
  cache.save_meta()

  cat = lambda k: pd.concat([f for f in frames[k] if f is not None and len(f)], ignore_index=True)
  pbp = prepare_pbp(cat("pbp"))
  pbp = pbp.merge(sched[["game_id", "div_game"]], on="game_id", how="left")
  pbp["div"] = pbp.div_game.fillna(0).astype(int)
  # Respect --week: drop anything at or after the target week of the current season.
  cutoff = lambda df, wk="week": df[~((df.season == current) & (df[wk] > latest))]
  stats = cutoff(cat("stats"))
  stats = stats[stats.season_type == "REG"].copy()
  snaps = cutoff(cat("snaps"))
  snaps = snaps[snaps.game_type == "REG"].copy()
  rosters = cat("rosters")
  pid = rosters.dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates("pfr_id").set_index("pfr_id").gsis_id
  # Snap counts carry PFR ids. The loaded rosters' pfr_id misses ~8% of skill-player rows in 2020-24 (~30% of all
  # rows); nflverse's player table maps ~99.8%. Roster map first, the player table for the rest (2026-10-14).
  # gsis_id_roster keeps the old roster-only map for the A/B (tools/experiments.py snap_map_rosters).
  snaps["gsis_id_roster"] = snaps.pfr_player_id.map(pid)
  players = cache.get("players", "all", lambda: nfl.load_players(), stale=cache.age_hours("players", "all") > 24 * 7)
  ppid = players.dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates("pfr_id").set_index("pfr_id").gsis_id
  snaps["gsis_id"] = snaps.gsis_id_roster.fillna(snaps.pfr_player_id.map(ppid))
  routes = frames["routes"]
  routes = pd.concat([r for r in routes if r is not None], ignore_index=True) if any(
    r is not None for r in routes) else None

  data = Data(current_season=current, latest_week=latest, seasons=seasons, pbp=cutoff(pbp), schedules=sched,
              stats=stats, rosters=rosters, snaps=snaps, injuries=cat("injuries"), depth=depth, draft=draft,
              routes=routes, exclusions=load_exclusions(rosters), pending_games=pending, practice=practice,
              avail_hist=avail_hist, ecr=ecr, teams=teams,
              qb_career=qb_career, pfr_def=cutoff(cat("pfr_def")))
  _log(f"seasons {seasons}; current {current}, data through week {latest}"
       f"{f' ({pending} game(s) pending)' if pending else ''}; {len(data.pbp):,} plays, {len(stats):,} player-games")
  return data


def prepare_pbp(pbp: pd.DataFrame) -> pd.DataFrame:
  pbp = pbp[pbp.season_type == "REG"].copy()
  pbp["neutral"] = pbp.location.eq("Neutral")
  pbp["home"] = np.where(pbp.neutral, 0, np.where(pbp.posteam == pbp.home_team, 1, -1))
  # Game-level wind: column when present, else parse the weather string; indoor = 0.
  parsed = pbp.weather.str.extract(r"[Ww]ind:?\s*\w*\s*(\d+)\s*mph", expand=False).astype(float)
  wind = pbp.wind.astype(float).fillna(parsed)
  wind = wind.where(~pbp.roof.isin(INDOOR_ROOFS), 0.0)
  pbp["game_wind"] = wind.groupby(pbp.game_id).transform("max").fillna(0.0)
  pbp["indoor"] = pbp.roof.isin(INDOOR_ROOFS)
  for c in ("pass", "rush", "qb_dropback", "qb_kneel", "qb_spike", "qb_scramble", "sack", "pass_attempt",
            "complete_pass", "interception", "pass_touchdown", "rush_touchdown", "touchdown", "fumble_lost",
            "special_teams_play", "two_point_attempt"):
    pbp[c] = pbp[c].fillna(0).astype(int)
  pbp["is_dropback"] = (pbp.qb_dropback == 1) & (pbp.qb_spike == 0) & (pbp.two_point_attempt == 0)
  pbp["is_designed_rush"] = (pbp.rush == 1) & (pbp.qb_scramble == 0) & (pbp.qb_kneel == 0) & (
    pbp.two_point_attempt == 0)
  pbp["is_st"] = (pbp.special_teams_play == 1) & pbp.play_type.isin(["punt", "kickoff", "field_goal",
                                                                      "extra_point"])
  pbp["epa"] = pbp.epa.astype(float)
  return pbp


def _routes_from_participation(nfl, season: int):
  """Dropbacks on field per player-game: the standard route-participation proxy for WR/TE."""
  part = _to_pd(nfl.load_participation([season]))
  part = part[part.offense_players.notna() & (part.offense_players != "")]
  pbp = _to_pd(nfl.load_pbp([season]).select(["game_id", "play_id", "week", "posteam", "qb_dropback",
                                                  "qb_spike", "season_type"]))
  pbp = pbp[(pbp.qb_dropback == 1) & (pbp.qb_spike != 1) & (pbp.season_type == "REG")]
  m = part.merge(pbp, left_on=["nflverse_game_id", "play_id"], right_on=["game_id", "play_id"])
  m["player"] = m.offense_players.str.split(";")
  m = m.explode("player")
  out = m.groupby(["game_id", "week", "posteam", "player"]).size().rename("dropbacks_on_field").reset_index()
  out["season"] = season
  return out.rename(columns={"player": "gsis_id", "posteam": "team"})


# NFL.com's web client credentials (public, embedded in nfl.com's own site). Unofficial use: NFL's terms likely
# disallow automated access and the key may rotate. Disable with [data] nfl_api_practice = false; the model then
# falls back to nflverse's final practice status. Past seasons are fetched once and cached permanently.
_NFL_CLIENT = {"clientKey": "4cFUW6DmwJpzT9L7LrG3qRAcABG5s04g", "clientSecret": "CZuvCL49d9OwfGsR"}
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
_DAY = {"DIDNOT": "D", "LIMITED": "L", "FULL": "F"}


def _nfl_api(url: str, body: dict | None = None, token: str | None = None) -> dict:
  h = {"User-Agent": _UA, "Content-Type": "application/json"}
  if token:
    h["Authorization"] = "Bearer " + token
  r = urllib.request.Request(url, data=json.dumps(body).encode() if body else None, headers=h)
  with urllib.request.urlopen(r, timeout=30) as resp:
    return json.load(resp)


def fetch_practice_days(season: int) -> pd.DataFrame:
  """Per player-week daily practice participation (e.g. 'DDL' = DNP, DNP, Limited) + game status."""
  import uuid
  tok = _nfl_api("https://api.nfl.com/identity/v3/token",
                 {**_NFL_CLIENT, "deviceId": str(uuid.uuid4()), "deviceInfo": "", "networkType": "other",
                  "nflClaims": None})["accessToken"]
  url = f"https://api.nfl.com/football/v2/injuries?limit=500&season={season}&seasonType=REG"
  rows, page = [], None
  for _ in range(80):
    d = _nfl_api(url + (f"&pageToken={page}" if page else ""), token=tok)
    inj = d.get("injuries") or []
    for i in inj:
      days = sorted(i.get("practiceDays") or [], key=lambda x: x.get("date", ""))
      rows.append({"season": season, "week": i.get("week"), "gsis_id": (i.get("person") or {}).get("gsisId"),
                   "position": i.get("position"), "game_status": i.get("injuryStatus") or "None",
                   "days": "".join(_DAY.get(x.get("status"), "?") for x in days),
                   # each day's date, for the player card's practice timeline (owner 2026-10-17)
                   "dates": ",".join(str(x.get("date") or "")[:10] for x in days)})
    nxt = (d.get("pagination") or {}).get("token")
    if not inj or not nxt or nxt == page:
      break
    page = nxt
  _log(f"practice days {season}: {len(rows)} player-weeks from NFL.com API")
  return pd.DataFrame(rows).dropna(subset=["gsis_id", "week"])


def load_ecr(nfl, sched: pd.DataFrame) -> pd.DataFrame:
  """FantasyPros weekly positional ECR (scraped Fridays), mapped to gsis ids and to the week it was for.
  The per-player leakage guard (scraped before that player's kickoff) is applied in Engine.attach_ecr.
  ecr_flex is the expert flex rank (display only, never a model input): nflverse doesn't carry FantasyPros' flex
  page, so it is their weekly superflex (OP) consensus with the QBs taken out, RB / WR / TE re-ranked 1..n."""
  all_r = _to_pd(nfl.load_ff_rankings(type="all"))
  r = all_r[(all_r.ecr_type == "wp") & all_r.pos.isin(POSITIONS)][["id", "pos", "team", "ecr", "sd", "scrape_date"]].copy()
  op = all_r[(all_r.ecr_type == "wsf") & all_r.pos.isin(["RB", "WR", "TE"])][["id", "ecr", "scrape_date"]].copy()
  op["ecr_flex"] = op.groupby("scrape_date").ecr.rank(method="first")
  op = op.assign(id=op.id.astype(str)).drop_duplicates(["scrape_date", "id"])[["id", "scrape_date", "ecr_flex"]]
  ids = _to_pd(nfl.load_ff_playerids())[["fantasypros_id", "gsis_id"]].dropna()
  ids["fantasypros_id"] = ids.fantasypros_id.astype("int64").astype(str)
  r["id"] = r.id.astype(str)
  r = r.merge(op, on=["id", "scrape_date"], how="left")
  r = r.merge(ids, left_on="id", right_on="fantasypros_id")
  r["scrape_date"] = pd.to_datetime(r.scrape_date)
  g = sched[sched.game_type == "REG"][["season", "week", "gameday", "home_team", "away_team"]].copy()
  g["gameday"] = pd.to_datetime(g.gameday)
  wk = g.groupby(["season", "week"]).gameday.agg(["min", "max"]).reset_index()
  out = []
  for sd, grp in r.groupby("scrape_date"):
    cand = wk[wk["max"] >= sd].sort_values("min")
    if cand.empty or (cand.iloc[0]["min"] - sd).days > 7:
      continue
    season, week = int(cand.iloc[0].season), int(cand.iloc[0].week)
    out.append(grp.assign(season=season, week=week))
  e = pd.concat(out, ignore_index=True)
  e = e.sort_values("scrape_date").drop_duplicates(["season", "week", "gsis_id"], keep="last")
  return e[["season", "week", "gsis_id", "pos", "ecr", "ecr_flex", "sd", "scrape_date"]]


def qb_career_before(nfl, first_season: int, start: int = 2006) -> pd.DataFrame:
  """Career regular-season pass attempts before the loaded window, so veterans are not mistaken for
  inexperienced QBs at the start of the window."""
  st = _to_pd(nfl.load_player_stats(list(range(start, first_season))).select(
    ["player_id", "season_type", "attempts"]))
  st = st[st.season_type == "REG"]
  return st.groupby("player_id").attempts.sum().rename_axis("gsis_id").reset_index()


def availability_history(nfl, season: int) -> pd.DataFrame:
  """Practice weeks labelled with whether the player played (any snaps) that week. Only players whose snap
  counts map to a gsis id, and only weeks their team played (byes excluded)."""
  pr = fetch_practice_days(season)
  sn = _to_pd(nfl.load_snap_counts([season]))
  ro = _to_pd(nfl.load_rosters_weekly([season]))
  pid = ro.dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates("pfr_id").set_index("pfr_id").gsis_id
  sn["gsis_id"] = sn.pfr_player_id.map(pid)
  sn = sn[sn.game_type == "REG"]
  tot = sn.offense_snaps.fillna(0) + sn.defense_snaps.fillna(0) + sn.st_snaps.fillna(0)
  played = set(map(tuple, sn.loc[tot > 0, ["week", "gsis_id"]].dropna().itertuples(index=False)))
  team = ro.dropna(subset=["gsis_id"]).drop_duplicates(["week", "gsis_id"]).set_index(["week", "gsis_id"]).team
  team_weeks = set(map(tuple, sn[["week", "team"]].drop_duplicates().itertuples(index=False)))
  pr = pr[pr.gsis_id.isin(set(sn.gsis_id.dropna()))].drop_duplicates(["week", "gsis_id"], keep="last")
  pr["team"] = [team.get((w, g)) for w, g in zip(pr.week, pr.gsis_id)]
  pr = pr[[(w, t) in team_weeks for w, t in zip(pr.week, pr.team)]].copy()
  pr["played"] = [(w, g) in played for w, g in zip(pr.week, pr.gsis_id)]
  return pr


def archive_injury_snapshot(cache_dir: Path, inj: pd.DataFrame):
  """Save a dated copy of the current week's injury report whenever it changes.

  nflverse publishes only the latest practice status per player-week, and no free source has historical
  Wed/Thu/Fri participation. The live file updates after each practice, so archiving every change builds our
  own daily history (e.g. DNP/DNP/LP vs LP/LP/FP) for a future practice-sequence availability model."""
  if inj is None or inj.empty:
    return
  wk = int(inj.week.max())
  cur = inj[inj.week == wk][["season", "week", "team", "gsis_id", "full_name", "position", "report_status",
                             "practice_status", "report_primary_injury"]]
  d = cache_dir / "injury_snapshots"
  d.mkdir(exist_ok=True)
  season = int(cur.season.iloc[0])
  prev = sorted(d.glob(f"inj_{season}_w{wk:02d}_*.parquet"))
  if prev:
    last = pd.read_parquet(prev[-1])
    if last.drop(columns=["snapshot_ts"]).reset_index(drop=True).equals(cur.reset_index(drop=True)):
      return
  ts = time.strftime("%Y%m%d_%H%M")
  cur.assign(snapshot_ts=ts).to_parquet(d / f"inj_{season}_w{wk:02d}_{ts}.parquet", index=False)


def load_exclusions(rosters: pd.DataFrame) -> pd.DataFrame:
  p = ROOT / "exclusions.csv"
  if not p.exists():
    return pd.DataFrame(columns=["gsis_id", "season", "week", "reason"])
  ex = pd.read_csv(p, comment="#", skipinitialspace=True)
  if ex.empty:
    return pd.DataFrame(columns=["gsis_id", "season", "week", "reason"])
  names = rosters.dropna(subset=["gsis_id"]).drop_duplicates("full_name").set_index("full_name").gsis_id
  ex["gsis_id"] = np.where(ex.player.str.match(r"^\d{2}-\d{7}$"), ex.player, ex.player.map(names))
  missing = ex[ex.gsis_id.isna()]
  for _, r in missing.iterrows():
    _log(f"exclusions.csv: could not match player '{r.player}' - row ignored")
  return ex.dropna(subset=["gsis_id"])[["gsis_id", "season", "week", "reason"]]


def depth_for_week(data: Data, season: int, week: int) -> pd.DataFrame:
  """Offensive depth chart (team, gsis_id, pos, rank) as of the given week, normalized across schemas."""
  raw = data.depth.get(season)
  if raw is None or raw.empty:
    return pd.DataFrame(columns=["team", "gsis_id", "pos", "rank"])
  if "dt" in raw.columns:  # 2025+: daily snapshots
    sched = data.schedules[(data.schedules.season == season) & (data.schedules.week == week)]
    first_day = pd.to_datetime(sched.gameday).min() if len(sched) else None
    dts = pd.to_datetime(raw.dt.unique(), utc=True)
    if first_day is not None and not pd.isna(first_day):
      dts = dts[dts.tz_localize(None) < first_day + pd.Timedelta(days=1)] if len(dts) else dts
    if not len(dts):
      dts = pd.to_datetime(raw.dt.unique(), utc=True)
    snap = dts.max().strftime("%Y-%m-%dT%H:%M:%SZ")
    d = raw[(raw.dt == snap) & raw.pos_abb.isin(POSITIONS)]
    if data.depth_per_team and len(sched):
      # (AR) each team's chart: the last snapshot before its own game day + 1 day (a Sunday team keeps Friday's moves)
      all_dts = pd.to_datetime(raw.dt.unique(), utc=True)
      parts = []
      for g in sched.itertuples():
        gd = pd.to_datetime(g.gameday)
        if pd.isna(gd):
          continue
        ok = all_dts[all_dts.tz_localize(None) < gd + pd.Timedelta(days=1)]
        if not len(ok):
          continue
        sn = ok.max().strftime("%Y-%m-%dT%H:%M:%SZ")
        for t in (g.home_team, g.away_team):
          parts.append(raw[(raw.dt == sn) & (raw.team == t) & raw.pos_abb.isin(POSITIONS)])
      if parts:
        new = pd.concat(parts, ignore_index=True)
        d = pd.concat([d[~d.team.isin(set(new.team))], new], ignore_index=True)  # teams on bye keep the week's base chart
    d = d.rename(columns={"pos_abb": "pos", "pos_rank": "rank"})[["team", "gsis_id", "pos", "rank"]]
  else:  # <= 2024: weekly snapshots
    d = raw[(raw.week == min(week, raw.week.max())) & (raw.formation == "Offense") &
            raw.position.isin(POSITIONS) & (raw.game_type == "REG")]
    d = d.rename(columns={"club_code": "team", "position": "pos", "depth_team": "rank"})
    d["rank"] = pd.to_numeric(d["rank"], errors="coerce")
    d = d[["team", "gsis_id", "pos", "rank"]]
  return d.dropna(subset=["gsis_id"]).sort_values("rank").drop_duplicates(["team", "gsis_id"])


def forecast_wind(games: pd.DataFrame) -> pd.Series:
  """Forecast wind (mph) at kickoff for upcoming games via Open-Meteo (free, no key). Indoor -> 0, unknown -> NaN."""
  out = pd.Series(np.nan, index=games.index)
  for i, g in games.iterrows():
    if g.roof in INDOOR_ROOFS:
      out[i] = 0.0
      continue
    if g.location == "Neutral" or g.home_team not in STADIUMS or pd.isna(g.gameday):
      continue
    lat, lon = STADIUMS[g.home_team]
    hour = int(str(g.gametime or "13:00").split(":")[0])
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=wind_speed_10m"
           f"&wind_speed_unit=mph&timezone=America%2FNew_York&start_date={g.gameday}&end_date={g.gameday}")
    try:
      with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "nfl-edge-site/1.0"}), timeout=10) as r:
        speeds = json.loads(r.read())["hourly"]["wind_speed_10m"]
      window = [s for s in speeds[hour:hour + 4] if s is not None]
      out[i] = float(np.mean(window)) if window else np.nan
    except Exception:
      pass
  if games.roof.isin(["outdoors", "open"]).any():
    _log(f"wind forecasts: {out.notna().sum()}/{len(out)} games resolved")
  return out


def forecast_conditions(games: pd.DataFrame) -> dict:
  """Display only (owner 2026-10-17: a weather mark in Rankings' Matchup column): game_id -> {wind (mph, kickoff
  window mean), pop (max % chance of rain), snow (cm)} for outdoor games, from Open-Meteo (free, no key). Indoor,
  neutral-site or unresolved games are left out. The projections use forecast_wind only."""
  out = {}
  for g in games.itertuples():
    if g.roof in INDOOR_ROOFS or g.location == "Neutral" or g.home_team not in STADIUMS or pd.isna(g.gameday):
      continue
    lat, lon = STADIUMS[g.home_team]
    hour = int(str(g.gametime or "13:00").split(":")[0])
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
           f"&hourly=wind_speed_10m,precipitation_probability,snowfall&wind_speed_unit=mph&timezone=America%2FNew_York"
           f"&start_date={g.gameday}&end_date={g.gameday}")
    try:
      with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "nfl-edge-site/1.0"}), timeout=10) as r:
        h = json.loads(r.read())["hourly"]
      win = lambda k: [v for v in h.get(k, [])[hour:hour + 4] if v is not None]
      w, pop, sn = win("wind_speed_10m"), win("precipitation_probability"), win("snowfall")
      out[g.game_id] = {"wind": round(float(np.mean(w)), 1) if w else None, "pop": int(max(pop)) if pop else None,
                        "snow": round(float(sum(sn)), 1) if sn else None}
    except Exception:
      pass
  return out


def team_name_fix(s: pd.Series) -> pd.Series:
  """nflverse uses LA for the Rams in pbp but LAR in some rosters/depth charts."""
  return s.replace({"LAR": "LA"})


_SANITIZE = re.compile(r"[^\x20-\x7E]")


def ascii_name(s: str) -> str:
  return _SANITIZE.sub("", s) if isinstance(s, str) else s
