# nfl-edge: accumulated insights

Everything learned building this project (Oct 2026, written during week 5-6 of the 2026 season). Sections: owner
preferences, data quirks, model findings with numbers, model vs Vegas, rejected ideas, engineering gotchas, UI
decisions, site / pipeline, open threads. Numbers are walk-forward backtests (every learned piece trained only on
seasons before the one tested) on 2021-2025 unless noted; "MAE" = fantasy-point mean absolute error on relevant
player-weeks (12,480 rows: played, >= 2 prior games, top-N by consensus), with 95% CIs from a season-week bootstrap.

## 1. Owner preferences (Hunter, GitHub ChefJulio)
- **Data-driven, no assumptions.** Every number in the model is either fitted from data or chosen by walk-forward
  backtest; hand-set values are not acceptable unless tested. A change ships only if it beats the current model out
  of sample (CI excludes 0); otherwise it stays off (switchable) and is documented. Report losses plainly. When the
  data can't distinguish options, prefer the data-estimated one over a hand-picked one.
- **Free data only; avoid dependencies** (no paid sources, no CSS/JS frameworks; dev-only tools are OK).
- **Full transparency:** formulas and fitted weights are public (Model tab section 10 is generated).
- **NFL availability is binary:** a Questionable player plays his normal role or sits; never discount a
  projection by play probability. Show "if active" projection + separate Inactive%; P < 0.5 = sits, volume
  redistributed; teammates get contingent "+X if he sits".
- **Defaults:** half PPR, 10-team league, 1QB 2RB 2WR 1TE 1FLEX (all adjustable on the page).
- **Presentation:** elegance and readability first; minimal, sleek, dark; important values easy to find; all
  reasonable columns sortable. Reviews screenshots closely; dislikes clutter, light pills on dark rows, misaligned
  columns, inconsistent signals, anything "mashed together", tables that scroll inside their own box.
- **Tests on Brave on iPhone (= WebKit).** Verify mobile with `tools/screenshot.py` (WebKit), never only Chrome.
- Works by pointing at a topic ("do the thinking"); expects a plan for big features, then execution; impatient with
  slow runs (keep backtests fast, report ETAs, explain long waits).

## 2. Data quirks (nflverse / nflreadpy and others)
- **Scrambles are `pass=1, rush=0`** in nflverse pbp. Any rushing filter must include `qb_scramble==1` or QB
  rushing collapses (this bug once cut projected QB rush yards from ~17 to ~4).
- **Roster status `INA` = that week's game-day inactive list** (the outcome). Use `ACT` + `INA` as "53-man roster"
  for membership; using only `ACT` leaks the answer into availability models and drops last week's inactives.
  `status_description_abbr`: A01 active, I01 inactive, R01 reserve/injured (IR), R48 IR designated to return,
  R04 PUP, other R* reserve codes, P* practice squad (DEV).
- **Rosters are per team-week; teams on bye or still to play (MNF) lack the latest week.** Use each team's own
  latest roster week. A player traded while a team was on bye can sit on two teams' latest rosters (keep his most
  recent); depth charts can list a player twice (join on gsis_id + team, keep the best slot).
- **Franchise codes changed** (OAK->LV 2020, SD->LAC 2017, STL->LA 2016; LAR vs LA by source).
  `Data.__post_init__` maps every team column (incl. `opponent`, `draft_club`) to current codes; game_id strings keep
  the originals.
- **"Played" for a player-week:** snap counts post 1-2 days after games, weekly player stats (from pbp) sooner; use
  the union (`returns.played_set`).
- **Snap counts are keyed by PFR id**; mapped to gsis via rosters `pfr_id` (about 19% unmapped, mostly non-skill).
- **Depth charts changed schema in 2025**: <=2024 weekly (`club_code`, `depth_team`, `formation`); 2025+ daily
  snapshots (`dt`, `pos_abb`, `pos_rank`). `data.depth_for_week` normalizes both.
- **Participation (routes) only through 2025**; route features unusable live.
- **Schedules `spread_line` > 0 = home favored.** Wind null for domes/closed roofs (= 0); upcoming games use
  Open-Meteo at kickoff (`data.forecast_wind`), historical games the realized wind.
