# nfl-edge

**[This week's report (live)](https://chefjulio.github.io/nfl-edge/)** - rebuilt on every push and daily.

Weekly opponent-adjusted NFL analytics for fantasy football (QB/RB/WR/TE) and team matchups. One command, one
static mobile-friendly HTML report.

```
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run.py            # auto-detects the next week to project
.venv\Scripts\python run.py --week 7   # project a specific week (uses only data before it)
.venv\Scripts\python run.py --open     # open the report when done
```

Output: `report/nfl_edge_week{N}.html`. The first run downloads ~4 seasons of data plus practice history from
2018 (a few minutes); later runs only refetch what changed.

## Report sections
1. **Player rankings** by position: projection (half PPR, if active) with a calibrated floor/ceiling range bar,
   Inactive% (injury + healthy-scratch risk), team-colored matchup with grade and points vs an average defense,
   season FP/G, start/sit tier, expert rank, stat line with TD odds (1 / 2 / 3+), bold takeaway. Tap a row for
   season stats and weekly points; bye-week players listed under each table.
2. **Matchups**: each team's adjusted pass/rush offense and defense and special teams; model margin/total vs
   Vegas, disagreements highlighted.
3. **Power rankings** with weekly sparklines and bootstrap certainty.
4. **Schedule luck**: teams (strength of opponents faced) and players (raw vs schedule-adjusted points/game).
5. **Role-change alerts**: snap / opportunity share spikes (waiver targets). Alerts only, not model inputs.
6. **Model**: how every number is calculated, the exact fitted formulas and weights, and the walk-forward
   track record (model vs FantasyPros experts vs Vegas-scaled vs raw stats), all from `MODEL.md` with live values.

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
nflverse via `nflreadpy` (play-by-play, schedules + Vegas lines, rosters, snaps, injuries, depth charts, draft,
participation), FantasyPros ECR via nflverse, Open-Meteo wind forecasts, and NFL.com's injury API for daily
practice participation. That last one uses the public key nfl.com's own site uses: unofficial, may break or
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
