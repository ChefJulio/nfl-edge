# nfl-edge

**[Live site](https://chefjulio.github.io/nfl-edge/)** - rebuilt on every push, on a schedule, and whenever news
breaks (injury statuses, practice reports, inactives, line moves: `tools/news_watch.py`).

A free, mobile-first site for following the NFL as a fantasy player: one place to look up any player or team,
follow games live, and get honest, tested projections and chance-to-play numbers. Built solo in October 2026.
The prediction models are one part; most of the site is reference and tracking that otherwise takes Spotrac,
OverTheCap, ESPN / CBS and a fantasy app together.

## What's on the site
- **Player search** (header, every page): any current or past player (prefix or partial name), active players
  first. A **player card** has: this week's projection with its range, matchup and stat line; **health** (official
  tag, chance to play, practice participation day by day against his team's report calendar, injury history and
  timeline); recent form; career **game logs** (dense, scannable, every game since his debut); bio, draft,
  **contract**; a news log; the **Edge grade** (a 0-99 percentile of production for his position: has he been
  succeeding in the NFL, not a prediction). Historical players included (Hall of Fame badge, era-correct teams).
- **Teams**: every team's page (power ranking, record, next matchup, schedule, playoff history, depth chart by
  recent snaps and as officially reported); league-wide Power rankings (points per game vs average, by unit),
  Standings, Playoff odds (10,000 simulated seasons), team Stats, the Draft (every pick, searchable).
- **Players**: Rankings (this week and rest of season, re-scored to your league's settings), Stats, Roles (snap
  and opportunity shifts), Injuries (every listed player, sorted by relevance), Moves (transactions incl.
  practice-squad elevations), Trends (a play-level query builder since 1999: situation, game, opponent strength,
  charting, teammate on/off, college / draft / contract / age filters with include-exclude and sliders; routes run
  and YPRR from 2016; game logs, streaks and best stretches; CSV export).
- **Games**: matchups with model vs Vegas lines, and a **gamecast** for every game: field view with play gains,
  parsed play text (penalties, who did what), fantasy points by play, every play sortable by win-probability
  swing and scrubbable, team and player box scores, highlight links; live games refresh every 30 seconds.
- **Fantasy**: import a Sleeper league (username or league id) or a public ESPN league (league id); lineup,
  matchup, live scoring, rosters, waivers and trade views, rankings re-scored to its scoring settings.
- **Model**: how every number is made, the fitted formulas, and the walk-forward track record (`MODEL.md`).

## How good the numbers are (measured, walk-forward 2021-25; details in the Model tab and `docs/INSIGHTS.md`)
- **Chance to play**: better than every reading of the official report (final-report Brier 0.086 vs 0.105 for
  "game status + Friday practice", 0.126 for "Questionable = 50/50"), calibrated within about a point in every
  probability band, from Tuesday (before any report) through game day; it knows the report calendar, flags
  overdue reports, and reads in-game injuries and returns. We aren't aware of another free source publishing
  tested, calibrated play probabilities (most publish only Q / D / O tags); not benchmarked against paid ones.
- **Projections**: start / sit picks about on par with the FantasyPros expert consensus and well ahead of season
  averages (fantasy MAE ~5.2 half-PPR points on fantasy-relevant players vs 5.6 for "season average so far").
  The value is mostly the player model: without Vegas lines and team ratings accuracy drops under 1%.
- **Trends** (Players > Trends): its counting matches nflverse's official season stats, 1999-2025: of ~64,000
  player-season rushing / receiving / passing totals, 83 differ, and the ones traced are corrections that only
  nflverse's season table has (its own play-by-play agrees with Trends). Report and tool: `docs/trends_audit.md`,
  `tools/trends_audit.py`. The same engine runs from the command line for scripts and LLMs (`tools/trends_cli.mjs`;
  catalog of every measure / filter / breakdown at `data/plays/schema.json` on the site).
- **Published record** (Model tab; `data/records/` on the site and the `archive` branch): every finished week, what
  the site showed before each game (chance to play at five checkpoints, projections; from the per-build snapshots,
  never recomputed) next to what happened, with the week's scorecard. Anyone can score us (format and rules on the
  Model tab); misses stay in.
- Every model change is pre-registered and gated on out-of-sample tests; rejected ideas are kept with their
  numbers (`docs/INSIGHTS.md`), so the record of what didn't work is as complete as what did.

## For contributors and agents
Start with `CLAUDE.md` (layout, commands, rules) and `docs/INSIGHTS.md` (data quirks, every backtest result
including rejected ideas, owner preferences, open threads).

## Model in brief
- **Team model** (`team_model.py`): ridge regression of play EPA on offense + defense + home, fit separately
  for pass, rush, special teams. Garbage time (WP outside 10-90%), kneels and spikes removed. Prior season
  weighted 0.3 decaying to 0 by week 8; exponential recency within season. Alpha tuned by time-split CV;
  200-game bootstrap for certainty. Volume (plays, pass rate) and a points calibration are learned on history.
- **Player model** (`player_model.py`): projected volume (team dropbacks/rushes x calibrated usage share)
  x efficiency per opportunity (empirical-Bayes shrinkage toward position x draft-round priors) x matchup
  (opponent's ridge coefficient), plus own-offense strength and the Vegas implied team total. Touchdowns use
  expected TDs from field position, blended toward actual TDs. Wind > 15 mph trims passing. RB/WR/TE are then
  blended with FantasyPros expert consensus when it is out (Fridays).
- **Injuries** (`injuries.py`): P(plays) from the Wed/Thu/Fri practice sequence + game status (boosted trees
  on 2018+ history). Projections are "if active" - availability is shown, not multiplied in. Players likely to
  sit (<50%) have their volume redistributed using where vacated targets/carries historically went (by
  position, depth-chart rank, current share), corrected so multi-week absences are not double-counted.
  Teammates of Questionable players show an "if X sits" upside.

## Configuration
- `config.toml`: every model knob (half-lives, prior weights, alpha grid, tiers, toggles).
- `scoring.toml`: `preset = "half"` (default), `"ppr"`, `"standard"`, or `"custom"`.
- `exclusions.csv`: drop injury-shortened games from a player's usage/efficiency (`player,season,week,reason`).

## Data sources (all free)
nflverse via `nflreadpy` (play-by-play, schedules + Vegas lines, rosters, snaps, injury history, depth charts,
draft, contracts, Next Gen Stats, PFR advanced stats), FantasyPros ECR via nflverse, ESPN's public APIs (injury
news, game feeds, transactions), ProFootballRumors (practice-squad elevations), Sleeper projections (reference),
Open-Meteo wind forecasts, and NFL.com's injury API: the single source for the current week's injury report
(practice days with dates, game statuses). That last one uses the public key nfl.com's own site uses: unofficial, may break or
conflict with NFL terms. Turn it off with `nfl_api_practice = false` (falls back to final practice status).
Each run also archives the live injury report so a local daily-practice history accumulates regardless.

## Model documentation (Model tab)
`MODEL.md` is rendered into the site's Model tab, with live values (tuned parameters, learned coefficients,
backtest results) filled in at every build. It carries a fingerprint of the model code and `config.toml`; when
they change without the doc being reviewed, the pre-commit hook blocks the commit, the GitHub build warns, and
the tab shows an "out of date" banner. One-time setup after cloning: `git config core.hooksPath .githooks`.
After updating the doc: `python tools/model_doc.py --stamp`.

## Validating changes
`python tools/experiments.py baseline,implied_total 2025` backtests config variants side by side (walk-forward,
everything trained only on earlier seasons). Decide on one season, confirm on another.