- **Injury reports (nflverse):** one row per player-week, final practice status, body part only ("Knee", never "torn
  ACL"). Daily Wed/Thu/Fri participation: NFL.com API (`api.nfl.com/football/v2/injuries`, public web client key),
  2016+, unofficial; toggle `nfl_api_practice`. Live report archived to `cache/injury_snapshots/`.
- **ESPN injury feed** (`site.api.espn.com/apis/site/v2/sports/football/nfl/injuries`, public, unofficial): ~800
  players with status, diagnosis detail ("Surgery", "Bruise"), side, and an estimated `returnDate` (after the
  season = effectively season-ending). **Current season only, no history** (core API per-athlete/season endpoints
  return nothing for past seasons). Archived daily by CI (`tools/espn_snapshot.py` -> `data/espn_injuries/` on the
  archive branch). ESPN ids map to gsis via `nflreadpy.load_ff_playerids()` (`espn_id`).
- **FantasyPros ECR** (nflverse `load_ff_rankings`): positional ranks scraped Fridays; only use a rank scraped before
  that player's kickoff. `fantasypros_id` is a float. Not available for older seasons in archived pages.
  nflverse has no FantasyPros flex page: `ecr_flex` (display only, FLEX view's rank + vs ECR) = the weekly superflex
  list (`ecr_type == "wsf"`, weekly-op) minus QBs, re-ranked. Before 2026-10-13 the FLEX view showed positional ECR.
- **Flex position mix check (2026-10-13, 2025-26 backtest, 18 weeks):** our top-12 flex averages 63% RB vs the
  experts' 55% (top-24: 55 vs 50; top-60: 44 vs 41). Not a bias against WRs: in our top 60, WRs score below
  projection (-1.32 [-1.94, -0.71]) more than RBs (-0.40 [-1.11, 0.31]); top-12 WRs -2.56 vs RBs -0.17. If
  anything the WRs are over-ranked (wider error = more winner's curse at the top). Not yet a formal test.
- **PFR advanced defense** 2018+ weekly (tested for defender values; didn't help).
- **QB career history** from `load_player_stats` 2006+ so veterans aren't flagged inexperienced.
- `nflreadpy.load_teams()` has colors and ESPN logo URLs.

- **Playoff history sources (2026-10-14):** FiveThirtyEight `nfl_games.csv` (MIT) covers 1920-2020 with a 0/1 playoff
  flag only (no rounds, no seeds), today's franchise codes (Raiders = OAK, Rams = LAR, WSH) and AFL + AAFC games mixed
  in (AAFC codes BBA / BCL / NAA; CLE and SF were AAFC 1946-49). The 1932 Bears-Portsmouth game counts as regular
  season (538 agrees). Rounds = date clusters per side; seeds 1975-1998 from Wikipedia's per-season "NFL playoffs"
  pages (a `| AFC 1 = Team` block; the API rate-limits bursts, so the fetch pauses and backs off); 1999 on from our
  tiebreaker code. Before 1975 no seeds (home field rotated by division). 1920-32: no playoffs, recognized champion
  shown. Era names (Houston Oilers, Phoenix Cardinals...) get text badges, modern names logos.
- **Depth charts (2026-10-14):** nflverse `load_depth_charts` from 2025 on = DAILY snapshots of ESPN's charts
  (`dt` column; every slot of offense in the team's base set, e.g. "3WR 1TE", base defense "Base 3-4 D" / "Base 4-3 D",
  and special teams; `pos_slot` + `pos_rank` = depth order; 3 separate WR slots). Some slots list no one (NaN name:
  drop before writing JSON). Teams' own "unofficial" depth charts exist only as PDFs in weekly game notes. Only
  offensive skill players have player pages (career logs); the Depth tab links everyone else to ESPN.
  Through 2024: weekly team charts (`formation` Offense / Defense / Special Teams, `depth_position` labels are messy:
  whitespace, team-specific names like JACK / LEO / NKL; several WRs share depth 1). Weeks 19+ (18+ before 2021) are
  playoffs. Official tags per week: injury report game status (2009 on) and weekly roster `status_description_abbr`
  codes, identified from known players: R01 / R48 = IR (R48 = designated to return), R04 = PUP, R05 = NFI, R40 =
  suspended (Kamara, Perryman 2023), R03 = did not report (C. Jones 2023 holdout), R06 = left squad; P0x = practice
  squad, I02 = emergency third QB. Full history ~21 MB; cold build ~7 min, warm ~30 s.
- **ESPN transactions feed (2026-10-14):** `site.api.espn.com/apis/site/v2/sports/football/nfl/transactions?season=Y
  &limit=100&page=P`, free, no key; ~1,100-2,800 entries a season back to 2002 (2001: ~500, thin). Free text, one
  entry per team per day, often several moves ("Signed LB X. Waived CB Y."). Format changed around 2009: before,
  positions are spelled out ("linebacker", "tackles A and B") and moves are chained with "; "; after, abbreviations
  ("WRs A and B", "LB's A and B") and ". "; roster dumps continue a move in a verb-less sentence ("Signed rookies.
  QB A, WR B"), which inherits the previous move's type. Team codes LAR / WSH (map to LA / WAS). The feed 404s any
  page holding a bad record: the fetcher re-requests that range in pages of 10, then 1, and skips only what 404s.
  2003 404s for nearly everything after ~record 600 (584 skipped: 2003 is a partial season, 632 entries). Player
  linking: name + team on that season's (then last season's) roster, else a unique name among players active that
  season, else position family breaks namesake ties. Coverage: moves typed 93-99% per season; players linked
  68-78% in 2002-06 (thinner rosters), 82-95% after; the rest are mostly camp / practice-squad players nflverse
  never lists.

## 3. Model findings that shipped (with evidence)
- **Team ratings:** ridge on play EPA per unit (pass/rush/ST), WP 10-90% filter, recency half-life 3 weeks, prior
  season 0.3 decaying to 0 by week 8, alpha by time-split CV. QB-aware pass offense: team + QB effect +
  inexperienced-QB indicator (<150 career dropbacks); team and QB penalties tuned jointly (pass CV 3017 -> 2974).
- **Playoff-odds drift = 0.9 (2026-10-14):** without it the odds were overconfident (2021-25 walk-forward: given
  5-15% -> 20.9% made it; 85-95% -> 79.1%). Pre-registered gate: best make-playoffs Brier on 2021-23 over
  {0, .3, .6, .9, 1.2, 1.5} (500 sims/week), adopt only if it also beats no drift on 2024-25. Picked 0.9 (2021-23
  0.1455 vs 0.1480); held-out 2024-25 0.1273 vs 0.1344, 85-95% band 89.0% actual vs 76.0%. Full 2021-25 rerun at
  1,000 sims: 0.1382 (was 0.1427), every calibration band within 2.3 points.
- **Training window fixed** at 2 seasons (`train_seasons`); it used to be "every loaded season" (a different and
  far slower model when more history was loaded).
- **Points formula** (`GameModel`): points = a + b x offensive EPA (volume x expected EPA/play) + c x net ST EPA,
  OLS, trained on **6 prior seasons** (`points_seasons`; with 2 the ST weight drifted 0.9 -> 3.3, with 6 it is
  ~2.1-2.3; margin MAE 10.71 -> 10.68, never worse per season, winners 59.2 -> 61.4%). Fixed ST weights 0-2.5 all
  within noise of the fit. Fitted home effect on ST plays is slightly negative.
- **Vegas implied team total as an efficiency input:** largest single factor (+0.036 MAE without it).
- **ECR blend** for RB/WR/TE only (+0.013 without); hurts QB, where the model alone beats experts.
- **Usage shares:** half-life **3** weeks (beat 5, -0.004; 8 worse). **Team-share normalization**
  (`Engine._normalize_shares`): shares are predicted player by player, so projected team totals swung 1.5x as much
  as real ones (sd .110 vs .076; over-subscribed teams over-projected). Each team's totals among players expected
  to play are pulled toward the training-measured typical total: carries 0.7, targets 0.3 -> **-0.017 MAE, RB
  -0.043, RB rank corr .507 -> .525** (carries drive it; targets alone no difference; full strength over-corrects).
- **Empirical-Bayes shrinkage** by position x draft tier, k by method of moments; TD shrinkage on expected TDs.
  Small-rate priors (scramble rate, fumbles/touch, aDOT, targets/route) fitted by method of moments (was hand-set).
- **Wind penalty grid-tuned:** 10 mph threshold, 3% per mph, 25% cap (-0.011 vs the old 15 mph / 2%); a fitted
  wind term and no wind both hurt TEs.
- **Ranges:** empirical quantiles by projection size, no extra widening (hand-set widening multipliers made
  calibration worse: 78.3/49.5% -> 80.0/50.2% inside 10-90 / 25-75 without them). TD odds: Poisson, calibrated.
- **Availability:** GB P(play) on Wed/Thu/Fri practice sequence + status (Brier .1026 vs .1081 table); healthy-scratch
  GB model (Brier .0532 vs .0678). Redistribution of vacated volume at 0.5 strength.
- **Return-timing model** (`nfledge/returns.py`, `tools/returns_eval.py`): for players out injured, P(plays team's
  next game) from games missed, designation (IR / IR-return / PUP / other reserve / active), report status, body
  part, position, week; GB classifier; chained k games ahead with a measured stay-active rate after return (an
  assumed 100% over-predicted 3-4 games out). Walk-forward Brier .132 vs .137 (designation x missed table) vs .178
  (rate); wins 4/5 seasons (2021 worse: trained on 2018-20 incl. COVID-reserve season). Isotonic calibration on
  leave-one-season-out predictions made it worse (.136), rejected. Mid-range probabilities run a bit pessimistic.
  Feeds lookahead weeks (`lookahead_availability`): < 50% sits; IR players expected back are added to the roster.
- **Power = the game model's margin vs an average team** (units x fitted points-formula weights; ST x 2c because a
  special-teams edge adds to one score and subtracts from the other) so Power and the Matchups bars agree exactly;
  it used to be face-value EPA (an untested display assumption).
- **Error breakdown** (`tools/error_breakdown.py`): share of squared error removed by fixing each layer alone: team
  volume ~0-10%, player share 10/30/34/38% (QB/RB/WR/TE), efficiency 21-31%, TDs 28-50%.
- **Versus experts** (relevant players with a pre-game ECR, 4,522 rows): MAE model 5.07 / model alone 5.12 / ECR
  5.11 / season average 5.40; better at QB (6.05 vs 6.18) and RB, tied WR/TE; strongest on injury-boosted roles
  (5.51 vs 5.72) and weeks 7+; weakest on low-data rookies/backups (4.09 vs experts 4.00).
- **Projection bias at the extremes:** 20+ point projections ~1 pt high, 8-12 ~0.3 low; a least-squares
  recalibration hurt MAE (skewed outcomes), so it is NOT corrected.

- **Depth charts by playing time (2026-10-14, adopted):** starters = each position's snap leaders over the team's
  last 3 games (missed game = 0; players off the roster / ruled Out / on a reserve list left out). Scored 2025-26
  (weeks 2+, ~5.7k team-game position groups) against who led the position in snaps that game: 87.7% vs 76.4% for
  ESPN's listed chart (last game only 84.6%, + injury filter 87.5%); wins at every position (QB 91-93 vs 88, RB 83
  vs 70, TE 79 vs 68, DL 82 vs 69). Week 1: ESPN's preseason chart wins (82.5% vs 70.5% from last season's final 3
  games), so a team's first game keeps the listed chart; from week 2 usage wins (90% vs 80%).
  `tools/depth_accuracy.py`, `tools/depth_week1.py`.

## 4. Model vs Vegas (game outcomes) -- key strategic finding
(Reproduce with `tools/vegas_compare.py` and `tools/residual_fix.py`.)
- Model-only (no Vegas inputs) margin MAE ~10.4-10.7 vs Vegas closing line ~9.5-9.8; winners 61% vs 67%.
- When they pick different winners: Vegas right **59%** (367 games 2021-25), 67% in 2026 wk 1-5 (12 games).
- Blending any weight of the model's margin into Vegas makes margin MAE worse (best = Vegas alone, w=0).
- **Against the spread** (break-even 52.4%), model lean covers 51.7% overall; by disagreement size 50.2 / 52.1 /
  55.1 / 50.7 / **48.1%** (0-1.5 / 1.5-3 / 3-5 / 5-8 / 8+ pts). The 3-5 bin is noise (+/-5.5 pts at n=316, best of 5
  bins). Bigger disagreements are WORSE: they signal information the model lacks. Totals: no edge (42-51%).
- **Residual corrections tested** (tools/residual_fix.py, test 2022-26): flat recalibration actual ~ a + b x model
  finds b = 1.6-2.1 (model margins too timid) and a = 2-4 (home under-rated) but applying it raises MAE (10.40 vs
  10.37); team "mistake memory" (recent per-team misses) -0.03 MAE, no ATS change. No learnable systematic error:
  the gap is missing information, not bias. Don't retry handicaps without new information.
- **Eval fix:** tools/game_eval.py now passes each team's most recent starting QB (it passed none, so QB effects
  were missing from every model-vs-Vegas number above it): margin MAE 10.66 -> 10.58; ATS still 51.7%.
