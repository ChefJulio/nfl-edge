"""NFL standings and the official tiebreaking procedures (current rules: 8 divisions of 4, 2002 on; 7 playoff teams
per conference from 2020, 6 before). One implementation, used by the Standings tab and the playoff odds.

Records count ties as half a win (the rule since 1972). Steps, from the NFL's tiebreaking procedures:

Division (two clubs): 1 head-to-head, 2 division record, 3 common games, 4 conference record, 5 strength of victory,
6 strength of schedule, 7 combined ranking in points scored + allowed among conference teams, 8 the same among all
teams, 9 net points in common games, 10 net points in all games, [11 net touchdowns in all games], [12 coin toss].
Three or more clubs: the same order; whenever a club is separated out, the remaining clubs restart at step 1 (two
clubs left: the two-club procedure). Head-to-head among 3+ = record in the games among the tied clubs.

Wild card (and seeding division winners): first only the best club of each division stays in a tie (division
tiebreak), then: 1 head-to-head only if one club beat (or lost to) each of the others (a sweep), 2 conference record,
3 common games (minimum 4), 4 strength of victory, 5 strength of schedule, 6 conference points ranking, 7 all-teams
points ranking, 8 net points in conference games, 9 net points in all games, [10 net touchdowns], [11 coin toss].

STOPGAPS (labeled): net touchdowns are not computed (needs play-level TD counts per team: would come from pbp), and
the coin toss is replaced by a fixed alphabetical order. Both matter only after every points-based step ties, which
is extremely rare. Strength of schedule mid-season uses the opponents of games played so far (the official figure
uses the full schedule; identical at season end).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

RELOCATED = {"OAK": "LV", "SD": "LAC", "STL": "LA", "LAR": "LA"}


@dataclass
class Rec:
  w: float = 0
  l: float = 0
  t: float = 0

  def add(self, res: float):  # 1 win, 0 loss, 0.5 tie
    if res == 1:
      self.w += 1
    elif res == 0:
      self.l += 1
    else:
      self.t += 1

  @property
  def g(self):
    return self.w + self.l + self.t

  @property
  def pct(self):
    return (self.w + 0.5 * self.t) / self.g if self.g else 0.0


@dataclass
class League:
  """Results so far: one row per team-game (team, opp, res, pf, pa) plus the alignment."""
  games: pd.DataFrame  # columns team, opp, res, pf, pa, week
  conf: dict  # team -> 'AFC' / 'NFC'
  div: dict  # team -> 'AFC East' ...
  _rec: dict = field(default_factory=dict)

  @classmethod
  def from_schedule(cls, sched: pd.DataFrame, teams: pd.DataFrame, season: int, through_week: int | None = None):
    s = sched[(sched.season == season) & (sched.game_type == "REG") & sched.home_score.notna()]
    if through_week is not None:
      s = s[s.week <= through_week]
    h, a = s.home_team.replace(RELOCATED), s.away_team.replace(RELOCATED)
    res_h = (s.home_score > s.away_score).astype(float) + 0.5 * (s.home_score == s.away_score)
    g = pd.concat([pd.DataFrame({"team": h, "opp": a, "res": res_h, "pf": s.home_score, "pa": s.away_score, "week": s.week}),
                   pd.DataFrame({"team": a, "opp": h, "res": 1 - res_h, "pf": s.away_score, "pa": s.home_score, "week": s.week})],
                  ignore_index=True)
    t = teams.assign(team_abbr=teams.team_abbr.replace(RELOCATED)).drop_duplicates("team_abbr")
    t = t[t.team_division.notna()]
    return cls(g, dict(zip(t.team_abbr, t.team_conf)), dict(zip(t.team_abbr, t.team_division)))

  # -- records ---------------------------------------------------------------------------------------------------
  def teams(self) -> list[str]:
    return sorted(self.div)

  def rec(self, team: str, opps=None) -> Rec:
    r = Rec()
    g = self.games[self.games.team == team]
    if opps is not None:
      g = g[g.opp.isin(opps)]
    for x in g.res:
      r.add(x)
    return r

  def overall(self, team):
    if team not in self._rec:
      self._rec[team] = self.rec(team)
    return self._rec[team]

  def div_teams(self, team):
    return [x for x, d in self.div.items() if d == self.div[team] and x != team]

  def conf_teams(self, team):
    return [x for x, c in self.conf.items() if c == self.conf[team] and x != team]

  def opps(self, team) -> list[str]:
    return list(self.games[self.games.team == team].opp)

  def common_opps(self, clubs) -> set:
    sets = [set(self.opps(c)) for c in clubs]
    return set.intersection(*sets) - set(clubs) if sets else set()

  def sov(self, team) -> float:  # combined record of the opponents it beat (each win counts once)
    beat = list(self.games[(self.games.team == team) & (self.games.res == 1)].opp)
    return self._combined(beat)

  def sos(self, team) -> float:
    return self._combined(self.opps(team))

  def _combined(self, teams) -> float:
    w = g = 0.0
    for x in teams:
      r = self.overall(x)
      w += r.w + 0.5 * r.t
      g += r.g
    return w / g if g else 0.0

  def net(self, team, opps=None) -> float:
    g = self.games[self.games.team == team]
    if opps is not None:
      g = g[g.opp.isin(opps)]
    return float((g.pf - g.pa).sum())

  def pts_rank(self, team, pool) -> float:
    """Combined ranking in points scored and points allowed among `pool` (lower = better)."""
    agg = self.games[self.games.team.isin(pool)].groupby("team")[["pf", "pa"]].sum().reindex(pool).fillna(0)
    return float(agg.pf.rank(ascending=False, method="min")[team] + agg.pa.rank(ascending=True, method="min")[team])

  # -- tiebreakers -----------------------------------------------------------------------------------------------
  def _split(self, clubs, key, higher=True):
    """The clubs best on `key` (ties kept together). Returns (best group, rest) or None when all equal."""
    vals = {c: key(c) for c in clubs}
    best = max(vals.values()) if higher else min(vals.values())
    top = [c for c in clubs if abs(vals[c] - best) < 1e-9]
    return None if len(top) == len(clubs) else top

  def _steps_division(self, clubs):
    common = self.common_opps(clubs)
    conf_pool = [x for x, c in self.conf.items() if c == self.conf[clubs[0]]]
    return [
      ("head-to-head", lambda c: self.rec(c, [x for x in clubs if x != c]).pct),
      ("division record", lambda c: self.rec(c, self.div_teams(c)).pct),
      ("common games", lambda c: self.rec(c, common).pct),
      ("conference record", lambda c: self.rec(c, self.conf_teams(c)).pct),
      ("strength of victory", self.sov),
      ("strength of schedule", self.sos),
      ("conference points rank", lambda c: -self.pts_rank(c, conf_pool)),
      ("league points rank", lambda c: -self.pts_rank(c, self.teams())),
      ("net points, common games", lambda c: self.net(c, common)),
      ("net points", self.net),
    ]

  def _steps_wildcard(self, clubs):
    common = self.common_opps(clubs)
    conf_pool = [x for x, c in self.conf.items() if c == self.conf[clubs[0]]]

    def h2h(c):  # applies only as a sweep: beat each of the others (+1) or lost to each (-1), else 0
      others = [x for x in clubs if x != c]
      g = self.games[(self.games.team == c) & self.games.opp.isin(others)]
      if set(g.opp) != set(others):
        return 0.0
      if (g.groupby("opp").res.min() == 1).all():
        return 1.0
      if (g.groupby("opp").res.max() == 0).all():
        return -1.0
      return 0.0
    steps = [("head-to-head (sweep)", h2h) if len(clubs) > 2 else ("head-to-head", lambda c: self.rec(c, [x for x in clubs if x != c]).pct),
             ("conference record", lambda c: self.rec(c, self.conf_teams(c)).pct)]
    if all(len(self.games[(self.games.team == c) & self.games.opp.isin(common)]) >= 4 for c in clubs):
      steps.append(("common games", lambda c: self.rec(c, common).pct))
    steps += [("strength of victory", self.sov), ("strength of schedule", self.sos),
              ("conference points rank", lambda c: -self.pts_rank(c, conf_pool)),
              ("league points rank", lambda c: -self.pts_rank(c, self.teams())),
              ("net points, conference games", lambda c: self.net(c, self.conf_teams(c))),
              ("net points", self.net)]
    return steps

  def break_tie(self, clubs: list[str], kind: str = "division") -> tuple[str, str]:
    """(the club that wins the tie, the step that decided it). kind: 'division' or 'wildcard'."""
    clubs = sorted(clubs)
    while len(clubs) > 1:
      if kind == "wildcard":  # only the best club of each division takes part
        by_div = {}
        for c in clubs:
          by_div.setdefault(self.div[c], []).append(c)
        if any(len(v) > 1 for v in by_div.values()):
          clubs = sorted(self.order(v, "division")[0] for v in by_div.values())
          if len(clubs) == 1:
            return clubs[0], "division tiebreak"
      steps = self._steps_division(clubs) if kind == "division" else self._steps_wildcard(clubs)
      for name, key in steps:
        top = self._split(clubs, key)
        if top is not None:
          if len(top) == 1:
            return top[0], name
          clubs = sorted(top)  # some clubs dropped out: restart from step 1 with the rest
          break
      else:
        return clubs[0], "coin toss (stopgap: alphabetical)"
    return clubs[0], ""

  def order(self, clubs: list[str], kind: str = "division") -> list[str]:
    """Clubs in finishing order: by win percentage, ties broken by the procedure (one club at a time)."""
    left, out = list(clubs), []
    while left:
      best = max(self.overall(c).pct for c in left)
      tied = [c for c in left if abs(self.overall(c).pct - best) < 1e-9]
      win = tied[0] if len(tied) == 1 else self.break_tie(tied, kind)[0]
      out.append(win)
      left.remove(win)
    return out

  # -- tables ----------------------------------------------------------------------------------------------------
  def division_order(self) -> dict:
    divs = {}
    for t, d in self.div.items():
      divs.setdefault(d, []).append(t)
    return {d: self.order(v, "division") for d, v in sorted(divs.items())}

  def order_with_reasons(self, clubs: list[str], kind: str = "division") -> list[tuple[str, str]]:
    """Like order(), with the tiebreak step that put each club ahead of the clubs it was tied with ('' = untied)."""
    left, out = list(clubs), []
    while left:
      best = max(self.overall(c).pct for c in left)
      tied = [c for c in left if abs(self.overall(c).pct - best) < 1e-9]
      win, why = (tied[0], "") if len(tied) == 1 else self.break_tie(tied, kind)
      out.append((win, why))
      left.remove(win)
    return out

  def conference_order(self, conf: str) -> list[tuple[str, str]]:
    """Every club of a conference in seeding order: division winners first (seeds 1-4), then the rest by the
    wild-card procedure (seeds 5+ while playoff spots last), each with its deciding tiebreak step."""
    winners = [o[0] for d, o in self.division_order().items() if self.conf[o[0]] == conf]
    rest = [t for t in self.div if self.conf[t] == conf and t not in winners]
    return self.order_with_reasons(winners, "wildcard") + self.order_with_reasons(rest, "wildcard")

  def seeds(self, n_playoff: int = 7) -> dict:
    """conference -> clubs in seed order (division winners 1-4, then wild cards)."""
    winners = {d: o[0] for d, o in self.division_order().items()}
    out = {}
    for conf in ("AFC", "NFC"):
      w = [t for d, t in winners.items() if self.conf[t] == conf]
      rest = [t for t in self.div if self.conf[t] == conf and t not in w]
      out[conf] = self.order(w, "wildcard") + self.order(rest, "wildcard")[:n_playoff - 4]
    return out


def playoff_teams_per_conf(season: int) -> int:
  return 7 if season >= 2020 else 6