- **Miss diagnosis** (tools/miss_diagnosis.py, 1,341 games 2021-26; excess = |model miss| - |Vegas miss|, mean
  +0.81): **surprise QB change** (game's starter != previous starter; 22% of games) excess 1.51 vs 0.60, 5/6
  seasons, 42% of all excess (eval uses last week's starter; the site uses projected starters, so verify starter
  accuracy next); **weeks 17-18** excess 1.48 vs 0.71, 5/5 seasons (resting starters / playoff status: compute
  clinched/eliminated from standings and test); weather, rest, division, inexperienced QB, weeks 1-3, rating lag:
  noise. Worst misses: model ~even where Vegas had 13-20 pt favorites (ratings over-shrunk for margins; test
  margin-tuned shrinkage). The absence tags (Out/Doubtful snap share) came out empty: a join bug to fix first.
- **Win probabilities** (tools/win_prob.py, walk-forward, 1,082 games 2022-26, P = logistic(k x margin), k fit on
  prior seasons): Vegas Brier 0.2113 / log loss 0.610 / 67.3% right; model 0.2353 / 0.664 / 61.6%; always-home
  0.2486. k: model 0.125-0.141, Vegas 0.118-0.148. Vegas well calibrated in every band. The model is under-confident
  under 65% (52.5% predicted -> 56% won) and over-confident at 70%+ (73% -> 67%, n=91): the same over-shrinkage as
  the miss diagnosis. Blend (logistic in w x model + (1-w) x Vegas, w and k fit walk-forward): w = 0-0.15, Brier
  0.2115, no gain over Vegas alone.
- **Power rank as a predictor** (tools/rank_predictor.py, ranks as of the week before, 1,337 games): better rank
  wins 61%; by gap 1-3 / 4-7 / 8-12 / 13-19 / 20+: 50 / 57 / 61 / 67 / 74%. Walk-forward Brier: rank gap + home
  0.2291 beats the SAME ratings as net gap + home 0.2316 (CI excludes 0) and the model margin 0.2353 (with home
  term 0.2349): rating-gap magnitudes are unreliable at the extremes; ranks discard them. Not yet adopted.
- **Darts** (tools/darts.py, 28 pre-game signals, walk-forward 2022-26, each alone / on top of rank + home / on
  top of Vegas): only **Elo (538 recipe: K 20, HFA 48, MOV multiplier, revert 1/3)** helps on top of rank: -0.0065
  [-0.0110, -0.0024], 5/5 seasons; Elo alone 0.2239 beats rank and model. Referee x team bias (vs spread) HURTS
  (+0.0043, noise); referee home rate, QB top/bottom 5, record, point diff, Pythagorean, close-game luck,
  turnovers, streaks, rest, bye, Thursday, prime time, division, travel/tz, west-early, dome-in-cold, surface,
  new coach: nothing. Nothing adds to Vegas. **SHIPPED 2026-10-12 (tools/elo_eval.py):** Elo fit walk-forward (350
  settings, log loss on prior seasons; stable K 16-20, HFA 25, revert .33-.5, margin yes). "Our model" win chance =
  logistic(home + rank gap + Elo/100) = Brier 0.2228 vs site's model-margin 0.2353 (-0.0125 [-0.0174, -0.0077])
  and rank + home 0.2292 (-0.0064 [-0.0108, -0.0023]); gains in weeks 2-6 AND 7+ (not just carry-over); adding
  net gap on top: nothing. Half the gap to Vegas (0.2111) closed. Coefs in config [report.win_model],
  nfledge/elo.py. Next ideas: Elo-style result memory inside the team ratings themselves; per-game QB adjust for Elo. **Referees vs the market** (tools/referees.py, 2,447 games 2017-26,
  33 refs, shuffle tests within season): home ATS by ref 1.42x chance spread (p=0.09) but no persistence (first-half
  vs second-half r = -0.05); totals vary LESS than chance (0.43x, p=0.99: the total line likely already prices
  the crew); ref x team ATS exactly chance (0.95x, r = 0.00). Extremes like Vinovich 40% home covers (144 games)
  don't carry forward. No referee effect to use. Next: fit Elo constants walk-forward; check if its gain is early
  season (cross-season carry-over our ratings lack).
- **Tossup line**: favorites the market gave under 59% won 54.3% +/- 6.4% (90%; 15% of games), indistinguishable
  from a coin flip; 3-point favorites (~60%) won ~61%. The tool prints the largest cut-off a coin flip explains
  (0.59) and the model's all-games k (0.141); both live in config.toml [report].
- Implication: the game model's value is structure (battles, Power), not beating lines; fantasy projections already
  use Vegas implied totals. **Shipped 2026-10-12, owner's "good prediction practice" pivot:** Matchups shows win
  chances, not picks. Headline = market chance when a line exists (model only before lines post), "Tossup" under
  59%, model chance as second opinion, edge pills removed, finals read "Favorite won" / "Upset, a 20% chance" /
  "Tossup, X won", and a track-record table (market favorites by confidence band, expected vs won, all seasons and
  this one). Still open: market-implied ratings for lookahead weeks without lines.
- **Opponent defense terms in the efficiency models (2026-10-14; ADOPTED "drop", owner delegated the call):** with the Vegas
  implied total and schedule-adjusted player rates in, `def_pass` / `def_rush` fit ~0 and several are
  wrong-signed (QB pass_td, QB rush_td, WR rec_yd). Gate set before running: adopt "drop" if MAE not worse (CI
  includes 0 or favors it) and no P(1+ TD) Brier worse. Walk-forward 2021-2026 (`experiments.def_terms`):
  drop = MAE -0.002 [-0.004, -0.000] overall, QB -0.008 [-0.016, -0.000], RB/WR/TE no difference, better in all
  6 seasons; TD Brier (QB pass/rush, RB rush/rec, WR/TE rec) all no difference. sign-constrained (refit without
  the term when wrong-signed) = no difference anywhere. Dropping the implied total instead = worse at every
  position (ALL +0.029 [+0.020, +0.038], QB +0.105): Vegas carries the opponent information, the defense terms
  fit noise. Passed the gate; config `def_terms = "drop"`, archive rebuilt.
- **Matchup display (2026-10-14):** the old 1st-32nd "defense vs position" rank measured only the defense
  ratings' effect beyond Vegas (max ~0.5 pts) and stretched it over a 32-step color scale; its order was mostly
  noise. Now `report.matchup_effect` = projection minus projection vs a league-average opponent: Vegas implied
  total minus the MARKET's defense term (`report.market_lines`: implied = mu + off + def + home x h, least squares
  over the season's lines, as-of weights incl. this week's lines; SEA -3.9 .. DAL +2.9 pts, home 0.77), team
  volume via the game model's Vegas formulas on the neutral lines, defense ratings 0. Our own game model's
  opponent effect was much milder than the market's (Stafford vs ARI +0.5 vs +1.4), and "season-average implied"
  counts QB changes / form as matchup. Week 6: |matchup| median QB 0.6, RB 0.6, TE 0.3, WR 0.2 pts. Color is
  continuous (owner): white at 0.0, faint tint (0.22) up to full at the week's 90th pct of percentile-point shift
  across fantasy starters (pooled); Soft/Tough tags = top quarter.

## 5. Tested and rejected (do not retry without new data/angle)
| Idea | Result |
|---|---|
| Team-specific home field | No persistence: corr -0.02 over 567 team-seasons (2005-25) |
| Recency by games played instead of calendar weeks (a bye doesn't age a team's / player's games; 2026-10-14) | Null: team ratings, usage shares and both together all within +-0.001 MAE at every position, 2021-25 walk-forward, CIs straddle 0. Week-6 2026 check: Mahomes 17.54 -> 17.57; largest mover +0.38 (K. Walker). Kept calendar weeks |
| Travel distance / time zones in HFA | No effect |
| Division-game HFA term | Real in results but worsened play-level CV; off |
| Shared stadium (LA, NY) adjustment | 7 games ever; no evidence |
| Air-yards share / aDOT | +0.004 (worse) |
| Snap share as a volume input | No gain (owner: snap trend is an alert) |
| TD blend strength k 50 / 400 | No effect |
| Stat-weighted defender values (PFR) | Overfit, worse OOS |
| Defensive / O-line / cornerback absences | No reliable pre-game signal |
| Pace / drive sustainability in volume model | No gain in plays MAE |
| Fitted wind term (instead of fixed penalty) | TE +0.012 (learned a positive TE effect) |
| Per-position share half-life | No difference |
| Spread-aware (game-script) shares | No difference (recent usage already carries it) |
| Finer draft-pick tiers for priors | No difference |
| Final linear calibration of projections | +0.013 (worse) |
| Starter QB share measured (0.97) vs 0.96 | +0.001 (worse) |
| Range-widening multipliers | Worse calibration |
| Isotonic calibration of return model | Brier .132 -> .136 |
| Game-margin handicaps (flat recalibration, team mistake memory) | No ATS gain |
| Coach 4th-down aggressiveness -> goal-line volume (`experiments.coach_aggr`, 2026-10-14) | Trait persists (coach go-rate on 4th-and-<=4 from the 40 in, shrunk vs league season rate: corr .36 [.27, .46] year to year) and shows in raw data (+0.30 inside-10 rushes/game per +10pp [+0.12, +0.50]; offensive TDs +0.08 [-0.03, +0.18], ns). As a team goal-line-model input (prior season): MAE identical all 6 seasons, TD Brier no difference. Real but too small (1 sd coach ~ +0.03 TDs/game) |
| QB-specific target shares (2026-10-14) | After a QB change, no position / depth tilt (RB -0.4, TE -0.6, WR -0.3 pts of share; short vs deep aDOT the same). A receiver's share WITH the incoming passer (shrunk, this + last season) predicts WORSE than his recent overall share at every k (k=10 +0.7 [+0.5, +0.9] pts of share error, k=200 +0.1 ns): pair history is stale. The surprise-QB-change error isn't target redistribution |
| Red-zone target role x team red-zone volume (`experiments.rz_struct`, gl_struct for WR/TE) | MAE no difference anywhere; P(1+ rec TD) Brier WR -0.00003, TE -0.0001 [-0.0003, +0.00005]: no difference. xTD already prices target location |
| Passing-down back x expected trailing (role-specific, after spread-aware shares was rejected) | tilt (3rd/4th-down vs early-down share of team RB targets) x expected deficit: +0.06 pts of team target share at 1 sd each, CI ~[-0.2, +0.2]: nothing |
| RB workload carryover / age x workload | Heavy last game (vs his norm) x short rest: no effect on next share (+0.03 [-0.02, +0.08] per touch per day) or yards per touch. Extra touches last game -> MORE share next game (+0.7 pts per touch): recency, already weighted. Age x cumulative season touches -> yards per touch: +0.015 [-0.016, +0.043] per yr per 100 touches: nothing |
| Garbage-time share of recent points -> next-week error | +0.002 [-0.06, +0.07] pts per +10 pts of share (all), no position significant: nothing |
| Folklore: revenge games, primetime | Revenge (vs a former team) -0.04 [-0.76, +0.64]; primetime -0.19 [-0.53, +0.16]; a player's primetime gap doesn't persist (corr +.04 [-.06, +.15]) |
| Division familiarity (2006-25 results, 2021-25 backtest) | First-meeting loser vs spread in the rematch -0.11 [-0.93, +0.70]; rematch margins +0.8 larger [0.0, +1.6] but not vs the spread; players in 1st / 2nd division meetings vs projection ns. Division games went under the total by 1.5-1.8 pts more than others 2006-19, but -0.09 [-1.41, +1.20] since 2020: the market corrected |
| Age as a model input (`experiments.age_input`, owner, 2026-10-14) | Descriptive: walk-forward error drifts with age, WR -0.10 pts/yr [-0.16, -0.04], RB -0.08 [-0.15, -0.004] (young RBs 21-23 +0.8 [+0.1, +1.5] above projection), QB/TE none; raw output by age is flat (survivors). One linear age term in all share + efficiency regressions: MAE ALL -0.000 [-0.004, +0.003], RB -0.004 [-0.008, +0.001], QB +0.010 [-0.001, +0.022], seasons mixed; QB pass-TD Brier -0.0004 better, others ns. Gate (overall MAE better) not met. Owner: stars age well (Brady, Adams), make it position-specific -> RB/WR only (`age_input = ["RB", "WR"]`), linear and quadratic (`age_shape`): RB -0.004 [-0.009, +0.001] / -0.002, WR -0.002 / -0.002 (both ns), TE +0.001 worse, 2026 worse in both. Rejected: the drift is real in the residuals but a fitted age term doesn't recover it out of sample |
| Insensitive (kept): train window 2/3/4, prior weight/decay, eff season weights, WP window, QB-inexp cutoff/penalty, GB sizes, redistribution trigger, team half-life | within noise |
| Gradient border / white logo circles / light pills on dark rows | Owner rejected visually |

## 6. Engineering gotchas
- **ESPN feed from the browser:** use `site.web.api.espn.com` for BOTH scoreboard and summary; `site.api.espn.com`'s
  scoreboard drops the CORS header for Chromium (Chrome / desktop Brave) though curl and WebKit get it. Never pass
  a fetch `cache` option: Chromium then adds Cache-Control/Pragma request headers, forcing a CORS preflight ESPN
  doesn't answer. ESPN team codes differ only for LA (LAR) and WAS (WSH). Play clocks have no numeric value: parse
  `clock.displayValue` "mm:ss". nflverse rosters carry `espn_id` (gsis -> ESPN athlete id; 18/18 matched on a game).
- **Testing pages that fetch JSON:** file:// blocks fetch; serve the build (`python -m http.server` in the output
  folder) and use `tools/screenshot.py --url=... --wait=... --click=...`. Check desktop in Chromium too, not only
  WebKit (the CORS issue above only showed in Chromium).
- **Windows shell + heredocs:** backslash escapes get mangled, and a Python patch string containing `\n` writes a
  real newline (broke a JS/print once). Use Write/Edit for code with escapes. `run.py` node-checks the page script.
- **Stop commands:** never combine `Stop-Process` with another command that might be permission-blocked (a blocked
  `Remove-Item` silently cancelled the whole command once, leaving a duplicate batch running and eating RAM).
- **Bash tool cwd resets** each call; `cd /c/Dev/BosDev/nfl-edge && ...`.
- **Multiprocessing on Windows** (spawn) can't start workers from a script piped on stdin: write a `.py` file.
- **Speed (keep):** ridge normal equations solved with Cholesky (`sla.cho_solve`; `np.linalg.solve` was 85 ms vs
  0.5 ms per pass-unit solve, 170x); normal equations built once per CV fold and reused across the alpha grid;
  player features via one factorize + `np.bincount` (2x vs groupby) and memoized per (season, week, ratings);
  vectorized QB-starter pick. Training 120s -> ~40s; backtest season 110s -> ~90s.
- **Parallel workers:** set OMP/OPENBLAS/MKL threads = cores / jobs before importing numpy (experiments.py does);
  each worker with 2018+ data holds ~1.4-1.5 GB; 9 workers saturate this 8-core/16-thread machine (~94% CPU).
- **Experiment cache keys** include model code: editing `nfledge/*.py` while a batch runs makes later jobs recompute
  (and results computed by already-running workers get labeled with the new hash; harmless only if outputs are
  identical). Defaults-preserving refactors were verified identical (max diff ~1e-14) before relying on that.
- **pandas 3:** Arrow-backed strings (empty week-1 frames come back as str dtype: cast to float); `Series.map` with
  datetimes can fail (merge instead).
- **CSS on table rows:** never decorate rows with pseudo-elements (`tr::after` detaches in iOS WebKit and floated as
  a stray colored line). Row trim = inset box-shadows on cells (`--top`/`--side`/`--extra`).
- **Sticky + overflow:** an `overflow-x:auto` wrapper traps `position: sticky`; see UI section for the solution.
- **iOS:** native `<select>` ignores dark styling unless `appearance: none`; `backdrop-filter` needs the `-webkit-`
  prefix (or just use an opaque background); `[hidden]` is overridden by any `display:` rule (add `x[hidden]{display:none}`).
- **Class-name collisions:** scope generic names (`div.stale` vs `td.ecr.stale`).
- **Visual QA:** `python tools/screenshot.py TAB [--device=desktop] [--pos=WR] [--page-y=N] [--table-x=N]`
  (Playwright WebKit iPhone 13 by default; dev-only install: `pip install playwright` + `playwright install webkit
  chromium`). For behavior tests, drive Playwright directly (click, select_option, check console errors). File://
  pages can't fetch `weeks.json` (CORS); harmless.
- **Caches:** `cache/model_<key>.pkl` (engine + projections; feature memo excluded from pickle),
  `cache/backtest_<key>.parquet`, `cache/experiments/<variant>_<season>_<key>.parquet`; keys hash config minus
  display-only sections (`docs.model_config`), scoring, data state, model code.
- **Late nflverse data (Monday games):** the schedule marks a game final hours before nflverse publishes its
  plays/stats/snaps (BUF@LA MNF 2026 wk5 was still missing Tuesday night). The final-count refetch trigger fires
  once, too early, so `data.missing_finals` also forces an hourly refetch while any final game is absent from the
  cached pbp/snaps/stats. Archive pages had the same flaw (built once, Tuesday morning): `site/archive.json` records
  each page's coverage `[pbp games, stat teams, snap games]`, and `--missing-only` rebuilds a page whose count rose.
- **MODEL.md fingerprint** covers `nfledge/*.py` except `report.py`/`docs.py` plus config (minus display sections);
  any model-code edit needs `tools/model_doc.py --stamp` (the pre-commit hook blocks otherwise).

## 7. UI decisions (current state)
- Dark team tiles (#171a20), white text, 2px primary border + full-height 3px secondary stripe inside left/right
  edges, drawn on cells. Logo circles in team primary or secondary (chosen by logo pixels). Position badges: QB rose,
  RB green, WR blue, TE amber.
- **Header:** season / week picker (dark custom selects), "Back to the current week" on other weeks; pills: games
  used, "Week N: x of y games final", scoring, injury report, updated. Tab bar opaque.
- **Rankings:** QB/RB/WR/TE/FLEX (FLEX built in the browser from RB/WR/TE rows, top 150: a 14-team league starts
  84 flex-eligible). Columns: #, ECR (positional; "lw" until Friday), Player (pinned), Projection (number + range
  bar + floor-ceiling; header aligned with the number), Actual (once games are final; green above 75th pct,
  red below 25th), Matchup (fixed slots: @/vs, logo, code, 5-bar meter, DvP rank), Inactive (centered), FP/G, Tier,
  Expected line (TD donuts), Takeaway. Rows listed at >= 2 projected points + every team's QB1.
- **Scoring & league panel:** presets (Half PPR, PPR, Standard, 6-pt pass TD, TE premium), per-stat values
  (yards as "yards per point"), teams / roster slots / flex / superflex; re-scores projections (exact from stat
  lines; blended projections and ranges scaled by the ratio), Actual, FP/G, weekly bars, ranks and tiers in the
  browser; saved in localStorage.
- **Tables:** full length, only the page scrolls. If a table fits its width (`.fits`) the real header sticks
  natively; wider tables (phone) scroll sideways with a header copy in a sticky strip under the tabs. Pinned name
  column; compact mode when scrolled sideways (logo + last name, 11px, ~100px), scrollLeft compensated, hysteresis.
- **Matchups:** "win chances, not picks" (owner: "we're not a betting site, we're promoting good prediction
  practice"). Track-record table on top. Per game: win-chance box (favorite logo + "Cowboys 80% to win" or
  "Tossup / too close to call", source label above it "Vegas odds" or "Our model, no Vegas line yet" (owner was
  confused by two different % on one card when the tag was small, right-aligned "Market"), bar split in team colors with the tossup zone hatched,
  Vegas line + O/U and "Our model: DAL 76%" underneath); away left / home right. **Owner rule: the model never
  publicly shows a point spread, score or total, only win %** (spreads are the market's). Battles in EPA per 100
  plays: the two offense-vs-defense totals (play-weighted; tap for Pass/Run), Special teams (per 100 ST plays),
  Home field (per play); power-rank chips by the team names; pace as "Projected plays: TB 61 (62% pass)". No
  Overall bar. Bar LENGTH = the edge's impact on the game through the fitted points formula (never printed), one
  scale for all rows: full bar (90%) = 95th percentile of offense-vs-defense impact over all pairings that week.
  Finding (2026 wk 5 fit): b = 0.68 pts per offensive EPA, c = 2.34 per special-teams EPA, so +1 EPA/100 is worth
  0.41 pts over ~60 scrimmage plays but 0.53 over ~11 ST plays: per unit of edge, ST weighs MORE (field position).
  ST bars are usually shorter only because teams differ less on ST (sd 1.9 EPA/100 vs 3-4.5 for pass/run units).
  Final score + Favorite won / Upset (with its chance) / Tossup outcome.
- **Power:** model margin vs average team by unit (7 ranks), rank range, schedule played/left, trend.
- Tabs: Rankings, Matchups, Power, Role changes, Model.
- **Player card / live / gamecast (2026-10-13):** shared `nfledge/static/gamecast.{js,css}` copied to the site root
  `assets/` and `game.html` (from `nfledge/pages/game.html`) by `report.write_site_assets` on every render, so archived
  pages get fixes without a rebuild. Each week page also writes `<page>.json` (report.week_data: players with
  ESPN ids, stat lines, ranges, pregame chances, battle bars; ~410 KB raw, ~60 KB gzipped). Rankings rows open a
  player card (replaced the old detail row; `#player/<gsis>` deep-links). Matchups tiles get a "Gamecast" link and
  a live strip while in progress (no ESPN win % on tiles, owner rule); gamecast page `game.html?d=<json>&g=<game_id>`
  has ESPN live win % (labeled ESPN, separate from pregame), game log (drive / every play, filters, WP swing per
  play), box score with fantasy pts vs our projections incl. targets, team stats, pregame box, replay mode for
  finished games. Test switches: `?sim=1` (week page: finished games treated as live), `&replay=1` (game page).
  Owner tests real live on Thursday night games. **Player news** on cards (current / lookahead weeks): RotoWire
  blurbs from ESPN's fantasy feed `site.web.api.espn.com/apis/fantasy/v2/games/ffl/news/players?days=60&playerId=<espn>`
  (CORS-open, one player per request; no bulk / multi-id form), fetched in the browser on card open, cached 5 min,
  never stored. Push notifications would need a server or a CI job + a push service (e.g. ntfy.sh): not built.
  **Career game log** on cards (owner asked for Sleeper's log with every season expanded): `tools/player_logs.py`
  (CI step after run.py) writes `site/data/players/<gsis>.json` for everyone on any week page (~1,000 players,
  ~8 MB): every REG game since 1999 (stats cached per season), snap % from 2012 (pfr -> gsis via load_players),
  home/away from the 1999+ schedule, weekly position rank (site scoring), and OUR pregame matchup rank +
  projection read from the published week JSONs (2021+, incl. lookahead weeks) - not hindsight.
  **Player card layout (2026-10-14, owner spec):** one building block everywhere, the stat grid (`.sg`: value over
  small label, rows are CSS subgrids so columns line up and short rows leave blanks; optional left label column).
  Profile box under the header: Age (to a tenth), Height, Weight, NFL yrs, Draft "R1:7 '18" (pick within round from
  nflverse draft table; OverTheCap fallback; UDFA), College (first listed = final school), then Contract (per year,
  total, guaranteed, % of cap, signed, free agent) from nflverse `load_contracts` (OverTheCap; active deal; cached
  24h in tools/player_logs.py). OverTheCap "years" on an extension = added years only (CMC 2024 2y ext runs
  through 2027), so the free-agent year comes from `season_history`: the season after the last one with cash paid
  (void years carry placeholder salaries 85 / 99 but $0 cash: Allen lists 2033, paid through 2030 -> FA 2031);
  deals with no cash posted yet (2026 rookies, minimum signings) use signed + years - 1. Week tab: Projection (big number + one rank pill "QB #1" colored by roster tier,
  replacing the tier badge + "QB1 in week 6" line; "% inactive" chip, reason at >= 5%; Floor / Middle / Ceiling /
  Confidence row) + Expected line (grid; TDs as chance of 1+); full-width Matchup tile with kickoff, click anywhere
  -> gamecast, team code -> team card; Season box (Scoring, Passing/Rushing/Receiving, Usage incl. QB scramble %
  this season + career, then Points bars green/red vs our projection with a tick, and Snap % bars on the same week
  columns, last 8 weeks; snap row hidden when every game >= 95%, i.e. most QBs: no 2026 participation data to drop
  garbage time). Then 3 latest news + last 5 games with "Show more" into those tabs.
  **Team card** (2026-10-13): same overlay/tabs (Overview / Game log / Players), `#team/<ABBR>`; opens from Power
  rows, Matchups tile headers (`.tm-open[data-tm]`), player-card team names, gamecast scoreboard. Week JSON now
  carries `power` (incl. `rank_hist`, this week pinned to the headline rank) and `teams` (names/logos/colors).
  `tools/player_logs.py` also writes `data/teams/<T>.json` (~3 MB): every REG game since 1999 (schedule + Elo +
  nflverse team stats), 2021+ our pregame chances and both power ranks, season averages with league ranks,
  remaining schedule. **nflverse team-stats EPA does NOT reconcile with pbp** (avg gap 6 EPA/game over 2026;
  one game matched exactly): team log shows yards/play instead. EPA from our own pbp would need 1999-2018 pbp.
  **Linking (2026-10-13):** one click rule in gamecast.js, innermost wins: `[data-open-pid]` / `tr.main[data-pid]` ->
  player card, `.tm-open[data-tm]` -> team card (Rankings opponent, byes, Role changes, Matchups QB names and team
  headers, card team names, game-log opponents, gamecast drive / box / scoreboard teams). ESPN play text "D.Prescott"
  is linked via first-initial + last-name (ties broken by the game's two teams). Card matchups open the gamecast
  (they jumped to the Matchups tile until the redesign below). **Gamecast game log:** newest first by default; sort Newest / Oldest /
  Biggest swings (top 40 by |ESPN WP change|); plays tinted by the team with the ball (lightened for dark colors),
  special teams neutral, timeouts / end-of-period as thin dividers; event chips TD/FG/XP/INT/FUM/SACK/FLAG/1ST.
  First down = next real play of the drive starts at 1st (from 1st down only if full distance gained; never on goal
  to go). Drive results are phrased for the offense ("Intercepted by TB").
  **Cards are week-independent (2026-10-13, owner's "option 3"):** header (current roster team from the log doc),
  game log and news are always current; a week picker on the card's Week tab (any week in `weeks.json`, default =
  the page's week, prev/next steps, kept when hopping card to card) lazily fetches that week's `<page>.json` and
  drives projection / matchup / availability / season-to-date (player) or matchup, odds, Power box, Players (team).
  Live overlays only apply when the picked week is the page's own. Players we didn't list that week still get a
  card ("not on our board" + his actual line from the log when he played). Log docs carry `name` and `espn` (cards
  open without a week row) and per game `gid` + `f` (week file). **Game-log rows (2021+) open that game's matchup**
  (owner: rows are links, not a week picker): now that game's gamecast, `game.html?d=<f>&g=<gid>`.
  **Owner model ideas tested (2026-10-13), both rejected (switches stay, off):**
  - Elite-unit weighting (`experiments.elite_boost/elite_top/elite_mode`, `TeamModel._elite_weights`): plays vs
    top-K opposing units (by the as-of fit) up-weighted. `tools/elite_eval.py` scores next-week team-game EPA/play
    MSE x1000 (baseline 80.995 over 2021-25): top-8 x2 +0.556 [+0.19,+0.94] worse, top-5 x2 +0.564 worse, linear
    ramp +0.363 worse; top-3/5 at 1.25-1.5x and top-8/12 at 1.5x all within noise (top-3 1.25x +0.035 [-0.07,+0.15]).
    Player MAE unchanged. Ridge already adjusts each play for the opponent; elite games are too few to add signal.
  - RB committee (`experiments.rbbc`: team lead-back carry concentration + interaction in the carry-share model)
    RB MAE -0.001 [-0.003,+0.001]; goal-line tilt (`experiments.gl_share`: inside-10 share minus carry share in the
    rush-TD rate model) -0.002 [-0.005,+0.001]; both -0.003 [-0.006,+0.000]. WR "better" -0.001 = noise-level.
    Concentration persists r=0.36 season to season (inside-10: 0.19); same head coach 0.36 vs new 0.29, CI on the
    difference [-0.20,+0.34]. 2025 range: SEA 0.54 (most committee) to IND 0.88 (most bellcow). Ledger gained
    carries_i10 / team_rush_i10 (unused unless gl_share is on).
  - Follow-ups (`tools/rb_followups.py`, metrics fixed before looking): gl_share on P(1+ rush TD) for RBs, Brier
    0.1896 -> 0.1893, diff -0.0003 [-0.0007,+0.0001] = no difference. Subgroups: goal-line share 10+ pts above
    carry share (n=1002) baseline under-predicts (actual .349, base .308, gl .325; Brier -0.0016 [-0.0027,-0.0005]);
    10+ pts below (n=933) gl over-corrects (.262 / .272 / .256). Net wash; owner agreed to stop if flat. RB range
    calibration by committee tercile all on target (10-90: .784/.813/.789; 25-75: .475/.518/.489). Display-only
    bellcow index on team cards: skipped (owner's call pending; the Players tab shows the split already).
  - **ADOPTED: `experiments.gl_struct`** (owner: "who cares if you're a goal-line back whose team is never on the
    goal line"). Diagnostic first: goal-line-heavy RBs on high-implied teams under-predicted 8.7 pts (n~240),
    exactly right on low-implied teams; the flat tilt over-shot bad teams. Structural term in the rush-TD rate:
    gl_frac = team inside-10 rush fraction (Linear on implied_pts + off_rush, per team-game; ~+0.004 per implied
    point) x gl_ratio (player i10 share shrunk with GL_RATIO_K=10 toward carry share, / carry share, cap 4).
    Pre-set gate met: RB P(1+ rush TD) Brier -0.000214 [-0.000434, -0.000004], 4/5 seasons better (2022 +0.00006),
    Poisson log-lik -0.7339 -> -0.7333, RB MAE -0.0004 [-0.0018,+0.0009]. Fitted RB weight +0.053 (QB -0.010).
    Gap closed only partly (high-scoring vultures 8.8 -> 7.6 pts): room for a stronger form later.
  - QB vulturing (owner): RBs whose QB takes many inside-10 runs are NOT over-projected (team_rush_i10 counts QB
    sneaks, so their i10 share already shrinks): actual .308 vs pred .277 (n=455, noise). Vulture QBs mixed/noise.
    Real miss = pocket QBs on high-scoring teams over-projected for rush TDs (.085-.088 actual vs .132-.134).
    Tested `experiments.qb_rush_split` (QB-only scr_frac + implied x designed share in QB rush-TD rate; gate set in
    advance): QB P(1+ rush TD) Brier -0.0002 [-0.0006,+0.0002] no difference, QB MAE +0.0013 [-0.0032,+0.0056];
    pocket/high gap 4.9 -> 4.0 only. OFF. Side finding: QBs over-predicted overall for rush TDs (.175 vs .157):
    a general QB rush-TD calibration issue, not tested yet.
  **Availability fixes (2026-10-13):**
  - BUG: healthy-scratch history counted the Monday BUF-LA game (final score in schedules, but nflverse pbp + snaps
    not published yet) as played-by-nobody: every BUF/LA player looked inactive in week 5 (Allen 21%, Stafford 40%
    scratch risk). Fix: a game counts as history only once its participation data exists (ledger or snaps).
  - STOPGAP (owner-approved, UNVALIDATED): ESPN early-week bridge (`nfledge/espn.py`, `InjuryModel.build_espn_bridge`,
    run.py live week only; part of the model cache key). Out / IR / Doubtful posted after the team's last game, team's
    report not out -> scored with p_next for that designation, status "X (ESPN)". First run mapped Questionable too
    (148 players incl. Lamb, Barkley at 27%): ESPN keeps Q on players who played through things, so Q/Day-To-Day
    are ignored (36 players, 8 fantasy-listed: Deebo 67%). TODO when ~6+ weeks of data/espn_injuries snapshots
    exist: compare ESPN early-week statuses with who played; refit rates or drop the bridge. Not used for lookahead
    weeks (ESPN return_date untested there).
  **Model tab everywhere (2026-10-13):** archived / lookahead pages used to show a one-line "archived week"
  placeholder. Now the current build writes the tab once (since Phase 6: `<site>/data/model.json`, drawn by
  `assets/model.js`; before: `model.html` from a Jinja template) and every week fetches it on first view, so every page
  shows the same, current description. MODEL.md opens with "The short version": a plain-language summary for
  non-technical, casual fans (owner's request); the technical detail follows unchanged.
  **Strict JSON (2026-10-13):** week files are written through `_json_safe` (NaN / inf -> null, `allow_nan=False`).
  Python's default emitted `NaN` (sos_past in week 1, sos_next on every archived week), which browsers can't parse,
  so the card's week picker said "no page" for ~95 weeks. Python readers (player_logs) never noticed.
  **Dark only (2026-10-13):** owner's call; light-theme tokens and `prefers-color-scheme` rules removed.
  **Matchups -> gamecast redesign (2026-10-13, owner):** the Matchups tab is now a dense selector: one compact tile
  per game (`a.mt`, the whole tile links to `game.html?d=&g=`; 1 per row on phones, auto-fill min 360px so 3
  across on desktop). Owner's look: team logos on the outside fading toward the middle (CSS mask), the two
  `bt_style` colors blending across the tile, @ (vs if neutral) in the center, one big number per side = win %
  before kickoff (Vegas, or ours before a line; underdog dimmed, both dimmed for a tossup), the score once live /
  final. Footer: kickoff + Vegas spread + "ours X%"; live = painted by `paintTiles` (clock, down and distance,
  possession dot); final = verdict pill. The gamecast tab for in-progress games is "Live" (owner: not "active"). Tile how-to and
  the "How often favorites win" table were removed from Matchups (owner: self-explanatory or in the Model tab); the
  table now sits at the end of the Model tab (`#track-record`). The full old tile (odds, battle bars, projected
  plays, team ratings) moved into the gamecast **Pregame** tab, rendered client-side from the week JSON (one
  renderer, `preTab`), plus every fantasy player in the game. Gamecast tabs Pregame / Live / Postgame open on the
  one matching ESPN's state (`GP.tab`, sticky once chosen); Postgame = result + verdict, full ESPN WP chart, top 6
  WP swings (`gameLog(..., {sort:'impact', limit:6})`), fantasy actual vs projection, team stats, replay (which
  switches to Live). If ESPN is down the page still renders from our file (`infoFromG`). Every matchup link (cards,
  log rows) now goes to the gamecast; tile jumping (`goToTile`, `#g-` scroll) is gone and old `#g-<id>` links
  redirect to the gamecast. Tile sides gained `record` and `rank`. Fixed in passing: the open "Pass/Run" label had a
  stray U+0091 control char where a minus sign belonged.

## 8. Site / pipeline
- `index.html` = current week: the week being played (any final game) until **Tuesday 06:00 ET** after its last
  game (`run.display_week`), then the next week. Daily CI at 14:00 UTC publishes the rollover.
- `<season>/week-NN.html`: archived weeks 2021 -> last week (built once by `tools/build_archive.py`, walk-forward,
  ~10 s/page, 1.9-3.2 MB; stored on the **`archive` branch**, which CI checks out into `site/`, appends missing
  weeks to, and pushes) and **lookahead** weeks (rest of the current season, rebuilt every run with
  `run.py --lookahead`, never committed; return-model availability, healthy otherwise, neutral weather, Vegas
  lines when posted). `weeks.json` (rewritten every build) feeds every page's picker so old pages list new weeks.
- **Archive pages reflect the model at the time they were built.** After model changes (e.g. share normalization,
  2026-10-12), regenerate: `tools/build_archive.py 2021-2026 --out=<dir> --jobs=6` (~8 min, needs ~10 GB RAM),
  then replace the files in a checkout of the `archive` branch and push.
- CI: `.github/workflows/deploy.yml` (contents: write for the archive commit; ~4-5 min per run).
- **Client-rendering migration (started 2026-10-14; owner's plan, phases 0-6):** Python writes DATA only (JSON);
  the browser renders. Done: app shell (`assets/shell.js`: 4 parents Players / Teams / Games / Model + sub-tab
  chips, hash routes `#players/stats`, old `#games` etc. mapped; phones: bottom tab bar with the chips above it,
  top nav hidden, owner's choice; `NAV_MODE = 'top'` keeps the old top strip in code), `NFLE.load` (cached JSON),
  `NFLE.Table` (`assets/table.js`: the one table component; fixed column widths when every column has `w`, so
  stacked tables align), area modules (`assets/<area>.js/.css` loaded on a tab's first open; shell.js `AREAS`), dev
  loop `tools/dev.py` (assets served live from `nfledge/static/`). New tabs: Teams > Standings
  (`data/standings/<season>.json`, `tools/standings_build.py`, 2002 on), Teams > Stats + Players > Stats
  (`data/stats/{teams,players}_<season>.json`, `tools/stats_build.py`, 1999 on; finished seasons aggregated once
  into `cache/seasonstats_*`; current season redone when a game goes final). Rankings / Power / Matchups / Roles /
  Model were still Jinja-rendered then (all client-rendered since Phase 6, below). `window.NFLE` is shared: modules MERGE into it (gamecast.js used
  to overwrite it, which wiped the shell's loader). Next (owner, 2026-10-14): player / team PAGES as routes
  (`#player/<id>`, `#team/<abbr>`) instead of overlay cards, with breadcrumbs and a working back button, before
  the Rankings migration.
- **Phase 2 done (2026-10-14): Players > Rankings renders in the browser** (`assets/rankings.js`) from the week JSON
  (`players` + `rk`: byes, show_act, tier teams; per player photo / vol / td / imp / byes / pend / pjw / ECR flags;
  JSON shape `"v": 2`). Rows are data: the scoring panel recomputes projection, range, rank, tier, slot, vs ECR and
  redraws through `NFLE.Table` (same cell markup and classes as the old template, so the template CSS still styles
  it). Old vs new compared side by side (desktop + iPhone, QB + FLEX): identical except rounding (JSON now keeps 3
  decimals). Week JSONs without `rk` (archived pages until rebuilt) keep their server-rendered table.
- **Players > Injuries** (2026-10-14): ESPN's injury list (`data/espn_injuries/latest.json`, written by the daily
  snapshot step) joined to our inactive % from the week data. Building it exposed a bridge bug: ESPN "Injured
  Reserve" was mapped to Out and scored with Out's carry-forward rate (67% inactive: a third of players listed Out
  play the next week). IR is a roster rule (4-game minimum), so the bridge now maps it to "IR" = inactive.
- **Tiebreakers** (`nfledge/standings.py`, presentation-side: excluded from the model fingerprint and cache key):
  division, wild card, seeds; seeds match ESPN's official seeding 2014-2025 exactly (24/24 conference seedings).
  ESPN's own standings feed before 2014 is incomplete / wrong (missing or partial seeds), so older seasons were
  spot-checked against known history instead (2006 NFC, 2007 AFC, 2009 AFC correct). Stopgaps: net touchdowns and
  the coin toss (fixed alphabetical) are not modeled; mid-season strength of schedule uses games played so far.
  The League keeps per-team result lists (not a DataFrame) so one seeding takes ~1.4 ms (the odds sim seeds 10,000).
- **Playoff odds (Phase 4b, 2026-10-14):** `tools/playoff_odds.py` -> `data/playoffs/odds.json` (CI, 10,000 sims,
  ~1 min); Teams > Playoffs opens on Odds for the current season (most likely seeding + odds table + track record).
  Method and numbers in MODEL.md ("Playoff odds"). The track record needs the archive worktree (week JSON power
  ranks as of each week), which CI doesn't check out, so it is COMMITTED: `data/history/playoff_odds_backtest.json`;
  rerun `--backtest` and commit after any change to the method. Drift (`[report] playoff_drift`) was pre-registered
  and adopted on held-out data (section 3).
- **Players > Moves (Phase 5, 2026-10-14):** `tools/transactions_build.py` -> `data/transactions/<season>.json`
  (rows: date, team, type, pos, name, pid, text; one row per player per move, newest first) + `index.json` (seasons,
  team logos). Raw feed pages cached per season in `cache/`; only the current season is refetched. View: season /
  team / move type / position / date range / search; phones keep season + search up top with the rest behind a
  Filters toggle, and fold the note under the name (the Details column is hidden), so the table fits without
  side-scrolling. Draws 250 rows at a time (a season is ~2-5k); any non-default sort draws the whole filtered season
  (`NFLE.Table` got `onSort` + `getSort` for this).
- **Phase 6 done (2026-10-14): Jinja retired; every week page is a static shell + its JSON.** `nfledge/pages/week.html`
  (plain HTML, `%TOKENS%` filled by `report.page_html`: title, root, asset version, a one-line `NFLE_CFG`) is the
  same ~2.5 KB for every week (was ~270 KB); `<page>.json` (`"v": 3`) adds `roles`, `power_vol`, `head` (data
  week, games final, injury report in, scoring) and per-team `net_hist` (Power trend line) to v2. Power, Matchups,
  Roles and Model render in the browser (`assets/{power,matchups,roles,model}.js`); the header (week picker from
  `weeks.json`, which the current week's build now writes too; past / upcoming tags; details popover) is in
  shell.js. Shared helpers: `NFLE.week()` (the week data, once loaded), `NFLE.fmt` (sgn / ord / rank-badge class /
  team logo / row trim). The template's CSS is `assets/site.css`. MODEL.md's `{{ L.name }}` values are filled by a
  strict regex (a name the build doesn't provide fails the build) and the HTML goes to `data/model.json`.
  `run.check_script` now `node --check`s every `static/*.js` once per run. Old URLs keep working: same page paths,
  same hashes (`#games`, `#power`... map onto routes). The archive was rebuilt in the new shape (95 pages); a
  module whose field is missing from an older week file leaves the section alone. `tools/screenshot.py` opens the
  dev server (pages need http:// to fetch their JSON).

- **Every player has a page (2026-10-14):** ~16k player files (~90 MB) from nflverse weekly stats (all positions,
  1999 on), weekly rosters (2002 on) and PFR snap counts (2012 on). Roster files before ~2016 use legacy club codes
  BLT / CLV / HST / ARZ / SL (`report.ROSTER_TEAM`). Snap counts carry PFR ids: map them through nflverse's player
  table, not the loaded rosters' `pfr_id` (rosters miss ~30% of snap rows: linemen, defenders, ~8% of skill players
  in 2020-24). Targets are missing in nflverse stats for some seasons (e.g. 2003-08: 0 targets). Ourlads' depth
  charts are more accurate per the owner, but their terms forbid scraping and republishing (checked 2026-10-14).
  Owner's decision (2026-10-14): no Ourlads at all, not even a link-out ("they don't want anyone but their users
  using their stuff"). Do not propose it again.

## 9. Open threads / next steps (as of 2026-10-12)
- **ESPN early-week buckets (2026-10-14, nfledge/espn_calib.py), MEASURED:** Wayback Machine captures of
  espn.com/nfl/injuries (near-daily 2022-24; the page embeds status + est. return date per player; tools/espn_wayback.py
  caches them) -> 23,695 Mon/Tue listings vs game-day inactives (tools/espn_return_eval.py -> committed priors
  data/history/espn_early_week.json). Played that week: Out + return 7+ days past the game 1.8% (n=652); Out 33.5%;
  ESPN Doubtful 4.2% (n=95; the model's official-Doubtful carry rate was 48%); Questionable 48% (not bridged).
  Return dates are mostly placeholders (= next game day) and run optimistic: first game back a median 14 days
  after the estimate (IR +38), earlier than estimated 1%. Priors capped at 50 cases so 2026 outcomes still count.
  Owner's audit cases now: Deebo 98% inactive, Henderson / Montgomery 96%. The pre-registered 4-week check is
  superseded by the backfill (measured directly). Questionable bucket DEFERRED (2026-10-14, owner left it to me): the
  Wayback data has no ESPN update time, so the bridge's 'news since his last game' filter can't be applied and its
  48% mixes fresh news with stale tags. Revisit once the daily snapshots (which keep `updated`) hold ~4 weeks of
  outcomes: measure Q-with-fresh-news early-week play rate, adopt as a bucket if it differs from no listing.
- **Model snap data gap FIXED (2026-10-14, adopted):** `data.load_all` mapped snaps pfr -> gsis through the loaded
  rosters only (lost ~8% of skill-player snap rows 2020-24). Now roster map + nflverse player table fallback.
  A/B 2021-25 (snap_map_rosters vs baseline): MAE -0.003 overall, 90% CI [-0.005, -0.001], better or tied every
  season and position (WR -0.001 CI excludes 0).
- **From the 2026-10-14 research batch (section 5 has the numbers):** (2) "Not extended entering
  the last rookie-deal year" (rounds 2-7, year 4, no new contract signed by then; knowable pre-season): actual minus
  projection -0.60 [-1.21, -0.03] vs others, placebo year 3 +0.20. Near the CI edge after many tests, so suspect;
  a plausible mechanism (the team passed on him). The naive "contract year = last season paid" version (-1.36) uses
  hindsight (cut players stop being paid) and must not be used. Re-test once 2026 adds data. (3) Coach aggressiveness
  is real but tiny; revisit only if a direct TD-rate input (not via goal-line volume) is wanted.
- **Done 2026-10-12 (results in section 4):** diagnose the model's biggest game misses. Next, in order: starter
  accuracy of projected QBs + use the site's starter logic in game_eval; fix absence tags; late-season playoff-status
  features; margin-tuned shrinkage. Original plan: (|model - Vegas| >= 5 where Vegas
  was closer): tag QB situation (backup/rookie/change), weeks 1-3, usage-weighted key absences + OL/secondary
  absences, rating staleness (recent form vs rating), rest/travel/division/late season, weather, ST/HFA share of
  the margin; compare tag rates in Vegas-closer misses vs overall, per season; hand-review the 20 worst; fix only
  what's clear and test walk-forward on margin MAE and ATS. If nothing stands out, the gap is market information.
- **Done 2026-10-12:** Matchups tossup / win-chance reframe (section 4). Possible follow-up: a live model track
  record (needs walk-forward model margins for past weeks, e.g. cached from the archive build).
- **Done 2026-10-12:** "Our model" win % = power rank + fitted Elo + home (section 4). Owner ruled out QB-adjusted
  Elo (Elo should stay results-only; QB info enters via the rank).
- **Defensive fatigue (tools/fatigue.py, 2026-10-13, 219k plays 2018-26, within defense-game):** cumulative snap
  load does NOT wear defenses down (-0.04 EPA/100 per +10 snaps [-0.49, +0.43]; pass/rush split both ~0). Short
  rest DOES matter: the series right after the defense's own offense had a quick (<=3 play) possession allows +3.7
  EPA/100 [+1.9, +5.1], robust to excluding turnovers and controlling for series start; each extra minute of own
  possession -1.2. (Previous-series length shows the opposite sign, -4.0 per +10 plays: an artifact of within-game
  demeaning, so treat magnitudes with care; "game flow / momentum" can't be separated from rest here.) Rating
  impact is small: team quick-possession share sd 6% -> ~0.2 EPA/100 on a defense rating (worst offense vs average
  ~0.6) vs a 3.9-4.5 spread between defenses. Not modeled; matters only when a bad offense suddenly improves.
  Within a long drive: no fatigue signal. Same-drive comparison (drive-ending plays excluded) is not monotonic
  (13+ play drives: plays 1-4 -2.5, 5-8 +4.8, 9-12 -2.4 EPA/100) and field position moves in lockstep with play
  number (plays 9-12: 95% in opponent territory), so it can't be isolated in-drive. Holding the field zone fixed
  across drives, later plays are BETTER for the defense (-3.7 to -7.1 EPA/100 per +5 plays), likely because a drive
  that is still deep on play 8 is a stalling offense. Every design: no evidence defenses tire late in drives.
- **PARKED (owner, 2026-10-13): news push notifications.** Owner doesn't want them now. If revived: a GitHub Actions
  cron (~30 min) reads a watchlist file, polls ESPN's per-player news feed (see section 7, player news) and sends
  new items via ntfy.sh (free push service + iPhone app); a static site can't push on its own.
- **PARKED (owner, 2026-10-12): prior-season carryover in team ratings.** `tools/carryover_eval.py --quick` (3
  seasons 2022/23/25, 765 games, fixed shipped win formula; current = prior_weight 0.3 fading to 0 by week 8,
  half-life 3). These knobs were "insensitive" on fantasy MAE but never tested on games. Findings: more carryover
  clearly helps weeks 2-8 (0.6 fading by wk 13: rank Brier -0.008, margin MAE -0.42 pts early; overall MAE -0.13
  [-0.24, -0.01]; better-rank pick 61.8% vs 60.0%) but hurts weeks 9+ (+0.004 / +0.08); never fading (1.0 all
  year) hurts late more (+0.010 / +0.19); half-life 6 no help. The win % blend barely moves (Elo already carries
  the prior season). Next if resumed: quick round of (0.6, 1.0) x fade by week (8, 10) -- strong start, early
  fade; then full 6-season walk-forward on the winner (`carryover_eval.py`, ~1 hr, cached per variant) + a fantasy
  MAE check (tools/experiments.py) before shipping. Beneficiaries: Power ranks, battle bars, fantasy matchups.
- **Proposed:** market-implied team ratings (fit to posted spreads/totals) for lookahead weeks and a Power "market
  view"; test vs actual margins and future closing lines.
- **Archive rebuilt 2026-10-13** (2021 - 2026 wk 4, 94 pages, current model + Matchups win chances / tossups / Elo;
  archive commit b3b7183). Rebuild again after any future model or Matchups change.
- **ESPN return estimates:** test as return-model features (est. weeks to return, surgery/tear/fracture) once
  enough 2026 injuries resolve (~midseason); owner wants them only as data-driven inputs, never as truth.
- **Accuracy levers:** rookies / low-data priors (college production, preseason usage); expected fantasy points per
  opportunity; NGS / FTN inputs.
- Play-caller effects (on hold); IDP question unanswered; light mode unreviewed.
- Speed: experiment batches recompute identical stages per variant (stage caching; per-worker 5-season data windows
  would halve memory and allow more workers).
