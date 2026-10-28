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
  projection by play probability. Show "if active" projection + separate chance to PLAY ("62% to play"; 2026-10-17,
  owner: one way everywhere, never the chance to sit); P < 0.5 = sits, volume
  redistributed; teammates get contingent "+X if he sits".
- **Defaults:** half PPR, 10-team league, 1QB 2RB 2WR 1TE 1FLEX (all adjustable on the page).
- **Presentation:** elegance and readability first; minimal, sleek, dark; important values easy to find; all
  reasonable columns sortable. Reviews screenshots closely; dislikes clutter, light pills on dark rows, misaligned
  columns, inconsistent signals, anything "mashed together", tables that scroll inside their own box.
- **Tests on Brave on iPhone (= WebKit).** Verify mobile with `tools/screenshot.py` (WebKit), never only Chrome.
- Works by pointing at a topic ("do the thinking"); expects a plan for big features, then execution; impatient with
  slow runs (keep backtests fast, report ETAs, explain long waits).
- **Standard gate (2026-10-16, thread 8; use unless a pre-registration says why not).** Gates had drifted (margins
  +0.003 / +0.005 / 0, seasons-better 3/5 vs 4/5, intervals over weeks vs games; docs/verdict_audit.md):
  1. Before running: estimate the interval width from the nearest earlier test on the same rows. If the smallest
     effect it could detect (MDE = 0.71 x CI width) exceeds the plausible effect, don't run it as a ship test:
     redesign (more rows, a forward test) or record it as "unresolved (too small to measure)".
  2. Improvement: paired difference on identical rows, 95% bootstrap CI over season-weeks (player metrics; the
     player-cluster interval reported alongside) or over games (game metrics); CI excludes 0 in the helpful
     direction AND better in at least two thirds of seasons (3/4, 4/5, 4/6).
  3. Guards, "not worse" = CI upper below: fantasy MAE +0.003, any position not significantly worse; game margin
     MAE +0.02; availability Brier +0.0005; playoff / division Brier +0.001; Spearman -0.005. Start / sit decision
     gain reported next to MAE (a guard too, if the owner adopts it).
  4. Seasons: decide on the usual walk-forward window, and re-confirm any ship with |effect| <= 0.005 fantasy MAE on
     an untouched season (2026 at season end) before calling it settled; prefer decide-2025 / confirm-2026 for new
     ideas (2021-25 carries ~50 significance verdicts, ~1.25 chance passes expected).
  5. Exceptions stay explicit: owner designs ship unless significantly worse; display probabilities gate on
     calibration (ECE / Brier), not MAE.
  6. Position-specific changes (2026-10-17): a change may ship for one position only when that position is named in
     the pre-registration (one test, not four: picking the best of four positions afterward roughly quadruples the
     chance of a false pass). A position that looks strong only after the fact is a lead: re-test it on an untouched
     season before shipping. Other positions are still checked as guards (team volume is shared, so a change aimed
     at one position moves the others' projections).
  7. MAE vs bias (2026-10-17; owner: "we're a prediction model priding ourselves on accuracy backed by data ... you
     decide"): fantasy changes are decided on MAE, the start / sit decision gain is a guard (not significantly
     worse), and bias is reported but not gated. Points are right-skewed, so the MAE-best forecast sits a little
     below the mean; chasing zero bias trades away accuracy. Bias matters only where it flips decisions, which the
     decision guard measures. Closes the redistribution "owner's call (pending)" (sec. 5, 2026-10-15).
     Scope (same day, after (W)): MAE decides between projections that stay EXPECTED values. Lineups, rest-of-season
     totals, team totals and the Fantasy win chance add projections up, and medians don't add (the sum of medians
     sits below the median of the sum), so a change whose gain is a shift toward the median is a change of what the
     number means, not an accuracy gain; the median is shown already as the middle of each range.

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
- **Team ratings:** ridge on play EPA per unit (pass/rush/ST), every play (no WP filter since 2026-10-15), recency half-life 3 weeks, prior
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
  [2026-10-16: the surprise-QB share was measured on the harness that rated last week's starter
  ({#game-eval-starter}); re-measured with tools/event_misses.py, thread 3 in sec. 9: QB change +0.47 [-0.13, +1.12].]
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
| Route share (dropbacks on field) as a target-share input (`route_input`, 2026-10-15) | ALL -0.002 [-0.007, +0.003] 2021-25; TE -0.021 [-0.036, -0.007] post hoc; no free live source matching the history's definition (heatradar republishes PFF true routes) |
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
| 2-point conversions in player projections (owner 2026-10-15: "do offenses lean on their stars?") | Worth 0.034 pts / player-game (0.085 for 10+ pt games; QB 0.14; best player 0.4); 1.65% of player-games. 2022-25 RB/WR/TE: a team's #1 by touches gets 23.0% of its 2-pt conversions vs 24.5% of its TDs (#2 13.1 vs 16.0, #3 16.5 vs 14.3): no star premium, they follow TD share; ~1.6 per team-season. Parked; League header lists them as not projected |
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
- **League tab (owner 2026-10-15): import, don't host.** Owner wants both a parallel tool for real leagues and,
  possibly later, a Sleeper-like hosted game. Import first (Sleeper + public ESPN, owner's pick): Sleeper's API is
  open with CORS *; ESPN reflects our origin but private leagues 401 without espn_s2 / SWID cookies; Yahoo is OAuth.
  Hosting leagues (accounts, live drafts, waivers, trades, chat) needs a backend + ops: parked as a separate project
  to scope after the owner uses the import tool. Tested on the owner's Sleeper league (12 teams, half PPR, QB / 2RB /
  2WR / TE / 2FLEX / DEF): all 167 rostered players mapped. Lineup advice: a 15-85% injury risk is 'wait for news',
  not a bench call (lineups can change until kickoff; Saquon wk 6, Wed DNP).
- **Rankings > Rest of season (owner 2026-10-15).** A Weekly | Rest of season switch on the Rankings tab (remembered per device). Owner's picks: through week 17 (fantasy seasons end there), this week counts until kickoff. Expected points = sum of each remaining week's projected stat line x P(play), re-scored exactly under the viewer's scoring. Columns: ROS pts, Pts/G (per game played), Games (expected), Sched (sum of matchup effects), a bar per week (B bye, dash = projected to sit), ROS tier, season FP/G. **Not yet:** a ROS range (needs measuring: weekly ranges don't add, a player's weeks are correlated); a ROS accuracy backtest; the lookahead weeks ignore ESPN return dates and the midweek ESPN rulings (Hurts: 0% this week, 100% from wk 7 though ESPN's return date is 10/26, after the wk 7 game). Lookahead chains a current injury forward from this week's chance (Lamar: 40% to play wk 6, 38% wk 7, 80% by wk 17) -- worth checking against outcomes.
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

- **Owner UI rules (2026-10-14):** game logs are fully reverse-chronological (newest season first; inside a season
  playoff rounds SB/CON/DIV/WC on top, then week 18 -> 1; upcoming weeks above played ones): "scrolling down goes
  back in time". Injury badges are compact codes everywhere (Q / D / O / IR / SSPD / PUP / NFI; full status on
  hover; gamecast.js injTag, exported as NFLE.injTag). Playoffs are taken seriously but kept apart: player, non-
  fantasy and team logs carry per-season "pg" (round in "po"; tools/player_logs.py round_of / postsched) shown as a
  "Playoffs" block above "Regular season", never mixed into regular-season totals, ranks or FP/G. Super Bowls are
  neutral (h = 2 for both sides: no "@"). Player Stats custom columns: one delegated change listener (the table
  redraws its header on sort) + a sort button per custom column (tapping the picker on phones can't sort).

- **Weekly rosters mark game-day inactives (INA) only from 2019 (2026-10-14).** Before that, ACT = on the roster:
  injured players who sat read as active (Allen's 4 missed games in 2018). "Played a game" = any snaps (PFR snap
  counts, which start in 2013: nflverse has NO 2012 snap data despite docs). Injury tab missed / played counts and
  durability count from 2013; 2009-12 episodes are listed with '-'. Episodes continue only while listed or on a
  reserve list (else backups who rarely play would 'miss' every game). Anything using INA as an outcome must stay
  in 2019+ weeks that have INA rows (espn_calib, espn_return_eval do).
- **Team page Playoffs tab (2026-10-14):** tools/playoffs_build.py team_summaries -> data/playoffs/teams.json. Titles =
  Super Bowls + NFL championship games won before the Super Bowl (1933-65) + 1920-32 standings champions + AFL
  titles; AAFC titles listed separately (not NFL records). Playoff rate since the 1970 merger (or founding).
  Green Bay checks out: 13 titles, 37-28.

## 9. Open threads / next steps

### STATUS BOARD (keep current: edit this list whenever an item opens, ships or closes; the log below is history)
Updated 2026-10-26. Injury / return items first (owner 2026-10-18: "the injury/return model needs to be pristine").

**Running / next up**
0. (DM / DM2 / DM3, 2026-10-26) all FAIL on the strict calibration bar; owner decision: non-fantasy players shown at
   the shipped fantasy numbers' standard (A1 position-group model on final reports, return weeks from the plan's chain;
   run.py all_positions_file -> data/injuries_all.json). The board's models are unchanged. Brashard Smith's "Season":
   a display bug (ros weeks stop early), fixed in health.back.
   Pending (owner: "later", 2026-10-26): QBs' chance to play runs high, 0.776 predicted vs 0.709 played on final
   reports 2021-25 (worst decile 21 points; QBs listed Questionable played 45%). Pre-register a QB-specific look
   (starter vs backup, a QB role input) before season end.
1. SHIPPED 2026-10-20 as (BE2) (owner); history kept: (owner delegated 2026-10-19, after Tank Dell: IR to return since the opener, full practices in week 6,
   coach naming week 7, on no page at all): reserve-list players whose practice window is open (on this week's report;
   before his team's first report of the week, last week's) join the board and get a return state. Built on branch
   wip/window-open (returns.window_open / _window_states, run.py extra candidates), NOT shipped: a local build showed
   (a) the practice model rates them as if on the active roster (Jeremy McNichols, IR, full practice, no game status:
   97%) though he can only play if activated: measure P(played | window open, practice pattern, final status) on
   2019-25 and use it for the current week; (b) a veteran back from a lost season has no role (Dell's shares read 0,
   projection 0.0; rookies have a draft prior, he has nothing): a role prior from his last seasons played. Then
   pre-register the check (played share vs our chance for touched players).
2. (AY, to pre-register) injured right before a bye / known only to ESPN: no report that week, so the chain never
   starts and every later week reads 100% (Tanner Hudson, torn pectoral, CIN bye week 6; Hockenson 2026-10-17).
   Plan in docs/handset_audit.md ("injured right before a bye").
3. (AU) game-day actives / inactives: shipped; its audit gate runs Tuesday after snap counts (tools/gameday_audit.py).
   Gate fails -> the rule comes out.

**Queued (pre-register before running)**
- Returning starters' role ((BH) FAIL, 9 cases): define a starter by games started; score 2026 returners at season end.
- (AS) midweek stage from the calendar; (AT) one "early week" definition (week clock entry, 2026-10-18).
- Week clock remaining moves (7 items, "Week clock ... REMAINING WORK" entry).
- Partial Vegas lines: if any game of a week lacks a line, every game drops to the model's own volume
  (team_model.GameModel.predict `.all()`); per-game fallback.
- Small IR-audit leftovers: qb2_play_rate needs a board QB at depth rank 1; debut prior's absolute depth_rank <= 2;
  kdst_build falls back to the last kicker when no kicker is active.
- Fantasy depth-aware values (replaces a STOPGAP in league.js; first entry below).
- Hand-set values not yet tested: docs/handset_audit.md #8-#22 (#14 = return-model settings), range calibration.

**Pending checks**
- (BJ) lead: at season end, return timing anchored on ESPN's date on 2026 daily snapshots only (failed on sparse 2022-25 captures; 2026 so far -0.24 on 50 states).
- Bye-week ESPN rule (owner 2026-10-20): at season end, played rate after a bye by ESPN bucket on 2026 snapshots vs the rates used.
- (BC) qbedge adopted 2026-10-19: at season end, 2026 game margin MAE base vs adopted (tools/game_eval.py 2026).
- ESPN long-date rule (owner decision 2026-10-19): at season end, 2026's touched players' played share before / after ESPN's date.
- News watcher relay (tools/news_watch.py): confirm the first run handed off to its successor (~21:45 UTC 2026-10-18).
- (AF) team-rating half-life: re-check at season end.
- Monday refit (BA, shipped 2026-10-19): on the first live Mondays, how far the Monday-night players' projections move when Sunday's games enter the ratings.

**Parked (owner)**: news push notifications; prior-season carryover in team ratings; market-implied ratings.

**Closed recently**: (BB) QB swing: premise confirmed, shrinkage arms FAIL, qbrun negligible pass not shipped; (BA) Monday refit FAIL on gain, guard passed; shipped by owner decision; (AX) / (AX2) FAIL; (AV) PASS shipped; IR audit fixes shipped; (AW) FAIL twice, closed; (AR) PASS shipped; (AQ) FAIL.

### Log (chronological from here)
- **Fantasy: depth-aware values (2026-10-17; replaces a STOPGAP).** The Fantasy tab's waiver moves (league.js
  movesFor) value a roster by its best lineup each remaining week by expected points, with every healthy player healthy
  through week 17. So a backup's insurance (he plays when a starter is hurt) and the waiver wire's own depth (a D/ST
  for a bye can be picked up that week) are worth ~0; the owner caught it ("drop McLaughlin for a second defense").
  Stopgap shipped: hold-one positions (QB unless 2-QB / superflex, TE, K, D/ST) only upgrade, and RB / WR never drop
  below 3 (league.js DEPTH_MIN). Remaining work: (1) weekly injury rates by position fitted from history (P a healthy
  starter misses week k+j), applied to future weeks; (2) lineup value as the expectation over who is available (each
  slot's expected points with the next man up when a starter sits; Poisson-binomial per position, flex last); (3) a
  waiver replacement level per position (the best free agent each week) as the floor a roster spot must beat;
  (4) check: rank-correlate predicted vs realized rest-of-season team points (2021-25 backtests) for the old and new
  values; then remove the rules. Then the trade calculator and finder (owner: team-relative; both sides' gain) on it.
- **Queued (2026-10-17): (AB) penalties in team ratings** (docs/handset_audit.md: penalty-nullified plays, 87% of them,
  never reach the team model).
- **Hand-set values queue (2026-10-17): docs/handset_audit.md.** 22 model values without fitting or a numbered
  test (4 high impact: prior-season weight, TD blend k, Tuesday / week availability model settings, redistribution
  minimum share). Each gets its own pre-registration here before it runs, decided by sec. 1 rule 7 (MAE, start /
  sit guard).
- **PRE-REGISTERED 2026-10-15 (owner: "still annoyed McLaughlin is projected 2.6 even if Judkins sits"): newcomer
  discount.** Wk 6 CLE: Estime signed this week (off MIN's practice squad) and gets ~12 carries from his old role;
  McLaughlin (the incumbent) ~3. Descriptive (2021-25 backtest, RB/WR/TE mid-season movers, 126 players): first game
  with the new team projected 2.78 vs actual 1.09 (bias -1.70 vs -0.51 for everyone else); games 2-3 normal (-0.59,
  -0.57). Variant `newcomer_05` (experiments.newcomer_scale = 0.5, a round value set before the run): in a
  RB/WR/TE's first game for a new team (last_team != team), his projected targets and carries x 0.5, the removed
  volume given to same-position teammates who are projected to play (applied after availability, so a sitting
  starter doesn't absorb it), in proportion to their own; projections recomputed (refined before the run: wk 6 the
  first draft handed Estime's cut to a sitting Judkins). ESPN's and our usage depth charts both list McLaughlin RB2.
  Gate: (i) on those
  newcomers' rows + their same-team same-position teammates that week, MAE lower with a 95% CI over season-weeks
  excluding 0; (ii) overall MAE not worse (CI upper < +0.003); (iii) no position significantly worse.
  **v1 run DISCARDED (implementation bug):** keyed on the features' `last_team`, which isn't the team of his last
  game: it flagged 13,190 rows (offseason movers all season), ALL MAE +0.086. Re-run with the pre-registered
  definition (no snap for this team before this week; players who have played somewhere), same gate.
  **Result: PASS, SHIPPED** (config experiments.newcomer_scale = 0.5): ALL -0.002 [-0.004, 0.000], 4/5 seasons
  better, WR -0.006 [-0.011, -0.002], no position worse; newcomers + same-team same-position teammates MAE -0.009
  [-0.011, -0.007] (727 first games, 100-190 a season); newcomer bias +0.50 -> +0.42. Live wk 6 check: only the 5
  teams with a newcomer change (CLE, HOU, IND, SEA, TEN; 355 other players identical); CLE with Judkins out:
  McLaughlin 2.6 -> 5.5, Estime 8.3 -> 4.1. OPEN: in the backtest ~9k rows on teams WITHOUT a newcomer also moved
  (mean |0.02|, both directions) and limiting the recompute to newcomer teams didn't remove it (identical results),
  while the live week shows none: an unexplained backtest-path difference worth tracing.
  Side analyses (owner): first games split by signed that week (113: projected 3.07, scored 1.29 = 42%) vs on the
  roster a week+ earlier (33: 1.65 vs 0.39 = 24%): not a separate effect, both barely contribute. Estime's projection
  (wk 6) = 30% carry share in games he played (2025 NO 46 carries / 5 g, 2024 DEN 76 / 13), carried over as if he
  were settled in; McLaughlin's long-run 18.5% (DEN) is pulled to 7.5% by 3 small CLE games.
- **Team-switch count vs projection error (owner idea, descriptive 2026-10-15; 2021-25 backtest, players projected
  5+):** mean actual - projection by team changes over the prior 5 seasons + this one: 0 -> -0.55 (n 9,962), 1 ->
  -0.88, 2 -> -1.24, 3+ -> -1.35 (+-0.4); same monotonic pattern for 2 / 3 / 4-year windows. Journeymen are
  over-projected. Overlaps the newcomer effect (first games are inside); NEXT: pre-register a switch-count input or
  shrink, excluding first games with a team, after the newcomer gate.
- **PRE-REGISTERED 2026-10-15 (owner: "do it"): journeyman adjustment.** k = team changes over the player's past 5
  seasons + this one (weekly rosters, ACT), capped at 3; rows that are his first game with a team excluded (the
  newcomer discount covers those). Multiplier per k = [sum actual / sum projected for k] / [same for k = 0], fit on
  the 2021-23 backtest (current model; all QB / RB / WR / TE rows with a projection >= 1 and an actual), applied to
  whole projected stat lines. Test on 2024-25 (untouched by the fit). Gate: (i) rows with
  k >= 1: MAE lower, 95% CI over season-weeks excluding 0; (ii) all rows: MAE not worse (CI upper < +0.003); (iii) no
  position significantly worse. Pass -> refit the multipliers on 2021-25 and ship.
  **Result: PASS, SHIPPED** (`tools/journeyman_eval.py`, current-model backtest): fit 2021-23 multipliers 1 / 0.94 /
  0.906 / 0.881; 2024-25 k >= 1 rows (4,096) MAE 3.714 -> 3.605 (-0.108 [-0.125, -0.090]); all rows (11,335)
  -0.039 [-0.045, -0.033]; RB -0.041, WR -0.052, TE -0.023 (all CI < 0), QB -0.011 [-0.059, +0.040]. Bias by k
  before -0.50 / -0.75 / -0.76 / -0.84, after -0.50 / -0.36 / -0.27 / -0.20. Shipped refit on 2021-25: 1 / 0.944 /
  0.912 / 0.892 (`data/history/journeyman.json`, config experiments.journeyman). Caveat: backtests of 2021-25 now
  include an in-sample adjustment.
- **QB rushing on a leg injury (owner, Caleb's hamstring 2026-10-15): too few cases.** Mobile QBs (proj 15+ rush
  yds) who played while listed with a leg injury: 14 games in 2021-25, rushed 18.1 vs 20.7 projected (-2.5 +- 10.5);
  healthy mobile QBs +1.0 +- 1.5. No adjustment; revisit only if the sample grows.
- **PRE-REGISTERED 2026-10-15 (owner: "if judkins sits, his replacement's projection would skyrocket, right?"):
  conserve vacated volume.** Wk 6: Judkins (68% of CLE carries, 60% to sit) is benched in the default scenario but
  only ~2.4 of his 11.5 points move to teammates (Estime +1.8, McLaughlin +0.6): the learned redistribution at 0.5
  strength hands out a fraction of the vacated share and the rest vanishes. Variant `redist_conserve`
  (injuries.redistribute_conserve): keep the learned allocation (who gets it) but rescale each team's additions so
  they sum to the vacated share (sits x share x (1 - absent fraction)), per share type. Walk-forward 2021-25
  (`tools/experiments.py baseline,redist_conserve`). Gate: (i) on rows whose projection changes by > 0.05 pts, MAE
  lower with a 95% CI over season-weeks excluding 0; (ii) overall MAE not worse (CI upper < +0.003); (iii) no
  position significantly worse overall. Bias on affected rows reported.
  **Result: FAIL, not shipped** (switch stays off). Overall ALL +0.001 [-0.001, +0.003], no position different;
  affected rows (1,767) MAE 4.472 -> 4.508 (+0.035 [+0.020, +0.049]), bias -0.09 -> +0.06; the 32 rows boosted 1+
  pts: MAE 4.97 -> 5.46, bias -0.98 -> +0.73. Full conservation overshoots: a sitting starter's work doesn't all
  reach the teammates we project (call-ups, fullbacks, QB runs, and the offense itself shifts). The answer to the
  owner's question: the backup's jump is real but smaller than one-for-one; the current 0.5 strength sits nearer the
  truth (-1.0 under vs +0.7 over). Shipped instead: both worlds shown (backup's projection if the starter plays /
  sits) and a game-time call in the League lineup.
- **Redistribution: KEPT (2026-10-15, owner delegated the call).** By boost size (2021-25 backtest, all players):
  1,444 rows with a < 0.5 pt boost (MAE with 3.94 / without 3.90) and 99 at 0.5-1.5 (4.95 / 4.82) are noise; the
  12 rows with 1.5+ pts (a backup taking a starter's role: actual 9.4, projected 7.7 with / 5.7 without; bias -2.1
  vs -4.0) are what fantasy cares about and it helps there, still under-projecting. OPEN, pre-register when there's
  a way to get more than 12 cases: redistribute only meaningful vacated volume, possibly at full strength.
- **PRE-REGISTERED 2026-10-15 (owner: "wire up defense and kickers", "make sure the relevant scoring settings are
  applied"): kicker projections.** Source: nflverse player stats (fg made / missed by distance band 0-19 / 20-29 /
  30-39 / 40-49 / 50-59 / 60+, PAT made / missed). Model: the team's expected FG and PAT attempts from its Vegas
  implied total (league-wide fit on the training seasons), the team's distance-band mix and the kicker's make rate
  per band, each shrunk toward the league (empirical Bayes), giving an expected kicking stat line that any league's
  scoring re-scores. Walk-forward 2021-25 (fit on the two prior seasons + the season so far), weeks 3+, every kicker
  who kicked. Baseline: the kicker's season-to-date average (standard scoring: FG 3 / 4 at 40-49 / 5 at 50+, PAT 1,
  miss -1). Gate: MAE lower with a 95% CI over season-weeks excluding 0 and better in >= 3 of 5 seasons. Fail: ship
  the baseline (season-to-date average, rescaled per league from his made / missed line) and say so.
  **Result: PASS, SHIPPED** (`tools/kicker_eval.py`): 2,298 kicker-games, MAE 3.706 vs 3.998 (-0.293 [-0.389,
  -0.204]), 5/5 seasons; mean 7.86 vs actual 7.84 (baseline 8.06); correlation with actual 0.158 vs 0.043.
- **PRE-REGISTERED 2026-10-15: team-defense (D/ST) projections.** Source: nflverse weekly team stats + schedules.
  Expected per game: sacks, INTs, opponent fumbles recovered, forced fumbles, defensive TDs, special-teams TDs,
  safeties, blocked kicks, passes defended, tackles for loss, forced punts (opponent punts), defensive 2-pt returns =
  league rate x (defense's rate / league) x (opponent offense's rate allowed / league), each rate the last 16 games
  shrunk toward the league (common stats 8 games of league weight, rare ones 30); points allowed ~ normal around the
  opponent's implied points (sd fit on the window); yards allowed ~ normal around a fit on the opponent's implied
  points and the defense's shrunk yards-allowed rate. Any league's tiers / per-point / per-yard scoring computed from
  those. Not projected: 3-and-outs, 4th-down stops. Walk-forward 2021-25 weeks 3+ (rates from games before the week,
  fits on the two prior seasons + season so far). Baseline: the D/ST's season-to-date average. Scored on ESPN's
  standard D/ST scoring (sack 1, INT 2, FR 2, TD 6, safety 2, block 2, points-allowed tiers 0 +5 / 1-6 +4 / 7-13 +3 /
  14-17 +1 / 18-27 0 / 28-34 -1 / 35-45 -3 / 46+ -5). Gate: MAE lower, 95% CI over season-weeks excluding 0,
  >= 3 of 5 seasons. Fail: ship the season average (rescaled per league from its stat line) and say so. The owner's
  Sleeper scoring (per point / per yard allowed + extras) reported alongside, not gated.
  **Result: PASS, SHIPPED** (`tools/dst_eval.py`): 2,398 defense-games, ESPN standard MAE 4.002 vs 4.339 (-0.337
  [-0.417, -0.258]), 5/5; mean 6.19 vs actual 6.16; corr 0.253 vs 0.075. Owner's Sleeper scoring 4.519 vs 4.939, 5/5.
  League tab lists every nonzero league setting we don't project (2-pt conversions, 3-and-outs, 4th-down stops, ...).
- **PRE-REGISTERED 2026-10-15 (owner: "anything worth trying taking OUT?"): removal tests.** Components never
  ablated on fantasy accuracy: QB effects in the team pass model (`no_qb_effects`), vacated-volume redistribution
  (`redistribution_0`), prior-season carryover in team ratings (`prior_weight_0`), the 10-90% win-probability play
  filter (`wp_none`). `tools/experiments.py baseline,<variant> 2021-2025`, relevant rows, 95% CI over season-weeks.
  Rule: REMOVE if overall MAE is not worse (CI upper bound < +0.003) AND no position is significantly worse (its
  CI above 0); KEEP otherwise. A removal that is significantly better is removed regardless of the 0.003 margin.
  (Prior-season carryover also helps team-game prediction early in the season (section 9 carryover note), so it is
  only removed if Matchups / Power are checked too.) Rejected experiment switches still in model code are dead code:
  air_yards, snap_input, croe / yacoe / cpoe, gl_share, rz_struct, qb_rush_split, coach_aggr, age_input,
  spread_shares, rbbc, elite_*, player_calibration linear, snap_map rosters, def_terms fitted / sign, wind_mode
  linear / quadratic (gl_struct is ADOPTED and stays). Delete, verified by identical baseline projections before /
  after; results stay recorded here.
  **Results (fantasy: `tools/experiments.py` 2021-25, 12,480 rows; games: `tools/game_eval.py --set` 2021-25, 1,279
  games):** WIN-PROBABILITY FILTER REMOVED: fantasy ALL -0.001 [-0.002, +0.001], no position worse; game margin MAE
  10.638 -> 10.548 (-0.090 [-0.158, -0.019]), better 4/5 seasons, winners 59.2 -> 61.0%: blowout plays carry signal.
  QB EFFECTS KEPT: fantasy ALL +0.000 [-0.001, +0.002] (TE -0.003 better) but games +0.011 [-0.075, +0.096] with the
  last two seasons worse (+0.058, +0.115) and total MAE +0.046. PRIOR-SEASON CARRYOVER KEPT: fantasy ALL +0.000
  [-0.006, +0.008] fails the 0.003 bound (2024 +0.012). REDISTRIBUTION: overall no difference (+0.000 [-0.001,
  +0.001]), but on the 5.7% of rows it changes (1,825) MAE is worse with it, +0.031 [+0.019, +0.042], while it
  removes the bias (teammates of a sitting player: -0.15 without, +0.01 with): the same mean-vs-MAE trade-off as the
  rejected linear calibration. Owner's call (2026-10-17): MAE decides, start / sit gain guards (sec. 1 rule 7); the
  strength is being searched under that rule ((V), docs/handset_audit.md #4).
- **Return games, fact check (owner 2026-10-15: "players returning from injury have huge fantasy games all the
  time").** Skill players averaging 8+ half-PPR before the absence, 2019-25 (n 473): pre-injury 12.5, return game
  10.8, next 3 games 11.0; booms (>= 1.5x his average) 14.2% of return games vs 18.5% of his other games, busts
  (<= 0.5x) 32.1% vs 20.5%. Big return games are common in absolute terms (42 of 1,361 return games scored 25+,
  94 scored 20+: Dalvin Cook 47.6, Derrick Henry 39.1, Bowers 37.3) but no more frequent than usual. Our weekly
  projections already get them right: archived 2021-26, return games projected 9.10 vs actual 9.25 (residual
  +0.14 +- 0.59), same as other games (+0.07). No return-game adjustment.
- **Return timing, diagnostic (2026-10-15):** P(back by his k-th game after the first missed one), skill players,
  walk-forward 2022-25: active-roster injuries calibrated (k 1-4: 44 / 66 / 80 / 86% actual vs 44 / 64 / 76 / 84%),
  inactive similar; IR wrong both ways: k 1-3 actual 0% (the 4-game IR minimum) vs predicted 1-10%, k 8 45.6% vs
  30.2% (too pessimistic once eligible).
- **PRE-REGISTERED 2026-10-15 (owner: "pinpointing returns from IR and injuries in general is very important"):
  return-timing v2.** Return model (next-game hazard, chained) with three additions: (1) IR rule: games spent on
  IR so far (`ir_games`) as a feature, and the hazard set to 0 while an IR player is below the season's minimum
  (2022+: 4 games; 2020-21: 3; earlier: 8); (2) practice window: on his team's practice report for the next game
  (window opened / designated to return) + his practice score that week, the flag carried forward once opened;
  (3) ESPN's estimated return: weeks from the next game to ESPN's return date at the latest Wayback capture between
  his last missed game and the next one (2022-25 captures; NaN otherwise), plus ESPN status, carried forward one
  week per game. Walk-forward test seasons 2023-25 (train 2019 .. season-1; all positions train, skill positions
  scored). Decision points: every return-model state; label P(back by his k-th next game), k = 1..8; both
  baseline and variant use production's step 1 (this week's practice estimate where on the report) and stay = 1.
  Gate: (i) Brier lower, 95% bootstrap CI by episode excluding 0, >= 2 of 3 seasons; (ii) each designation with
  n >= 150 rows x k-bucket (1-2 / 3-4 / 5-8) within 5 points of actual; (iii) IR rows that the rule makes
  impossible predicted <= 1%. Ablation (each addition alone) reported, not gated.
  **v2 result (`tools/return_v2_eval.py`): FAIL, not shipped.** Brier 0.1189 -> 0.1333 (+0.014 [+0.009, +0.020]),
  0/3 seasons; later horizons too pessimistic (active k 5-8 -6.8, inactive -14, IR k 5-8 17.6% vs 40.9% actual).
  Ablation: IR rule alone +0.0017 [-0.000, +0.003] (but rule-impossible IR rows 0.1% vs base 5.2%, actual 0.4%);
  practice window alone +0.0054; ESPN return alone +0.012. Cause: the chain rolls today-only information forward
  (this week's practice score becomes NaN = "not practicing" in later steps; ESPN's estimate is counted down as
  if exact), so errors compound. Baseline's own IR weakness: k 5-8 27.9% vs 40.9% actual. 2025 Wayback coverage
  of ESPN's injury page is thin (21 captures, 4 parsed), so ESPN is effectively tested on 2023-24.
- **PRE-REGISTERED 2026-10-15: return timing v3 (direct horizons; last attempt).** Same information, no chain:
  one classifier, P(back by his k-th next game | state at decision time, k), k = 1..8, trained on every state x k
  with a known outcome (walk-forward, train 2019 .. season-1). Features: the return model's (missed, designation,
  report, injury, position, week) + k + IR games so far and games short of the minimum (hazard-free: k beyond the
  shortfall is learnable; and the prediction is forced to 0 when k <= shortfall) + practice window / score this
  week + ESPN weeks-to-return / status at decision time + this week's practice-model P(plays) when on the report.
  Baseline: production (chain, step 1 = this week's estimate, stay 1). Same gate as v2. If it fails, stop and
  record; production keeps the chain.
  **v3 result (`tools/return_v3_eval.py`): FAIL, not shipped; stopped as committed.** Brier 0.1189 -> 0.1138
  (-0.005 [-0.010, -0.000]), 2/3 seasons. IR pinpointing fixed: IR k 1-2 / 3-4 / 5-8 actual 6.4 / 21.1 / 40.9% vs
  v3 7.7 / 21.7 / 39.5 (production 9.7 / 19.1 / 27.9); rule-impossible IR rows 0.0% (actual 0.4%); active-roster
  within 2.6. Fails (ii) on the small groups: game-day inactive (I01) -9.4 / -16.7 / -11.5, IR designated to
  return -10.3 / -12.8 / -4.0, other reserve 5-8 -7.1.
- **PRE-REGISTERED 2026-10-15, to be judged on FRESH 2026 outcomes only: hybrid return timing.** v3's direct model
  for players on IR (designation ir, plus the IR minimum rule), production's chain for every other designation.
  Chosen after seeing v3's per-designation results on 2023-25, so those seasons can't judge it; it is evaluated
  on 2026 return-model states from week 7 on whose outcomes resolve this season (decision points before any
  2026 outcome was looked at). Not live until then. Gate: IR rows' Brier lower than production's with a 95%
  bootstrap CI by episode excluding 0, and IR calibration by k-bucket within 5 points; non-IR rows unchanged by
  construction. Earliest look: after week 14 (enough IR returns to resolve).
- **PRE-REGISTERED 2026-10-15 (owner: "after week 14 doesn't help us today"): the same hybrid on untouched
  seasons 2021 and 2022.** No v1-v3 test or selection used 2021-22 outcomes (v2/v3 tested 2023-25). Walk-forward:
  2021 trained on 2019-20, 2022 on 2019-21 (COVID-era training, and 2021 has no ESPN data: the hybrid's IR model
  runs without it). Gate on IR rows (skill players, k = 1..8): (i) Brier lower than production's chain (step 1 =
  practice estimate, stay 1), 95% bootstrap CI by episode excluding 0, better in both seasons; (ii) IR calibration
  by k-bucket within 5 points. Pass -> ship the hybrid now; the fresh-2026 check above still runs as confirmation.
  **Result: PASS, SHIPPED 2026-10-15** (`tools/return_hybrid_eval.py`; re-run through the production code in
  `tools/return_timing_check.py`, identical): IR rows 6,118 / 280 episodes, Brier 0.1727 -> 0.1578 [-0.028, -0.002],
  2021 0.204 -> 0.179, 2022 0.140 -> 0.136; k 1-2 / 3-4 / 5-8 actual 7.6 / 24.0 / 41.6% vs hybrid 6.5 / 21.8 / 39.2
  (chain 6.7 / 15.7 / 23.4). Live in `returns.lookahead_availability` for designation ir; also reserve-list players
  now join lookahead rosters from P >= 0.05 (was 0.5, which left IR players at 0 ROS points).
  **IR-minimum rule on the chain alone: FAIL** (2023-25 IR rows 0.1356 -> 0.1428, +0.0071 [+0.004, +0.011]): it
  pushes returns later in a chain that was already late; the rule lives inside the hybrid instead.
- **IR minimum as a hard rule (owner design: an NFL rule, not a model).** Production's chain with the hazard set
  to 0 while an IR player is short of the minimum (no new features). Ships unless significantly worse: Brier on
  IR rows 2023-25 not worse with a 95% CI excluding a 0.005 loss.
- **SHIPPED 2026-10-15 (owner design, data check): a returned player counts like a healthy one in the lookahead.**
  Owner: once back for even one game, the odds he's past the injury are very high; re-aggravation is small. Data
  (2022-25 skill players, role-matched by offensive snap share): starters back from an injury absence play their
  next 1-6 games 95.9 / 88.3 / 86.8 / 85.6 / 84.6 / 74.0% vs healthy starters 95.2 / 89.6 / 88.2 / 86.7 / 84.9 /
  82.2% (h 6: n 104, noisy); mid and low roles alike; longer absences no worse (starters back after 4+ missed:
  89.7%). The return chain multiplied every post-return game by stay_active 0.892 while healthy players count
  1.0 in the lookahead, an 11-point penalty on every returning player in ROS. `p_active(stay=1.0)` there.
- **PRE-REGISTERED 2026-10-15 (owner-approved): midweek ESPN "Out" rulings during practice week.** Trigger: Hurts
  (PHI, wk 6) ruled out Thursday, ESPN Out with a return date after the game, yet 12% inactive because once a
  team's report is out `availability()` uses the practice model only (Wed FP) and the ESPN bridge skips that team.
  Data: Wayback captures of espn.com/nfl/injuries on Wed/Thu/Fri, 2022-24 (fetched into a separate file,
  `cache/espn_injury_midweek.parquet`, so the Mon/Tue calibration input is untouched). Sample: Sunday games only;
  players ESPN lists Out / IR at a capture made after at least one of his team's practice days was published
  (a day counts as published from 22:00 UTC that day) and before the final (Friday) report; one row per
  player-week = the latest such capture; outcome = active that week (weekly roster status ACT). Baseline = what
  production does: the practice model (walk-forward, trained on seasons before the test season) on the practice
  days published at the capture, no game status; players not on the report get 0.95. Rule: replace that with the
  ESPN bucket's play rate (Out with return date after the game / Out / IR = 0), rates estimated leave-one-season-
  out from the other seasons' rows. Gate: pooled Brier lower with a 95% bootstrap CI (2,000 player-week resamples)
  on the difference excluding 0, AND lower in at least 2 of the 3 seasons. Fewer than 100 player-weeks:
  inconclusive, not shipped. Result goes here (and section 3 or 5) either way.
  **v1 result (`tools/espn_midweek_eval.py`): formal PASS, judged INVALID, not shipped.** 9,552 player-weeks,
  Brier 0.863 -> 0.028, 3/3 seasons. But 95% of rows are players NOT on the practice report (mostly long-term IR,
  play rate 2%) scored at the 0.95 placeholder, which production never assigns them (IR players aren't projected):
  the pass is that straw man. On-report rows (n = 478, the Hurts case) played 23.8% of the time; baseline mean
  0.737, rule mean 0.022, Brier 0.419 -> 0.235. Wayback captures have no "updated" time, so a midweek ESPN "Out"
  can be last week's stale label, which production's freshness filter (update after the last game) would drop.
  **v2, pre-registered after seeing only those on-report aggregates (not a blind gate; stated so):** on-report
  rows only; buckets Out / Out+ret / IR (IR on a practice report = designated to return); rule = leave-one-season-
  out play rate of ON-REPORT rows in the same bucket; same gate (Brier CI excludes 0, >= 2 of 3 seasons,
  n >= 100), plus a calibration check: the rule's predicted rate within 10 points of the actual rate per bucket.
  **v2 result: PASS, SHIPPED 2026-10-15.** n = 488; Brier 0.419 -> 0.164, diff -0.254 [-0.297, -0.209], 3/3
  seasons (2022 0.318 -> 0.069, 2023 0.428 -> 0.194, 2024 0.479 -> 0.191). Calibration (actual / rule / old
  baseline): Out+ret 0% / 0% / 42% (n 43); Out 9.6% / 12.6% / 59% (n 187); IR on report 38% / 36% / 90% (n 258).
  Starkest: practice "DD" + ESPN Out played 0.7% (n 136) vs 32% from the practice model. Shipped as
  `InjuryModel.midweek_ruling` with pooled rates (`data/history/espn_midweek.json`), production keeping the
  feed's freshness filter (ESPN update on/after the team's last game) that the Wayback test couldn't apply; the
  final game status takes over. Live check: Hurts (Out+ret, Wed FP) goes 12% -> 100% inactive.
  **Remaining (not tested, not shipped):** ESPN Doubtful midweek; players ESPN rules Out who are NOT on the
  practice report (v1's sample was mostly long-term IR); a live-data recheck of the rates once the daily ESPN
  archive (with update times) covers ~8 weeks of midweek rulings.
  **Explored 2026-10-15 (owner: "explore the opens"; descriptive, Wayback Wed-Fri 2022-24):** (a) ESPN Out NOT on
  the report: 85% are on reserve lists that week (RES 521 / Out, 350 / Out+ret), 24 + 8 on the active roster:
  not worth a rule, CLOSED. (b) ESPN Questionable not on the report: mostly stale labels on backups (ACT 1,422 /
  INA 744), the healthy-scratch model's job: CLOSED. (c) ESPN Doubtful on the report: n 68, played 2.9% vs 42.5%
  practice-model baseline; too few for a gate and the baseline is biased (d): RETEST after (d). (d) FOUND: the
  practice model is overconfident midweek for EVERY report player, not just ESPN-listed ones. On all 3-day report
  weeks 2022-24 (n 9,240 per state), mean predicted vs actual play: 1 day published 86% vs 65%; 2 days 76% vs 65%;
  full week with game status 83% vs 82% (calibrated). Cause: trained on complete weeks only, where "no game
  status" means cleared; midweek, no status yet reads the same. Lamar (wk 6, Wed DNP) 81% to play is this.
- **Lookahead availability beyond the next game (diagnostic 2026-10-15, `tools/return_horizon_eval.py`, walk-
  forward 2022-25).** The return-timing model was validated on the next game only; ROS uses it to week 17. (1) By
  horizon it drifts: active-roster injured players actual vs predicted k=2 65.5% / 58.1%, k=4 71.7 / 74.8, k=6
  71.2 / 81.4 (actual plateaus ~71%: some never return to the lineup; the constant stay-active rate doesn't
  capture it); IR players k=6 30.2 / 20.1 (too pessimistic). (2) The chain ignores this week's practice report.
  Replacing step 1 with the practice model's P(plays) (variant written into the script BEFORE the run; no gate set)
  on states with a practice row (n 18,542 rows): Brier k=1 .247 -> .101, k=2 .246 -> .180, k=4 .219 -> .192,
  k=6 .228 -> .211. Not yet a gate: see the pre-registration below.
- **PRE-REGISTERED 2026-10-15: lookahead starts from this week's estimate.** Two changes, each gated separately,
  walk-forward 2022-25 (return model and practice model fit on seasons before the test season), label = played
  his team's k-th game, k = 2..6 pooled (k = 1 is the current week, already served by the weekly model):
  (A) players already out (a return-model state) whose next game has a practice row: step 1 of the chain = the
  practice model's P(plays) for that game instead of the hazard; later steps chain the hazard as now.
  (B) newly injured: on the report for game G after playing the previous game (no state), which production now
  treats as healthy from G+1 on (P = 1.0). Variant: P(G) = practice model, then if he misses G a state is built
  (missed 1, designation active, his report status and injury) and the hazard chains from there.
  Gate (each): pooled Brier over k = 2..6 lower, 95% bootstrap CI of the difference (2,000 resamples of
  player-episodes) excluding 0, lower in >= 3 of 4 seasons. The long-horizon plateau (1) is a separate problem,
  not fixed here.
  **Results (`tools/lookahead_chain_eval.py`):** (A) PASS: 3,514 episodes, Brier 0.2277 -> 0.1940, diff -0.034
  [-0.039, -0.029], 4/4 seasons; k=2 actual 67.4% / old 54.8% / new 62.4%; k=6 73.4 / 77.7 / 81.4 (the plateau
  overshoot remains). SHIP. (B) PASS on paper: 10,891 episodes, Brier 0.215 -> 0.150, 4/4; but NOT SHIPPED: skill
  players NOT on any report also play only 91% of their next game falling to 81% at k=6 (on-report: 88% -> 80%),
  so B's discount is mostly ordinary attrition that the lookahead applies to nobody else (everyone healthy = 1.0):
  shipping it would rank every player on a report below his true standing relative to the rest.
  **OPEN (the real fix):** a lookahead availability for EVERYONE: P(plays his k-th next game) from role / snap
  share, position, current report and the return model, so healthy players also carry attrition and injured ones
  are compared fairly. ROS totals are then all lower, but ranks are fair.
- **PRE-REGISTERED 2026-10-15: B' (likely to miss this week).** B restricted to skill players (QB/RB/WR/TE) whose
  practice-model P(plays game G) < 0.5. Gate: (i) pooled Brier over k = 2..6 lower than P = 1.0, CI excluding 0,
  >= 3 of 4 seasons; AND (ii) fairness: the group's actual play rate over k = 2..6 is at least 10 points below that
  of skill players not on the report who played the previous game (so the discount is the injury, not ordinary
  attrition); AND (iii) the variant's mean prediction within 5 points of actual over k = 2..6.
  **Result: FAIL, not shipped.** 831 episodes: Brier 0.460 -> 0.226 [-0.256, -0.211], 4/4 (i passes); group plays
  54.0% vs 85.8% for not-on-report skill players, a 31.7-point gap (ii passes); but predicted 60.1% vs actual 54.0%
  (iii fails by 1.1 points: k=6 76.2 vs 68.7, the same long-horizon optimism as (A) and the diagnostic). Hurts
  therefore still shows 100% from wk 7. The unified lookahead availability (OPEN above) would fix the plateau and
  is the way to cover him; retest B' inside it.
- **PRE-REGISTERED 2026-10-15 (owner: "if it's data backed i support it"): unified lookahead availability.** One
  classifier, P(skill player plays his team's k-th game from decision week W) for EVERY fantasy-relevant player,
  replacing "return chain for players out, 1.0 for everyone else". Population: QB/RB/WR/TE with >= 1 offensive
  snap this season before W, on the team's roster at W (any status); W = 2..16; label = played (any snap) his
  team's k-th game from W (k = 1 is W itself). Features (all as known before W's games): k; position; offensive
  snap share over his last 3 team games; share of his team's last 4 games played; games played this season;
  this week's P(plays) (practice model on the final report when on it, else none) and on-report flag; roster
  designation (active / IR / IR-return / PUP / other reserve); return-model state (missed games) and its chained
  P(active) at k with step 1 = this week's estimate (production's current lookahead); week W. Gradient-boosted
  trees, same settings as the practice model. Walk-forward: decision seasons 2020-25, test 2022-25, each trained
  on decision seasons before it (practice and return models inside the features are walk-forward too).
  Baseline: production now (return chain with this-week step 1 for players in a return state, 1.0 for the rest).
  Evaluated on k = 2..12 with the k-th game in week <= 17. Gate: (i) pooled Brier lower, 95% bootstrap CI
  (2,000 player-season resamples) excluding 0, lower in >= 3 of 4 seasons; (ii) calibration: mean predicted within
  3 points of actual for each k in 2..12, and within 3 points for each group pooled over k: in a return state /
  on this week's report but not in a state / neither; (iii) the Hurts group (on the report, this-week P < 0.5,
  not in a state) within 5 points. Pass -> ship as the lookahead availability for all players (IR-return
  additions to the roster unchanged); ROS totals then carry attrition for everyone.
  **v1 result (`tools/ros_avail_eval.py`): PASS, NOT SHIPPED.** Brier 0.2395 -> 0.1526 [-0.095, -0.080], 4/4;
  by k within 1.2 points; groups within 2.3; Hurts group 59.4 vs 60.1 actual (old 100). But a subgroup check
  (seen before this v2) by position x role (offensive snap share last 3: <0.3 / 0.3-0.7 / >0.7) x k-bucket: starter
  RBs under-predicted 3.3 / 5.9 / 6.8 points (k 2-4 / 5-8 / 9-12), mid RBs and mid / starter TEs 3-5 under,
  starter QBs 4.7 over at 9-12 (actual 72%): rankings compare starters across positions, so that skews them. Also
  a bug: players on a bye at W have no roster row that week and were left out (Gibbs: 100% everywhere).
- **PRE-REGISTERED 2026-10-15: unified lookahead availability v2.** Same design, with: roster row = his latest at or
  before W (bye weeks); added feature season-long offensive snap share before W (separates established starters
  from 3-game blips); trees max_depth 5, 400 iterations (more room for position x role x k interactions; chosen
  before the run). Gate: v1's (i)-(iii), plus (iv) every position x role x k-bucket cell with n >= 300 within 5
  points of actual.
  **v2 result: FAIL, not shipped.** (i)-(iii) pass (Brier 0.2440 -> 0.1543 [-0.098, -0.082], 4/4; by k within 1.3;
  groups within 2.2; Hurts group 59.3 vs 60.1); (iv) fails: starter RBs -3.7 / -7.0 / -7.8, mid RBs -3.1 / -5.3 /
  -4.8, starter QBs 9-12 +4.1. Diagnosis (after the run): in-sample the model is calibrated (RB starters k >= 5:
  83.2 vs 84.3), but RB starters' later-game play rate is 74.9% (2020) and 74.4% (2021) vs 89.0 / 86.7 / 78.4 / 87.7
  in 2022-25: the COVID-19 reserve list (2020-21) pulled healthy starters for a week or two, and every test season
  trained on those years. Note the cells are clustered (the same ~50 RB starters a season repeat across weeks and
  k), so a 5-point cell bound is near the season-to-season noise (2024 alone: 78%).
- **PRE-REGISTERED 2026-10-15: unified lookahead availability v3 (post-COVID training).** v2 unchanged except the
  decision seasons used to train start in 2022 (2020-21 excluded: COVID reserve list; finding above came from the
  v2 test data, so this is not blind). Test seasons 2023, 2024, 2025 (each trained on 2022 .. season-1). Gate:
  v2's (i)-(iv) with (i) needing >= 2 of 3 seasons. Live model then trains on 2022 onward.
  **v3 result: FAIL, not shipped; STOPPED here** (three versions; a fourth would be gate shopping). Brier 0.2407 ->
  0.1546 [-0.096, -0.077], 3/3; by k within 1.3; Hurts group 57.3 vs 60.4 (ok); but (ii) the out-injured group
  46.7 vs 50.8 (-4.1 > 3) and (iv) mid RBs 5-8 / 9-12 -4.9 / -5.5 fail. Starter RBs now fine (-1.6 / -2.2), QB
  starters within 2.8, WR low 9-12 -4.3. Every version beat production by ~0.09 Brier yet none met the per-group
  bounds. Code kept as research: `tools/ros_avail_model.py`, `tools/ros_avail_eval.py` (rows cached per season).
  **Next angle if resumed (needs its own pre-registration):** fewer, fatter cells (the per-cell bound is near the
  clustered season-to-season noise: ~50 RB starters a season repeat across weeks and k), or a bound with a
  player-cluster CI instead of a fixed 3/5 points; or model the out-injured group by the return chain + a fitted
  plateau and use the classifier only for healthy players. ROS meanwhile: injured-only lookahead (+ (A)), healthy
  players at 1.0 (overstates everyone's ROS by ~15-25% evenly; ranks mostly unaffected except vs injured players).
- **PRE-REGISTERED 2026-10-15: partial-week practice models.** For k = 1 and 2 published practice days, a model
  trained on report weeks truncated to their first k days (3-day weeks; same features with no game status, same
  GB settings), used while a team's final report (any game status on it) is not out. Walk-forward 2021-25 (train on
  seasons before the test season, availhist 2018-25), all 3-day report weeks, both states pooled. Baseline: the
  current full-week model on the same truncated rows (= production today). Gate: Brier lower, 95% bootstrap CI of
  the difference (2,000 player-week resamples) excluding 0, lower in >= 4 of 5 seasons, AND mean predicted within
  3 points of actual for each k. Pass -> ship in `availability()` / `report_avail()`; midweek ESPN rulings keep
  precedence; then retest (c) against the new baseline.
  **Result: PASS, SHIPPED 2026-10-15** (`tools/partial_week_eval.py`). Brier 0.203 -> 0.160, diff -0.044
  [-0.046, -0.042], 5/5 seasons; mean predicted vs actual: 1 day 66.2% vs 65.0% (old 86.4%), 2 days 65.7% vs
  65.0% (old 75.2%). Per sequence (actual / old / new): D 39.7 / 80.9 / 40.8; L 79.8 / 90.5 / 79.2; F 86.6 /
  89.4 / 91.4; DD 16.1 / 29.6 / 15.7; LL 77.1 / 91.8 / 77.0. Small overshoot on all-full starts (FF 87.6 actual,
  92.7 new). Live wk 6: Lamar (Wed DNP) 19% -> 60% inactive. "Final report out" = anyone on the team's report has
  a game status, or the team has 3 practice days (backtests always see final weeks: unchanged).
  **(c) retest:** ESPN Doubtful on the report, n 67: played 3.0%, new baseline 22.3% (old 41.8%): a real gap
  left, but n < 100: OPEN, revisit when the live ESPN archive (daily from 2026-10-13, with update times) adds
  ~35 midweek Doubtfuls (pool with Wayback). **SHIPPED anyway 2026-10-15 by owner direction (not gated):** "Doubtful players almost
  never play"; every source agrees (official Friday Doubtful 2021-25 3.8% of 573, model 2.2%; ESPN early-week
  4.2%; midweek 2 of 71). Rate 2.8% in `espn_midweek.json` (`gated: false`). Still recheck on live data. ESPN Questionable on the report, n 4,690: played 63.2%, new baseline
  58.3% (old 75.4%): ESPN's Questionable adds nothing the practice days don't: CLOSED, no rule.
- **NEXT (owner-approved 2026-10-14): Players > Trends, a play-level query builder.** "Rushing YPC for Ravens
  players in the 4th quarter, 2022-24" -> leaderboard. Design agreed: the query is a sentence of tappable chips
  (stat family + metric / who: team, player, league, or against a team / filters: quarter, down & distance, field
  zone, score margin, time left, home/away, opponent, shotgun, run direction, pass depth / group by: player, team,
  season, opponent, quarter, down); results = leaderboard with the league baseline, a min-sample slider (low-n rows
  greyed, not hidden), a trend line when grouped by season, the query in the URL (shareable), rows open player
  pages, starter example queries. Season type toggle Regular / Playoffs / Both (owner: include playoffs). All in
  the browser: per-season compact play files (run + pass plays, ~33.5k/season, ~25 columns ~0.35-0.5 MB gzipped;
  1999-2026). The cached pbp (cache/pbp_*.parquet) is a prepared subset missing success, first_down, shotgun,
  no_huddle, yards_after_catch, pass/run location and gap: the build must load full nflverse pbp per season.
- **Trends: SHIPPED 2026-10-14; charting added same day ("add everything we have data for").** Data quirks found:
  - **nflverse files QB scrambles under play_type "run"** (qb_scramble = 1). Classify by qb_scramble first, or
    dropback / pass-rate counts lose ~3% of plays (league PROE read -5.5 instead of ~-2).
  - **Air yards and pass location start 2006** (0% before); YAC likewise. xpass / cpoe / xyac from 2006.
  - **Participation (NGS) 2016-2025, never the current season**; coverage shell / man-zone from 2018. **The
    vocabulary changed in 2023**: formations (SINGLEBACK / I_FORM / EMPTY -> UNDER CENTER / SHOTGUN / PISTOL) and
    routes (OUT / FLAT -> QUICK OUT / DEEP OUT / SWING, HITCH -> HITCH/CURL...). Mapped to one set; the out / flat /
    swing family merged because its boundaries moved. Coverage counts shift too (COMBO 1233 in 2023 vs 77 in 2025).
  - **FTN charting 2022 on incl. the current season** (CC-BY-SA, credit in the page note). Box / rushers / QB
    alignment fall back to FTN where participation is missing (current season): a source switch at 2026.
  - nflverse xpass runs high (2024 league pass_oe -1.7%): read PROE against the league column.
  - Coverage is measured, not hand-listed: index.json `cov`; trends.js drops uncovered seasons and says so.
  - Not built: QB sneak (is_qb_sneak), penalties, defenders' names from participation, drives.
- **RESULT {#charting-ab} (charting A/B): all four variants null** (croe / yacoe / cpoe / oe_all: |d MAE| <= 0.001 at every
  position, every CI spans 0, no season pattern). Left off. Run crashed once on a half-written cache parquet (fixed:
  atomic Cache writes).
- **PRE-REGISTERED 2026-10-14 (before any run): charting stats in projections.** Variants croe (catches over
  expected per target -> reception rate), yacoe (YAC over expected per catch -> receiving yards), cpoe (completions
  over expected per attempt -> QB passing yards), oe_all (all three). From nflverse cp / xyac (2006 on, live
  weekly). Team PROE is already an input (team_model pass_rate: proe_team), so not re-tested. FTN / participation
  features excluded: participation is never available live, FTN only from 2022 (too few walk-forward seasons).
  Walk-forward 2021-2026 vs baseline, tools/experiments.py, 95% bootstrap over season-weeks. GATE: adopt a
  variant if its all-position MAE CI upper bound < 0 and no position's CI lower bound > 0; or, if the all-position
  CI spans 0, adopt it only for the positions it targets (croe / yacoe: RB-WR-TE, cpoe: QB) when that position's
  CI upper bound < 0, it is better in at least 4 of 6 seasons, and no other position is significantly worse.
  Otherwise off. If more than one passes, oe_all decides (adopt the combination only if it beats each single).
- **Trends owner prefs (2026-10-14):** rows under the minimum are HIDDEN (count shown), not greyed; minimum has
  -/+ 1 steppers and a slider capped at the largest sample; distance filter / group-by by exact yards to 15+.
  Special teams added (<season>_st.json, kicking team's side; kickoffs: nflverse posteam = RECEIVING team, so
  team / score / wp / EPA flipped in the builder). 2025 kickoff touchbacks 21% vs 64% in 2024 (new rules).
- **Bijan 2023 = 19 diagnosed (owner: "dig deeper"):** 25 incompletions -27.7 EPA and 3 INTs -13.4 on passes TO
  him (Ridder / Heinicke), 3 lost fumbles -13.9, catches +28.2, rushing ex-fumbles -0.061/carry (league -0.046;
  boom-bust, 35% success). Target EPA bills receivers for their QB's throws (Gibbs 2023 -23 the same way).
  PRE-REGISTERED fix v1.1 (definition, decided on logic): receiving value = (catch - cp) x [league EPA(complete)
  - EPA(incomplete) at that air-yard depth, per season] + on catches (yac_epa - xyac_epa); rushing unchanged
  (fumbles are his). GUARDRAIL: ships if, walk-forward 2021-2025 all players, its rank corr. with next-season
  fantasy pts/g is not significantly below v1's (95% CI of v1.1 - v1 not entirely below 0). Face check reported.
- **FINAL (owner 2026-10-14: "it should correlate with output, not advanced-metric skill"): OVR = output.**
  Fantasy pts/g (site scoring) among qualified players, shrunk by measured k toward the qualified average. Next-
  season fantasy pts/g rank corr. (season-only grade, 2019-2024 -> next): QB .42 -> .58, RB .31 -> .63, WR .31 ->
  .68, TE .17 -> .60 vs the per-play EPA version. Face: Bijan 2023 84 (12.8 ppg) vs Allgeier 60; Saquon 2022-25
  95/90/99/87; G. Wilson 77-93; leaders read right. Lesson: three rounds of "skill" metrics (EPA, learned ridge,
  NGS) each produced cases the owner rightly called absurd; output is what people judge players by, and it is
  also the most stable. The EPA / RYOE / catchable work below now powers only the stat bars.
- **RESULT {#rb-ryoe}: RB via NGS RYOE + catchable-ball attribution -> superseded by output.** Face check passed: Bijan 2023 43 > Allgeier 39
  (was 24 / 32); Saquon 2022-25 58 / 76 / 97 / 34 (was 18 / 9 / 94 / 9); leaders read right (2023 RB CMC, Conner,
  Hall, Cook; WR Aiyuk, Deebo, Metcalf; TE Kittle, LaPorta, Andrews; 2025 RB Bijan, Cook, Henry, Achane, Gibbs).
  Guardrails (next-season fantasy pts/g, season-only grade): RB +0.021 [-0.092, +0.129], WR -0.033 [-0.087,
  +0.026], TE -0.036 [-0.115, +0.056], QB +0.000. Catchable fix: FTN is_catchable_ball (2022+) decides a target's
  catch expectation instead of cp (cp sees depth / route, not ball placement). Known leftover: per-play grades can
  bury volume receivers on awful offenses (Garrett Wilson 2023 2nd pct among qualified WRs).
- **OVR scale (owner): 50-99** = 50 + pct x 49/99 among the qualified (the lowest qualified player is a 50, not a
  0); sentence and stat bars keep the plain percentile.
- **PRE-REGISTERED (owner: "fix the ratings, get it to a point it makes sense"): RB rushing via NGS RYOE.** RB
  value = RYOE x league EPA per rushing yard (that season) + lost-fumble cost vs the league rate, + receiving
  (receiver's part, vs the RB average); per play among qualified. Ships if (a) RB face check passes (Bijan 2023 >
  Allgeier 2023; Saquon 2022 / 2024 / 2025 not bottom-quartile; workhorse stars top half) and (b) guardrail: RB
  rank corr. of season-only grade with next-season fantasy pts/g (both seasons qualified, 2019-2025) not
  significantly below the current grade's.
- **RESULT {#depth-pbp-notes}: pbp injury notes do NOT help the depth window** (h3_note50 -0.0001 [-0.0002, -0.0000], h3_note80 -0.0001
  [-0.0005, +0.0002] vs healthy3): the snap-pattern rule already catches the injuries that cost playing time. Not
  used for depth. News blurbs (tools/espn_news.py, owner idea): per-player ESPN endpoint only (no league feed), current
  season only -> archived daily for players on ESPN's injury list (~800 requests, 0.25 s apart, once a day); parsed
  with patterns (left / exited ... game, did not return, questionable to return, ruled out for the rest, forced out,
  injured his X during, quarter mentions); event = the last game HIS team kicked off before the blurb ("last Sunday's
  win" posted Sunday morning = the week before), explicit "Week N" only in the injury phrase's sentence. ~280 events
  wk 1-5 2026. Untestable on past seasons -> kept out of depth until the archive can test it. BOTH sources now mark
  the Injuries tab: an episode's in-game origin ("hurt in the week 3 game, Q2") = a note / blurb in its first week or
  the week before.
- **PRE-REGISTERED: play-by-play injury notes in the depth window.** nfledge/ingame.py (notes link 100% via team +
  jersey). Variants on top of healthy3: h3_note50 / h3_note80 = a game ALSO counts as left hurt when he has an injury
  note in it and played under 50% / 80% of his max share of his previous 3 played games (no next-week listing
  needed). GATE: adopt the better one if its accuracy minus healthy3 has a 95% CI above 0. Finding first: notes are
  incomplete (Jefferson 2026 wk 3 has none: noted only when play stops for a player down).
- **RESULT {#depth-healthy3} healthy3: SHIPPED (depth_build V7).** vs "both": +0.0003 [-0.0006, +0.0012] overall (no worse), starters
  back from injury 82.0 -> 83.1% (base 73.6). MIN wk 6: Addison 95, Jefferson 93 (was 34 / 67), Jennings 79.
- **Better in-game injury signal (owner idea):** pbp `desc` notes "TEAM-##-F.Last was injured during the play" (~3 /
  game since ~2010, ~1 / game 2003): team + jersey -> gsis via that week's roster. Candidate uses: depth "left hurt"
  flag (replace the snap heuristic, re-test), injury-history episodes (game + quarter he got hurt), availability model.
- **PRE-REGISTERED (owner design, 2026-10-14): "healthy3".** Each player's last 3 HEALTHY games that season (newest
  first, weights .5/.3/.2), skipping games he missed hurt (0 snaps + listed / reserve that week) and games he LEFT
  hurt (snap share under half his max of his previous 3 played games, and listed / reserve / absent-and-listed the
  next team week), reaching back as far as needed. Owner-specified rule -> ships unless it tests significantly worse
  than "both" (95% CI of healthy3 - both entirely below 0); result reported either way.
- **RESULT {#depth-window} (depth window): "both" ADOPTED** (depth_build V6, RECENCY .5/.3/.2 + games missed hurt skipped). 27,780
  cells 2019-2026, per starter: base 81.7%, skip_inj 83.1, recency 82.5, last1 82.7, both 83.6 (+2.0 [+1.8, +2.1]),
  better at every group; starters back from injury 73.6 -> 82.0. MIN wk 6: Addison 97, Jennings 79, Jefferson 67
  (was WR4 at 34), Felton 62. tools/depth_window_eval.py reproduces.
- **PRE-REGISTERED (owner: "test it"): depth-by-playing-time window.** Variants vs the live "last 3 team games,
  missed = 0": skip_inj (a game he missed while on that week's injury report or a reserve list leaves his average
  instead of counting 0), recency (weights .5 / .3 / .2 newest first), both, last1 (last game only). Score: share of
  predicted starters (fixed N per group) among the game's top-N snap-getters in the group; 2019-2026 regular season,
  weeks 4+, players ruled Out / reserve that week excluded for every variant. GATE: a variant replaces the live one if
  its accuracy minus the live one's has a 95% bootstrap CI (over team-games) above 0; among passers, the best.
- **Depth chart fixes (owner 2026-10-14, Jordan Addison):** (1) BUG: the playing-time chart's "on the team" check used
  ACT-only weekly rosters, so one inactive game (INA) erased a starter (Addison 83-98% snaps, vanished after missing
  week 5); now ACT or INA. (2) Out / reserve players who would have started by playing time stay at the end of the
  group, faded and struck through, with their tag (depth_build V5, flag [3]). (3) BUG: listed-chart rows called
  pl.map(who), passing the row array in as the snap % ("58,1,%" in special teams and the Listed chart view).
- **Spot starters get an asterisked OVR (owner 2026-10-14, Tyler Huntley):** unqualified players with >= 2 games
  at >= 50% of offensive snaps that season, graded on those games only, percentile vs the qualified pool (not joining
  it), [9] = 1, dashed badge "OVR 79*". Owner: no fringe sneaking in; kept strict (Huntley 2026: 48% in week 4 relief,
  100% week 5 = one game, ungraded until his next start). ~60-130 such players a season.
- **Trends two-way grids (owner pick from the ideas list, 2026-10-14):** "by X and Y" -> shaded grid (green / red
  vs the league, flipped for lower-is-better metrics; counts shade by size), sample under each value, cells under the
  minimum hidden, an All column, player / team / coach rows only (columns must fit a phone; caps 40 x 24), player /
  team rows sorted by their overall metric. Remaining ideas (ranked): type-a-question parser, distribution strip,
  +/- ranges + sample-adjusted sort, tap-through to plays, compare mode, lines for any ordered grouping, Rank column,
  web worker, share-as-image.
- **Penalties (owner 2026-10-14, "you pick where"):** team page Week tab box (per game + league rank, drawn, top
  calls, most-flagged players), player page box (season by type + career by season), Teams > Stats columns.
  nflverse pbp keeps one (the main) penalty per play; ~3,500 / season, 92% with a player. Bug fixed: stats_build
  deduped flags on drive + team + yards + play type, merging repeat false starts on a drive (now per play_id).
- **Gamecast (owner 2026-10-14):** Postgame "Player stats" = ESPN's full box score (all categories, team toggle,
  tile rows). game.html now loads shell.js + ui.css (shared tile CSS moved out of site.css: site.css hides
  non-active sections and blanks the game page). Replay: 2.5 s / play default (Slow 4 / Fast 1.3), a card per play
  (down & distance, a one-line headline from ESPN's play type + yardage with full names via the box score, the play
  drawn on the field: line of scrimmage, first-down line, gain / loss / kick arrow, then "-> 2nd & 2"). Win %
  tooltip clamps by its measured width.
- **One look everywhere (owner 2026-10-14): use NFLE.ui (shell.js) for ANY new list or matchup.** Player rows =
  NFLE.ui.player (headshot + team badge, name, pos + team; team logo when no photo), team rows = NFLE.ui.team
  (logo, nickname, "KC · 4-0"); both as tiles: table cls 'tiles', row class 'teamrow', row attrs
  NFLE.ui.tileStyle(TEAMS, team) with TEAMS = NFLE.week() -> D.teams. Matchups = NFLE.ui.matchTile(g, href) (the
  Games tab tile; NFLE.paintTiles() repaints live ones anywhere). Applied: Rankings, Power (already), Player Stats
  (stats JSON gained 'espn' for headshots), Team Stats, Standings, Trends (player / team groupings; no headshots:
  play files carry gsis only), player page (tile + "Matchup effect" box), team page Week tab (tile replaces the
  score / matchup / odds boxes).
  Second pass (owner: "look again"): Roles (faces), Injuries, Moves, Draft (also showed PFR codes KAN / NOR: now
  current codes), Playoffs (odds table + seed tiles with team trim), team page Players tab. Headshots for any list
  with a player id: data/espn_ids.json (gsis -> ESPN id, players active since 2010, stats_build), NFLE.ui.ready.
- **UI prefs (owner 2026-10-14):** player / team page header (photo, name, position, grade, team) is sticky
  (top: var(--navh), set by shell.js from the top bar's height; the page container needs overflow: clip, never
  hidden/auto, or sticky breaks). The grade badge reads "OVR", not "EDGE" (EDGE is a position).
- **Grade = per play among qualified players (owner 2026-10-14):** "grading should be per-opportunity; cut off
  non-relevant backs". Value over replacement per play (dropbacks + carries + targets); qualified = NFL stat-title
  minimums per team game (14 att QB, 6.25 carries or 1.875 catches RB, 1.875 catches WR/TE): ~190-210 players a
  season. QB/WR/TE read sensibly; RBs still odd (Saquon 2022 18, 2025 9; Jeanty 2025 1) because rushing EPA per
  carry is mostly the line / scheme. Proposed next: NGS rush yards over expected per carry for the RB run component.
- **Grade display fixes (owner: "Allgeier 87 vs Bijan, really?"):** (1) the by-season table showed the 3-season
  window grade, so Allgeier's "2023" was mostly his 2022 -> each season now that season only ([6], [7]); the header
  stays current form (window). (2) percentiles weighted by games played (shrunk 1-3 game backups piled at the mean
  and any above-average player leapt past them). Still: Saquon 2022 15 / 2023 5 / 2025 4, Allgeier 2024 87 as a
  backup. EPA per play can't see RB workload and swings with line / scheme / fumbles (RB next-season rank corr.
  ~.19 vs ~.81 for fantasy pts/g). Rookies need no special case: no penalty, just no earlier seasons in the window.
  Owner decision pending: what the grade should reward.
- **RESULT {#edge-grade-v1-2} v1.2: PASSED guardrail -> LIVE** (fantasy pts/g -0.013 [-0.028, +0.005]; QB .625 = , RB .389 -> .333,
  WR .546 -> .511, TE .161 -> .203). Bijan 2023 19 -> 42 (rest = 3 lost fumbles -13.9 and 35% rush success; Allgeier
  87 because his window includes a good 2022). Open owner question: EPA grade vs fantasy-style volume credit.
- **RESULT {#edge-grade-v1-1} v1.1: FAILED guardrail** (next-season fantasy pts/g -0.026 [-0.045, -0.007]; WR .546 -> .468): removing
  the throw also removed credit for EARNING targets (an average target worth 0). PRE-REGISTERED v1.2 (owner: "an RB
  penalized for a pass play?"), same guardrail, second look at these seasons: + league EPA of a target at that
  air-yard depth (that season), i.e. credit for earning the target independent of this QB's accuracy.
- **RESULT {#edge-grade-v2} (Edge grade v2): FAILED, v1 stays.** Team-changers (n=486, targets 2021-2025): next-season value/g rank
  corr. v1 .131, v2 .145, diff +0.014 [-0.082, +0.115]; fantasy pts/g -0.013 [-0.120, +0.085]. All players
  (reported only): value/g -0.027 [-0.063, +0.015]; fantasy pts/g +0.043 [+0.006, +0.079] (a lead, not a pass:
  post-hoc; needs a fresh holdout = the 2026 season). Face check, 2023 RBs (percentile among regulars): Bijan v1 16
  -> v2 76, but Gibbs 66 -> 32 and Saquon 2 -> 7: no version is clearly more sensible. Lesson: next-season value
  for movers is barely predictable (~.13) from ANY public stat set; the noise floor swamps the ability-vs-context
  distinction. `tools/grade_build.py --eval2` reproduces (cache/grade_eval_v2.parquet).
- **PRE-REGISTERED 2026-10-14 (before building): Edge grade v2 = ability, not situation.** Owner: keep v1 live
  meanwhile. v2 inputs are context-neutral only (NO raw EPA / value): NGS rush yards over expected per carry,
  separation, NGS YAC over expected; pbp CPOE, catch rate over expected, YACOE; PFR yards after contact, broken
  tackles, drops; role shares (carry / target / air-yards / snap share); explosive-run rate; QB sack and INT
  rates, depth; age, draft capital. Weights learned per position by walk-forward ridge to next-season value/g.
  GATE: among players who CHANGED TEAMS between seasons (main team by games, >= 6 games before and >= 4 after),
  pooled 2021-2025 targets, v2's rank correlation with next-season value/g minus v1's (shrunk 3-season value/g)
  must have a 95% bootstrap CI above 0. Reported, not gating: all players, and next-season fantasy points/g.
  Pass -> v2 replaces v1 on cards. Fail -> v1 stays, result recorded.
- **Edge grade v1 flaw (owner: "Bijan 2023 = 19 seems super wrong"):** value = EPA over replacement charges a
  receiver for his QB's incompletions / INTs (Bijan 2023 rec EPA -12.9 on 86 Ridder-era targets) and can't separate
  a back from his line (Bijan ~ Allgeier per carry; Saquon 2023 near bottom). It measures value produced in that
  offense, not ability.
- **NFL Edge grade (owner 2026-10-14: "something we're confident and proud of").** Pre-registered gate: a learned
  grade (ridge per position on shrunk per-play stats incl. YACOE, CROE, CPOE, PFR yards after contact / broken
  tackles / drops, age, draft) must beat last season's value/g AND last season's FP/g at ranking next-season value,
  walk-forward 2021-2025, CI excluding 0. Result: v1 (target = raw EPA/g) was mis-specified (most runs lose EPA, so
  RB volume read as bad: last FP/g correlated -0.17 with it); v2 target = EPA over replacement/g (one definitional
  change, then frozen): grade beat both baselines at every position on point estimate but no CI excluded 0
  (ALL +0.030 [-0.002, +0.066] vs last value; QB .627 / RB .194 / WR .304 / TE .178 rank corr.). FAILED -> owner
  chose the simple, honest version: "production grade" = shrunk EPA over replacement/g percentile (it is the
  baseline that the learned model could not beat). Known limit: RB EPA is line/scheme-heavy (Bijan 2023 = 19).
  Percentile population = everyone at the position who played that season (backups shrink to the mean, so a
  below-average starter can rank under them). Ideas for a v3 (fresh holdout needed, 2026 season-end): longer
  history (2006+ without PFR), fantasy-relevant target, rookies' draft prior.
- **Owner questions 2026-10-14 (answered, not yet approved):** (1) A/B charting stats in projections, volume-first:
  team PROE, YACOE / catchable rate, opponent pressure (contested catch is unstable, low priority); FTN only from
  2022 = 3-4 backtest seasons. (2) "NFL Edge grade" (Madden-like overall): don't cite Madden (EA proprietary,
  hand-set); build a per-position composite with weights learned from next-season predictiveness, shrunk by
  sample, shown as percentile / 40-99 with the stats behind it; gate = beats last-season fantasy points alone at
  predicting next season.
- Player Stats / Team Stats Regular / Playoffs toggle: DONE (c5e9abd).
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
- **Route data for the current season (checked 2026-10-15):** nflverse participation still ends at 2025 (2025 file
  posted 2026-02-10; FTN supplies it after each season). Sleeper's 2026 weekly stats carry snaps, no routes. FTN
  charting 2026 is per play (no per-player routes). Free live source found: heatradar.app/nfl/routes embeds JSON
  per player-week (routes, route share, TPRR, YPRR, slot / wide / inline rate; weeks 1-5 on 10-15, >= 8 routes). Its
  field names match PFF's premium export (republished; licensing unclear, could vanish), and it counts true routes
  while our history counts dropbacks on field (pass-blocking TEs / RBs differ). Use only if routes help at all.
- **PRE-REGISTERED 2026-10-15 (before any run): routes as a usage input (`route_input`).** route_share and
  route_share_long (dropbacks on field / team dropbacks, same recency weights as tgt_share) added to the target-share
  regression. Walk-forward 2021-2025 (the seasons with participation) vs baseline, tools/experiments.py, 95%
  bootstrap over season-weeks. GATE: all-position MAE CI upper < 0 and no position's CI lower > 0. If it passes, a
  second check before any live use: no season has both sources, so heatradar's 2026 route share vs snap share must
  match 2025 participation's route share vs snap share by position (slope within 10%, corr within .05).
- **PRE-REGISTERED 2026-10-15 (before any run): head-to-head vs Sleeper, then a blend.** Sleeper's projections API
  (`api.sleeper.app/projections/nfl/{season}/{week}`, company = rotowire, back to 2019) gives each player-week's
  stat line; scored in our half-PPR rules from the stats (Sleeper's own pts use INT -1 and bonuses). Rows: the
  baseline backtest's relevant rows (played, >= 2 prior games, top-N), 2021-2026 wk 5, matched by sleeper id ->
  gsis (data/fantasy_ids.json); unmatched / unprojected rows reported. Caveat: only the last saved Sleeper value
  exists (updated_at often after the week's Sunday), so theirs may include game-day news ours lacks. (1)
  Scoreboard, descriptive: MAE by position and season, ours vs theirs, CI on the difference. (2) Blend: final =
  (1 - w) ours + w Sleeper, w per position fit on 2021-23 (grid 0-1 by 0.05), tested 2024-26. GATE: all-position
  MAE CI upper < 0 on 2024-26 and no position's CI lower > 0. Live: Sleeper's API is free and open (CORS *).
- **RESULT {#route-input} route_input (2026-10-15): FAIL.** Walk-forward 2021-25: ALL -0.002 [-0.007, +0.003]; TE -0.021 [-0.036,
  -0.007] (better), RB -0.002, WR +0.004, QB 0; seasons -0.006 / -0.006 / -0.001 / +0.005 / -0.004. The TE gain is a
  post-hoc subgroup; a TE-only version would need its own pre-registration AND a live route source (heatradar, PFF
  definition) -- not pursued now. Moved to section 5 terms: routes as a usage input, no overall gain.
- **RESULT {#sleeper-blend} Sleeper head-to-head + blend (2026-10-15): gate passed, then INVALIDATED by leakage -> NOT shipped.**
  12,948 relevant rows 2021-26 wk 5, all matched. (1) Ours vs Sleeper MAE 5.176 vs 5.225, -0.049 [-0.092, -0.009]:
  QB -0.190 [-0.330, -0.049], WR -0.080 [-0.127, -0.032], TE -0.040 ns, RB +0.055 [+0.004, +0.105] (they're
  better). By season -0.31 / +0.01 / +0.05 / +0.06 / -0.07 / +0.06 (2026 wk 1-5): roughly a tie after 2021, and
  Sleeper's numbers are leak-advantaged (below), so we're at least even. Rank corr ours / theirs QB .369/.348, RB
  .533/.552, WR .420/.411, TE .373/.376. (2) Pre-registered blend, fit 2021-23 (QB .25, RB .70, WR .05, TE .15),
  tested 2024-26: -0.020 [-0.039, -0.002], GATE PASS; through the engine -0.024 [-0.042, -0.004].
  LEAKAGE (found while checking the live build): Sleeper's API keeps only the last saved projection, updated_at
  after kickoff on ~100% of 2024-26 rows, and players hurt IN the game are re-saved at 0: 2026 wk 4 Chase (20% of
  snaps, 4.2 pts), Barkley (7%), Mariota (16%), McConkey all show Sleeper 0 though they played. The earlier
  "disagreement predicts our error equally before / after late saves" check (corr .107/.170 vs .167/.144) did not
  catch it. Also a design error: our displayed projection is "if he plays" (availability separate), so a Sleeper 0
  (their availability call) must not be blended in. Leak-free version (Sleeper 0 = no number, 93 rows): fit
  2021-23 QB .05 / RB .75 / WR .05 / TE .15, test 2024-26 -0.011 [-0.029, +0.007] (WR -0.005 [-0.008, -0.002],
  others ns; seasons -0.036 / +0.009 / +0.011): FAIL. Same weights as the original fit with zero-skip -0.014
  [-0.032, +0.004]. Non-zero rows may carry partial post-game edits too, so even that is optimistic.
  -> sleeper_blend = {} (off; engine code kept, zero-skip rule built in). FORWARD TEST (pre-registered now): every CI
  run saves Sleeper's current-week projections (tools/sleeper_snapshot.py -> archive branch data/sleeper_proj/);
  at season end (2026 wk 7-17) take, per player, the last snapshot before his kickoff; weights = the zero-skip
  2021-26 fit (QB .15 / RB .60 / WR .20 / TE .25, fixed now); GATE: relevant rows, blend vs ours MAE CI upper < 0, no
  position's CI lower > 0. The tool for that comparison is not written yet (sleeper_compare.py reads the API).
- **Weeks 1-2 were never backtested (found 2026-10-15, tools/early_weeks_eval.py).** The standard backtest starts at
  week 3. Weeks 1-2 2021-26 (4,847 played rows): veterans fine (QB/RB/TE/WR MAE vs experts 6.01/3.78/2.43/4.11 vs
  6.86/3.74/2.36/4.05), rookies under-projected: bias RB +1.27, WR +1.64, TE +0.70; R1 WR +4.68 (proj 4.2, actual
  8.8). Cause: a player with no usage history gets share_hat = 0 (player_model.share_hats: `p[share] <= 0 -> 0`),
  so debuts project ~0 (2023 wk 1 Bijan Robinson 0.0 -> 17.3; Nacua, Addison, Flowers, Worthy, BTJ, Egbuka 0.0);
  37 of 66 rookie 10+ point games in weeks 1-2 were projected under 5. Veterans' RB / TE bias -0.54 / -0.39 there is
  likely the rookies' volume landing on them. The old "weakest on rookies (4.09 vs experts 4.00)" line is stale:
  weeks 3+ 2021-26 we beat the experts in every rookie / games-played bucket.
- **PRE-REGISTERED 2026-10-15 (before building): debut usage prior (`experiments.debut_prior`).** For an RB / WR /
  TE with no history in the loaded data (not in the feature frame), target share and carry share = a per-position
  regression fit on earlier rookies' first career games (rosters rookie_year = season, first ledger game): share ~
  depth-chart slot that week (1 / 2 / 3+ / unlisted) + draft tier (R1 / R2-3 / R4-7 / UDFA), fit walk-forward on
  every loaded season before the test season. Replaces the current 0; QBs unchanged (starter logic covers them);
  team-share normalization then applies as usual. Tests: weeks 1-2 2021-26 (tools/early_weeks_eval.py) and the
  standard weeks 3+ 2021-25 (tools/experiments.py, mid-season debuts). CI: 95% bootstrap over TEAM-weeks for weeks
  1-2 (only 12 season-weeks), season-weeks for weeks 3+. GATE: (i) weeks 1-2 debut rows MAE lower, CI excluding 0;
  (ii) weeks 1-2 all rows CI upper < +0.003 and no position's CI lower > 0; (iii) weeks 3+ all-position CI upper <
  +0.003.
- **BUG FIXED 2026-10-15: newcomer discount flagged debuting rookies in backtests.** `_newcomers` required "played
  somewhere", checked against a first-game table spanning every LOADED season, so in backtests a rookie debut who
  plays in later seasons counted as a newcomer (live has no future seasons: never affected). Harmless while debuts
  projected 0 (likely the OPEN "~9k rows, ~0.02" backtest side effect); with a debut prior it halved the rookie and
  handed the cut to his position mates. Now "played somewhere before this week".
- **RESULT {#debut-prior-v1} debut_prior v1 (weeks 1-2, after the bug fix): FAIL on part (i).** Debut rows +0.096 [-0.229, +0.411]
  (n 358); all rows -0.029 [-0.057, -0.002]; teammates -0.039 [-0.051, -0.028]; positions all ns. By depth slot,
  debut MAE old -> new: RB1 7.78 -> 4.85, RB2 4.26 -> 3.18, WR1 6.37 -> 5.00, TE1 4.61 -> 3.17, WR2 3.76 -> 3.64 (n
  10/25/17/7/63), but slot 3 / unlisted worse (RB3 1.93 -> 2.90, WR unl 1.19 -> 1.76): their median game is ~0 while
  the prior is a mean pulled up by rare big games. (Before the bug fix the halved prior gave debut rows -0.254 and
  teammates +0.024: the bug did both.) Not shipped.
- **PRE-REGISTERED 2026-10-15 (before seeing any weeks 3+ debut rows): debut_prior v2 ("d12").** Same prior, applied
  only to debuts listed at depth slot 1 or 2 that week; slot 3+ / unlisted stay 0. Decided on FRESH rows: weeks 3+
  2021-25 (mid-season debuts; tools/experiments.py debut_d12 vs baseline, both with the bug fix). GATE: debut rows
  (no history) MAE lower, 95% CI over season-weeks excluding 0; all rows CI upper < +0.003; no position's CI lower >
  0. Weeks 1-2 numbers for v2 are reported but are in-sample for the slot choice.
- **debut_prior v2 on weeks 3+ 2021-25: NO POWER.** Only 5 slot-1/2 debut rows (relevant-row MAE unchanged; debut
  rows +0.40 [-0.84, +1.63]). AMENDED 2026-10-15 before running: the deciding test moves to weeks 1-2 of 2016-2020
  (seasons no test has touched; weekly depth charts exist), same gate as v1 parts (i)-(ii), team-week CIs, v2 vs
  baseline. Pass -> ship d12; fail -> off until 2027 weeks 1-2.
- **RESULT {#debut-prior-v2} debut_prior v2 "d12": PASS -> SHIPPED (config experiments.debut_prior = "d12").** Fresh weeks 1-2
  2016-20 (history 13 seasons): debut rows (n 150) -1.023 [-1.699, -0.318]; all rows (3,932) -0.070 [-0.102, -0.038];
  RB -0.180 [-0.266, -0.101], TE -0.022, WR -0.037, QB -0.002 (ns); teammates -0.032 [-0.044, -0.021]; every
  season better (-0.071 / -0.057 / -0.039 / -0.101 / -0.082). Weeks 3+ 2021-25 relevant rows +0.000 [0.000,
  +0.001]. In-sample 2021-26 weeks 1-2: debut -0.654 [-1.352, -0.000], all -0.040 [-0.064, -0.017]. Weeks 1-2 are
  still unmeasured by the standard backtest: tools/early_weeks_eval.py + tools/debut_gate.py cover them.
  OPEN (newcomer side effect) likely closed by the bug fix above; not re-measured.
- **PRE-REGISTERED 2026-10-15 (owner: "did you test 95%+? 98?"): narrower blowout filters.** Only 10-90% (old) vs
  none was tested on games; 5-95 only on fantasy MAE (2026-10-12 audit, insensitive). Variants team_model.wp_window
  = [0.05, 0.95] and [0.02, 0.98] vs no filter, tools/game_eval.py 2021-25 --only=fitted, paired by game. GATE: adopt
  a window only if margin MAE beats no filter with the 95% CI over season-weeks excluding 0 (if both do, the better
  one); then confirm fantasy MAE not worse (tools/experiments.py, CI upper < +0.003).
- **RESULT {#blowout-filters} narrower blowout filters (2026-10-15): both FAIL, no filter stays.** Game margin MAE 2021-25 (1,279
  games, paired): none 10.548 (winners 61.0%); 2-98% 10.573, +0.025 [-0.022, +0.076], worse every season (60.2%);
  5-95% 10.630, +0.082 [+0.023, +0.143], worse every season (59.0%); old 10-90% 10.638 (+0.090). Monotone: every
  slice of blowout plays removed costs accuracy. Switch kept off (team_model.wp_window absent). Context: the removal
  moved week-6 2026 ranks a lot (SEA net 1 -> 6, MIN 2 -> 8; SEA offense 29 -> 24: 18% of its plays in blowout
  states at +0.26 EPA/play vs -0.16 otherwise; MIN defense 2 -> 1). The Power tab's move arrows compare weeks, not
  model versions, so a model change the same week looks like movement.
- **SHIPPED 2026-10-15 (owner: rooting guides "restricted to the current week", "be elegant where we present it",
  and the odds-by-week chart from a scorereport.net screenshot):** research (PFF 2021 method, scorereport, 538,
  inpredictable, ESPN FPI) -> paired flip: per simulated season, re-run standings with only that game flipped, so a
  swing is the game's own effect (splitting seasons by result is noise-dominated: SE ~sqrt(p(1-p)/N) per group).
  2,000 seasons x 14 games, standard errors ~0.2-0.3 pts; a swing shows only if >= 0.5 pts and >= 2 SE. Goal ranked:
  make playoffs, else division (team > 95% or < 3% to make it), else top seed; conflicts tagged. Best / worst case =
  all of this week's games their way / against them, 500 seasons (paired). Placement: team page Playoffs tab (chart +
  guide, above the history), a one-line "Rooting interests" box on the Week tab (current week only), Matchups tile
  note for the top 3 games by 2p(1-p) x summed playoff swing. Odds run 49 s locally with rooting (multi-process).
- **Depth by playing time: injured players with a role stay listed (owner 2026-10-15, Jordan Mason).** Two causes he
  vanished: the roster check counted ACT / INA only, so every IR player (status RES) was dropped before the
  injured-starter rule ran; and that rule kept only would-be starters (Mason was RB2, 45%). Now RES counts as on the
  team, an Out / reserve player with a healthy-game share >= 15% is kept (tagged, end of group), and a week whose
  roster isn't published yet (per team) keeps the latest roster's reserve tags. Finished seasons in cache/depth_site
  keep the old rule until rebuilt.
- **Number chips site-wide (owner 2026-10-15, after the box score):** shell.js NFLE.chips + a MutationObserver wraps
  plain stat values in data tables in span.sc (headers span.sc.h) when 80%+ of a column qualifies; cells with their own
  markup (bars, badges, words like "cov") stay plain; `no-chips` on a table opts out. NFLE.Table adds 8 px per
  non-pinned column on fixed-width tables so chips don't clip. Box score (pst-tbl) keeps its tighter packed variant.
- **PRE-REGISTERED 2026-10-15 (owner: "aren't expert rankings available before Friday?"): early-week ECR.** FantasyPros
  weekly ECR exists all week (DynastyProcess re-scrapes twice daily), but nflverse's history keeps only Friday's, so
  Tue-Thu projections run without the expert blend and early-week ranks can't be backtested. Every CI run now saves
  the current scrape (tools/ecr_snapshot.py -> archive branch data/ecr_snapshots/). TEST once 4+ weeks of snapshots
  exist (from 2026 wk 7): projections as they stood Tue / Wed / Thu (archived pages), re-blended with that day's
  ECR using the CURRENT Friday-fit blend weights, vs as published (no ECR). Relevant RB / WR / TE rows. GATE:
  MAE better with the 95% CI over team-weeks excluding 0 on the Tue-Thu rows, no position worse; then early-week
  ECR goes live (the same pre-kickoff guard).
  **SHIPPED AHEAD OF THE TEST 2026-10-27 (owner: "can we ask for forgiveness instead of permission ... our testing shows
  our projections are better when we incorporate ecr ... waiting til friday causes a jarring 3-5pt swing for some
  players all at once").** data.load_ecr adds the current week's live scrape (load_ff_rankings(type="week"); the same
  PPR positional pages as the history) to the Friday history; each row is tied to its week by its own game's kickoff,
  not the scrape date (an early-Tuesday scrape holding last week's ranks can't land on this week), and the
  per-player pre-kickoff guard stands. Training reads past seasons' ECR only, so nothing retrains. Tuesday's pool is
  thinner (2026-10-27: 264 players vs ~450-500 by Friday). The test above still runs as registered: if early-week
  ECR fails it, the live scrape comes back out.
- **Rankings: K and D/ST tabs (owner 2026-10-15).** From data/kdst.json (this week through 17), standard ESPN scoring
  (the rules both models' gates used); weekly (proj, matchup, team pts / FG att / XP for kickers; opp pts / sacks /
  takeaways for defenses, tiers) and rest of season (this week's game drops once it kicks off). Scoring helpers moved
  to shell.js NFLE.kdst (League tab uses the same). The scoring panel still applies to QB / RB / WR / TE only.
- **PRE-REGISTERED 2026-10-15 (owner: why is Drake Maye 6.5-11% inactive with full practices?): role in the
  practice model (`injuries.practice_role`).** Diagnosis: the practice / partial-week GB models see only the practice
  days, game status and a skill flag, and learn "played a snap"; backups who are active but never enter count as
  not playing, so every player on the report inherits backup-level risk (history 2019-25: listed, final day Full, no
  status: QBs 16.3% no snaps, but starting QBs (50%+ snaps last game) 4.0%, skill starters 1.2%; Maye got 6.5% FFF /
  11% FF). Variant: add his recent role, the mean snap share (offense or defense) over his last 3 games before that
  week (0 if none), to both the full-week and partial-week models. GATE (walk-forward 2021-25,
  tools/experiments.py baseline,practice_role): availability Brier on injury-report player-weeks lower with the 95%
  CI over season-weeks excluding 0; fantasy MAE not worse (CI upper < +0.003). Reported, not gating: calibration
  for starters with full practice and no status. Separately OPEN: Maye week 1 2026 showed 46.9% healthy-scratch
  risk as the starter (archived page); check the healthy-scratch model's week-1 inputs.
- **Week-1 healthy-scratch bug (found 2026-10-15, Drake Maye wk 1 46.9%).** The healthy-scratch model's history
  features (games, active rate, last game, snap share) count the current season only, and it trains on week 2+. In
  week 1 every player has n_prev 0 / snap_avg 0, a profile that in training means "backup with no role": all 32
  depth-1 QBs get P(active) 0.70 from the model trained through 2025 (Josh Allen too); the archived wk-1 page had Maye
  at 0.53, a hair from the < 50% "sits" line that hands his volume to teammates.
- **PRE-REGISTERED 2026-10-15: carry last season into the scratch history (`injuries.scratch_carry`).** A player with
  no games yet this season starts from his previous season's totals (games, active games, mean snap share when
  active, whether he played his last game); training then includes week 1. Rookies / no prior season: unchanged.
  TEST (tools/early_weeks_eval.py, weeks 1-2 2021-26, baseline vs scratch_carry, all candidate rows): GATE (i)
  week-1 Brier of availability vs played, players not on the injury report, lower with the 95% CI over team-weeks
  excluding 0; (ii) weeks 1-2 fantasy MAE (played rows) not worse, CI upper < +0.003; (iii) weeks 3+ 2021-25
  fantasy MAE not worse (tools/experiments.py).
- **RESULT {#practice-role-all} practice_role (all positions): written gate PASS, but QB significantly worse -> not shipped as is.**
  Walk-forward 2021-25, availability Brier on injury-report player-weeks 0.0987 -> 0.0950, -0.0037 [-0.0047, -0.0027],
  better every season; fantasy MAE -0.000 [-0.001, +0.001]. By position: RB -0.0048 [-0.0071, -0.0025], TE -0.0045
  [-0.0066, -0.0025], WR -0.0046 [-0.0062, -0.0032], QB +0.0033 [+0.0008, +0.0059]. Diagnosis correction: depth-1
  QBs listed with full practice and no status actually played only 94.1% (n 220): the old model's 93.8% was
  right (Maye's 6.5% was fair for his spot); the role input made them 97.4% (overconfident). Skill starters with
  full practice: old 93.8% / new 97.0% / actual 96.7% (the real fix).
- **PRE-REGISTERED 2026-10-15 (amendment, before running): role input for RB / WR / TE only
  (`injuries.practice_role = ["RB","WR","TE"]`).** Precedent: the expert blend is position-limited the same way.
  QB rows get role -1 (no role information). GATE (2021-25 walk-forward): availability Brier overall CI upper < 0,
  QB CI lower <= 0 (not significantly worse), fantasy MAE CI upper < +0.003.
- **RESULT {#practice-role-skill} practice_role RB/WR/TE only: PASS -> SHIPPED (config injuries.practice_role).** Availability Brier on
  injury-report player-weeks 2021-25 0.0987 -> 0.0931, -0.0056 [-0.0068, -0.0044]; QB -0.0099 [-0.0137, -0.0062], RB
  -0.0043, TE -0.0038, WR -0.0060 (all CIs exclude 0); every season. Fantasy MAE ALL -0.000 [-0.002, +0.001] (TE
  +0.001 [0.000, 0.002]). Correction to the earlier note: the "94% of healthy starting QBs play" figure was wrong:
  the depth chart still listed benched QBs as QB1 (Tyrod Taylor, Tannehill, Richardson...). See the job-security
  study below.
- **RESULT {#scratch-carry-v1} scratch_carry: FAIL on part (iii).** Weeks 3+ 2021-25 fantasy MAE +0.003 [-0.000, +0.006], QB +0.020
  [+0.003, +0.043] (training on week-1 rows changed the model for every week). Not shipped; a week-1-only version
  (seed only week-1 rows, train as before) would need its own test.
- **Job-security study (owner 2026-10-15: "at what points do teams bench a healthy QB? same for other positions;
  contracts / sunk cost?"; tools/job_security.py, 2012-25, healthy = not on the injury report at all, benched = 0
  snaps while a teammate at his position plays 50%+).** QBs: incumbent starters (started the team's first game)
  benched 1.43% of weeks 1-17 vs 11.4% for interim starters; by season-to-date EPA/dropback percentile (incumbents):
  bottom 10% 4.7%, 10-25% 3.2%, 25-50% 1.8%, top half ~0.6%; first-round rookie behind him 10.2% vs 1.2%; team
  <30% wins 2.9% vs 50%+ ~0.6%; R1 1.1% vs later ~2%; paid 12%+ of the cap 0.8%. Sunk cost: bottom-25% performers
  paid 7%+ of the cap 3.0% vs 3.9% cheaper (10 vs 18 events: direction as expected, not distinguishable from noise).
  Top-half benchings were almost all final-week rests. RBs: zero-snap benchings 0.5% (they lose carries, not the
  game). Usage: 2021-25 backtest, top-10% RBs (season FP/G) got 7% more carries than projected (17.05 vs 15.96),
  bottom 25% 2% fewer; WR +3% / -5%.
- **PRE-REGISTERED 2026-10-16 (before running): (A) `injuries.job_security` - healthy-scratch model features:**
  incumbent (started his team's first game: QB 70%+ snaps, others led the position group), season-to-date EPA per
  opportunity percentile at his position (as of the week), a first-round rookie at his position behind him, team
  win % before the week, contract APY share of the cap that season, and the team's last regular-season week. GATE:
  availability Brier on players NOT on the injury report (the scratch model's rows), 2021-25 walk-forward, lower
  with the 95% CI over season-weeks excluding 0, no position significantly worse; fantasy MAE CI upper < +0.003.
  **(B) `experiments.share_quality` - the player's EB-shrunk opponent-adjusted EPA per opportunity (rush for carry
  share, target for target share) as a share-regression input.** GATE: fantasy MAE all-position CI upper < 0, no
  position's CI lower > 0.
- **PRE-REGISTERED 2026-10-16: scratch_carry v2 ("week1").** Seed last season's history only into each team's first
  game of the season; the model's training is unchanged (weeks 2+ identical by construction). GATE (weeks 1-2
  2021-26, tools/early_weeks_eval.py + tools/scratch_gate.py): week-1 availability Brier for players not on the
  report lower, CI over team-weeks excluding 0; weeks 1-2 fantasy MAE CI upper < +0.003.
- **scratch_carry v1, weeks 1-2 (for the record; v1 already failed part iii):** week-1 availability Brier, players not
  on the report, 0.1248 -> 0.1078 (-0.0170 [-0.0211, -0.0130]); the current model's week 1 is badly calibrated (QBs
  mean P(active) 0.332 vs 0.482 actually played; carry 0.535). Weeks 1-2 fantasy MAE -0.0017 [-0.0069, +0.0043]
  (part ii FAIL, upper > +0.003). v2 (week-1-only seeding, training unchanged) is the follow-up.
- **Watch list (owner 2026-10-16): Lamar Jackson / Tyler Huntley (BAL), Baker Mayfield / Jalon Daniels (TB);**
  tools/watch_players.py prints them for this week + lookahead. Baseline (wk 6): Lamar 84.6% inactive but Huntley
  46.6% inactive; Baker 97.2% but Daniels 41.2%: the healthy-scratch model scores a backup QB as a generic backup
  unless the starter is officially Out / Doubtful (ahead_out), so his chance to play ignores the starter's.
- **PRE-REGISTERED 2026-10-16 (before computing): backup QB plays when the starter sits.** For the team's QB2 (depth
  2, not on the injury report) when the team's QB1 has a chance to sit: P(QB2 plays) = P(QB1 sits) + (1 - P(QB1
  sits)) x r, r = the measured rate a healthy QB2 plays when QB1 plays (fit on 2021-23 backtest rows). TEST on the
  cached baseline backtests 2024-25 (QB2 rows whose QB1 had avail < 0.95): Brier of the rule vs the current
  availability, lower with the 95% CI over team-weeks excluding 0 -> implement in the engine.
- **RESULT {#scratch-carry-v2} scratch_carry v2 (week-1-only seeding): FAIL on part (ii).** Week-1 availability Brier, players not on
  the report, 0.1248 -> 0.1174 (-0.0074 [-0.0118, -0.0031]), but it overshoots (RB / WR / TE mean P(active) ~0.91
  vs 0.84-0.88 actual) and weeks 1-2 fantasy MAE +0.0012 [-0.0050, +0.0091]. Off. OPEN: week 1's healthy-scratch
  numbers are badly calibrated (QBs 0.33 vs 0.48 actual); a calibrated week-1 model (e.g. its own week-1 fit on
  last season's state) is the next idea.
- **SHIPPED 2026-10-16: backup QB plays when the starter sits (config injuries.qb2_play_rate = 0.232).** Gate (pre-
  registered above): 2024-25 QB2 rows whose QB1 had avail < .95, n 371: Brier 0.2283 -> 0.1957 (-0.0326 [-0.0562,
  -0.0093]); mean P(play) 0.425 / rule 0.465 / actual 0.439. Note: a healthy QB2 plays only 74.6% of the time when
  QB1 sits (a QB3 / stale chart), so the rule's "1.0 when QB1 sits" is generous; refining it is a later test.
- **RESULT {#job-security} (A) job_security: PASS -> SHIPPED (config injuries.job_security = true).** Availability Brier, players not on
  the report, 2021-25 walk-forward (n 30,567): 0.0765 -> 0.0763, -0.0002 [-0.00045, -0.00001] over season-weeks. By
  position: RB -0.0010 [-0.0013, -0.0006], WR -0.0002 [-0.0005, +0.0001], TE -0.0000, QB +0.0005 [-0.0003, +0.0013]
  (none significantly worse). Fantasy MAE -0.000 [-0.001, +0.001]. A small gain, mostly RBs; for QBs the features
  add nothing the depth chart and active history don't already carry (QB benchings of healthy incumbents are rare,
  1.4% of weeks). Owner-requested contract input included (cap share).
- **RESULT {#share-quality} (B) share_quality: FAIL.** Fantasy MAE +0.002 [0.000, +0.003] overall, worse; no position better. Off.
- **PRE-REGISTERED 2026-10-16 (before running): (C) `injuries.practice_rest` - veteran rest days in the practice
  model** (owner: Keenan Allen, 34, DNP Wednesday "Not injury related - resting player" with a groin listed second;
  the model reads only the D/L/F sequence, so a rest DNP looks like an injury DNP). Variant `practice_rest`: a flag
  for the week when any of his report / practice injury fields says resting; variant `practice_rest_age`: the flag +
  his age at the start of the season. GATE (each variant vs baseline): availability Brier on injury-report player-
  weeks, 2021-25 walk-forward (tools/experiments.py; final reports), lower with the 95% CI over season-weeks
  excluding 0; no position significantly worse; fantasy MAE CI upper < +0.003. Also reported: mean P(play) vs actual
  for rest-flagged weeks. The flag comes from the week's final record, so it is judged on final-report weeks only;
  midweek it would be partly hindsight.
- **PRE-REGISTERED 2026-10-16 (before running): (D) `experiments.grade_prior` - the Edge grade as a projection
  input** (owner: "does factoring our Edge grade into projections help?"). The grade (tools/grade_build.py) predicts
  next-season value per game from the player's recent seasons; built walk-forward for season s from seasons before
  s only (no in-season information), as an input to the share regressions (carry share, target share, dropback
  share). GATE: fantasy MAE 2021-25, all positions CI upper < 0; no position's CI lower > 0.
- **AMENDMENT to (D), before running (2026-10-16):** the published Edge grade is not the advanced-stats ridge in
  grade_build.py but "current form" = fantasy points per game over this season and the two before (weights 1 / .6 /
  .3), shrunk toward the position mean. Testing the preseason-only version would test something the site doesn't
  show, so `grade_prior` = that number AS OF THE WEEK (games before the week only; priors from completed seasons),
  as an input to the carry, target and dropback share regressions. Gate unchanged.
- **Finding 2026-10-16: the listed reason matters and the practice model ignores it.** Wednesday-DNP weeks, played
  that week (2018-25, n >= 40 each): hamstring 46%, neck 50%, concussion 58%, groin 60%, ankle 67%, knee 69%, toe 80%,
  back 81%, illness 81%, personal matter 82%, "Not Injury Related" 94%, resting player 98%. (C) only flags the word
  "resting", so it misses the plain "Not Injury Related" label (679 such weeks) and "Rest".
- **PRE-REGISTERED 2026-10-16 (before running): (E) `injuries.practice_reason`** - the practice model gets the
  week's listed reason as a category (one flag each): hamstring, neck, concussion, groin / quad / thigh / calf
  (soft-tissue leg), ankle, knee, foot / toe, shoulder / elbow / hand / wrist (upper body), back / hip / ribs, illness,
  personal matter, rest (any "rest" or "Not Injury Related" without another reason), other. Same gate as (C):
  availability Brier on injury-report weeks 2021-25 lower with the CI excluding 0, no position significantly worse,
  MAE CI upper < +0.003; final-report weeks only (the reason is the week's final record). If both (C) and (E) pass,
  ship (E) (it contains (C)).
- **Collect now, test later:** ESPN's injury notes (archived daily since 2026-10-13: detail = strain / sprain / tear /
  surgery, side, return date, reporter comment: "expected to play", "game-time decision", "trending toward", "rest
  day"). Too little history to test; a season of archive will be.
- **Finding 2026-10-16: body part x practice pattern** (Questionable, 3-day weeks, 2018-25; descriptive, (E) is the
  test). Within the SAME practice pattern the listed reason moves the play rate 15-30 points: DDL hamstring 51% vs
  ankle 77%; DLL concussion 54% vs foot 83%; DDD hamstring 20% vs illness 50%; LLL concussion 59% vs knee 73%.
  Hamstring is the worst or near it in every pattern; concussion is bad whenever he didn't finish the week full.
- **Finding 2026-10-16: same body part again does NOT mean more missed time.** Episodes 2020-25 (history from 2019):
  missed 1+ games, first time 60% / same part earlier this season 57% / same part in an earlier season 55%; average
  missed 1.05 / 1.01 / 1.06. By part (first / same season / earlier season): hamstring 71 / 64 / 68%, ankle 61 / 54 /
  57%, knee 63 / 62 / 58%, concussion 73 / 78 / 72% (repeat n 41). Likely why: a part listed again is often a nagging
  injury he plays through, while serious repeats go to IR and drop off the report. Not worth a model input.
- **Finding 2026-10-16 (owner: Ladd McConkey, missed week 5, limited Wed + Thu, site said 17% out): the practice
  models don't know he missed last week.** Limited Wed + Thu in 3-day weeks (2018-25): played 77.5% overall, 89.1% if
  he played his team's previous game, 59.3% if he missed it (n 2,193); WRs 63%, foot 65%. Then by Friday (missed
  last week): DNP 19%, limited 50%, full 86%. The partial-week model said 82.5% for McConkey.
- **PRE-REGISTERED 2026-10-16 (before running): (F) `injuries.practice_prev`** - the practice and partial-week models
  get "missed his team's previous game" (no snap in it) and how many games in a row he has missed (capped at 4). GATE:
  availability Brier on injury-report weeks 2021-25 lower with the CI over season-weeks excluding 0, no position
  significantly worse, MAE CI upper < +0.003; also reported separately for partial weeks (tools/partial_week_eval.py),
  where the McConkey case lives.
  Also on FINAL reports (Questionable, 3 practice days, 2019-25), played after playing / after missing the previous
  game: DDD 36 / 9%, DDL 75 / 35%, LLL 78 / 60% (n 1,020 missed), LLF 94 / 83%, FFF 93 / 65% (n 319); all 75 / 61%.
  The gap survives the game status, so (F) matters for the final model too, not only midweek.
- **PRE-REGISTERED 2026-10-16 (before building): (G) Tuesday model** (owner: Tuesday = waiver claims + the day before
  the first report; "get more accurate on Tuesdays"). Today, before a team's first report, the chance to play is last
  week's final status carried forward (p_next: one number per status). New: P(plays this week) for everyone on last
  week's final report (not on a reserve list), learned from what is known on Tuesday:
  last week's game status and practice days (counts, last day), whether he played last game, his snap share there vs
  his usual (left early), an in-game injury note (nfledge/ingame.py), games missed in a row, weeks on the report this
  episode and his practice days since the injury first appeared (the whole episode, not just last week), the listed
  reason (category), an extra rest week (bye) before this game, position, role, age. Gradient-boosted, walk-forward
  (trained on seasons before the test season). tools/tuesday_eval.py.
  GATE: 2021-25, Brier vs the current carry-forward on the same player-weeks, lower with the 95% CI over season-weeks
  excluding 0 and lower in at least 4 of 5 seasons; calibration: every predicted-probability decile within 4 points
  of what happened. Reported also: players who missed last game; Out-last-week players; in-game injuries. Live ESPN
  news (the early-week bridge) has too little history to be part of this test; it keeps overriding where it applies.
- **RESULT {#tuesday-model} (G) Tuesday model: PASS.** 2021-25, players on last week's final report (n 18,258): Brier 0.1378 ->
  0.1243, diff -0.0135 [-0.0160, -0.0110]; better 5/5 seasons (2024 only barely: 0.1327 -> 0.1313); worst decile
  2.7 pts. Subgroups (Brier; predicted old / new vs actual): missed last game 0.262 -> 0.233 (53 / 46 vs 47%); in-game
  injury note 0.257 -> 0.185 (78 / 61 vs 57%); left early 0.224 -> 0.182 (80 / 68 vs 65%); Questionable last week
  0.157 -> 0.137; Out last week 0.234 -> 0.238 (slightly worse: the one place the old table is as good).
- **AMENDMENT (G2), before running:** the test above only covers players already on last week's report. The core
  Tuesday case is a player who got hurt Sunday while healthy (not on that report); today the site treats him as
  healthy until news says otherwise (healthy-scratch model / ESPN bridge). Added population: players NOT on game k's
  report with an in-game injury note in game k or a snap share 20+ points under his usual. Baseline: what the site
  shows them (the healthy rate; carry-forward "None"). Same gate on that population, the model trained on both.
- **RESULT {#tuesday-hurt-unlisted} (G2): PASS.** Hurt in last game while not on its report (in-game note, or snaps 20+ points under his
  usual; n 7,973, 2021-25): Brier 0.2032 (shown healthy: the 88% healthy rate) -> 0.1531, diff -0.0501 [-0.0553,
  -0.0448], better 5/5 seasons; predicted 74.6% vs played 75.0%. In-game note: predicted 64.5%, played 65.0%; left
  early only: 80.9% vs 81.3%. (G) with the model trained on both populations: 0.1378 -> 0.1237 [-0.0166, -0.0116],
  5/5, worst decile 2.2 pts. -> SHIP: the Tuesday model replaces the carry-forward before a team's first report.
- **RESULT {#practice-rest} (C) practice_rest: FAIL; practice_rest_age: FAIL.** Availability Brier, players on the report 2021-25
  (n 7,598): rest flag 0.0931 -> 0.0930 (-0.0001 [-0.0005, +0.0004]); + age 0.0931 -> 0.0936 (+0.0005 [-0.0002,
  +0.0013]; RB MAE significantly worse). A vet's rest Wednesday is followed by full Thursday / Friday practice, which
  the model already reads as healthy: by the final report the label adds nothing. (The Tuesday model and (E) carry
  the listed reason, including rest, where it can matter: before the practice days exist.) Off.
- **PRE-REGISTERED 2026-10-16 (before running): (H) `injuries.tuesday_prior` - keep the Tuesday number after the
  first report** (owner: "if Tuesday is so accurate why are we throwing it out?"). The practice and partial-week
  models get the Tuesday model's P(plays) for that week as an input (the Tuesday model for season s trained on
  seasons before s only, for training and test rows alike; NaN where there is none). Today the Wednesday model starts
  over from the practice days (McConkey: Tuesday 48% -> one "limited" day -> 82.5%). GATE: as (F): availability Brier
  on injury-report weeks 2021-25 lower with the CI over season-weeks excluding 0, no position significantly worse,
  MAE CI upper < +0.003; partial weeks reported separately. If (F) and (H) both pass, ship the lower Brier.
- **PRE-REGISTERED 2026-10-16 (before building): (I) one availability model for every day of the week** (owner:
  "shouldn't Wednesday, or any given day, just use the same approach Tuesday does, with extra information?"). Today
  three models hand off (Tuesday -> partial-week 1-2 days -> full-week practice) and each starts over. New: ONE model,
  rows = (player, game) at each stage of the week: 0 = Tuesday (no report yet), 1 = Wednesday, 2 = Thursday, 3 =
  final report. Inputs: everything the Tuesday model has (from his last game) + this week's report so far (on it or
  not, practice days so far, the listed reason, and the game status at stage 3) + his role. Population: everyone on
  this week's final report or in the Tuesday population. Walk-forward 2021-25 (trained on seasons before), compared
  stage by stage with what the site uses at that stage today (stage 0: the shipped Tuesday model; 1-2: the partial-
  week models; 3: the full-week practice model with the role input), on the same rows; game status Out excluded
  (0% by rule). tools/week_avail_eval.py.
  GATE: stage 3 (the largest: final reports) Brier lower with the 95% CI over season-weeks excluding 0, no position
  significantly worse; stages 1 and 2 lower with the CI excluding 0 or at worst CI upper < +0.002; stage 0 CI upper <
  +0.002 vs the Tuesday model; every stage's deciles within 4 points. Then, as a second step before shipping, fantasy
  MAE 2021-25 CI upper < +0.003 (tools/experiments.py). (F) and (H) are dropped in favor of this.
- **RESULT {#one-model-v1} (I) one model for every day: FAIL (as registered), with large gains.** 2021-25, Brier today -> one model:
  Wednesday 0.2166 -> 0.1334 (-0.083 [-0.088, -0.078], 5/5), Thursday 0.1488 -> 0.1026 (-0.046, 5/5), final report
  0.0948 -> 0.0846 (-0.010 [-0.012, -0.008], 5/5; every real position better or no different), Tuesday 0.1327 ->
  0.1345 (+0.0018 [+0.0012, +0.0025], worse than the dedicated Tuesday model). Missed his last game: Wednesday
  predicted 80.5% today / 47.0% one model / 47.6% played; final 78.9 / 68.7 / 68.7%. Failed on: calibration (final
  report worst decile 6.2 pts: 61.4 predicted vs 67.6 actual; Wednesday 4.4 pts: 89.0 vs 85.3), Tuesday slightly
  worse, and rows with no position recorded (a data gap) worse. Not shipped.
- **PRE-REGISTERED 2026-10-16, second attempt after seeing (I): (I2).** Changes, each general rather than tuned to
  (I)'s numbers: (1) Tuesday keeps the dedicated Tuesday model; the one model serves stages 1-3 only. (2) A calibration
  step per stage: isotonic regression fit on season s-1 predictions of a model trained on seasons before s-1, applied
  to the season-s model. (3) Missing positions filled from the rosters. GATE: (I)'s gate for stages 1-3 AND, because
  this attempt was designed after seeing results, the same direction on data nothing has touched: 2026 weeks so far
  (trained through 2025): stage 3 Brier lower than today's practice model and stages 1-2 not worse. Then fantasy MAE.
- **RESULT {#one-model-v2} (I2): availability gate PASS.** 2021-25, today's model -> one model (calibrated): Wednesday 0.2166 ->
  0.1350 (-0.082 [-0.086, -0.077], 5/5, worst decile 3.6 pts), Thursday 0.1488 -> 0.1039 (-0.045, 5/5, 1.4 pts),
  final report 0.0948 -> 0.0844 (-0.0104 [-0.0124, -0.0084], 5/5, 3.2 pts); no position significantly worse (DB
  +0.003 [-0.007, +0.008]). Untouched 2026 weeks 1-6 (trained through 2025): Wednesday 0.2299 -> 0.1286, Thursday
  0.1634 -> 0.1033, final 0.0946 -> 0.0817. Missed last game: Wednesday predicted 80.5% today / 48.6% / played 47.6%.
  Tuesday stays the dedicated Tuesday model (0.1327 vs 0.1350). Next: the fantasy MAE step (experiments.py).
- **Finding 2026-10-16 (owner: "is a starter with a bad replacement rushed back?"): yes at QB and RB, not WR / TE.**
  Regular starters (60%+ snaps last 3 games, 5+ FP/G) who missed games and returned in-season, 2012-25 (n 695);
  replacement = the teammate at the position whose snap share jumped most; his first fill-in game's fantasy points vs
  the starter's usual, in thirds. Back after missing 1 game: weak fill-in 60% / middle 54% / strong 41% (avg missed
  1.86 / 2.00 / 2.46). QB 62 / 53 / 26% (n 212); RB 63 / 36 / 30% (n 78); WR 60 / 60 / 57%; TE 55 / 50 / 67% (n 95).
  Caveat (likely large at QB): reverse cause - a team expecting a long absence prepares the backup (first-team reps,
  game plan), so his first game looks strong because the absence was always going to be long. The clean version
  measures the replacement BEFORE the injury (his earlier starts / grade going in); that is the one to test as an input
  to the return-timing and availability models, QB and RB only.
- **RESULT {#edge-grade-prior} (D) grade_prior (Edge grade as of the week, as a share-model input): FAIL.** Fantasy MAE 2021-25 +0.003
  [+0.000, +0.007] (worse); QB -0.003 [-0.011, +0.004], RB +0.003, WR +0.006 [-0.000, +0.013], TE +0.003; worse in 3
  of 5 seasons. The grade is recent fantasy output, which the share and efficiency inputs already carry in finer form
  (opportunity shares + per-opportunity rates, recency-weighted); adding the blended number only adds noise. Off.
- **RESULT {#one-model-mae} (I2) step 2, fantasy MAE: by the letter FAIL (CI upper +0.004 vs < +0.003), not significantly worse.**
  2021-25: ALL +0.001 [-0.004, +0.004]; QB -0.010 [-0.030, +0.005]; RB +0.004 [-0.002, +0.011]; WR +0.002 [+0.000,
  +0.004] (edge of significance); TE +0.001; seasons -0.003 / +0.003 / +0.003 / -0.005 / +0.006. Availability Brier
  on report rows in the same runs 0.0935 -> 0.0903. -> SHIPPED under the owner-design rule (the one model is the
  owner's design: ship unless shown significantly worse; overall it is not), with this miss of my own pre-set MAE bar
  recorded. Projections barely move because availability changes the projection only when a player crosses 50%
  (who sits and whose volume is redistributed); the displayed inactive % is where it matters. Owner may hold it to
  the stricter bar: config injuries.week_model.
- **PRE-REGISTERED 2026-10-16 (before running): (J) team habits in the one availability model** (owner: "test by
  team"; Footballguys 2017-22: Philadelphia's Questionable players played 79%, Houston's 49%). Input `team_q`: the
  share of this team's final-report Questionable players who played, over its games before this week (the two
  seasons before + this season so far), shrunk toward the league rate with 20 pseudo-cases. Compared with the one
  model as shipped (I2), same rows, same calibration step. GATE: final report Brier lower with the 95% CI over
  season-weeks excluding 0, no position significantly worse; Wednesday / Thursday CI upper < +0.002; deciles within
  4 points; same direction on the untouched 2026 weeks. Also reported: spread of team_q across teams.
- **RESULT {#team-habits} (J) team habits: FAIL.** team_q varies (team-seasons 2021-25: 10th-90th percentile 59-80%, range 41-87%)
  but adds nothing the one model doesn't already see: final report 0.0844 -> 0.0841 (-0.0003 [-0.0010, +0.0004]);
  Questionable only 0.1793 -> 0.1779; QB significantly worse (+0.0074 [+0.0034, +0.0113]); Wednesday +0.0003,
  Thursday +0.0004; 2026 Wednesday worse. The habit shows up in each player's own practice days and status, which the
  model reads player by player. Off (code kept: tuesday.add_team_q, tools/team_q_eval.py).
- **Finding 2026-10-16 (owner: "anything else that might be a blind spot?"): where the one model is off.** Walk-
  forward 2021-25 final reports (predicted 83.5%, played 83.5% overall). Fine: bye next week (gap within 2.3 pts),
  short week / extra rest (within 1.4). Off: week 18 predicted 82.1% vs played 75.2% (-6.9; week 16+ Questionable
  -4.8); Questionable players who were Q 3+ times before and always played +4.8 (76.2 vs 81.0), who played < 60% of
  those -6.2; 3+ healthy teammates at the position -7.5 BUT measured from the same game's snaps (leaks the outcome:
  if he sits, backups play more), so not trusted as measured.
- **PRE-REGISTERED 2026-10-16 (before running): (K) three inputs for the one model.** (1) Calendar: week number and a
  final-week flag. (2) His own record when Questionable: times Q on a final report before this week and how often he
  played, shrunk toward the league rate with 3 pseudo-cases. (3) Depth, measured cleanly: teammates at his position
  who played 20%+ of snaps in the team's previous game and aren't on this week's report. Compared with the one model as
  shipped, same rows, same calibration; tools/k_eval.py. GATE as (J): final report Brier lower with the 95% CI excluding
  0, no position significantly worse; Wednesday / Thursday CI upper < +0.002; deciles within 4 points; same direction
  on 2026 so far. Each input also reported alone (descriptive, not gated).
- **RESULT {#blind-spots-k} (K): FAIL.** Combined (calendar + own Questionable record + clean depth): final report 0.0844 -> 0.0840
  (-0.0004 [-0.0012, +0.0004]); Wednesday -0.0003, Thursday -0.0002; 2026 Wednesday +0.0006. Alone (descriptive):
  calendar final -0.0007 [-0.0014, -0.0001] (the only signal; 2026's weeks 1-6 can't show a late-season effect),
  own record -0.0001 [-0.0007, +0.0005], clean depth +0.0002 [-0.0004, +0.0007]. The blind-spot pockets were partly
  selection (scanning many groups finds the biggest misses, which shrink back) and the same-game depth gap was the
  leak. Next for late season: the team's playoff situation (clinched / eliminated) from standings, which only weeks
  16-18 can confirm. Off (code kept: tuesday.add_k_feats, tools/k_eval.py).
- **PRE-REGISTERED 2026-10-16 (before running): (L) late-season stakes from playoff odds** (owner: "do it", after (K)
  found late-season rest is the real remaining gap). Inputs, as of the week before its games (tools/playoff_odds.py
  simulations, the same method as the Playoffs tab; each week's finished games only): the team's chance to make the
  playoffs, win the division and get the bye, plus the week number. Clinched = ~100%, eliminated = ~0%, a locked seed
  = odds that can't move. (L1) in the one availability model (players on the report), tools/stakes_eval.py vs the one
  model as shipped, same rows, same calibration. (L2) in the healthy-scratch model (players not on the report: rested
  healthy starters), tools/experiments.py availability Brier on non-report rows. GATE for each: weeks 15-18 Brier
  lower with the 95% CI over season-weeks excluding 0, no position significantly worse; weeks 1-14 not worse (CI
  upper < +0.0005); deciles within 4 points. (2026's weeks so far can't test a late-season effect; it is reported
  for weeks 1-14 only.)
- **RESULT {#stakes-injured} (L1) stakes in the one model: FAIL (narrowly).** Weeks 15-18 final report 0.0962 -> 0.0942 (-0.0020
  [-0.0047, +0.0003]; better 4/5 seasons; QB -0.0097 [-0.0178, -0.0016]); weeks 15-18 Wednesday -0.0041 [-0.0081,
  -0.0005], Thursday -0.0026 [-0.0058, +0.0005]; weeks 1-14 about zero but not tight enough for the "not worse" bar
  (Wednesday +0.0005 [-0.0005, +0.0016]); 2026 weeks 1-6 +0.0014 to +0.0026. Odds help late and add noise early, when
  every team is alive. Off.
- **RESULT {#stakes-healthy} (L2) stakes in the healthy-scratch model: FAIL (no change).** Non-report players weeks 15-18 (n 8,081):
  0.0839 -> 0.0839 (-0.00001 [-0.00042, +0.00037]); weeks 1-14 -0.00007; week 18 predicted active 84.3% with and
  without, played 82.1%. The final-week flag already in the healthy-scratch inputs (job security's last_week) carries
  most of the week-18 rest; what's left is ~2 points. Fantasy MAE -0.002 [-0.005, +0.001]. Off. Late-season stakes:
  closed for now (L1 near-miss on injured players, L2 nothing on healthy ones).
- **Finding 2026-10-16 (outside review by the Claude app, from the scrapeable site: "the inexperienced-QB penalty is
  very large (-21.5 per 100 dropbacks) and barely shrunk; check it"): it is, if anything, too SMALL.** [WITHDRAWN
  2026-10-16: a test-harness artifact, see {#game-eval-starter}.] Walk-forward
  game predictions 2021-25 (tools/game_eval.py --only=fitted), per team-game, starter = most dropbacks, inexperienced =
  < 150 career dropbacks entering the game (the model's own rule). Model margin miss from that team's side (positive
  = predicted better than they did): inexperienced starter (n 204) +2.41 pts [+0.51, +4.34], better in 4 of 5 seasons
  (2021 +3.7, 2022 -1.1, 2023 +2.5, 2024 +1.4, 2025 +5.3); experienced (n 2,354) -0.21 [-0.76, +0.32]. Vegas, same
  games: +1.42 [-0.46, +3.28]. Candidate test (not run): a stronger or experience-scaled penalty in the pass unit, gated
  on game margin MAE. (The reviewer's other points: rank history now flags QB-driven weeks; retired team codes
  removed; a separate power.json declined - index.json is one shared load for every tab.)
- **PRE-REGISTERED 2026-10-16 (before building): (M) Power rank = rest-of-season strength, injury-aware (owner chose
  "C": how good a team is from here on; this week's lineup stays as a column).** C for a team at week w = the mean,
  over its remaining regular-season games, of P(usual starting QB back that game) x net rating with him + (1 - P) x
  net rating with his backup; P from the return-timing chain fit only on outcomes known before week w (healthy usual
  starter: P = 1); usual starter = most starts this season before w (tie: the incumbent); backup = the most recent
  starter if not the usual one, else depth-chart QB2. A = today's rank basis (net with the most recent starter).
  tools/power_c.py, 2021-25, every week 2-18. GATE: (1) rank correlation (Spearman, 32 teams) with each team's actual
  point differential per game over its remaining games, averaged over season-weeks: C - A > 0 with the 95% CI over
  season-weeks excluding 0, on season-weeks where at least one usual starter is out (where C and A differ); overall
  C not worse than A (CI lower > -0.005). Reported, not gated: the same vs record and point differential so far;
  (2) playoff-game margins from C entering the playoffs (~65 games); (3) playoff odds with week-by-week C ratings,
  scored like the existing odds backtest (a separate test before changing the odds).
- **RESULT {#power-rank-c} (M) Power rank = rest-of-season strength: PASS -> SHIPPED.** tools/power_c.py (calls the
  site's own nfledge/powerc.py), 2021-25, 85 season-weeks: mean Spearman with rest-of-season point differential per
  game: C 0.445, A (this week's lineup) 0.436, point differential so far 0.424, win % so far 0.381. C - A on the 75
  season-weeks with a usual starter out +0.0102 [+0.0016, +0.0193] (gate); all weeks +0.0083 [+0.0002, +0.0163];
  better 4 of 5 seasons (2025 -0.005); C - PD so far +0.020 [+0.001, +0.040]. Teams without their usual starter then
  went -3.25 per game vs A -2.12 / C -1.56: backups are overrated generally (see the inexperienced-QB finding).
  Live: Power ranks by C (Net, units blended by the usual starter's mean chance over the remaining games, so units
  still add up), "This week" column = A; trend = C by week; schedule left rates opponents by their expected QB.
  Playoff odds still hold the current rank; test (3) pending.
- **PRE-REGISTERED 2026-10-16 (before running): (N) playoff odds with week-by-week, injury-aware ratings.** Today the
  simulation holds each team's current Power rank for every remaining game (an injured starter's backup "plays" the
  whole season). Variant: each remaining game uses ranks for ITS week, from ratings = P(usual starter plays that week)
  x net with him + (1 - P) x net with the backup (nfledge/powerc.py, chain fit on outcomes known before the week);
  playoff games use the last regular week's ranks. Baseline: today's rule (constant rank from this week's lineup),
  recomputed with the same code. Also reported: constant rest-of-season rank (C). tools/odds_c_eval.py, 2021-25, every
  week, 1,000 simulated seasons per week, the same random draws for both. GATE: make-playoffs Brier lower with the 95%
  CI over season-weeks excluding 0; division and bye Brier not worse (CI upper < +0.001).
- **RESULT {#odds-weekly-c} (N) playoff odds with week-by-week, injury-aware ratings: FAIL (no effect).** 2021-25, every
  week, 1,000 sims, same draws: make-playoffs Brier A 0.1372, weekly 0.1373 (+0.00007 [-0.00022, +0.00038]), C held
  constant 0.1373 (+0.00005 [-0.00024, +0.00035]); division +0.00020 / +0.00016; bye -0.00002 / -0.00001; seasons
  split 2-3. The win model uses the rank GAP (coarse) + Elo + this week's Vegas line, few teams are affected at once,
  and the record already banked dominates season outcomes. Weekly variant off. The live odds read Power's rank, which
  became C with (M): measured no different from the old rule, kept so the odds and the Power page use one rank.
- **PRE-REGISTERED 2026-10-16 (before running): (O) blend an uncertain QB into win chances** (owner: "is the split right
  at 50%?"). The 50% rule (P < 0.5 sits) stays for player projections: with two outcomes, the single scenario that
  minimizes expected absolute error is the likelier one, which flips at exactly 50%. A win chance is a probability, so
  for games where a team's usual starting QB is on the final report with P(plays) 5-95% (the one availability model,
  walk-forward), compare: binary = rate the team with the starter if P >= 0.5 else the backup; blend = P x win chance
  with the starter + (1 - P) x with the backup. Win chance from the game model's margin (normal, spread from the other
  seasons' misses). tools/qb_blend_eval.py, 2021-25, the game model as in tools/game_eval.py. GATE: win-chance Brier on
  those games lower with the 95% CI over games excluding 0. If it passes: Matchups' model chance and Power's "This
  week" use the blend.
- **RESULT {#qb-blend-winchance} (O) blend an uncertain QB into win chances: FAIL (no effect).** 204 games 2021-25 with
  a usual starter on the final report at 5-95%: win-chance Brier binary 0.2221, blend 0.2221 (-0.0000 [-0.0026,
  +0.0025]); seasons split 3-2. Most such QBs are Questionable at 70-90% and play, so the blend moves the chance a point
  or two. Vegas on the same games 0.2011: the market prices the injury news we don't see (and backups are under-
  penalized, see the inexperienced-QB finding). The 50% rule stays everywhere.
- **PRE-REGISTERED 2026-10-16 (before looking): (P) missing pass catchers and backs in the team rating** (owner asked
  whether "this week" counts non-QB injuries; it doesn't: only QBs, and CB / O-line adjustments were rejected). Inputs
  per team-game, knowable before kickoff: the share of the team's targets (and separately carries) over its last 3
  games held by WR / TE / RB players listed Out or Doubtful on the final report. Players already out for weeks are
  already absent from those games, so only fresh absences count. Adjustment to the predicted margin: b_pass x (own
  missing target share - opponent's) + b_rush x (same for carries), b fit by least squares on the game model's margin
  misses in the seasons before (walk-forward, tools/game_eval.py --save predictions). tools/skill_absence_eval.py,
  2022-25 (2021 has no earlier season of misses). GATE: margin MAE on games where either team misses >= 15% of its
  target or carry share: lower with the 95% CI over games excluding 0; all games not worse (CI upper < +0.02).
- **RESULT {#skill-absence-margin} (P) missing pass catchers and backs in the team rating: FAIL.** Walk-forward fits
  point the right way and are stable: b_pass -5.2 to -9.7, b_rush -1.6 to -3.0 points per 100% of share (so a team
  missing a 25%-target WR is about 2 points worse). But on the 311 of 1023 games 2022-25 with a team missing >= 15%,
  margin MAE 10.953 -> 10.987 (+0.034 [-0.179, +0.250]); all games 10.294 -> 10.309 (+0.015 [-0.053, +0.084]). A
  1-2 point nudge is small against ~10-point misses, and the game model already sees some of it (team volume features
  over recent games). "This week" stays QB-only for injuries. Rerun on the corrected harness (next entry): same
  verdict, 311 games 10.731 -> 10.750 (+0.019 [-0.198, +0.239]); all 10.165 -> 10.171 (+0.006 [-0.061, +0.075]).
- **RESULT {#game-eval-starter} test-harness fix: tools/game_eval.py rated each team's PREVIOUS starting QB, not this
  game's; the inexperienced-QB "too small" finding above is withdrawn.** Checking that finding before testing a bigger
  penalty: the harness rated last week's starter in 311 of 2,558 team-games 2021-25 (12%), so a backup's first start
  was predicted with the injured veteran and the penalty never applied. The live site was never affected (it rates
  this week's projected starter, report.matchups / team_tables). Split of the old predictions (miss from the team's
  side, + = overrated): inexperienced starter, rated QB wrong (n 83) +5.96 [+3.08, +8.89]; rated QB right (n 124)
  +0.46 [-1.99, +2.99]. Fix: rate the QB who started the game (most dropbacks) as a stand-in for the announced starter.
  Walk-forward 2021-25, 1,279 games: margin MAE 10.547 -> 10.428, winners 61.2% -> 62.1% (Vegas 9.766). With the
  right QB, inexperienced starters: first starts after a change (n 83) +1.95 [-0.90, +4.86] (Vegas +2.45), continuing
  (n 124) +0.43 [-2.02, +2.92] (Vegas +1.07): no evidence the penalty is too small, so no test. Earlier game_eval
  comparisons were paired on the same harness and stand. New lead: an EXPERIENCED QB taking over (n 228) is overrated
  +3.06 [+1.22, +4.87] (Vegas +1.55) - veteran backups / new arrivals rated near their old (shrunk) career level.
  Also: tools/rank_predictor.py (win-chance blend scoring) has the same previous-starter rating; to fix and rescore.
- **PRE-REGISTERED 2026-10-16 (before running): (Q) which rank feeds the Matchups win chance.** Found while fixing the
  harness: the win chance is logistic(home + rank_gap x (away rank - home rank) + elo_per_100 x Elo diff / 100); its
  coefficients were fit (tools/elo_eval.py) on ranks that rated each team's PREVIOUS starter, and since (M) the live
  page feeds it Power's rest-of-season rank C, which (M) gated on the rest of the season, never on single games. For
  one game, this week's lineup is the information that matters (the live page knows the projected starter). Variants,
  ranks from the site's own code (tools/power_c.py, every season-week 2021-26): A = net with the previous starter (the
  fitting basis), N = net with this game's actual starter (stand-in for the announced starter), C = live. For each,
  the three coefficients refit walk-forward (seasons before the test season, 2021 on; Elo with the config settings),
  scored by Brier on games 2022-26 with a Vegas line. GATE: Matchups switches to N (this week's lineup rank, with
  coefficients refit on N over every season) unless C beats N with the 95% CI over season-weeks excluding 0. Reported:
  the same on games where either team's usual starter is out (where the ranks differ), and A for reference.
- **RESULT {#win-rank-this-week} (Q) which rank feeds the Matchups win chance: N -> SHIPPED.** tools/win_rank_eval.py,
  1,084 games 2022-26 with a line: Brier A 0.2220, N 0.2203, C 0.2214 (Vegas 0.2114). C - N +0.0011 [-0.0007,
  +0.0030] (C does not beat N: switch); N - A -0.0017 [-0.0033, -0.0001]. Games with a usual starter out (194): A
  0.2176, N 0.2122, C 0.2159 (C - N +0.0037 [-0.0017, +0.0097]). N best or tied in every season (2022: C 0.2243 vs N
  0.2244). Live: Matchups uses Power's rank_now (this week's projected starter) with new keys week_home 0.1838,
  week_rank_gap 0.0313, week_elo_per_100 0.3242 (fit on N, every season 2021-26). The playoff odds keep the
  rest-of-season rank and the old weights (fit on A); refit on C = home 0.1841, rank_gap 0.0252, elo 0.3616 - a
  candidate for the odds backtest, not applied.
- **Finding 2026-10-16 (corrected harness, game misses from the team's side, + = overrated, 2021-25): QB changes are
  overrated, most of all QBs new to the team.** Same QB as last game (n 2,247) -0.38 [-0.93, +0.15]; changes: new
  arrival, last started for another team (n 65) +6.07 [+2.39, +9.73] (Vegas +2.69); experienced backup (n 90) +2.15
  [-0.56, +4.78] (Vegas +0.55); inexperienced (n 83) +1.95 [-0.99, +4.85] (Vegas +2.45); usual starter returns (n 73)
  +1.48 [-1.76, +4.83] (Vegas +1.75). The QB effect is one number per QB from all his plays, so a veteran's level
  carries over to a new team, new system and receivers at full value.
- **PRE-REGISTERED 2026-10-16 (before building): (R) a new-to-the-team QB term.** A second league-level indicator in
  the pass unit next to the inexperienced one, fit the same way (one coefficient, penalty qb_inexp_alpha): 1 on a pass
  play when the QB had < 150 dropbacks for THIS team before that week (play-by-play window) and >= 150 career (so it
  never overlaps the inexperienced term). At prediction time it applies to the projected starter by the same rule.
  Config team_model.qb_newteam_dropbacks (absent = off). Tests: (1) tools/game_eval.py 2021-25 (corrected harness)
  baseline vs --set team_model.qb_newteam_dropbacks=150; (2) tools/experiments.py baseline,qb_newteam 2021-2025.
  GATE: (1) margin MAE on games where either starter carries the new flag: lower with the 95% CI over games excluding
  0; all games not worse (CI upper < +0.02); (2) fantasy MAE, all relevant players, not worse (CI upper < +0.005).
- **RESULT {#qb-newteam} (R) a new-to-the-team QB term: FAIL (right direction, within noise).** tools/qb_newteam_eval.py
  on game_eval 2021-25: games with a flagged starter (n 281 of 1,279) margin MAE 10.704 -> 10.627 (-0.077 [-0.232,
  +0.072]); all games 10.428 -> 10.405 (-0.023 [-0.061, +0.013]). Fantasy (tools/experiments.py baseline,qb_newteam
  2021-25): ALL +0.001 [0.000, +0.001] (QB +0.003 [0.000, +0.005]; guard met, effect nil). The flag (< 150 dropbacks for the team) also catches offseason signings in their first
  games, diluting the mid-season-arrival effect behind the finding (65 games); narrowing it to those now would be
  chosen after seeing the data. Off (config absent); the code stays as an experiment.
- **Finding 2026-10-16 (outside review of the testing approach, read-only checks on the caches; latest baseline
  parquet per season, scored rows, weeks 3+). Work plan: threads 1-8 below, in order.**
  - Kickoff rule: kickoff EPA to the receiving team ~0 in 2018-23 -> +0.255 (2024), +0.253 (2025), +0.231 (2026).
    Team sd of kickoff EPA 0.05-0.09 before -> 0.103 (2025), 0.144 (2026 partial). Points-formula ST weight
    (fit_points_st_net) by test season 2021-26: 0.98 / 1.34 / 2.24 / 2.38 / 2.31 / 2.24. With points_seasons = 6 the
    2026 fit is 4/6 pre-rule. Nothing in the repo mentioned the rule.
  - Scored set misses breakouts: 18.8% of weekly top finishes (top 12 QB / 24 RB / 36 WR / 12 TE, 2021-26) are outside
    the scored rows: 200 have < 2 games, 1,110 played but sit outside the top-N (TE 252 / 996, WR 578 / 2,988). Mean
    proj 4.48; where ECR exists (n 1,046) ours 4.63 vs ECR 4.97. The top-N is ranked by mean(proj, raw_fpg, vegas),
    i.e. partly by our own projection.
  - Residual correlation: QB-WR same team +0.32 / opposing +0.09; QB-TE +0.28 / +0.07; QB-RB +0.05; WR-WR, RB-RB,
    WR-RB ~0. league.js sums player variances as independent for the matchup win chance.
  - Season drift, mean actual - proj, 2021-26: all -0.18 / +0.04 / +0.40 / +0.67 / -0.02 / +0.33; QB -0.63 / +0.66 /
    +1.07 / +1.46 / +0.37 / +1.06 (under-projected 5 of 6 seasons).
  - Wind, training vs live: training uses pbp game wind (max over game, data.py); live uses an Open-Meteo forecast
    (mean of 4 hourly values at 10 m). Different source AND definition. Penalty active on 19% of scored rows (mean
    11%). Forecast wind isn't archived numerically.
  - Lines, training vs live: backtests use nflverse lines as they stand after the game (effectively closing); live
    Tue-Sat builds use that day's line. No archive of the lines used live.
  - Threads: (1) archive what the live site used; (2) kickoff-rule regime; (3) information the stats can't see (change
    events); (4) score where fantasy value is; (5) QB calibration; (6) correlation-aware League win chance (owner
    asked before shipping a change to what the site shows); (7) rest-of-season accuracy; (8) testing hygiene. Rules:
    descriptive check first, pre-register only on a signal persisting across seasons; prefer decide-2025 /
    confirm-2026 over another pass on 2021-25; check the harness matches production; scan pockets are hypotheses.
- **Thread 1 (2026-10-16): live-input archive SHIPPED; the live-vs-backtest gap can't be measured on past weeks.**
  Every current-week build now writes data/live_inputs/<season>_<week>_<time>.json (nfledge/live_inputs.py; CI
  commits it to the archive branch with the playoff-odds history): each game's spread / total as the schedule had
  them, the wind fed to the model, the ECR scrape date used, and per player proj / proj_no_inj / avail / ecr /
  wind_penalty / implied_pts / spread_team (~23 KB a build). ECR scrapes themselves were already archived
  (tools/ecr_snapshot.py). No record of earlier live builds exists: archived week pages are walk-forward rebuilds made
  after the week (final lines, recorded wind, final report, Friday ECR), the Pages artifact isn't kept, and the Wayback
  Machine has no captures of the site. tools/live_vs_backtest.py (ready, smoke-tested) compares, per player, the last
  live build before his kickoff with the walk-forward page: MAE by position, distribution of projection differences,
  largest gaps with line / chance-to-play / ECR differences. PENDING CHECK: run it from Tuesday 2026-10-20 (week 6, the
  first archived live week) and after each week; record the gap once 3+ weeks exist.
- **Thread 2 (2026-10-16): kickoff-rule regime - no signal, no test.** Descriptive, REG plays 2017-26 (2026 partial):
  (a) split-half persistence (odd vs even weeks, 32 teams, SE ~0.18 per season) of team mean kickoff EPA: returns
  2017-23 mean r +0.07 vs 2024-26 +0.01; coverage +0.25 vs +0.12. No rise after the rule. Team per-game kickoff EPA sd
  0.25-0.45 before, 0.35 / 0.55 / 0.73 (2024 / 25 / 26 partial; fewer games inflate it). (b) Points-formula ST weight
  fit on one season at a time: 2018-23 0.18 / 0.76 / 0.93 / 1.68 / 1.13 / 2.24, 2024-25 0.88 / 1.19 (+-0.5); the
  rise in the 6-season-window weights (0.98 -> 2.24) happened before the rule. The ST term is a net edge (own minus
  opponent's expected ST EPA, team_model GameModel._features), so a league-wide kickoff shift sits in the ST
  intercept and cancels. Side finding: field goals have NEVER been in the ST unit (nflverse sets
  special_teams_play = 0 on all 7,622 FG plays 2019-26, and data.py's is_st requires it), though MODEL.md said
  they were (fixed). FG EPA split-half r for the kicking team +0.12 mean, positive 8 of 10 seasons; expected margin
  effect ~0.1 pt, below what a decide-2025 / confirm-2026 test can detect: not tested (thread 8 power note).
- **Thread 3 (2026-10-16): change events vs the excess miss over Vegas - no persistent signal, parked.**
  tools/event_misses.py on the corrected game_eval predictions (1,279 games 2021-25 with a line; excess = |model miss|
  - |Vegas miss|, mean +0.66), each event vs games without it, by lag in team games: QB change this game (n 288)
  +0.47 [-0.13, +1.12], positive 4/5 seasons (the overrating (R) tried to fix); 1-2 games after +0.18 / +0.09.
  Head-coach change (schedule coach differs from the previous game): 8 / 8 / 7 games, unreadable. New snap leader at
  RB / WR / TE (seen after the game, so lag 1-3): +0.31 [-0.52, +1.07], -0.08, -0.99. Arrival (>= 50% snaps for a
  team after playing elsewhere that season): -0.21 / -0.29 / +0.00. v1 used the top-2 WR set (fired in 82% of games),
  replaced. Offensive coordinator / play-caller changes: no data source in nflverse; not checked. The old surprise-QB
  "42% of excess" came from the starter-rating artifact. Nothing to pre-register.
- **PRE-REGISTERED 2026-10-16 (owner: "non contact jerseys, something we can parse from news blurbs and account for
  and subsequently test relating to active%"): non-contact jersey, FORWARD test.** Parse: tools/espn_news.py writes
  data/espn_news/jersey.json (pattern: non- / no-contact jersey, red / yellow jersey; not "non-contact injury"), one
  sighting per (player, his team's next game). ESPN serves the current season only, so there is no 2021-25 history:
  2026 so far has 13 sightings, 5 in game weeks (Moore wks 3, 4, 6; Bateman 5, 6), and of the 12 finished
  player-weeks 11 played (descriptive, outcome-blind to the model). Rows: sightings published within the 6 days
  before the game, player on that week's final injury report. Trigger: 40 such rows with outcomes (2026 on). Check:
  actual active rate minus our final P(play) on those rows, 95% CI over rows; if it excludes 0, pre-register a
  jersey input to the availability model (stage-3 feature, walk-forward on the accumulated rows, Brier gate); if not,
  record "no information beyond practice status". Until then nothing in the model changes.
- **Thread 4 (2026-10-16): scoring where fantasy value is (tools/fantasy_value_eval.py, latest baseline backtests
  2021-26).** (1) Extended set (played with >= 30% offensive snaps or projection >= 3, incl. < 2 earlier games; 22,799
  player-weeks, 12,902 also in the scored rows; selecting on snaps uses the outcome, fine for a same-rows comparison):
  model vs ECR MAE, rows with ECR (19,075): ALL +0.002 [-0.021, +0.025]; QB +0.281 [+0.148, +0.422] (worse; thread 5);
  RB -0.063 [-0.100, -0.025]; WR -0.021 [-0.044, +0.003]; TE -0.025 [-0.039, -0.009]. Rows outside the scored set
  (8,045 with ECR): 3.227 vs 3.180, bias (actual - proj) +0.28 vs ECR -0.03: we under-project fringe players a bit.
  (2) Breakouts (first top-12 QB / 24 RB / 36 WR / 12 TE week of a season, week 4 on; 1,268): ECR ranks him higher
  than we do 61-80% of the time that week and the next (ECR adopts faster), BUT the week after, on the 905 who played
  with an ECR rank, MAE ours 4.367 vs ECR 4.356 (+0.010 [-0.083, +0.101]); bias +0.40 vs +0.30; QB +1.74 vs +1.08
  (thread 5). Faster adoption isn't more accurate: no recency test warranted. (3) Decision metric, now printed by
  tools/experiments.py next to MAE: pairs of the reference's relevant players within 6 consensus ranks (same week,
  position), points gained per pair over a coin flip by starting the one projected higher, paired CI over season-weeks.
  Baseline 2021-25: ALL +0.887 (68,160 pairs), QB +0.978, RB +0.997, WR +0.773, TE +0.872. vs ECR on shared pairs
  (fantasy_value_eval): model +0.475 vs ECR +0.418 (model better 3 of 6 seasons). First use: the rejected
  qb_newteam variant was MAE +0.001 (worse) yet decisions +0.004 [+0.001, +0.008] (better): the two metrics can
  disagree. PROPOSAL to the owner: make the decision metric a gate criterion next to MAE (a change ships only if
  neither is significantly worse), first use the pending redistribution call. Not adopted until he says so.
- **Thread 5 (2026-10-16): QB calibration, descriptive; cause not pinned down, no test yet.** Scored QB rows 2021-26
  (1,992; latest baseline backtests): actual - proj mean +0.60, median +0.29 (so mostly real bias, partly skew). By
  component, fantasy points per game: passing yards +0.13 / +0.48 / +0.55 / +0.46 / +0.23 / +0.65 (2021-26, positive
  every season; raw +9.5 yds, median +7.7); passing TDs -0.18 / 0.00 / +0.43 / +0.81 / +0.30 / +0.40; INT, rushing
  yards, fumbles ~0; rushing TDs -0.39 / -0.06 / +0.20 / -0.11 / -0.08 / +0.09 (raw -0.013 per game: the logged
  over-prediction, tiny). Passing yards = volume -2.1 + efficiency +9.9: dropbacks are right (35.82 vs 35.84; the
  starter's share is under-forecast 0.92 vs 0.96 but team dropbacks over, cancelling) while yards per dropback is
  low every season, pooled 6.16 vs 6.44 (+0.15 / +0.27 / +0.39 / +0.37 / +0.29 / +0.02 for 2026 so far). Pocket QBs
  carry it (+15.7 yds; mobile -3.9). By projected-efficiency quintile (all QBs with 15+ dropbacks, which conditions
  on the outcome, so only the PATTERN is read): +0.70 / +0.24 / +0.20 / +0.27 / +0.08, i.e. largest for the QBs
  projected worst, smallest for the best: not shrinkage toward a backup-heavy mean (that would hit the best most),
  and not sample size (n_db < 300 +0.19 vs 300+ +0.32). Open hypotheses, to check before any test: (a) the weighted
  linear rate fit trains on every QB row incl. relief / garbage appearances, whose level differs from starts; (b) the
  defense / wind terms' mean effect on starters vs on the training mix; (c) a rate-feature definition mismatch
  (sacks / scrambles in the dropback denominator vs pass yards). Training on full games only would condition on the
  outcome (early exits have low yards per dropback), so it is NOT the fix. Next: compare in-sample (training rows)
  vs test bias by row type to locate (a)-(c).
  **Located (same day): the fixed wind penalty drives most of it.** QB scored rows by penalty applied: none (1,612)
  pass yds +7.5, ypd 6.51 actual vs 6.30 projected; 0-5% (72) +8.0; 5-10% (134) +16.0; 10-20% (104) +18.5; 20%+
  (70) +31.7, ypd 5.92 vs 4.82 (real passing drops ~9% at ~20 mph, the projection 23%). Penalized rows miss more than
  unpenalized in all 6 seasons. Undoing the penalty on penalized rows (all relevant positions, 2,495): MAE worse at
  every position (ALL +0.155 [+0.092, +0.218]; WR +0.253, TE +0.169, RB +0.066, all CI > 0; QB +0.081 [-0.148,
  +0.308]), so the penalty earns its place for MAE; bias: receivers right (WR -0.07 with it, -1.09 without), QBs
  over-penalized (+0.66 with, -1.00 without; zero near 60% strength). The penalty was grid-tuned on all positions'
  MAE (sec. 3), which receivers dominate. NOT tested: a QB-only strength would be picked after looking at 2021-26,
  and the MAE effect on ~380 windy QB rows is far below what an interval that wide can show (thread 8 power). Also
  standing: backtests feed the game's recorded wind (pbp, data.py game_wind) while live builds feed an Open-Meteo
  forecast mean (data.forecast_wind) - the penalty was tuned on the former; the live-input archive (thread 1) is the
  way to measure how the two compare. The +7.5 yds with no penalty stays open ((a)-(c) above).
- **PRE-REGISTERED 2026-10-16 (before running): thread 6, correlation-aware Fantasy matchup win chance.** Today
  (league.js): P(win) = Phi((E_a - E_b) / sqrt(sum of each starter's variance)), variance = pa x sd^2 + pa(1-pa) x
  proj^2, sd = (p90 - p10) / 2.563, players independent. New: add 2 x rho x s_i x s_j for every pair of starters in
  the same game (same lineup: + ; opposing lineups: the cross-covariance enters the difference with a minus sign), rho
  by position pair and relation (same team / opponents), fit as the correlation of standardized residuals
  ((actual - proj) / s) on seasons before the test season (2021 on). Rows: tools/h2h_eval.py, latest baseline
  backtests, simulated 1-QB / 2-RB / 3-WR / 1-TE lineups from that week's players with proj >= 3, three kinds:
  unstacked (no two starters from one game), QB+1 and QB+2 (QB with one / two of his pass catchers), opponents drawn
  unstacked; 20,000 matchups per kind per test season. Metric: calibration (expected calibration error over 10
  probability bins) and Brier on actual results. Decide on 2025, confirm on 2026 (weeks so far). GATE: ship (to the
  owner, who approves the display change) if, in BOTH seasons, ECE is lower for QB+1 and QB+2 and unstacked Brier /
  ECE are not worse (within 0.002); else keep independent sums and record.
- **Thread 7 (2026-10-16): rest-of-season accuracy, descriptive (tools/ros_eval.py).** No archive of the live
  rest-of-season numbers exists (lookahead pages are rebuilt every run), so this scores a walk-forward stand-in: at
  week W, projection if active x the team's remaining games, vs points actually scored from W on (missed games = 0);
  baseline = FP/G so far x the same games. 2021-25, W = 4 / 8 / 12, players projected 5+ with 3+ games (2,563).
  Spearman ours vs baseline: all positions by season 0.615 / 0.635 / 0.656 / 0.659 / 0.679 vs 0.619 / 0.608 / 0.647 /
  0.628 / 0.613 (better 4 of 5, tied 2021); by position and W ours is better in 11 of 12 cells (QB W8 0.515 vs 0.564);
  TE weakest (0.25 at W 4-8). Bias of assuming every remaining game is played: actual / projected - 1 = -15.8% (base
  -18.2%), i.e. ~16% of rest-of-season points never happen (injuries, benchings, rest). The live page projects healthy
  players at 100% for every lookahead week, so its rest-of-season totals likely carry the same over-projection.
  Candidate (not run): a games-missed discount by position for healthy players in the lookahead, fit on earlier
  seasons; gate on rest-of-season bias and Spearman, decide 2025 / confirm 2026, then the unified lookahead
  availability "next angle" (sec. 9) as its own pre-registration.
- **Thread 8 (2026-10-16), part: player-cluster bootstrap.** tools/experiments.py now prints, next to the
  season-week interval (ci_lo / ci_hi), the same interval resampling whole players (pl_lo / pl_hi). First use
  (baseline vs qb_newteam 2021-25): nearly identical (ALL [0.000, 0.001] both; QB [0.000, 0.005] vs [0.001, 0.005]).
- **Thread 8 (2026-10-16): power and multiple-comparison audit; full table in docs/verdict_audit.md (~120 verdicts).**
  MDE = 0.71 x the 95% CI width (80% power, two-sided 5%), compared with the effect the notebook expected, else the
  notebook's own "negligible" margin (fantasy MAE 0.003, margin MAE 0.02, availability Brier 0.0005, playoff Brier
  0.001, Spearman 0.005). RELABELLED "unresolved (too small to measure)", not rejected: (P) {#skill-absence-margin}
  MDE 0.31 vs a ~0.03-0.12 plausible gain; (R) {#qb-newteam} 0.22 vs ~0.2; (O) {#qb-blend-winchance} 0.0036 vs
  <= 0.0004; also route_input, age_input, gl_share, rbbc+gl_share, qb_rush_split, K, L1 (near miss), L2,
  practice_rest, learned Edge grade, Edge v2, the leak-free Sleeper blend, division unders since 2020, and three
  "not worse" bars whose CI was wider than the bar (prior carryover KEPT, I2's MAE step, scratch_carry v2).
  Failures that hold up (harm significant or gain excluded): redist_conserve, return v2, the IR-minimum chain rule,
  blowout 5-95, share_quality, grade_prior, Edge v1.1, debut v1, (N) {#odds-weekly-c}. 2021-25: 50 significance-style
  verdicts, 21 passed (expected by chance ~1.25); four passes sit at the CI edge (gl_struct, job_security, (M), hybrid),
  about one could be chance; repeated attempts at the same questions add hidden comparisons. PENDING CHECK, 2026
  season end, re-confirm the small ships: newcomer (-0.002), def_terms drop (-0.002), snap-map fix (-0.003, 90% CI),
  half-life 3 (-0.004, no CI), gl_struct, job_security, Power C (M), Matchups rank N (Q), I2's fantasy leg, healthy3,
  Edge v1.2, points_seasons 6 (no CI), the ESPN Doubtful rate, hybrid (already registered). Gate template: sec. 1.
  MODEL.md "What we tried": P, R, O now read "Unresolved (too small to measure)".
- **RESULT {#h2h-corr} thread 6, correlation-aware Fantasy matchup win chance: PASS -> SHIPPED (owner: "let the data
  decide, we lean towards being correct").** tools/h2h_eval.py (v1 sampled lineups with pandas filters and took over an
  hour; stopped and rewritten with per-week arrays, same definitions; no result was read from v1). rho fit on 2021-24
  for the 2025 decision (same team QB-WR +0.240, QB-TE +0.176, QB-RB +0.029, RB/WR/TE teammates -0.01 to -0.06;
  opponents QB-QB +0.138, QB-TE +0.087, QB-WR +0.050, others ~0). 20,000 matchups per kind. ECE current -> corr:
  2025 unstacked 0.0116 -> 0.0125 (within 0.002), QB+1 0.0200 -> 0.0183, QB+2 0.0203 -> 0.0160; 2026 (weeks 3-5)
  unstacked 0.0046 -> 0.0041, QB+1 0.0126 -> 0.0121, QB+2 0.0094 -> 0.0086; Brier equal to the third decimal
  everywhere (QB+2 2025 0.2086 -> 0.2084). Gate met in both seasons. Live (league.js): rho refit on 2021-25 (same QB-WR
  +0.244, QB-TE +0.195; opp QB-QB +0.143, QB-TE +0.090), spread = sqrt(var A + var B - 2 cov(A, B)) with same-game pairs
  only; kickers / defenses carry no correlation. Effects are small (stacks a little less confident), as expected.
- **PRE-REGISTERED 2026-10-17 (before building): (S) durability per snap instead of per game** (owner: "maybe
  durability itself should be measured by snaps rather than games?", after a check that low-snap backups look durable
  because they are rarely on the field). Today (tools/player_logs.py injury_history): A = share of his team's games
  he was not out injured (2013 on), shrunk toward the position group's pooled rate by 17 games, percentile within the
  group. New: B = games missed injured per 1,000 snaps played (offense snaps for QB / RB / WR / TE / OL, defense snaps
  for DL / LB / DB; kickers, punters, long snappers excluded), shrunk toward the group's pooled rate by K snaps.
  Rows: player-seasons T = 2014-2025 where he was on the roster for 8+ of his team's games in T, with history from
  2013 to T-1; both scores use only that history. Target: share of his team's games in T he missed injured (the same
  episode logic). Metric: Spearman rank correlation, within each position group, of the score (more durable = higher)
  with fewer games missed in T; a season's value = the groups' correlations weighted by rows. K per group from
  {250, 500, 1000, 2000}, chosen on T = 2014-2019 only. GATE (decide on T = 2020-2025, untouched by the K choice):
  ship if B - A > 0 with a 95% player-cluster bootstrap CI excluding 0 AND B better in at least 4 of the 6 seasons;
  otherwise keep A. MDE: no earlier test on these rows; ~1,500 rows a season and the two scores share their inputs,
  so the paired interval should be far narrower than either correlation's (to be reported). Reported alongside:
  every group, and QBs on their own (the case that started this).
- **RESULT {#durability-per-snap} (S) durability per snap instead of per game: FAIL (clearly worse).**
  tools/durability_eval.py, 1,226-1,652 rows a season. K chosen on 2014-19: 250 snaps everywhere but TE (2000).
  Decide 2020-25: within-group Spearman with fewer games missed next season, A (today) 0.128-0.167 a season vs B
  0.073-0.135; B - A -0.028, 95% player-cluster CI [-0.039, -0.016] (width 0.022), B better 1 of 6 seasons. Every group
  worse or level (WR +0.007); QBs worst: A +0.103, B -0.024 (per-snap history says nothing about a QB's next season).
  Why, likely: missed games already shrink a player's snaps, so the rate double-counts the injury that cost him the
  snaps, and per-snap exposure ties the score to role (starters log more snaps per missed game) rather than to how
  often he gets hurt. Kept A. The earlier check that started this (backup QBs rank high under A) is real but small:
  starting QBs average the 45th percentile; a snap-share pool cut (10-35%) barely moves it (45th -> 47th).
- **PRE-REGISTERED 2026-10-19 (owner, on (S): "shouldn't we be testing how many snaps we expect the player to survive
  before missing a game? rather than just flat missing games"): (S2) durability judged by snaps survived.** (S)'s
  target, share of next season's games missed, carries exposure like the per-game score does (a backup who barely
  plays rarely gets hurt, so both call him durable). New target, per player-season T (2014-25, 8+ team games on the
  roster in T, history 2013..T-1, same rows as (S) otherwise): his unit snaps (offense for QB / RB / WR / TE / OL,
  defense for DL / LB / DB) in T before his first game missed injured (on the report or an injury reserve list and not
  active), the event; no such game = censored at his snaps in T. Players out injured in their first week of T and
  rows with no snaps in T are left out. Scores: A (today: share of games available, shrunk 17 games) and B (games
  missed injured per 1,000 snaps, shrunk with (S)'s K: 250, TE 2000; not re-chosen). Metric: Harrell's concordance
  (C-index) of the score with snaps survived, within each position group, weighted by rows. GATE (2020-25): ship B as
  the card's durability if B - A > 0 with a 95% player-cluster bootstrap CI excluding 0 AND B better in at least 4
  of 6 seasons; else keep A. Reported: every group, QBs alone.
- **RESULT {#durability-snaps} (S2) durability judged by snaps survived: PASS, shipped.** tools/durability_snaps_eval.py,
  2020-25, 1,332-1,404 rows a season (622-667 events). C-index with snaps survived: A 0.550-0.570, B 0.573-0.595; B - A
  +0.026, 95% player-cluster CI [+0.021, +0.031], B better 6 of 6 seasons and in every group (QB 0.541 -> 0.582, LB
  0.547 -> 0.594, OL 0.577 -> 0.581). Reported alongside (not gating): regulars only (30+ unit snaps a game in their
  history) the two are level, B - A +0.004, B better 5 of 6: the per-game score's edge in (S) came from rewarding
  low exposure, which a per-snap target no longer pays. Live (tools/player_logs.py injury_history): per-snap durability
  for QB / RB / WR / TE / OL / DL / LB / DB (K 250; TE 2000), percentile among the group's players with 1,000+ snaps;
  under 1,000 snaps no percentile ("too little time on the field to rank"); kickers, punters, long snappers keep the
  per-game share. Supersedes {#durability-per-snap}'s verdict: that test's target carried exposure too.
- **PRE-REGISTERED 2026-10-17 (before building): (T) snap trend as an early sign of a role change** (owner, after
  "snap share as an input" was recalled as tried: "if we're projecting snap counts ... isn't that potentially a good
  indicator?"). snap_input (the recency-weighted snap share) added nothing once target / carry shares were known. New
  angle: snap_trend = his offense snap share averaged over his last 3 games played minus that recency-weighted share,
  an input to the target-share and carry-share regressions (experiments.snap_trend). Hypothesis: a fresh jump in snaps
  (new starter, depth change) precedes the share catching up. Walk-forward 2021-25, `tools/experiments.py
  baseline,snap_trend`. Primary rows: RB / WR / TE with |snap_trend| >= 0.15 (the role changers). GATE: on the primary
  rows, fantasy MAE lower with a 95% season-week CI excluding 0 and better in >= 4 of 5 seasons; guards: all rows MAE
  CI upper < +0.003, no position significantly worse. MDE to be reported from the run's own interval (no earlier test
  on this subset).
- **PRE-REGISTERED 2026-10-17 (before building): (U) a backup's snap share in who absorbs a sitting teammate's work**
  (owner: "a wr or backup rb that has solid snap share, what happens to their fantasy output when the player ahead of
  them gets injured compared to players with lower snap shares"). First look (cached baselines 2021-25, played rows the
  model handed some vacated share): beneficiaries under-projected at every snap level (RB +0.3 to +1.2 pts, WR 60%+
  +0.7), largest for RBs at 40-60% prior snaps (+1.22, n 149); no clean gradient, every bucket within noise. Handing
  out ALL the vacated share already failed (redist_conserve). New: the absorption regression gets one more column per
  (missing, receiving position): vacated share x his share of his position group's recent snap share
  (injuries.absorb_snap), so the learned split can follow snaps as well as depth rank and projected share. Walk-forward
  2021-25, `tools/experiments.py baseline,absorb_snap`. GATE (as redist_conserve's): on rows whose projection changes
  by > 0.05 pts, MAE lower with a 95% season-week CI excluding 0 and better in >= 4 of 5 seasons; overall MAE CI upper
  < +0.003; no position significantly worse. Bias on affected rows reported, by the snap buckets above.
- **RESULT {#snap-trend} (T) snap trend as an early sign of a role change: FAIL (no effect; a guard worse).**
  tools/experiments.py baseline,snap_trend 2021-2025 + tools/snap_eval.py. Primary (RB / WR / TE, |snap_trend| >=
  0.15, 4,934 rows): MAE 4.943 -> 4.943, +0.0002 [-0.0025, +0.0031] (width 0.0056), better 2/5 seasons. Snaps up (906
  rows): bias -0.17 -> -0.02, MAE unchanged. All rows +0.0015 [+0.0001, +0.0029], TE +0.0025 [+0.0003, +0.0049]
  (significantly worse); start / sit gain 0.000. A snap jump already shows in his recent targets and carries, which the
  share regressions weight by recency. Switch stays off.
- **RESULT {#absorb-snap} (U) a backup's snap share in who absorbs a sitting teammate's work: FAIL (no effect).**
  tools/experiments.py baseline,absorb_snap 2021-2025 + tools/snap_eval.py. The absorption fit (non-negative least
  squares) put almost no weight on the snap column: only 70 rows moved > 0.05 pts, MAE 4.680 -> 4.672, -0.008 [-0.040,
  +0.024], better 2/5; all rows -0.0000 [-0.0002, +0.0002], no position different. Given depth rank and projected
  share, the backup's prior snap share says nothing more about how much of the starter's work he gets. Open lead from
  the first look: beneficiaries are under-projected at every snap level (~0.5-1 pt) while full conservation overshoots
  (redist_conserve): the redistribution strength in between has not been tuned. Switch stays off.
- **PRE-REGISTERED 2026-10-17 (before running): (V) how much of a sitting starter's work reaches RBs** (owner, after
  (U): "why was that number picked by hand? yes"). injuries.redistribution_scale = 0.5 is hand-set (initial commit,
  2026-10-12: "keeps teammate projections near-unbiased"); never searched between 0.5 and full conservation (1.0,
  redist_conserve, overshoots). (U)'s first look: RB beneficiaries under-projected +0.3 to +1.2 pts at every snap
  level; the config note: "helps RB, slightly hurts WR". Named position (sec. 1 rule 6): RB receivers only; every other
  receiver keeps 0.5. Grid RB scale {0.5 (today), 0.65, 0.8, 1.0}: pick the value with the lowest MAE on RB rows whose
  projection moves > 0.05 pts in 2021-2024; DECIDE on 2025: those rows' MAE lower than 0.5 with a 95% season-week CI
  excluding 0; guards on 2025: all rows MAE CI upper < +0.003, no position significantly worse; CONFIRM on 2026 weeks so
  far: same direction on the affected RB rows, not significantly worse overall. Bias on affected RB rows reported.
- **RESULT {#rb-redist-scale} (V) how much of a sitting starter's work reaches RBs: FAIL, 0.5 kept (now tested).**
  tools/experiments.py baseline,rb_scale_65,rb_scale_80,rb_scale_100 2021-2026 + tools/rb_scale_eval.py. Choose window
  2021-24, affected RB rows: 0.65 +0.0001 [-0.020, +0.021] (131 rows, bias -0.72 -> -0.63); 0.8 +0.004 [-0.020, +0.029]
  (232, -0.73 -> -0.59); 1.0 +0.005 [-0.027, +0.040] (289, -0.92 -> -0.72). No value beats 0.5, so no decide / confirm
  step. More strength shrinks the bias without lowering MAE (sec. 1 rule 7: MAE decides). Start / sit gain 2021-26 ALL
  0.000 at 0.65 and 0.8. docs/handset_audit.md: redistribution_scale now TESTED.
- **PRE-REGISTERED 2026-10-17 (before running): (W) a per-position calibration curve on the final projection**
  (owner, on whether elite outliers distort the model: "sure try it"). Look first (cached baselines 2021-25, played
  rows by projected rank within position): top-5 RBs actual - projected -1.21 [-2.24, -0.20], top-5 WRs -1.55 [-2.39,
  -0.68], WR 6-12 -0.80; middle tiers +0.3 to +0.6: projections too spread out at the top. The rejected "final linear
  calibration" (sec. 5, +0.013) was one least-squares line; this is a monotone MEDIAN curve per position (sec. 1 rule 7:
  MAE decides). Curve: the fit rows' projections cut into 20 equal-count bins; each bin's median actual; made
  non-decreasing by weighted pool-adjacent-violators (weights = bin counts); applied by linear interpolation between
  the bins' median projections, flat beyond the ends. Rows: tools/experiments.py relevant rows of the cached baseline
  backtests (played, 2+ prior games, top-N by consensus). Walk-forward: season s in 2022-2025 uses a curve fit on
  2021..s-1 only. GATE: pooled MAE (calibrated - raw) with a 95% season-week CI excluding 0 below, better in >= 3 of 4
  seasons; guards: no position significantly worse; start / sit gain (same-position pairs: a monotone curve keeps the
  order, so unchanged by construction; reported). CONFIRM: curve fit on 2021-25 applied to 2026 weeks so far, same
  direction, not significantly worse. Bias by tier reported. Ranges (p10 / p90) untouched in this test.
- **RESULT {#median-calibration} (W) per-position median calibration curve: gate PASS, NOT SHIPPED (the gain is a
  shift to medians).** tools/calib_eval.py: walk-forward 2022-25 MAE 5.155 -> 5.096, -0.059 [-0.092, -0.026], better
  4/4 seasons (RB -0.092, WR -0.073 significant; QB +0.022, TE -0.038 no difference); 2026 confirm -0.020 [-0.067,
  +0.071]. Decomposition (tools/calib_decomp.py): a constant per-position median shift alone (QB +0.4, RB -1.2, WR
  -1.1, TE -1.0 pts) gives -0.063 [-0.086, -0.039]; the curve's SHAPE with each position's average kept gives -0.0006
  [-0.023, +0.022]. So the tier pattern that motivated it (top-5 RBs / WRs over-projected, middle under) is not
  exploitable: ranking players by our own projection selects the weeks we guessed high. The whole gain is moving every
  projection from its expected value to its median (calibrated rows then run 1-2 pts under at every tier), which would
  bias every sum the site makes (sec. 1 rule 7, scope). Not shipped; owner may overrule.
- **PRE-REGISTERED 2026-10-17 (before running): (X) last season's weight in team ratings** (docs/handset_audit.md #1;
  owner: "continue the queue"). team_model.prior_weight 0.3 fading to 0 by prior_decay_week 8 is from the initial
  commit; the "insensitive" row (sec. 5) has no numbers; the parked game test (sec. 9, 2026-10-12, 3 seasons, fixed win
  formula) found 0.6 fading by week 13 better in weeks 2-8 (margin MAE -0.13 [-0.24, -0.01] overall) and slightly worse
  in 9+. Grid: weight {0.3, 0.6, 1.0} x fade week {8, 10, 13}, half-life 3 (half-life is #5, separate).
  tools/carryover_eval.py walk-forward (every game re-rated with ranks as of the week before; win formula refit on
  earlier seasons). Primary metric: margin MAE (the team model's own target), games weeks 2+ with a line. CHOOSE the
  lowest margin MAE on 2022-23; DECIDE on 2024-25: margin MAE diff vs today with a 95% season-week CI excluding 0 below;
  guards: shipped win-chance Brier not significantly worse, and fantasy MAE (tools/experiments.py 2021-25) CI upper <
  +0.003 with no position significantly worse; CONFIRM on 2026 weeks so far, same direction. If today's setting is
  the 2022-23 choice, keep it (now tested).
- **RESULT {#prior-season-weight} (X) last season's weight in team ratings: FAIL, 0.3 fading by week 8 kept (now
  tested).** tools/carryover_eval.py --gate. Choose 2022-23 (510 games): every alternative beat today, 1.0 fading by
  week 10 most (margin MAE -0.190 [-0.290, -0.100]; 0.6 / wk 13 -0.188). Decide 2024-25 (511 games): that choice +0.017
  [-0.140, +0.173] (2024 -0.010, 2025 +0.043) and the win chance worse (Brier +0.0037 [+0.0007, +0.0066]); 2026 so far
  +0.046 (63 games). The 2022-23 advantage did not carry to later seasons (the parked 3-season look leaned on 2022-23
  too). docs/handset_audit.md #1 now TESTED.
- **PRE-REGISTERED 2026-10-17 (before running): (Y) injury attrition for rest-of-season values** (owner: "you can
  continue", step 2 of the Fantasy depth work, sec. 9). Rest-of-season values assume every healthy player stays healthy
  through week 17. Measure instead: for a REGULAR who is HEALTHY in week w (played, offense snap share >= 50%, not inside
  an injury episode), P(he misses week w+j injured) for j = 1..12 (a missed week with a roster tag inside an injury
  episode; byes skipped; cut / practice squad / free agent / retired censored), by position, from the career logs
  (tools/attrition_eval.py; snap counts 2013 on). Curve = per-position rate at each j, fit on seasons before s. GATE
  (a display probability: calibration, sec. 1 rule 5): walk-forward 2021-25, the curve's Brier on P(out) beats the
  current assumption (P = 0) in every season and its calibration error (10 bins) stays under 0.01; reported against a
  flat per-position rate (one number for every j) to show whether the horizon matters. If it passes, future weeks'
  chance to play for healthy players = 1 - curve(j), and lineup values become the expectation over who is available.
- **RESULT {#injury-attrition} (Y) injury attrition curve: FAIL (calibration).** tools/attrition_eval.py, 222,100
  healthy-regular week x horizon rows 2013-26. P(out injured) rises with horizon (all seasons: QB .031 at 1 week ->
  .112 at 12, RB .025 -> .133, WR .029 -> .112, TE .031 -> .120). Walk-forward 2021-25: Brier beats P = 0 every season
  (2021 .1104 -> .0991 ... 2025 .1094 -> .0970; the horizon adds ~.001 over a flat rate) but calibration error .027-.044
  (bar .01): fit on every season since 2013, it runs low, because injury absences have risen over the decade (healthy
  regulars out injured the next week, weeks 2-6: .018 in 2013-14, .034 in 2021-25; 2026 so far .031, not unusual,
  checked for the owner, who had read that injuries are worse this year).
- **PRE-REGISTERED 2026-10-17, second attempt after seeing (Y): (Y2) the same curve fit on the last 3 seasons only.**
  Walk-forward 2021-25 (season s fits on s-3..s-1): Brier beats P = 0 every season AND calibration error < 0.01; and,
  because this was designed after seeing (Y), the same on 2026 so far (fit 2023-25), which neither attempt used.
- **RESULT {#injury-attrition-recent} (Y2) the attrition curve fit on the last 3 seasons: FAIL (calibration in 3 of 6
  seasons).** tools/attrition_eval.py --recent=3. Brier beats P = 0 every season (2021 .1104 -> .0977 ... 2025 .1094 ->
  .0962; 2026 so far .0862 -> .0774) and the horizon helps over a flat rate (~.0013); calibration error 2023-25
  .0016-.0036 (pass) but 2021 .029, 2022 .016, 2026 .020 (1,705 rows, short horizons only). Year-to-year swings in the
  injury rate leave any fixed curve off in some seasons. Not used: Fantasy rest-of-season values keep "healthy stays
  healthy" and the hold-one / 3-deep roster rules (sec. 9). Possible next angle: a curve that updates in-season from
  the current year's absence rate (shrunk toward the recent seasons), gated the same way at season end.
- **PRE-REGISTERED 2026-10-17 (before running): (Z) the TD blend k** (docs/handset_audit.md #2). player_model.td_blend_k
  = 150 is from the initial commit; "k 50 / 400: no effect" has no numbers. TD input = expected TDs + n / (n + k) x
  (actual - expected), n = opportunities. Grid k {25, 50, 100, 150 (today), 300, 600, expected TDs only}. tools/
  experiments.py 2021-2026 (variants td_k_*). CHOOSE the lowest fantasy MAE (relevant rows) on 2021-23; DECIDE on
  2024-25: MAE lower than 150 with a 95% season-week CI excluding 0 and better in both seasons; guards: no position
  significantly worse, start / sit gain not significantly worse (sec. 1 rule 7); CONFIRM on 2026 so far, same
  direction. If 150 is the 2021-23 choice, keep it (now tested).
- **RESULT {#td-blend-k} (Z) the TD blend k: FAIL, 150 kept (now tested; truly insensitive).** tools/experiments.py
  2021-2026 + tools/grid_eval.py. Choose 2021-23, MAE vs 150: k 25 -0.0004 [-0.0012, +0.0005], 50 -0.0003, 100 -0.0001,
  300 +0.0002, 600 +0.0005, expected TDs only +0.0012 [-0.0009, +0.0032]. Decide 2024-25 (k 25): +0.0010 [-0.0005,
  +0.0025] (2024 -0.0002, 2025 +0.0021), RB +0.0024 [+0.0006, +0.0044] worse; start / sit +0.007 (no difference);
  2026 +0.0016. The whole range sits within +-0.0012: TD shrinkage strength barely moves MAE. docs/handset_audit.md #2.
- **PRE-REGISTERED 2026-10-17 (before running): (AA) the Tuesday and week availability models' settings**
  (docs/handset_audit.md #3: never searched). nfledge/tuesday.py TUE_GB (300 iterations, 15 leaves, min leaf 40) and
  WEEK_GB (400, 31, 40), both learning rate .05, l2 1. Grid per model: leaves {7, 15, 31, 63} x iterations {200, 400}
  x min leaf {20, 40, 80}. tools/avail_grid_eval.py, the live pipeline (week model: fit + per-stage calibration, T.week_
  model; Tuesday model: T.fit) walk-forward. Metric: Brier (week model: stages 1-3 pooled; Tuesday: its own rows).
  CHOOSE the lowest Brier on 2021-23; DECIDE on 2024-25: lower than today with a 95% CI (player-game clusters)
  excluding 0 and lower in both seasons; guard: calibration error (10 bins) not above today's + 0.005; CONFIRM 2026 so
  far, same direction. Each model decided separately (two pre-named tests).
- **RESULT {#avail-gb-week} (AA, week model) availability settings: FAIL on the 2026 confirm, today's kept (now
  tested; re-check at season end).** tools/avail_grid_eval.py week, 134,106 rows. Choose 2021-23: 31 leaves / 200
  iterations / min leaf 80, Brier .10554 vs today's (31 / 400 / 40) .10736. Decide 2024-25: -.00133 [-.00187, -.00078],
  2024 -.00195, 2025 -.00075 (pass). Confirm 2026 so far: +.00017 (fail, small sample). The calibration figures this run
  printed (.1335 -> .1359) were misaligned (predictions paired with other rows' outcomes; fixed in the tool); Brier was
  computed per season and is unaffected. PENDING CHECK at season end: rerun the decide-confirm on full 2026; if the
  2026 sign flips, ship 31 / 200 / 80.
- **RESULT {#avail-gb-tuesday} (AA, Tuesday model) availability settings: FAIL, today's kept (now tested).**
  tools/avail_grid_eval.py tuesday, 37,132 rows. Choose 2021-23: 7 leaves / 200 / min leaf 80, Brier .13461 vs today's
  (15 / 300 / 40) .13543. Decide 2024-25: +.00049 [+.00007, +.00094] (worse; 2024 -.00031, 2025 +.00126); 2026 +.00257.
  (Calibration figures printed by this run predate the alignment fix; the verdict rests on Brier.)
- **PRE-REGISTERED 2026-10-17 (before running): (AC) the redistribution trigger** (docs/handset_audit.md #4).
  injuries.redistribute_min_share = {tgt 0.08, carry 0.15}: the smallest projected share of a sitting player whose
  volume is handed out; "lower / higher within noise" has no numbers. Grid tgt {.04, .06, .08, .12} x carry {.08, .15,
  .25}. tools/experiments.py 2021-2026 (variants minshare_*), tools/grid_eval.py: CHOOSE the lowest MAE on 2021-23;
  DECIDE on 2024-25 (CI excluding 0 below, better in both, no position significantly worse, start / sit not
  significantly worse); CONFIRM 2026 so far, same direction. Today's the choice -> keep (now tested).
- **RESULT {#redist-min-share} (AC) the redistribution trigger: FAIL, tgt .08 / carry .15 kept (now tested; flat).**
  tools/experiments.py 2021-2026 + tools/grid_eval.py. Choose 2021-23, MAE vs today: every cell within +-0.0007, none
  with a CI excluding 0; best tgt .08 / carry .08 -0.0000 [-0.0004, +0.0003] (carry .25 the same). Decide 2024-25:
  +0.0005 [-0.0001, +0.0010] (2024 +0.0003, 2025 +0.0007; RB +0.0013 [-0.0000, +0.0028]); start / sit -0.004 [-0.012,
  +0.004]. 2026 so far -0.0002 [-0.0025, +0.0025]. Lower thresholds (hand out smaller shares) were slightly worse on
  2021-23, higher ones no better: today's sits at the flat bottom. docs/handset_audit.md #4.
- **DESCRIPTIVE 2026-10-17, before pre-registering (AB): does flag-proneness persist?** tools/penalty_archive.py sorts
  every flagged regular-season play 2012-26 (cache/penalty_plays): ~1,450 a season run then wiped out (called_back:
  holding, DPI, offside; flag on offense 47%), ~950 pre-snap (false start, delay, neutral zone), the rest stood (their
  yards already inside the play's EPA). The would-be result of 99.5% of called-back scrimmage plays reads from the text.
  EPA a team gives away on wiped-out plays, per game (scratch/pen_persist.py, 2012-25): odd vs even games of a season r
  .10 (offense) / .09 (defense); next season r .11 / .22. A season's figure is ~82% noise: the true team-to-team spread
  is ~0.2 EPA per game, against ~6 points for offenses. Expectation: the fourth unit (AB-a) fits near zero.
- **PRE-REGISTERED 2026-10-17 (before building): (AB-a) penalty-nullified plays as a fourth team unit.** team_model.
  pen_unit = true: plays wiped out by a flag (play_type no_play with a penalty; called back and pre-snap) form a unit
  "pen" with offense and defense ratings (EPA to the offense on those plays), its ridge penalty chosen by the same
  time-split CV as the other units, so a streak shrinks. pen_net = league nullified plays per team-game x (our
  expected pen EPA - theirs) enters the points formula as a fitted term beside st_net. tools/game_eval.py 2021-25
  --only=fitted, paired by game, against today. GATE: margin MAE lower with the 95% CI over season-weeks excluding 0;
  then fantasy MAE not worse (tools/experiments.py, CI upper < +0.003). Reported: the fitted pen weight and penalty per
  season.
- **PRE-REGISTERED 2026-10-17 (before building): (AB-b) called-back plays' would-be results as unit evidence.**
  team_model.called_back = true: called-back scrimmage plays (from the archive: a pass, run or sack before the flag)
  join the pass / rush units at their would-be EPA, estimated from the parsed outcome (yards, incomplete, interception,
  sack, touchdown) by a regression of EPA on down, distance, field position and outcome, fit on unflagged plays of
  seasons before the one projected. One test, the full set (no sub-selection of flag types afterwards). Same harness
  and GATE as AB-a, each decided separately against today; if both pass, both together are checked the same way.
- **PRE-REGISTERED 2026-10-17 (owner: "what if we pretended all pass interference calls went as completed passes to
  the target instead?"): (AB-c) defensive pass interference as a pass play.** DPI is enforced as a catch at the spot
  plus a first down, and its EPA says so, but the play is no_play and never reaches the pass unit. Offensive PI stays
  out (crediting the foul as a catch would reward it; AB-b covers its called-back result). Descriptive, before this
  pre-registration (scratch/dpi_persist.py, 2012-25, 261 a season, +1.73 EPA each): DPI EPA DRAWN by an offense per
  game, odd vs even games r .25, next season .21 (2.5x general flag cost); COMMITTED by a defense .11 / .08 (noise).
  team_model.dpi_pass = true: DPI plays join the pass unit at their own EPA. Same harness and GATE as AB-a, decided
  separately against today; any that pass are combined and checked the same way.
- **AMENDMENT 2026-10-17, before any (AB) run (found while building).** Wiped-out plays are not all outside the
  ratings: called-back RUNS (rush = 1 on a no_play row: 365 in 2024, mostly offensive holding, -0.65 EPA each) sit in
  the rush unit today at the flag's EPA, while called-back passes (qb_dropback 0) never reach the pass unit. So: (AB-a)
  the pen unit takes every wiped-out play and those rows leave the rush unit (a play counts in one unit); reported with
  it, not gated: the rush unit without them alone (team_model.rush_no_play = false), to show which half moves.
  (AB-c) DPI rows carry no passer in nflverse: they are credited to the team's main passer that game (most dropbacks).
- **RESULT {#pen-unit} (AB-a) penalty-wiped plays as a fourth unit: FAIL (as the persistence check predicted).**
  tools/game_eval.py 2021-25 --only=fitted, 1,279 games paired (scratch/ab_compare.py). Today 10.428 (winners 61.9%).
  Pen unit: +0.005 [-0.038, +0.046] (2021 +0.096, 2022 -0.018, 2023 -0.008, 2024 -0.107, 2025 +0.062); its fitted points
  weight swings 1.01 / 0.21 / -0.03 / 1.92 / 1.73 by season. Reported, not gated: the rush unit without its wiped-out
  runs alone -0.002 [-0.009, +0.005] (no difference: the inconsistency costs nothing measurable). Switches kept off
  (team_model.pen_unit, rush_no_play).
- **RESULT {#dpi-pass} (AB-c) defensive pass interference as a pass play: FAIL.** +0.017 [-0.006, +0.039] (worse in
  2021 and 2025, flat otherwise); with the pen unit -0.008 [-0.058, +0.039]. Drawing DPI persists more than flags in
  general, but ~0.5 a game at +1.7 EPA is a high-variance slice: adding it to the pass unit moves ratings more than it
  informs them. Switch kept off (team_model.dpi_pass).
- **RESULT {#called-back} (AB-b) called-back plays at their would-be result: FAIL (closest of the three).** -0.022
  [-0.051, +0.007] (2021 +0.001, 2022 -0.061, 2023 -0.024, 2024 -0.000, 2025 -0.025; winners 61.9 -> 63.2%); total MAE
  +0.013. Not better than noise; no re-run on these seasons. Switch kept off (team_model.called_back); its pieces (the
  archive's would-be parse, the EPA regression) stay for a fresh pre-registered test on 2026 at season end.
  Answer to the owner's question: penalties are not missing from the team ratings in any way that measurably costs
  game accuracy. Flags on plays that stand are inside those plays' EPA; wiped-out plays are mostly noise team to team.
- **DESCRIPTIVE 2026-10-17 (owner: "do we account for likelihood of coming back after a bye? ... total calendar dates
  to return after certain injuries? ... affects thursday game return likelihood right?"):** the return chain
  (nfledge/returns.py) counts GAMES missed and skips byes; it has no calendar. Injured players still on the active
  roster, 2014-26 (22,052 states, scratch/ret_days.py), P(back next game) by days to it: <= 5 (Thursday) 26.0%, 6-8
  29.8%, 9-12 37.4%, 13+ (after a bye) 46.2%; after one missed game 33.8 / 38.5 / 48.2 / 55.2%. Concussion 38 / 53 / 68
  / 66% (the extra days matter most: a protocol clock), hamstring 37 / 43 / 44 / 66%, ankle 31 / 38 / 41 / 61%, knee
  30 / 35 / 45 / 52%. The current week's practice model was already checked for short weeks / extra rest (within 1.4
  points, section above): practice days carry it there. The return chain (later weeks, Expected back) does not.
- **PRE-REGISTERED 2026-10-17 (before building): (AD) calendar days in the return chain.** Two features added to the
  return model's state: gap = days from the game he just missed to his team's next game; days_out = days from the
  last game he played to that next game. The chain steps them along his team's real schedule (byes, Thursday games).
  tools/return_days_eval.py, walk-forward 2022-25 (each season fit on the seasons before), the harness of tools/
  lookahead_chain_eval.py. GATE: (1) P(back next game) Brier on every state, pooled, lower with a 95% bootstrap CI
  (2,000 player-episode resamples) excluding 0 and lower in >= 3 of 4 seasons; (2) the chain over his next 2-6 games
  not worse (CI upper < +0.002); (3) calibration error (10 bins) not above today's + 0.005; CONFIRM on 2026 so far,
  same direction. Injured-reserve players (return_timing.py, which shares these features) checked the same way
  before the features reach it.
- **RESULT {#return-calendar} (AD) calendar days in the return chain: PASS (narrow), shipped.** tools/return_days_eval.py,
  walk-forward 2022-25, 12,754 states. Next game: Brier .1128 -> .1121, -0.0007 [-0.0014, -0.0000], better 2023-25 (2022
  +0.0001); active-roster states -0.0018 [-0.0034, -0.0002]. Next 2-6 games +0.0000 [-0.0003, +0.0004]. Calibration
  error .0218 -> .0235 (bar +.005). 2026 so far -0.0001 (same direction, 478 states). Where it matters, by days to the
  next game (actual / today / calendar): <= 5 16.5 / 20.1 / 16.9%; 6-8 20.0 / 19.7 / 19.0%; 9-12 24.1 / 20.1 / 24.6%;
  13+ (after a bye) 31.9 / 22.3 / 29.0%: today's model said ~20% whatever the schedule. Injured reserve / PUP: -0.0001,
  2 of 4 seasons: return_timing.py keeps its features. Shipped in nfledge/returns.py (CHAIN_FEATURES; the chain steps
  through his team's real schedule, which also feeds Power C's QB availability).
- **DESCRIPTIVE 2026-10-17, before pre-registering: range calibration today** (the queued item; scratch/range_desc.py,
  walk-forward backtests 2021-25 cache/experiments/adopted_*, played, projection >= 1). Overall 10-90% ranges hold 82.3%
  (7.4% below p10, 10.3% above p90). By position x weekly rank tier (top / starter / flex / deep): top three tiers
  75.8-82.1% (QB flex lowest; RB / TE flex 12-13% above p90); deep tiers 85-90% (points can't go below 0, so p10 sits
  at the floor: 1-5% below). The earlier "top tiers 73-75%" note predates later model changes.
- **PRE-REGISTERED 2026-10-17 (before running): (AE) ranges from out-of-sample misses.** engine._fit_quantiles takes
  each position's quantile offsets from projections on the TRAINING seasons, made by a model fit on those seasons
  (in-sample misses run small). Variant: the same binning (12 projection bins per position, >= 30 rows), fit on the
  walk-forward backtest's own rows from every earlier test season (out of sample), on misses divided by the row's
  widening factor m (games, low sample, injury boost; engine.py), then x m again. Score on 2023-25 (each fit on 2021 ..
  s-1): mean pinball loss over p10 / p25 / p50 / p75 / p90, played rows, projection >= 1. GATE: lower with a 95% CI over
  season-weeks excluding 0 and lower in each of 2023-25; guard: top-three-tier 10-90% coverage no further from 80% on
  average. tools/range_eval.py.
- **RESULT {#range-oos} (AE) ranges from out-of-sample misses: FAIL, today's kept (now tested).** 15,128 rows 2023-25:
  pinball 1.3144 -> 1.3133, -0.0011 [-0.0034, +0.0011] (2023 -0.0006, 2024 +0.0009, 2025 -0.0036); top-three-tier
  coverage gap from 80% 0.022 both ways (QB flex 73.6 -> 73.8%). The widening factor is 1 (config [uncertainty] all
  off), so the variant used the offsets as they are. Ranges are calibrated within noise already: the in-sample source
  doesn't show up as too-narrow ranges. Range calibration closed.
- **PRE-REGISTERED 2026-10-17 (before running): (AF) within-season recency in team ratings** (docs/handset_audit.md #5).
  team_model.half_life_weeks = 3 ("6 no help" on games, no numbers). Grid {2, 3 (today), 4, 6, 8}. tools/game_eval.py
  --only=fitted, model-only, paired by game. CHOOSE the lowest margin MAE on 2021-23; DECIDE on 2024-25: lower than 3
  with a 95% CI over season-weeks excluding 0 and lower in both seasons; CONFIRM 2026 so far, same direction; then
  fantasy MAE not worse (tools/experiments.py, CI upper < +0.003). Today's the choice -> keep (now tested).
- **RESULT {#half-life} (AF) team-rating half-life: FAIL, 3 kept (now tested); PENDING CHECK at season end.**
  tools/game_eval.py 2021-26 (scratch/af_compare.py). Choose 2021-23 vs 3 (10.389): 2 +0.026, 4 -0.014, 6 -0.026, 8
  -0.029 [-0.100, +0.042] (chosen). Decide 2024-25 (8): -0.046 [-0.170, +0.087], 2024 -0.114, 2025 +0.021 (fail).
  Not the pre-registered pick but seen: 4 on 2024-25 -0.052 [-0.099, -0.002], both seasons, 2026 so far -0.018; 2 is
  worse (+0.101 [+0.008, +0.203]). Adopting 4 now would be picking after seeing; instead a fresh pre-registered test
  at season end: 4 vs 3 on full 2026 (gate: lower margin MAE, CI excluding 0).
- **PRE-REGISTERED 2026-10-17 (before running): (AG) season weights in player efficiency** (docs/handset_audit.md #6).
  player_model.eff_season_weights = [1, .6, .3] (this / last / two seasons back; "flat and steep within noise", no
  numbers). Grid last {.3, .6, 1} x two back {0, .3, .6} (today .6 / .3). tools/experiments.py 2021-2026 (variants
  effw_*), tools/grid_eval.py: CHOOSE the lowest fantasy MAE (relevant rows) on 2021-23; DECIDE on 2024-25: lower than
  today with a 95% season-week CI excluding 0 and lower in both seasons; guards: no position significantly worse,
  start / sit not significantly worse (sec. 1 rule 7); CONFIRM 2026 so far, same direction. Today's the choice -> keep.
- **RESULT {#eff-season-weights} (AG) season weights in player efficiency: FAIL, [1, .6, .3] kept (now tested; flat).**
  tools/experiments.py 2021-2026 + tools/grid_eval.py. Choose 2021-23, MAE vs today: every cell within +-0.003, none with
  a CI excluding 0 (last .3 / two back 0 +0.0029 [-0.0001, +0.0059] the worst); chosen .3 / .6 -0.0002 [-0.0031,
  +0.0027]. Decide 2024-25: -0.0031 [-0.0065, +0.0003] (2024 -0.0029, 2025 -0.0033; no position significant); 2026 so
  far +0.0053 [-0.0075, +0.0133] (fail). docs/handset_audit.md #6.
- **PRE-REGISTERED 2026-10-17 (before running): (AI) the newcomer volume multiplier** (docs/handset_audit.md #7).
  experiments.newcomer_scale = 0.5 ("a round value set before the run"; only 0.5 vs off was tested). Grid {.3, .4, .5
  (today), .6, .7}. tools/experiments.py 2021-2026 (variants newcomer_s*), tools/grid_eval.py: CHOOSE the lowest
  fantasy MAE (relevant rows) on 2021-23; DECIDE on 2024-25 (CI excluding 0 below, better in both, no position
  significantly worse, start / sit not significantly worse); CONFIRM 2026 so far, same direction. Today's the choice
  -> keep. (Relevant rows include the newcomers and the teammates whose volume they take.)
- **RESULT {#newcomer-scale} (AI) the newcomer multiplier: FAIL, 0.5 kept (now tested).** tools/experiments.py 2021-2026 +
  tools/grid_eval.py. Choose 2021-23 vs 0.5: .3 +0.0005, .4 +0.0002, .6 -0.0001, .7 -0.0002 [-0.0013, +0.0008] (chosen).
  Decide 2024-25 (.7): +0.0014 [+0.0004, +0.0026], worse both seasons (WR +0.0026); 2026 so far -0.0016. The
  multiplier is flat near 0.5 and a weaker cut is worse later. docs/handset_audit.md #7.
- **DESCRIPTIVE 2026-10-17 (docs/handset_audit.md #8, count first): the shrinkage bounds.** Player efficiency rates are
  shrunk toward position x draft-tier means with strength k (pseudo-opportunities) by method of moments, clipped to
  [5, 2000]. scratch/kbind.py, models trained for 2022 and 2025: of 22 rate cells, the lower bound never binds; the
  UPPER binds in 15 (2022) and 9 (2025), mostly where no between-player spread is measurable (tau2 <= 0, k = inf: RB
  rush yards / TDs / adjusted EPA per carry, RB receiving per target, TE receiving TDs, QB INT rate), else 2,100-3,500.
  Finite k: median 414 (2022) / 238 (2025). So the cap alone sets how much a player's own history counts in those
  rates (200 carries: 200 / 2,200 = 9% own).
- **PRE-REGISTERED 2026-10-17 (before running): (AJ) the shrinkage cap.** player_model.shrink_k_max: grid {500, 1000,
  2000 (today), 5000, 100000 (~ the prior alone)}. tools/experiments.py 2021-2026 (variants kmax_*), tools/grid_eval.py:
  CHOOSE the lowest fantasy MAE (relevant rows) on 2021-23; DECIDE on 2024-25 (CI excluding 0 below, better in both,
  no position significantly worse, start / sit not significantly worse); CONFIRM 2026 so far, same direction. Today's
  the choice -> keep. The lower bound (never binds) and the 100 fallback are left as they are.
- **RESULT {#shrink-cap} (AJ) the shrinkage cap: FAIL, 2000 kept (now tested).** tools/experiments.py 2021-2026 +
  tools/grid_eval.py. Choose 2021-23 vs 2000: 500 -0.0015 [-0.0043, +0.0015] (chosen), 1000 -0.0010, 5000 +0.0010,
  100000 +0.0014. Decide 2024-25 (500): +0.0013 [-0.0017, +0.0043] (2024 -0.0027, 2025 +0.0052; RB +0.0038); 2026 so
  far -0.0026 [-0.0041, -0.0018]. Mixed by season: the cap matters (the gradient over 2021-23 is monotone: less
  shrinkage slightly better) but not reliably. docs/handset_audit.md #8.
- **DESCRIPTIVE 2026-10-17 (owner: "do players that score more touchdowns from further out have more value than those
  that typically only score touchdowns from goal line plays?"):** scratch/td_dist.py, play-by-play 2012-25, 1,028
  player-season pairs (80+ touches / targets both years). Year to year (Spearman): long TDs (from 20+ out) per chance
  .38; goal-line conversion (scoring when inside the 5) .03 (noise: not a skill); share of chances inside the 5
  (role) .25; yards per chance .82. Next season's TDs per chance: yards per chance .47, long-TD rate .33 (but only .04
  beyond yards per chance in a rank regression), goal-line conversion .07. So distance scorers are worth more because
  they are explosive, which yards per chance carries. Our TD projections (walk-forward 2021-25, 541 RB / WR / TE
  seasons): misses vs last season's yards per chance, Spearman .05 overall (RB .03, TE -.07) but WR +.15 (n 230):
  explosive receivers beat their projected TDs. Found by slicing after looking: a lead, not evidence.
- **QUEUED, PRE-REGISTERED 2026-10-17 (before building; runs after (AJ)): (AK) explosiveness in WR receiving TDs.**
  Variant: the WR receiving-TD expectation per target gains a term in his prior yards per target (shrunk toward the
  position x draft-tier mean like his other rates, same season weights), its weight fitted with the rest of the TD
  model on the training seasons. WR only (the lead is WR; RB / TE unchanged). tools/experiments.py 2021-2026, variant
  wr_td_explosive vs baseline: GATE fantasy MAE on WR relevant rows lower with a 95% season-week CI excluding 0 and
  lower in >= 4 of 6 seasons; guards: overall MAE not worse (CI upper < +0.002), WR P(1+ rec TD) Brier not worse,
  start / sit not significantly worse.
- **DESCRIPTIVE 2026-10-17 (owner: "do players score more annually? ... worth normalizing by year?" and "rule changes
  as signals that affect scoring?"):** scratch/era.py, QB / RB / WR / TE half-PPR points per team-game: 1999-2003
  111-119, 2010-16 122-133, peak 2020 138.1, 2021-25 125-131 and falling (trend 1999-2025 +0.79 a year; 2015-25 -0.65);
  season to season +-3.6 (sd 4.4). Rule-change years: 2004 illegal contact, pass yards 213.7 -> 225.1; 2024 dynamic
  kickoff; 2025 touchbacks to the 35, yet scoring fell (124.6). Our walk-forward projections' overall bias (actual -
  projected, played rows, projection >= 3): 2021 -2.6%, 2022 -0.9%, 2023 +0.6%, 2024 +5.5%, 2025 -1.6%: the model
  trains on prior seasons, so a season's environment reaches it late (Vegas totals carry part of it). Grades and
  ranks are within-season percentiles already. A rule-change flag as an input: ~5 cases since 1999, each different,
  and unvalidatable as a hand-set number; covered empirically by (AL).
- **PRE-REGISTERED 2026-10-17 (before running): (AL) in-season calibration of the projection level.** For week w of
  season s, every projection x r(s, w), r = (A + k M) / (P + k M): A, P = actual and projected points of the season's
  played rows (projection >= 3) in weeks before w; M = their mean projection; k pseudo player-games (shrinks r to 1
  early). One league-wide r (uniform: never reorders players within a week, so start / sit is unchanged). Grid k
  {250, 1000, 4000} (no in-sample estimate available before 2021). tools/env_eval.py on the walk-forward backtests
  (cache/experiments/adopted_*), weeks 3-18, rows played with projection >= 3: CHOOSE the lowest MAE on 2021-23;
  DECIDE on 2024-25: MAE lower with a 95% CI over season-weeks excluding 0 and lower in both seasons; guard: no
  position significantly worse. Reported: each season's bias before / after, 2024-25 (the kickoff-rule years) by
  week. If it passes: ship as a projection-level factor (live, from this season's finished weeks), and a field-
  position prior for mechanical rule changes is pre-registered as a second step for weeks 1-2.
- **RESULT {#season-calibration} (AL) in-season calibration of the projection level: FAIL, not shipped.** tools/
  env_eval.py, 18,173 rows 2021-25. Choose 2021-23: k 250 -0.0113 [-0.0167, -0.0063] (chosen), 1000 -0.0083, 4000
  -0.0044. Decide 2024-25: +0.0112 [+0.0005, +0.0233] (2024 +0.0297, 2025 -0.0070; RB, WR worse). It did fix the level:
  bias 2021 -2.6 -> -1.4%, 2022 -0.9 -> +0.1%, 2023 +0.6 -> +1.7%, 2024 +5.5 -> +2.0%, 2025 -1.6 -> -0.9% (r in 2024
  reached 1.03-1.05 by week 4). Why MAE got worse where bias improved: outcomes are right-skewed (median / mean
  0.74-0.81), so raising projections toward the mean costs absolute error. Not gated, squared error: 2021 -0.04, 2022
  +0.03, 2023 +0.06, 2024 -0.13, 2025 +0.02 (on ~38): a season-level bias of up to 5% (~0.4 pts a game) is small next
  to a single game's spread (~6 pts). Answer to the owner: scoring environments shift +-3% a year and rule changes
  move them, but correcting for it doesn't make individual projections more accurate; the rule-change prior step is
  not pursued. Where the level would matter is in sums (rest-of-season totals, win chances): a possible later test.
- **RESULT {#wr-td-explosive} (AK) explosiveness in WR receiving TDs: FAIL (gate), switch off.** tools/experiments.py
  2021-2026, 4,989 WR relevant rows. WR MAE 5.141 -> 5.141, +0.000 [-0.001, +0.002]; every season within +-0.001;
  overall +0.000. Seen but not gated: WR start / sit gain 0.785 -> 0.800, +0.016 [+0.003, +0.030] (overall +0.006
  [+0.001, +0.012]): the term reorders close WR pairs correctly more often without moving average error. Not adopted
  on that (the gate was MAE; switching measures after the result is the forking path). PENDING: a fresh test with WR
  start / sit as the primary measure, on full 2026 at season end (pre-register before running).
- **PRE-REGISTERED 2026-10-17 (owner, Jalen Hurts ruled out with a blood clot shows 99% for week 7; "at your
  discretion"): (AH) the lookahead chain for newly injured players.** Today a player on this week's report who played
  his team's last game (no return-model state yet) counts as fully available from next week on. (B) of 2026-10-15
  passed its Brier gate (0.215 -> 0.150) but was held back for ranking fairness (healthy players also miss games and
  are counted at 1.0). On review, the chain shipped for players already out (A) has the same footing: once back he
  counts 1.0 (stay = 1.0), so B extends that treatment; it is tested on what the site ranks with. Variant: his next
  game = this week's chance to play (as now); if he misses it, a return-model state (missed 1, active, his report
  status and injury, the calendar) chains his later games, back = 1.0 thereafter. Everyone else unchanged.
  tools/newinj_eval.py, walk-forward 2022-25 (return model fit on seasons before; backtest rows cache/experiments/
  adopted_*, weeks 3-17, QB / RB / WR / TE projected >= 3 if active): predicted points over his team's next 6 games
  (projection if active x chance to play each game) vs actual points. GATE: MAE lower with a 95% CI over season-weeks
  excluding 0, lower in >= 3 of 4 seasons; guard: mean weekly rank correlation (Spearman) not lower (CI lower bound >
  -0.002). Reported: newly injured rows alone.
- **RESULT {#newinj-chain} (AH) the chain for newly injured players: PASS, shipped.** tools/newinj_eval.py, 14,985 rows
  2022-25 (3,077 newly injured). Points over the next 6 games, MAE 16.916 -> 16.749, -0.167 [-0.198, -0.138], better
  4/4 seasons (2022 -0.167, 2023 -0.127, 2024 -0.162, 2025 -0.212). Weekly Spearman 0.6725 -> 0.6781, +0.0055 [+0.0036,
  +0.0076]: ranking against healthy players improves, so the fairness worry that held B back does not hold. Newly
  injured alone: MAE 18.06 -> 17.25; predicted 46.6 -> 43.4 points vs 41.1 actual. Shipped in nfledge/returns.py
  (_newly_injured; lookahead weeks, rest of season, Fantasy values, Power C). Live check: Hurts (ruled out, blood
  clot) week 7 100% -> 22%, then 35 / 46%; Lamar 27 / 48 / 61%.
  CORRECTION 2026-10-17 (owner: "Hurts is on IR now"): Power C was never wired to it. nfledge/powerc.py's branch for a
  usual starter on this week's report who played the previous game still counted him healthy after this week (Hurts on
  IR: back for 11 of 12 remaining games, 91.7%, Eagles Net -1.1). Now powerc._newly runs the same chain (56%). Added
  with it, for players ESPN lists on injured reserve before nflverse's rosters do (returns.espn_ir / ir_newly): out
  for the league minimum (4 games) or until ESPN's estimated return date if later, then the chain from the active
  state (the chain's IR state is learned mostly from season-ending stays and put Hurts at 7%). Hurts: 48.5%. A rule
  and a feed, no fitted values: same path for the player projections' lookahead.
- **PRE-REGISTERED 2026-10-17 (owner: "one source of truth ... sensible first and backed by data"): (AM) one
  availability plan for every page.** Audit (after the Hurts IR fix): three copies of "will he play in week X" drifted -
  the lookahead (returns.lookahead_availability), Power (powerc, its own chain: lookahead pages counted an injured QB
  healthy after that page's week, Hurts 93% on week 8's page), and the current-week injury model; the chain started only
  for practice-report players; ESPN's IR list reached only newly injured players. Change: run.py builds ONE plan per
  build, as of the current week (P(plays) per injured player per remaining week; the current week from the injury
  model), passed explicitly to every page's projections AND to Power (powerc reads it instead of its own chain when
  given; archive pages and every walk-forward tool keep the historical path, so recorded results cannot move). Players
  whose current-week chance comes from any source (practice report, ESPN bridge, Tuesday model, carried status) start
  the newly-injured chain, not only practice-report players. Two parts change predictions and are tested first:
  (1) ESPN IR for players already out: route a state to the IR direct model (return_timing, already shipped for IR by
  nflverse designation) when ESPN lists him on IR even though nflverse's designation is not IR yet. Test:
  tools/return_hybrid_eval.py --espn-ir, walk-forward 2023-25 (ESPN captures 2022-on), skill positions, rows with
  ESPN IR and designation not IR; production (chain) vs routed (direct model). GATE: Brier lower with the 95% CI by
  episode excluding 0, better in >= 2 of 3 seasons, every k-bucket calibrated within 5 points; and all rows' Brier not
  worse (CI upper < +0.001). Fail: ESPN IR stays newly-injured-only. (2) the ESPN return-date floor for newly injured
  IR players (shipped earlier today with the league minimum): from the captures 2022-25, the share of IR players with an
  ESPN return date who played a game before that date. GATE: <= 10% -> keep the floor; else drop it (league minimum
  only, a rule). The rest (one plan, Power reading it, the broader chain start) applies already-tested models to more
  players / pages; checked by the before / after table of every injured player and QB-dependent team.
- **RESULT {#avail-plan} (AM) one availability plan: shipped; ESPN-IR routing for players already out FAIL (not
  shipped); return-date floor PASS (kept, widened by owner choice).** (1) tools/return_hybrid_eval.py --espn-ir,
  walk-forward 2023-24 (2025 had no such rows), 41 episodes / 277 rows with ESPN IR and no IR designation yet: direct
  model Brier 0.2122 -> 0.1520, -0.0602 [-0.1243, -0.0028], better 2/2 seasons; all rows -0.0011 [-0.0022, -0.0000];
  but k-bucket calibration 3-4 games -7.2 points and 5-8 +5.7 (gate: within 5): FAIL as registered (production's chain
  was off by +26 / +16 / +18 points on the same rows; a re-registered gate comparing calibration with production's
  is a possible follow-up, not run). The tool was updated to share the chain's schedule tables (AD came after it).
  (2) ESPN return-date floor, captures 2022-25: 922 IR stints with a return date ahead of a game; 3.6% played before
  it (2022 3.9%, 2023 4.8%, 2024 3.0%, 2025 3.2%): PASS (<= 10%). Owner chose (A): the floor (league minimum from his
  team's next unplayed game, and ESPN's return date) applies to every ESPN-IR player not yet designated, already out
  or newly injured (test 2 measured all IR stints) - a rule and a measured date, no routing to the direct model.
  (3) Found while checking, fixed: ReturnModel.states counted a game as missed before it was played (nflverse's weekly
  rosters list the week from its first game on), so from Thursday to Monday night every injured player carried a
  phantom missed game (Hurts read as already out; Caleb Williams 4 straight misses, 48% next week). Only final games
  count now; walk-forward results are unaffected (every past game is final). Live check, week 6 (Sunday, 1 game
  final): Power QB-back share on this week's page / week 7's / week 8's - PHI 0.485 / 0.530 / 0.582 (lookahead pages
  had 1.0), BAL 0.659 / 0.719 / 0.763, TB 0.662 / 0.722 / 0.763, CHI 0.918 / 0.937 / 0.951; Caleb Williams 71% this
  week, then 80 / 87 / 91%; healthy teams' 0.995-0.999 scratch-risk drift gone (1.000).
- **PRE-REGISTERED 2026-10-18 (owner, spot-starting Bucs D/ST vs a Steelers offense missing Pittman and Roman Wilson;
  queued, not run): (AN) opponent pass-catcher absences in D/ST sacks and takeaways.** D/ST points allowed already come
  from Vegas implied points (injuries priced in); sacks, INTs and fumbles recovered come from 16-game rates and ignore
  who is missing. Input (knowable before kickoff, as in {#skill-absence-margin}): the opponent's share of targets over
  its last 3 games held by WR / TE / RB listed Out or Doubtful on the final report (fresh absences only), plus a QB
  change flag already in the game model. Variant: sacks, INTs and FR each x exp(b x missing share), one b per stat fit
  by Poisson regression on the D/ST model's walk-forward residuals in the seasons before (tools/dst_eval.py), 2022-25.
  Scored on ESPN standard D/ST points (and the owner's Sleeper scoring alongside, not gated). GATE: on defense-games
  facing a team missing >= 15% of its target share, MAE lower with a 95% CI over games excluding 0; all games not worse
  (CI upper < +0.01). Report the fitted b per stat (sign and size) and the MDE: {#skill-absence-margin} was too small
  to measure, so a FAIL here is labelled "unresolved" unless its CI rules out a gain of 0.2 points per affected game.
- **RESULT {#dst-absence} (AN) opponent pass-catcher absences in D/ST sacks and takeaways: FAIL (resolved: no
  meaningful effect).** tools/dst_absence_eval.py, D/ST model walk-forward, 2,398 defense-games 2021-25 (253 vs an
  opponent missing >= 15% of its targets), b fit on seasons before, test 2022-25. Fitted multipliers small and unstable
  (b_sack -0.21 to +0.17, b_int +0.14 to +0.65, b_fum_rec -0.02 to +0.20 per 100% of share: a 20% absence moves a stat
  by a few percent). Affected games (206): MAE 4.143 -> 4.166, +0.023 [-0.004, +0.050]; all (1,918): 3.971 -> 3.975,
  +0.004 [+0.001, +0.008] - worse. The CI rules out the 0.2-point gain, so FAIL, not "unresolved". Why: the current
  model is already calibrated on exactly these games - projected 6.40 vs actual 6.34 points; sacks 2.45 vs 2.48, INTs
  0.74 vs 0.76, FR 0.50 vs 0.49. A short-handed offense doesn't give up more sacks or turnovers than its rates say
  (and Vegas already lowers its points). D/ST stays as is.
- **PRE-REGISTERED 2026-10-18 (owner: "full participant and on the practice report full participant are technically
  different, but by how much? ... we should be tracking all practice participation ... assume they practiced full when
  nothing reported"): (AO) days off the practice report.** The availability model reads each player's listed days
  only ('L' for a player first listed Friday, the same string as one listed only Wednesday). NFL.com's practice API
  dates every listed day (stored since 2026-10-17; refetched for 2018-25 for this test). Team practice dates = the
  dates anyone on that team's report that week was listed. Padded string = his status on each team date, 'F' where
  he wasn't listed (the league's rule: a player not on the report practiced fully). Descriptive (the owner's "by how
  much"): play rate and model residual for days listed F vs days off the report, by position in the week (before his
  first listing = a new injury; after his last = dropped off). Test, the full-week practice model (final reports,
  status not Out), walk-forward 2021-25 trained on seasons before (2018 on): A production (listed days only);
  B padded ('F' for days off); C padded + a count of days off the report (keeps listed-F and unlisted apart).
  GATE (B or C replaces A): Brier lower with the 95% CI over season-weeks excluding 0, better in >= 4 of 5 seasons,
  calibration by decile within 2 points; C over B only if C beats B with the CI excluding 0. Rows whose string
  changes reported alone. The partial-week models keep raw strings (their day count marks the stage).
- **RESULT {#off-report} (AO) days off the practice report: FAIL (production keeps listed days only).**
  tools/offreport_eval.py, 31,034 labelled practice weeks 2018-25, all dated (refetched); padding changed 19.3% of
  strings. Descriptive (status not Out, played rate): listed FFF all week 92.0%; off the report BEFORE his first
  listing (a new injury, e.g. FFL) 83.9% (n 3,439); off it AFTER his last listing 70.8% (n 1,354: dropped off the
  report is often a move to IR / release, not a clean bill); off in the MIDDLE 87.6% (n 655). So "not listed" is
  not "listed as full": it carries its own information. Walk-forward 2021-25: B (padded with F) worse, Brier 0.0993
  -> 0.1011, +0.0019 [+0.0009, +0.0029], 2/5; C (padded + days-off count) 0.0988, -0.0004 [-0.0013, +0.0003], 3/5,
  calibration off up to 9 points; C beats B (-0.0023 [-0.0038, -0.0010]) because it gives the distinction back. The
  listed-days string already encodes it (a 1-day 'L' is a late addition or an early drop). Display keeps padded FP
  for days before his first listing only (that day he practiced, unlisted); see the display note.
- **PRE-REGISTERED 2026-10-18 (owner: "practice days are uniform ... can be back tracked from the game date"):
  (AP) the week's stage from the calendar.** League policy fixes the three report days by game day (Sun game: Wed-Fri;
  Mon: Thu-Sat; Thu: Mon-Wed; Fri / Sat: Tue-Thu; Wed: Sun-Tue); 2026 check: 181 of 186 team-weeks' dated reports
  fall inside them (the 5 others: Melbourne week 1, extra report days in travel weeks). Today the site calls a
  team's final report out when anyone on it has a game status or 3 listed days (InjuryModel.final_report_teams),
  which uses the full-week model early in a week with extra report days, and the partial model late when nobody was
  listed all week. Variant: final once the third derived report day's report is in (extra filed days kept as days).
  Test, tools/stage_eval.py: dated reports 2021-25 (refetched with {#off-report}), each team-week replayed at the end
  of each derived report day (what was published by then; game status only with the third), both rules choosing
  the model (full-week vs partial k = 1 / 2), models trained walk-forward as production on seasons before. Scored:
  Brier on played, status not Out. GATE: rows where the rules disagree, calendar Brier lower with the 95% CI over
  season-weeks excluding 0; all rows not worse (CI upper < +0.0005). Report how often they disagree.
- **PRE-REGISTERED 2026-10-18 (same thread): (AQ) short-week practice reports.** Teams playing 3-4 days after their
  last game (Thursday after Sunday, etc.) mostly hold walkthroughs and file ESTIMATED participation. Variant: the
  full-week practice model gets a short-week flag (days from his team's previous game to this one <= 5). Same rows
  and walk-forward as the model's own fit (avail_hist 2018 on), test 2021-25, status not Out. GATE: Brier lower with
  the 95% CI over season-weeks excluding 0 on short-week rows, all rows not worse (CI upper < +0.0005), calibration
  by decile within 2 points on short-week rows.
- **RESULT {#calendar-stage} (AP) the week's stage from the calendar: PASS, shipped.** tools/stage_eval.py, 52,029
  player-days replayed 2021-25 at the end of each derived report day. The rules disagree on 74 (0.1%), all the
  heuristic calling the final report LATE (nobody listed all three days, no game status), never early. Disagreeing
  rows: Brier 0.1728 -> 0.1081, -0.0647 [-0.0934, -0.0322]; all rows -0.00009 [-0.00018, -0.00002]. Shipped in
  InjuryModel.final_report_teams: final once the team's third calendar report day's reports are in (the old rule
  kept as well; it was never early). nfledge/practice_calendar.py is the foundation (owner: "use it as a way to expect
  reports ... a foundation"): report days per team for display and expectations whatever the model tests say.
- **RESULT {#short-week} (AQ) short-week practice reports: FAIL (calibration gate).** Same tool, full-week model
  with a short-week flag (<= 5 days since his team's last game), 1,079 short-week rows of 16,596, 2021-25. Short-week
  rows Brier 0.1021 -> 0.0953, -0.0068 [-0.0099, -0.0034]; all rows -0.0005 [-0.0007, -0.0003]: accuracy passes. But
  calibration on short-week rows was off by up to 11.7 points by decile (gate: 2), so not shipped. ~108 rows per
  decile makes that gate noisy; a follow-up would compare against production's own calibration on those rows,
  registered before running.
- **PRE-REGISTERED 2026-10-18, a second look at (AQ) after its calibration gate failed (owner: "AQ, why wait?";
  weaker evidence than a first pass, recorded as such): (AQ2) short-week flag, calibration judged against
  production's own.** Same rows, models and walk-forward as {#short-week}. Calibration error = mean absolute gap
  between predicted and actual play rate over 10 equal-count bins (ECE) on short-week rows. GATE: (i) short-week
  Brier lower with the CI excluding 0 (already met); (ii) ECE of the flag model minus production's ECE on the same
  rows: 95% bootstrap CI (resampling season-weeks) upper bound < +0.01; (iii) all rows not worse (CI upper < +0.0005).
- **RESULT {#short-week-2} (AQ2) short-week flag, calibration vs production's: FAIL (unresolved).** Production's
  own short-week calibration error (ECE) 0.0329, the flag model's 0.0353: +0.0024 [-0.0284, +0.0185], the upper bound
  past the +0.01 gate. So the 11.7-point decile gap in {#short-week} was mostly noise (production is about as
  calibrated there), but 1,079 rows can't rule out a 2-point calibration loss. Accuracy gain stands (Brier -0.0068
  [-0.0099, -0.0034]). Not shipped; revisit when 2026's short weeks add rows.
- **Week clock (owner 2026-10-18), shipped in stages; REMAINING WORK.** nfledge/week_clock.py (+ tests/test_week_clock.py,
  10 calendar cases) is the one source for the week: current week, kickoffs (zoneinfo), per-team report deadlines,
  rollover, waiver run; written to every week page as "clock" and applied in the browser (shell.js NFLE.clock).
  Moved onto it: run.display_week; InjuryModel.final_report_teams (per team; replaced a league-wide report date);
  kickoff times in the browser (also fixed a DST bug: Nov 1 2026 read as EDT); the header's report status (per team,
  next deadline); ET dates and practice strips on the card; game-log results only once final with snaps published;
  builds on report deadlines / inactives / rollover (tools/news_watch.py). Still inferring on their own (from the
  2026-10-18 audit), to move next: (1) league.js claimWindow (hard-coded Tue 2am-Wed 2am CT for every platform; use
  clock.waivers and the league's own settings); (2) data.latest_week means "any game final", not "completed" (engine
  live flag for the Sleeper-blend experiment, OFF; fitting loops include a partial week - check before changing, it can
  move projections); (3) depth chart snapshot frozen after a Thursday game for Sunday teams (data.depth_for_week,
  depth_build.py); (4) ESPN snapshot / news file dates in UTC (espn_snapshot.py, espn_news.py); (5) espn_calib
  EARLY_DAYS vs the live bridge's report-presence rule; (6) gamecast.js weekOfDate (assumes a Thursday opener);
  (7) the tuesday.py stage taken from the player's own day count rather than the calendar.
- **PRE-REGISTERED 2026-10-18 (week clock audit, owner: "keep going"): (AR) each team's depth chart as of its own
  game.** data.depth_for_week takes one daily ESPN depth snapshot for the whole week, the last before the week's
  FIRST game day + 1 day, so after a Thursday game every Sunday / Monday team's chart is frozen at Thursday night
  (Friday changes - a starter demoted, a backup promoted - never reach its projection). Variant
  (experiments.depth_per_team): per team, the last snapshot before its own game day + 1 day (still before kickoff:
  no leakage). Daily snapshots exist from 2025 only, so tools/experiments.py baseline,depth_per_team 2025 (and 2026
  weeks 1-5 reported, not gated). GATE: fantasy MAE on the rows whose depth input changes lower with the 95% CI over
  season-weeks excluding 0; all rows not worse (CI upper < +0.003); no position significantly worse.
- **QUEUED 2026-10-18 (week clock, model side; each needs its own pre-registration before running):** (AS) midweek
  stage from the calendar: live the partial-week model is picked by the player's own listed-day count (a player first
  listed Thursday is "stage 1"), while the partial models are trained on players listed from the first report day;
  variant: stage = the team's report days in (week clock) with days before his first listing filled as full practice
  (the {#off-report} display rule), partial models retrained on the same construction. (AT) one "early week"
  definition: espn_calib.EARLY_DAYS (calibration: capture within 3 days of the team's last game) vs the live bridge
  (no report published yet): align both on the week clock (before the team's first report deadline) and refit the
  ESPN early-week rates.
- **RESULT {#depth-per-team} (AR) each team's depth chart as of its own game: PASS, shipped.** tools/experiments.py
  baseline,depth_per_team 2025 (daily snapshots exist from 2025), ~15-20 teams' charts change a week (879 depth rows
  over 2025). Fantasy MAE ALL 5.168 -> 5.166, -0.001 [-0.003, -0.000] (player-resampled [-0.003, -0.000]): QB -0.003
  [-0.008, -0.000], RB -0.003 [-0.005, -0.000], WR / TE no difference; no position worse. Start / sit gain +0.010
  [+0.001, +0.021]. Rows whose depth input doesn't change are identical, so the gain sits on the changed rows. Range
  calibration and availability Brier unchanged. Live: config experiments.depth_per_team = true.
- **PRE-REGISTERED 2026-10-18 (owner, Sunday of week 6: "how often does that signal really mean the player plays ...
  be diligent"): (AU) game-day actives / inactives.** Measured first (nflverse weekly rosters ACT / INA on game day x
  final injury status, played = any snap, 2019-25, QB / RB / WR / TE): Questionable declared ACTIVE 97.4% played
  (n 1,992), INACTIVE 0.0% (871); Doubtful ACTIVE 28.6% (14), INACTIVE 0.0% (328); Out INACTIVE 0.0% (1,821); not on
  the report INACTIVE 0.0% (5,089: healthy scratches). 69.6% of Questionable players are declared active. Today the
  site ignores the game-day list (the midweek ESPN rule stops at the final report, so a Questionable player ESPN marks
  inactive stays at his pre-game chance). Live source, checked on week 6's 1 p.m. slate: ESPN's feed marks declared
  inactives status Out + fantasy status INACTIVE (updated 11:33-11:46 ET, after the 11:30 posting) and flips a
  Questionable player who dresses to Active (Caleb Williams 11:46 ET); nflverse rosters lag a day. Rule (measured
  rates, no fitted values): once a team is past its inactives time (week clock: kickoff - 90 min), on our board:
  ESPN INACTIVE -> P(plays) 0; Questionable now ESPN Active (updated on game day) -> 0.974; Doubtful now Active ->
  0.286 (n 14, noted). Nobody else changes. Prospective check (this week on): each override archived
  (data/live_inputs/gameday_<date>.json: ruling, time, the model's pre-ruling chance); tools/gameday_audit.py after
  the week's snap counts: GATE to keep it - no INACTIVE override played; ACTIVE-Questionable played rate's 95% CI
  includes 0.974; Brier of the overridden chances below the pre-ruling chances on the same players.
- **PRE-REGISTERED 2026-10-18 (owner: "healthy scratch model needs to be fixed when starters ahead of them get hurt";
  Tanner McKee, PHI QB1 with Jalen Hurts on IR, read 44% to play and the starter pick fell to Cole Payton): (AV)
  "out ahead" counts reserve-list starters.** The healthy-scratch model's ahead_out (players at his position, out this
  week, with a bigger recent snap share) is built from the week's ACT / INA roster rows, so a starter moved to IR /
  PUP / NFI (roster status RES) drops out of it: McKee had ahead_out 0, while Huntley (Lamar Out, still ACT) had 1.
  The model itself handles promoted backups (QB rank 1 with a starter out ahead: predicted 97.7%, played 94.1%,
  2021-25 in-sample). Variant (injuries.ahead_reserve): out = on the report Out / Doubtful OR on a reserve list this
  week; their snap share = their last known (earlier weeks). Test: the scratch model refit walk-forward 2021-25 (season
  s trained on seasons before, production's settings), Brier on not-on-report rows. GATE: rows whose ahead_out changes,
  Brier lower with the 95% CI over season-weeks excluding 0; all rows not worse (CI upper < +0.0005).
- **RESULT {#ahead-reserve} (AV) "out ahead" counts reserve-list starters: PASS, shipped.** tools/ahead_eval.py, the
  healthy-scratch model refit walk-forward 2021-25 on 36,936 not-on-report rows; ahead_out changes on 5,216 (14.1%).
  Changed rows: played 89.3%, production predicted 85.9% (under, the bug), the variant 89.6%; Brier 0.0713 -> 0.0682,
  -0.0031 [-0.0050, -0.0011]. All rows -0.00029 [-0.00059, +0.00001]. Live: config injuries.ahead_reserve = true
  (Tanner McKee: ahead_out 0 -> 1). Pattern noted (owner: "players on IR threw a wrench ... over and over"): an audit
  of every consumer that picks "this week's players" by roster status or board membership is under way.
- **PRE-REGISTERED 2026-10-18 (owner: "0 snaps has never meant injured ... lots of players are active and don't play";
  "it shouldn't conflate availability with healthy scratches at all"; Tanner McKee, healthy, read 55% to play): (AY3)
  the healthy-scratch model's label is the game-day active list, not a snap.** Today the label is "took a snap", so a
  dressed backup who never plays reads as a scratch (McKee: weeks 1-3 inactive as QB3, 4-5 dressed as QB2, 0 snaps all
  five; act_rate 0.16, 46%). Variant (injuries.scratch_label = "dressed"): label = on the weekly roster's game-day
  active list (ACT) vs inactive (INA), 2019 on, only weeks whose inactives are published; the history features
  (rate, last game) count dressed weeks; same features and settings otherwise. Rows: not on the injury report (a
  healthy scratch by definition: 4,676 of 8,010 skill-player inactives 2019-26). Test (tools/scratch_dressed_eval.py):
  walk-forward 2021-25, season s trained on 2019..s-1, both models scored against the dressed label (what the site
  shows as "not a healthy scratch"). GATE: Brier lower with the 95% CI over season-weeks excluding 0, and calibrated
  (predicted vs actual inactive rate within 2 points overall and for QBs). Ships with a display split: Health / injury
  tags = injury availability only; healthy-scratch risk its own tag; the chance he takes the field (injury x scratch x
  the backup-QB rule) drives sits and expected points.
- **RESULT {#scratch-dressed} (AY3) the healthy-scratch label = the game-day active list: PASS, shipped.**
  tools/scratch_dressed_eval.py, walk-forward 2021-25 on 34,911 not-on-report rows with published inactives (dressed
  91.3%). Brier vs the dressed label: snap model 0.0753 -> dressed model 0.0397, -0.0355 [-0.0367, -0.0343].
  Calibration (inactive actual / snap model / dressed model): all 8.7% / 14.6% / 8.9%; QB 16.5% / 47.9% / 16.6%; RB
  8.4 / 9.4 / 8.4; WR 6.6 / 7.3 / 6.7; TE 6.7 / 7.7 / 7.5. Live: config injuries.scratch_label = "dressed". Display
  split shipped with it: inactive (Health, injury tags) = injury only; scratch = its own "Scratch x%" tag and card state;
  play = takes the field (sits, redistribution, starter picks, Fantasy expected points). Tanner McKee: Health
  healthy; P(dressed) 87% from this model alone (three QB3 inactives, depth chart still rank 2 in week 6).
- **PRE-REGISTERED 2026-10-18 (owner: "mckee was never going to sit this game once hurts got ruled out"): (AY4) the
  next-up QB is not a healthy scratch.** After (AY3) McKee read 11% healthy-scratch risk: a QB next up by the depth
  chart (someone ahead out, rank - out ahead <= 1) who rarely dressed before was inactive 10% of the time (5 of 50,
  2019-25), but all 5 were depth-chart errors (another healthy QB was the real next man: Flacco 2020, Gilbert 2020,
  Hill / Siemian 2021, Winston 2024). Rule (injuries.nextup_qb): a next-up QB with no healthy QB at his team (not out,
  not on the report) ahead of him by recent snap share (more than 0.05) gets the measured inactive rate of that group
  instead of the model's number; 2019-25 in-sample: 1 of 240 inactive (0.4%; Ben DiNucci 2020, benched). Test
  (tools/nextup_eval.py): walk-forward 2021-25, the rate from seasons before s, against production (AY3) on those rows.
  GATE: Brier on the rule's rows not worse (CI upper < +0.0005) and calibrated (within 1 point); other rows unchanged.
- **RESULT {#nextup-qb} (AY4) the next-up QB rule: FAIL (by the calibration clause), not shipped.**
  tools/nextup_eval.py, walk-forward 2021-25: 210 rule rows, 0 inactive. Brier 0.00100 -> 0.00030, -0.00070
  [-0.00111, -0.00034] (the accuracy clause passes); the rule's rate from earlier seasons averaged 1.37% vs 0.00%
  actual, outside the pre-registered 1-point band (production said 1.92%, up to 15.7% on single players). The miss is
  in the owner's direction: next-up QBs with nobody healthy ahead are inactive even less than the rule assumed (the
  only case 2019-25: Ben DiNucci 2020, benched). Code kept off (config injuries.nextup_qb unset). A re-test needs its
  own pre-registration (e.g. calibration judged against production's, or a gate on events, not a point band).
- **RESULT {#nextup-qb2} (AY4, revised definition) the promoted backup QB: PASS, shipped.** Owner, on the snap rule: "backup qbs
  only ever get snaps in serious garbage time or if the starter gets hurt" - backups' snap shares can't rank them (it
  passed McKee, Payton and Milton alike). Revised: each team-week's starting QB from pre-game facts
  (InjuryModel._qb_picks): last game's starter (most snaps, 30%+) if healthy, else the healthy QBs who dressed as his
  backups last game, best depth rank first. 2019-25: returning starter 30 of 3,045 inactive (1.0%: week 17-18 rests and
  benchings, left to the model), promoted backup 2 of 214 (0.9%; the model averaged 3.6%, up to 32.6%), everyone else
  29.2%. The same pre-registered gate, walk-forward 2021-25 on 166 promoted backups: inactive 1.20%, model 4.11% (up to
  56.9%), rule 1.37%; Brier 0.0166 -> 0.0123, -0.0043 [-0.0092, -0.0008]: PASS. Live: config injuries.nextup_qb =
  0.0093 (the 2019-25 rate). Tanner McKee: 11% -> 0.9%.
- **PRE-REGISTERED 2026-10-19: (AY5) the backup-QB rule names the backup by who dressed, not depth rank.** The rule
  (config qb2_play_rate) takes QB1 = depth rank 1 and QB2 = depth rank 2; a depth-rank-2 QB2 played only 74.6% of the
  games his QB1 sat (a QB3 or a stale chart; {#nextup-qb2} found the same errors). Variant: QB1 = last game's starter
  (most snaps, 30%+), QB2 = the healthy QB who dressed as his backup last game, best depth rank first
  (InjuryModel._qb_picks). Test (tools/qb2_dressed_eval.py), 2019-25, team-weeks where last game's starter took no
  snap: did the named QB2 take a snap, depth rank 2 vs the dressed backup. GATE: the dressed backup's play rate higher,
  95% CI over team-weeks (paired) excluding 0; and in team-weeks where the starter played, the named QB2's relief rate
  not above qb2_play_rate's 0.232 by more than 5 points.
- **RESULT {#qb2-dressed} (AY5) backup QB named by who dressed: FAIL, not shipped.** tools/qb2_dressed_eval.py,
  2019-25: 211 team-weeks where last game's starter took no snap; the two ways name the same QB2 in 198. Named QB2
  played: depth rank 2 79.6%, dressed backup 81.0%, +0.014 [-0.014, +0.047]. Where they differ (13): 38.5% vs 61.5%,
  too few to clear the gate. Relief rate when the starter plays: 23.0% / 23.7% (fine). Takeaway: the depth chart's
  QB2 is right almost always; the rule's real gap is that a correctly named QB2 plays only ~80% of his starter's missed
  games (another QB starts: a signing, a QB3 promoted, a gadget QB), which "1.0 when QB1 sits" overstates.
- **IR audit 2026-10-18 (owner: "players on IR threw a wrench in our model over and over"), fixes shipped.** One audit
  of every consumer that picks "this week's players" by roster status or board membership. Fine as built: vacated-
  volume redistribution (an IR'd WR1 / RB1's share is redistributed exactly as for one listed Out), the QB starter
  pick, depth features, CB personnel, the Tuesday model, display. Gaps fixed (rules, no fitted values; checked on week
  6 data): (1) {#ahead-reserve}, above. (2) The availability plan missed reserve-list players ESPN's IR list doesn't
  carry (PUP / NFI / ESPN lag / unmatched ids): every skill player on a reserve list is now out this week (69 entries
  this week, Power reads them instead of "absent = healthy"); those NEWLY placed (not on a list the week before) start
  the return chain with the IR floor; long-term reserve players keep their IR-model inputs untouched (a first version
  fed them p_now 0 and shifted 19 players' return odds 2-4 points: reverted). (3) A player placed on IR in his team's
  bye week was skipped by the newly-injured chain: his state now starts from his next game (simulated Amon-Ra St.
  Brown, DET bye week 6: out weeks 7-10, then 64% / 69% / 75%). (4) Power's backup QB: the best-ranked QB who is neither
  the usual starter nor on a reserve list (was "depth rank 2": Cole Payton over Tanner McKee). Remaining, small:
  qb2_play_rate needs a board QB at depth rank 1 (skipped when an IR'd starter keeps slot 1; the scratch model, now
  fixed, covers it); the debut prior's absolute depth_rank <= 2; lookahead games with no Vegas line ignore the starting
  QB in the opponent's points (gm.predict without starters).
- **PRE-REGISTERED 2026-10-18 (IR audit follow-up, "proceed at your discretion"): (AW) the game model rates a
  starting QB in the player projections.** Engine.project_week calls the game model with no starters, so qb_term = 0
  for every team: its points (and, with no Vegas line, its own spread, which sets the projected pass rate) treat every
  offense as having a league-average QB, though the game model is fit on rows rated with each game's actual QB. With
  Vegas lines (the current week, every backtest week) only the points fallback is touched, so backtests never saw it;
  every lookahead week (7-18 today: no lines posted) is fully exposed: elite-QB teams under, backup-QB teams over.
  Test: tools/lookahead_qb_eval.py, walk-forward 2021-25, weeks 3+, injuries on, project_week in model-only mode
  (use_vegas=False: what a lookahead week sees), three arms on identical rows: none (production); asof (each team's
  most recent starter before the week: what a lookahead week knows); game (the game's starter, most dropbacks, the
  stand-in for an announced starter as in {#game-eval-starter}). Rows: experiments.py "relevant" rows of the none arm.
  GATE (asof vs none): player MAE lower with the 95% CI over season-weeks excluding 0, and no position's CI entirely
  above 0. Ship: lookahead weeks pass each team's projected starter (Power's usual starter, the backup when the plan
  has the usual starter under 50% that week); the current week passes this week's projected starter too (touches only
  the no-line points fallback). Secondary, reported: the game arm; team points MAE.
- **RESULT {#lookahead-qb} (AW) the game model rates a starting QB in the player projections: FAIL (narrowly), not
  shipped.** tools/lookahead_qb_eval.py, walk-forward 2021-25, model-only mode, 12,480 relevant player-weeks. asof
  (most recent starter) vs none: MAE 5.203 -> 5.199, -0.0034 [-0.0070, +0.0003] (lower in 4 of 5 seasons; QB -0.0144
  [-0.0315, +0.0016], RB -0.0038, WR +0.0001, TE -0.0002: no position worse). game (the game's starter) vs none: -0.0041
  [-0.0078, -0.0006]. Team points MAE 7.741 -> 7.671 asof (-0.070 [-0.130, -0.017]), 7.625 game (-0.117 [-0.177,
  -0.060]): the game model's points clearly improve; the player projections barely move (implied points are one input
  among several). Gate (asof arm) failed on the CI's upper end.
- **PRE-REGISTERED 2026-10-18, a second look at (AW) after its gate failed (labelled as such: weaker evidence than a
  first test).** The asof arm rates last week's starter even when the injury model already has him out this week; the
  rule production would use rates the projected starter (who the projections themselves start, injuries included:
  Engine.project_week projects once, takes each team's top non-sitting QB, projects again). Arm proj vs none, same
  rows, same harness, same GATE (MAE lower, 95% CI over season-weeks excluding 0; no position's CI entirely above 0).
  One look only: a FAIL closes (AW) until there is new information.
- **RESULT {#lookahead-qb-2} (AW) second look, the projected starter: FAIL; (AW) closed.** proj vs none: MAE 5.203 -> 5.200, -0.0022
  [-0.0055, +0.0009] (QB -0.0089 [-0.0234, +0.0053]; no position worse); team points 7.741 -> 7.676 (-0.065 [-0.119,
  -0.015]). Kept: Engine.project_week(starters=) (default None, production unchanged) for the eval. Reading: rating
  the QB makes the game model's own points better, but the player projections don't measurably follow (implied points
  are one input among several; volume shares and player rates dominate). Not retried without new information (e.g.
  a test of the lookahead pages' displayed implied totals, or a player model fit in model-only mode).
- **PRE-REGISTERED 2026-10-18 (owner: "the injury/return model needs to be pristine"; audit of all 372 ESPN-listed skill
  players): (AX) players who open the season on a reserve list get a return timeline.** ReturnModel.states starts an
  episode only after a game played that season (ever_played), so a player on IR / PUP / NFI before week 1 has no
  state: the lookahead never brings him back and his rest-of-season value is 0 (2026: 84 skill players, among them
  James Conner, Zach Charbonnet, Isiah Pacheco, Ricky Pearsall, Jayden Higgins, Christian Kirk, Tank Dell). 2019-25:
  ~70 a season; played that season R48 (IR, designated to return) 80%, R04 (PUP) 58%, R01 (IR) 24%; median return
  week 7-9. Variant (injuries.opened_out): states also cover a player on a reserve list (roster status RES, any code)
  in his team's first game who hasn't played that season, from that game until he plays; two features read by both
  the chain and the direct IR model: opened_out (1 in those episodes) and prior_g (games he played the season
  before, every episode). Test: tools/opened_out_eval.py, walk-forward 2022-25 (each season fit on the seasons
  before), skill players, P(back by his k-th next game) k = 1..8, scored as production combines them (direct model
  for IR, the chain otherwise, stay 1, step 1 = the practice estimate when on the report). GATE: (i) new episodes:
  Brier lower than a per-code base rate (share back by game k in earlier seasons' opened-out episodes, same code
  group and k), 95% CI by episode excluding 0, lower in >= 3 of 4 seasons (production's answer, never back, also
  reported); (ii) new episodes calibrated: each code group (ir / ir_return / pup / other) x k-bucket (1-2 / 3-4 / 5-8)
  with n >= 150 within 5 points; (iii) existing in-season episodes not worse: Brier CI upper < +0.002.
- **RESULT {#opened-out} (AX) season-start reserve players in the shared return models: FAIL ((ii), (iii)), not
  shipped.** tools/opened_out_eval.py, 2022-25, 460 opened-out episodes (19,879 state x k rows). (i) PASS: Brier 0.0701
  vs per-code base rate 0.0860, -0.0158 [-0.0216, -0.0106], 3 of 4 seasons (production's "never back" 0.1041).
  (ii) FAIL: R48 (IR, designated to return) over by 22-29 points (actual 17 / 34 / 55% by k 1-2 / 3-4 / 5-8; the base
  rate was as far off), PUP under by up to 14, other reserve lists under by up to 11; IR (R01, the direct model) within
  3. (iii) FAIL: in-season episodes 0.1180 -> 0.1190, +0.0010 [-0.0014, +0.0033] (the shared models moved). Descriptive
  (scratch, after the result): roster codes exist from 2021 only (2019-20 week-1 reserve players coded A01); a week-1
  R48 exists from 2024 only (15 cases: 88% / 71% back); R01 back that season 36 -> 10% 2021 -> 2025, 33% with 8+ games
  the season before vs 13%.
- **PRE-REGISTERED 2026-10-18, a second look at (AX) after its gate failed (labelled: weaker evidence than a first
  test; one look only, a FAIL closes (AX) until new information).** (AX2) a dedicated direct model for opened-out
  episodes: return_timing's model (its features + prior_g), trained only on opened-out episodes from 2021 on (codes
  exist), walk-forward; the chain and the IR model untouched (trained without those episodes, production features), so
  in-season predictions are identical by construction ((iii) reported, must be exactly 0). Same tool (--dedicated),
  same rows, GATE (i) and (ii) as (AX).
- **RESULT {#opened-out-2} (AX2) a dedicated direct model for opened-out episodes: FAIL ((i), (ii)); (AX) closed.**
  (i) Brier 0.0868 vs base rate 0.0862, +0.0006 [-0.0071, +0.0089] (better in 2 of 4 seasons); (ii) R48 over by 10 /
  13 points (k 1-2 / 3-4), PUP under by 12 at k 5-8, other reserve lists under by 8; IR within 3. (iii) 0 by
  construction. Reading: ~460 episodes in four test seasons, codes only from 2021 and their meaning drifting (a week-1
  R48 from 2024; R01 return rate 36 -> 10%) is too little to learn a calibrated timeline. Neither model nor the base
  rate is calibrated; production's answer (never back, Brier 0.104) is the worst of all three. Code kept, off
  (injuries.opened_out; ReturnModel(opened_out=)). OWNER DECISION pending (2026-10-18): keep "never back", or a
  labelled rule (not a fitted model) for these players, e.g. the IR minimum + ESPN's return date, or their 2024-25
  rates by code.
- **PRE-REGISTERED 2026-10-18 (owner: "our injury model is still broken especially relating to game time decisions
  that end up inactive. look at tyler warren"): (AY) a last-day downgrade in the practice model.** Week 6: Tyler
  Warren (Q, Full / Full / Limited) 84% -> inactive; Quinshon Judkins (Q, DDL) 78% and Sean Tucker (Q, DLL) 71% ->
  inactive. Descriptive 2018-25 (data.avail_hist): Questionable players played 69.4% (n 8,303); a downgrade on the last
  practice day (its score below the day before) 57.2% (n 449); FFL 53% (n 38). The practice model sees the first and
  last days and their difference (trend), not a drop on the final day. Variant: two more inputs, last_change (last day's
  score minus the day before's; 0 with one day) and downgraded (last_change < 0). Test: tools/downgrade_eval.py,
  production's features (practice + role + rest) and settings, walk-forward 2021-25 (season s trained on seasons
  before), labelled weeks not ruled Out. GATE: downgrade rows Brier lower, 95% CI over season-weeks excluding 0, and
  their mean prediction within 5 points of the actual rate; all rows not worse (CI upper < +0.0005).
- **RESULT {#last-day-downgrade} (AY) a last-day downgrade in the practice model: FAIL (production is already calibrated
  there).** tools/downgrade_eval.py, 2021-25, 486 downgrade rows of 16,596: played 62.6%, production 63.7%, variant
  63.8%; Brier -0.0015 [-0.0039, +0.0010]; Questionable downgrades 303: played 57.8%, production 57.8%. All rows -0.00017
  [-0.00034, +0.00001]. Warren was not a downgrade: his report was Friday only, "L" (the site pads the days before his
  first listing with F, {#off-report}), i.e. a late addition. Walk-forward production on Questionable players: all 5,596
  played 70.8%, predicted 69.9%; listed one day only 430: 64.7% vs 68.3%; Friday-only "L" 221: 63.3% vs 71.5% (its
  0.8-0.9 band: 13 rows, 61.5% vs 85.0%; Warren 84%).
- **PRE-REGISTERED 2026-10-18, a new hypothesis from (AY)'s check: (AZ) late additions.** A player first listed on his
  team's last report day of a full report week is a new injury; the model sees "one day listed" (n_days) but not
  whether his team held a full week of reports. Variant: late_add = listed on one day only while his team listed
  someone on 3+ days that week; added to production's features. Test: tools/downgrade_eval.py --late, same harness.
  GATE: late-add rows Brier lower (95% CI over season-weeks excluding 0) and their mean prediction within 5 points of
  the actual rate; all rows not worse (CI upper < +0.0005).
- **RESULT {#late-add} (AZ) late additions: FAIL (no miscalibration to fix).** 1,967 late-add rows (listed one day
  while the team listed someone 3+ days): played 81.8%, production 80.3%, variant 80.4%; Brier -0.0001 [-0.0004,
  +0.0003]; the Questionable ones (423): played 64.8%, production 68.3% (within noise). All rows -0.00015 [-0.00026,
  -0.00004]. Reading for the owner's question: the practice model is calibrated on game-time decisions (Questionable:
  70.8% played, 69.9% predicted); Warren's 84% sat near the top of a group that plays ~65%, and the game-day ruling
  (AU) set him to 0 at the inactives deadline as designed.
- **PRE-REGISTERED 2026-10-19 (owner: "it's monday now. we don't modify power rankings until tuesday right? why?"):
  (BA) refit the team ratings once Sunday's games are in, not at the Tuesday rollover.** Today the ratings (and with
  them Power's rank, the model's win chances, playoff odds, rest-of-season projections) are fit on games before the
  week the site shows (TeamModel.fit(season, week): plays with week < target), so week N's results wait for the 06:00
  ET Tuesday rollover, ~36 hours after Sunday's games. Only injuries / starting QBs move Power in between. Variant:
  from Monday morning, fit on every game of week N whose play-by-play has landed except that week's Monday game(s)
  (Thursday, Saturday, Sunday incl. SNF), with Elo updated through the same games; the page stays week N. Test
  (tools/monday_refit_eval.py, to write; needs a game cutoff in TeamModel.fit / weights), walk-forward 2021-25,
  N = 2..17, three arms on identical rows: stale (production on Monday: weeks < N), monday (the variant), tuesday
  (weeks <= N: today's post-rollover fit, a reference, not gated). Prediction: the model-only win chance (power-rank
  gap + Elo + home, config report.win_model), ranks from each arm's net ratings with each team's usual starter (the
  backtest has no injury plan). Scored: week N+1's games (what Monday's Power and Matchups inform); week N's Monday
  games (the variant moves their win chance mid-week: both teams' opponents are refit, their own games are not).
  Metric: Brier, paired by game, 95% CI from a bootstrap over season-weeks.
  GATE: (1) week N+1, monday vs stale: Brier lower, CI excluding 0; (2) week N's Monday games, monday vs stale: CI
  upper below +0.01 (small n, ~120 games: a guard against harm, not a test of gain). Reported, not gated: weeks
  N+1..N+4; monday vs tuesday (the cost of leaving out the Monday game); N+1 games involving a Monday-night team vs
  not (mixed-vintage ratings: two teams' ratings a game behind). Expectation written down: (1) should pass (more
  data); the gate's real work is (2) and catching a bias from the half-life weights treating a partial week N as a
  full one. Ship if PASS: a build after the last Sunday game's play-by-play lands refits as above (the news watcher's
  clock gets the event); Power and Matchups say "Ratings include games through Sunday; <Monday teams> update
  Tuesday"; the rest-of-season schedule drops the games already played; the week-by-week history keeps one point per
  week, written at the rollover as now.
- **RESULT {#monday-refit} (BA) refit the team ratings once Sunday's games are in: FAIL, not shipped.**
  tools/monday_refit_eval.py, walk-forward 2021-25, N = 2..17 (TeamModel.fit gained `exclude`, game_ids left out;
  production never passes it). Week N+1 (1,196 games): Brier stale 0.2223, monday 0.2221, tuesday 0.2215; monday -
  stale -0.0001 [-0.0035, +0.0030]: gate (1) FAIL. By season +0.0007 / -0.0042 / +0.0027 / +0.0000 / +0.0001. Week N's
  Monday games (95): 0.2509 -> 0.2486, -0.0023 [-0.0056, +0.0011]: gate (2) PASS. Reported, not gated: N+2 -0.0040
  [-0.0065, -0.0017], N+3 -0.0031 [-0.0057, -0.0005], N+4 -0.0002 [-0.0031, +0.0027]; monday vs tuesday within
  +0.0007 at every horizon (leaving out the Monday game costs nothing measurable); N+1 games with a Monday-night team
  -0.0003, without -0.0001 (no mixed-vintage harm). Not a bug: the arms' N+1 win chances differ by 4.4 points on
  average (0.8 monday vs tuesday). Reading: even the full Tuesday refit beats stale on N+1 by only 0.0008, well inside
  this test's reach (~0.003), so a week of results moves next week's win chance a lot but its accuracy too little to
  measure. The N+2 / N+3 gains are post hoc (week N+1's games are on the site by Tuesday, refit). Kept: the Tuesday
  rollover; the display question (Power showing Sunday's results on Monday) is the owner's, not an accuracy case.
- **Owner decision 2026-10-19 on (BA): ship the Monday refit into the model (owner-design rule).** "i'd like them to
  update and feel current on mondays, but i don't want to recklessly force it into our model" -> after the gates were
  explained (no gain, guard passed): "feels like we can justify just using the normal model". One set of numbers
  (a display-only copy would have left Power's rank and the win chances disagreeing). Built: team_model.sunday_refit
  (every game through the week's last Sunday final with its plays in, all or nothing; the Monday game(s) excluded);
  TeamModel.set_live, set by run.py after training only, makes fit(season, week) the week + 1 fit minus the Monday
  game(s); Elo the same (elo.ratings_before `also`; playoff_odds reads index.json "refit"); records count every
  finished game on the live page; Power says "Updated with this week's games through Sunday"; tools/news_watch.py
  starts a build when nflverse republishes the play-by-play after the week's Sunday games are final. Thursday games
  wait for Sunday's (a midweek refit would move the weekend's projections before lineups lock: untested). To watch on
  the first live Mondays: how far the Monday-night players' projections move (not covered by the gate).
- **PRE-REGISTERED 2026-10-19 (owner, on the Ravens' "this week +0.5": "that lamar is 0.5 team epa better than
  huntley?"): (BB) is the quarterback swing too small?** The live fit rates Lamar Jackson +0.037 EPA/dropback (+1.1
  pts/game at 37.7 dropbacks x 0.743 pts/EPA) and Tyler Huntley -0.004 (-0.1): Lamar -> Huntley moves the Ravens ~1.2
  pts/game, where the market typically moves several. Josh Allen +1.6, Burrow +0.7, Hurts -0.6; Tanner McKee -6.5,
  nearly all the inexperienced term. Suspected causes: (1) QB effects are ridge-shrunk hard (qb_alpha_grid picks 300,
  tuned by time-split CV on play EPA, never on starter changes), so the team pass coefficient keeps the starter's
  quality when he sits; (2) the QB term covers dropbacks only: designed QB runs sit in the team rush unit and stay
  with the team. Prior evidence, none of it a test of this: removing QB effects changed game margin MAE +0.011
  [-0.075, +0.096] (they add almost nothing at their size); experienced backups starting are overrated +2.15 [-0.56,
  +4.78] (Vegas +0.55, n 90; finding 2026-10-16); new arrivals +6.07; usual starter returning +1.48 [-1.76, +4.83].
  Test (tools/game_eval.py, corrected harness: each game rates its actual starter; walk-forward 2021-25, each season
  tuned and trained on the two before; --save for paired rows; a new tools/qb_swing_eval.py scores them).
  Rows: "QB-change team-games" = the game's starter (most dropbacks) is not the team's usual starter (most starts this
  season before that week), plus the usual starter's first game back after missing one or more; every other
  team-game is "same QB". Arms: base (production); a100 and a30 (team_model.qb_alpha_grid fixed at [100] / [30]:
  less QB shrinkage; team penalties still tuned); qbrun (new, behind config team_model.qb_rush_effects: a QB term in
  the rush unit on designed QB runs, same penalty as the pass unit's, applied to the game's starter); reported only:
  qbrun with the better of a100 / a30.
  Diagnosis first (reported, sets nothing): base's signed gap to the market on QB-change rows from the changed team's
  side (model margin - Vegas closing margin; + = we rate them better than the market), by kind (backup in, starter
  back, new arrival, inexperienced), next to the same on same-QB rows.
  GATE, each arm vs base, paired by game, 95% CI from a bootstrap over season-weeks: (1) on QB-change rows the mean
  |model margin - Vegas margin| is lower, CI excluding 0 (the market's line is a far less noisy yardstick than one
  game's score, and the quantity in question is the size of the swing); (2) on QB-change rows the margin MAE against
  actual results is not worse (CI upper < +0.10), and on all games not worse (CI upper < +0.02), so an arm can't pass
  by copying the market while missing results; (3) fantasy MAE, all relevant players (tools/experiments.py
  2021-2025), not worse (CI upper < +0.005). Ship: an arm passing all three (two passing: the lower QB-change gap to
  Vegas). Reported, not gated: the implied Lamar -> Huntley swing and the five largest live QB swings under each arm;
  win-chance Brier on QB-change games (tools/win_rank_eval.py basis).
- **RESULT {#qb-swing} (BB) is the quarterback swing too small?: premise CONFIRMED; a100 / a30 FAIL; qbrun passed
  by a negligible margin and is NOT shipped (owner: "skip").** tools/game_eval.py + tools/qb_swing_eval.py, 1,279
  games 2021-25 (527 QB-change games). Diagnosis (base, model - Vegas margin from the team's side): same QB -0.38
  [-0.50, -0.27] (n 1,937); backup in +1.73 [+1.22, +2.23] (199); new arrival +2.61 [+2.01, +3.25] (188);
  inexperienced -0.55 [-1.27, +0.17] (160); starter back -0.25 [-1.23, +0.80] (74): teams starting an experienced
  backup or a new arrival are rated well above the market; the inexperienced term is about right. a100: (1) +0.022
  [-0.068, +0.110] FAIL, (2) QB-change MAE +0.084 [+0.000, +0.171] FAIL, all games -0.002; backup-in gap 1.73 -> 1.84.
  a30: (1) -0.026 [-0.168, +0.119] FAIL, (2) +0.142 [-0.009, +0.292] FAIL, all +0.024 [-0.065, +0.113] FAIL;
  backup-in gap 1.69. So QB shrinkage is not why backups read too good. qbrun: (1) -0.001 [-0.002, -0.000], (2)
  -0.001, all -0.001, fantasy ALL -0.000 [-0.000, +0.000]: every gate passed by about a thousandth of a point (designed
  QB runs are ~5% of designed runs; Lamar +0.008 EPA/run). Not shipped: the gate had no minimum effect size (my error;
  future gates state one), and shipping means plumbing a term into Power / Matchups for no visible change; the code
  stays behind team_model.qb_rush_effects (off). Fantasy: a100 ALL -0.001 [-0.001, +0.000], a30 -0.001 [-0.002,
  -0.000]. Lead: the error sits in how a non-usual starter is rated (few, scattered, shrunk-to-average plays), not in
  the usual starter's rating.
- **Finding 2026-10-19 (owner: "our model might not take qb quality seriously enough? a team sucks if their qb sucks,
  and a team is good if their qb is a baller"), exploratory, run after (BB)'s results: the game model underweights
  quarterback quality.** Usual-starter team-games 2021-25 from (BB)'s base predictions, QB quality = his EPA/dropback
  on every earlier dropback in the data, shrunk with 200 pseudo-dropbacks at the league mean. By quintile, model -
  Vegas / model - actual from the team's side: bottom +1.62 / +1.80, 20-40 +1.00 / +0.55, 40-60 -0.75 / -1.42, 60-80
  -1.17 / -1.46, top -2.59 [-2.96, -2.22] / -2.96 [-4.12, -1.80]. Regression on 1,504 team-games, holding the model's
  own margin: each 0.1 EPA/dropback of QB edge over the opponent's QB (sd 0.122) = +2.10 pts [+1.34, +2.91] of actual
  margin the model misses (Vegas sees +2.26 [+2.03, +2.49]); the model's margin itself is not compressed against
  results (-0.059 [-0.317, +0.187]). Reading: the market prices a QB's track record and we don't; the team ratings
  see recent plays (half-life 3 weeks, last season gone by week 8), QB terms shrunk toward 0, so a stable, long-run
  skill is mostly discarded, which also fits backups reading too well ((BB)). Exploratory: chosen after seeing
  (BB), on the same games; (BC) tests a fix and checks 2026 as data this finding never saw.
- **PRE-REGISTERED 2026-10-19: (BC) give the model each quarterback's track record.** Career quality q = EPA per
  dropback on his dropbacks before the game (every season in the data), shrunk with K = 200 pseudo-dropbacks at the
  league mean (the finding's measure; K = 100 and 400 reported). Arms, each behind config (off = production):
  qbprior (team_model.qb_prior_scale): the pass unit's QB effects are shrunk toward lambda x (q - league) instead of
  toward 0, q from dropbacks BEFORE the current season (no double counting of the plays the fit sees); lambda tuned
  by the existing time-split CV over {0, 0.25, 0.5, 0.75, 1} jointly with the QB penalty. qbedge (game_model
  qb_career_edge): a points-formula input, own q - opponent's q (as of before the game, current season included),
  coefficient fit by least squares on the training seasons like the formula's other inputs.
  Test: tools/game_eval.py 2021-25 (corrected harness), --save per arm, scored by tools/qb_swing_eval.py (extended
  with the gates below); fantasy tools/experiments.py 2021-2025. 2026 weeks 2-6 scored the same way and reported as
  the out-of-sample check.
  GATE, each arm vs base, paired, 95% CI from a bootstrap over season-weeks: (1) all games margin MAE against actual
  results lower, CI upper < 0, and the mean improvement at least 0.05 points (minimum effect, after (BB)); (2) on
  QB-change games, |model margin - Vegas margin| lower, CI upper < 0; (3) fantasy MAE, all relevant players, not
  worse (CI upper < +0.005). Ship: an arm passing all three; both passing: the larger all-games improvement. If one
  ships, Power, Matchups and the playoff odds use it too (the QB term is how Power's "this week" and rest-of-season
  ratings move with the starter). Reported, not gated: the finding's QB-edge slope re-run on each arm (should move
  toward 0); the (BB) diagnosis by kind; the live Lamar -> Huntley swing; 2026 weeks 2-6.
- **AMENDMENT to (BC), 2026-10-19, before any result was seen (runs had started; no output read).** Owner: "we want to
  be more accurate as a prediction model, using vegas as a comparison, not a strict 'closer to'". Gate (2) rewarded
  agreeing with the market for its own sake; it becomes: (2) on QB-change games, margin MAE against actual results
  not worse than base (CI upper < +0.10), the games where a wrong QB value would hurt most. |model - Vegas| on
  QB-change games moves to reported, not gated. Gates (1) and (3) unchanged. Standing rule from here: gates score
  accuracy on outcomes; the market is a benchmark and a diagnostic, never a pass condition.
- **Scan 2026-10-19 (owner, Monday night after week 6: "scan [key injuries] manually and report back").** Against
  the live site: Davante Adams (ruptured hamstring Sunday, procedure, ESPN return Nov 25) read 100% every later week;
  Romeo Doubs (IR Monday, return Nov 29) 100% (the rollover's IR path should catch him); Deebo Samuel (ESPN return
  Nov 8, ~week 10) 75% by week 9; Terry McLaurin's week-6 card read 0% to play for a game he started (an ESPN Out
  posted mid-game: fixed, rulings posted after a team's kickoff no longer apply to that game). Cause of the first and
  third: ESPN's estimated return date reaches the current week (bridge / midweek buckets), newly placed IR (floor) and
  IR players (return_timing.py), but not the return chain every other injured player's later weeks come from, though
  ESPN's dates run late, not early (median 14 days; INSIGHTS bridge entry). Waivers run Wednesday ~03:00 ET, so
  Monday / Tuesday rest-of-season values are the ones people act on.
- **PRE-REGISTERED 2026-10-19 (owner: "at your discretion"): (BD) ESPN's estimated return date in the return chain.**
  Variant: the chain's hazard (returns.ReturnModel, CHAIN_FEATURES) gains espn_wk (weeks from his team's next game to
  ESPN's return date, from the latest capture between the game he just missed and that next game: return_timing.enrich,
  the IR model's own feature), espn_has, espn_out (ESPN status Out); as the chain steps to his team's following game
  espn_wk drops by that gap / 7 (the date is fixed). No capture = missing (seasons before 2022; the model handles it).
  Test: tools/return_espn_eval.py, the harness of tools/return_days_eval.py: every return-model state, walk-forward
  2022-25 (each season fit on the seasons before), label = played his team's k-th game after it, k = 1..6; 2026 so far
  as CONFIRM. GATE: (1) states with an ESPN capture, Brier over k = 1..6 pooled: lower, 95% CI over 2,000 player-state
  resamples with upper < 0, improvement at least 0.003 (minimum effect), lower in >= 3 of 4 seasons; (2) all states,
  k = 1..6: not worse (CI upper < +0.0005); (3) calibration error (10 bins, k = 1, states with a capture) not above
  today's + 0.005; CONFIRM 2026 same direction. Ship: the live chain uses it for players already out and for newly
  injured ones (their state gets the live feed's date), so lookahead weeks, rest of season, Fantasy values and Power C
  all move. Reported, not gated: states whose ESPN date is 14+ days past the next game (the Adams case); a rule arm
  (no game before ESPN's date when it is 14+ days past the next game and ESPN says Out) on the same rows; IR / PUP
  states apart (return_timing.py already reads ESPN).
- **RESULT {#return-espn} (BD) ESPN's estimated return date in the return chain: FAIL, not shipped.**
  tools/return_espn_eval.py, walk-forward 2022-25, 12,754 states (7,450 with an ESPN capture; by season 2,747 / 2,316 /
  2,305 / 82: the Wayback backfill is thin for 2025). Harness note (mechanical, set after the first run crashed with no
  output read): columns with no data in a training window drop out, as return_timing.fit does, so the 2022 test
  season, trained on 2019-21 with no captures, equals today's chain. (1) states with a capture, k = 1-6: Brier .1621
  -> .1632, +0.0011 [-0.0006, +0.0026], better 2 of 4 (2022 equal; 2023 +.0068, trained on one season of captures;
  2024 -.0029; 2025 -.0091): FAIL. (2) all states +0.0004 [-0.0005, +0.0013]: pass. (3) calibration .0215 -> .0179:
  pass. CONFIRM 2026 (94 states with a capture) -0.0806. Reported, the Adams case (ESPN Out, date 14+ days past the
  next game; 31 states): played 32.2% of the next six games, today 50.9%, variant 19.7%, rule (no game before ESPN's
  date) 24.6%; Brier .2221 -> variant .1530 (-0.069 [-0.169, +0.019]), rule .1160 (-0.106 [-0.189, -0.037]). IR / PUP
  states +0.0022 [+0.0003, +0.0042] (return_timing.py already reads ESPN). Reading: as a learned input the date needs
  more seasons of captures than exist; where it is long, today's chain is badly optimistic and a plain rule fixes
  most of it, but on 31 cases and as a reported arm, so it is a lead, not a result.
- **RESULT {#qb-track} (BC) give the model each quarterback's track record: qbedge PASSED all three gates but is NOT
  adopted yet (it does not hold on 2026 and fades by season: owner's call); qbprior FAIL.** tools/game_eval.py 2021-26 +
  tools/qb_swing_eval.py --bc (amended gate 2), 1,279 games 2021-25 (527 QB-change). qbedge: (1) all games margin MAE
  10.435 -> 10.291, -0.144 [-0.281, -0.013] (>= 0.05): PASS; (2) QB-change games -0.206 [-0.473, +0.050]: PASS; (3)
  fantasy ALL +0.000 (the backtests use Vegas lines, so the points formula never reaches projections): PASS. By season
  -0.364 / -0.189 / -0.155 / -0.121 / +0.108 (2021-25); 2026 so far (77 games) +0.061 [-0.435, +0.593]. QB-edge slope
  +2.20 -> +0.19 [-0.85, +1.23] (the bias is gone); gap to Vegas, backup in 1.73 -> 0.82, new arrival 2.61 -> 1.33,
  same QB -0.38 -> -0.14; QB-change |model - Vegas| 4.05 -> 3.43 (reported). qbprior (lambda tuned per season: 0.25 /
  0.75 / 1.0, QB penalty moving with it): (1) -0.057 [-0.141, +0.024] FAIL; (2) -0.132 pass; fantasy ALL +0.000; slope
  +1.62. Not adopted under the owner's rule (clean passes are adopted when they also hold on the current season):
  2026 runs the wrong way (within noise) and the gain shrinks every season to a loss in 2025, unexplained.
- **Owner decision 2026-10-19 on (BD)'s lead: ESPN's long return dates as a rule (owner-design; not a test pass).** "it
  seems like taking espn expected return dates seriously makes a whole lot of sense so do it." returns.espn_out_long:
  a player ESPN lists Out (not injured reserve: those already have the IR floor / IR model) with an estimated return
  date at least 14 days past his team's next unplayed game gets 0 for every game before that date in the lookahead
  chain (lookahead weeks, rest of season, Fantasy values, Power C); the current week keeps the injury model's own number;
  after the date, the chain. Evidence on record: (BD)'s reported rule arm, 31 cases 2022-25, played 32% of the next six
  games vs the chain's 51%, Brier .2221 -> .1160 (-0.106 [-0.189, -0.037]); ESPN dates run late (median 14 days).
  Checked on live data: Deebo Samuel (Out, Nov 8) week 7 0%, week 9 on the chain (that game is on the date itself);
  Davante Adams as of the week 7 rollover: weeks 8-10 0%, week 12 69%. To check at season end on 2026's own cases
  (daily ESPN snapshots since 2026-10-13): played share before / after ESPN's date for players the rule touched.
- **Decision 2026-10-19 on (BC) qbedge (owner: "the qb thing, you choose"): ADOPTED.** Before deciding, an exploratory
  look at the fade (scratch/qb_fade.py; not pre-registered): the base model's QB-edge miss by season, per 0.1 EPA/db,
  2021-26: +2.80 / +1.78 / +3.80 / +2.40 / +0.67 / +1.48 (career measure; a recent-two-seasons measure gives the same
  shape), qbedge: +1.35 / -0.62 / +2.76 / +0.49 / -3.35 / -0.37. The model underrates QB quality every season; 2025 was
  the season it did least, and a fixed correction overshot there; qbedge's six-season average residual is ~0. So the
  fade is one season's small bias, not a stale track record. Shipped: config game_model.qb_career_edge = true (points
  formula, fitted weight 10-15 points per team per 1.0 EPA/db across 2021-26); report.qb_value adds 2 x weight x his
  track record above the league, per dropback, to Power's pass offense, its rest-of-season blend (usual / backup by
  pbar) and schedule strength, so Power's ranks, Matchups' model win chance and the playoff odds move with it. The
  Matchups battle bars stay pure EPA per 100 plays (owner rule: explanations in EPA/100). Pending check: 2026's games
  at season end, margin MAE base vs adopted.
- **Descriptive 2026-10-20 (owner questions, before (BE) / (BF)).** (a) Snap share after an absence, established RB / WR
  / TE (50%+ of snaps over the 4 games before), 2019-25, relative to before: after a bye 0.94 / 0.93 / 0.93 / 0.92 in
  return games 1-4 (n 1,841); 3-5 weeks 0.80 / 0.87 / 0.87 / 0.87 (306); 6-10 weeks 0.71 / 0.78 / 0.82 / 0.84 (107);
  11-16 weeks 0.63 / 0.71 / 0.65 / 0.64 (50); a lost season or more 0.66 / 0.73 / 0.78 / 0.72 (27): long absences come
  back on a snap count, and part of the role doesn't return (scratch/return_snaps.py). (b) Ruling timing: day-1 DNP
  played 42.6% (5,168), by final status Out 0.6% / Doubtful 1.9% / Questionable 59.6% / none 81.1%; DNP all week with
  no status 70%. ESPN Out first seen (2022-25 captures, normal weeks): game day 17% played (65), Monday 29% (2,083),
  Tuesday 22% (215), Wednesday-Saturday 0 of 71; still Out at the last capture 20% vs changed 45% (scratch/
  ruling_timing.py; the archive is mostly Monday / Tuesday snapshots). (c) Practice report days 2026: Sunday-game teams
  Wed / Thu / Fri (160 each, Mon / Tue / Sat 1 each), Thursday-game teams Mon / Tue / Wed (10 / 12 / 12), Monday-game
  teams Thu / Fri / Sat.
- **PRE-REGISTERED 2026-10-20 (owner: "shouldn't we treat active players in the nfl as players that might play, and
  their practice participation is the best signal ... are we treating their injury list status too importantly?"; "yea
  go ahead"): (BE) roster designation as an input, not a gate.** Today a reserve-list player is never a candidate
  (engine.candidates: ACT / INA only), the availability plan sets him to 0 this week, and the one week model never
  trains on him (tuesday.week_rows skips anyone on a reserve list at his previous game). Variant: a reserve-list player
  whose practice window is visibly open (stage 0: on his previous week's report; stages 1-3: on this week's) becomes a
  row and a live candidate, with inputs res_prev (on a list at his previous team game), res_code (designated to return /
  injured reserve / PUP / other, from the roster's status code) and res_weeks (consecutive team weeks on the list,
  capped 17); every other row gets 0s. The same model and calibration rate everyone. Live: returns.window_open
  candidates (branch wip/window-open), the plan no longer zeroes them; the lookahead state for opened-out players stays
  as built there. Test: tools/reserve_avail_eval.py, rows of tools/week_avail_eval.py, walk-forward 2021-25 (week_model:
  season s trained on seasons before, calibrated on s-1), 2026 so far CONFIRM. GATE: (1) reserve-window rows, Brier vs
  today's 0 (they are off the board): lower, 95% CI over season-weeks with upper < 0, improvement >= 0.01; (2) every
  other row, variant model vs today's model: not worse (CI upper < +0.0005); (3) calibration on reserve-window rows at
  stages 1 and 3: mean predicted within 3 points of the played rate, each; CONFIRM 2026 same direction on (1).
  Reported: played rate and prediction by res_code x final status; Jeremy McNichols / Tank Dell type rows (window open,
  full practice, no status). Ship: (BE) live as above.
- **RESULT {#reserve-avail} (BE) roster designation as an input, not a gate: FAIL (gate 3 at stage 1), large gains.**
  tools/reserve_avail_eval.py, 2021-25: 3,353 reserve-window rows (839 players), played 39.9%. (1) Brier vs today's 0
  .3993 -> .1861, -0.2132 [-0.2491, -0.1789]: PASS. (2) other rows .1172 -> .1170, -0.0002 [-0.0006, +0.0002]: PASS.
  (3) stage 3 predicted 63.8% vs played 63.9%: pass; stage 1 53.9% vs 45.5%: FAIL (stage 0 17.9 / 18.6; stage 2 54.4 /
  45.5). CONFIRM 2026: .3607 -> .1856. Stage 3 by list x status (played / predicted): designated to return,
  Questionable 53.6 / 59.2% (192), none 69.6 / 65.7% (56); IR, Questionable 68.0 / 65.4% (172), none 87.0 / 81.2% (46);
  PUP / NFI Questionable 59.6 / 61.9% (57); Doubtful 0 of 31 anywhere. Window open, no final status, practiced: 82.9%
  played, 80.2% predicted (146; Jeremy McNichols' 97% came from the active-roster model). Reading: midweek
  calibration is fit on the season before, ~95% active-roster rows, and its stage-1 map doesn't fit reserve players.
- **PRE-REGISTERED 2026-10-20, a second look at (BE) after gate 3 failed (labelled: weaker evidence than a first
  test): (BE2) reserve-aware calibration.** Same rows, harness and gates; one change: tuesday.week_model's per-stage
  isotonic calibration is fit separately for reserve rows (res_prev = 1) and other rows when the calibration season
  has at least 100 reserve rows at that stage, else pooled as before.
- **PRE-REGISTERED 2026-10-20 (owner: "we need a case for players that missed the entire last season ... more of a snap
  count"; Tank Dell projected 0.0): (BF) a role for players returning to an empty recent-usage window.** Today a
  player's usage shares come from a recency window that holds this season's games and last season's fading by week
  8, so his first game back after a lost season (Dell) or after missing this season's first half reads a share of 0
  and a projection near 0: 429 such first games back 2021-25 (300 mid-season returns, 129 after a lost season; 52 with
  half the snaps or more). Variant (experiments.return_role): when the recent window is empty and the long window
  (this and the two previous seasons, efficiency weights) is not, his shares = long-window shares x his position's
  first-game-back factor, fit on seasons before the target season (actual share in that game over the long-window
  share, ratio of sums; QB dropbacks, RB carries, WR / TE targets; < 15 cases -> pooled; fit on 2019-25 for 2026: QB
  0.80, RB 0.76, WR 0.67, TE 0.46). Test: tools/experiments.py baseline,return_role 2021-2025 (cached backtests) scored
  on (a) the touched rows (first game back with an empty recent window, played) and (b) all relevant rows.
  GATE: (1) touched rows, fantasy MAE lower, 95% CI over season-weeks with upper < 0, improvement >= 0.5 points; (2)
  all relevant rows not worse (CI upper < +0.003); (3) touched rows, mean projection within 1.5 points of mean actual.
  Reported: by position; mid-season returns vs lost-season returns.
- **RESULT {#reserve-avail-2} (BE2) reserve-aware calibration (second look, weaker evidence): FAIL (gate 3 at stage 3,
  by 0.4 points).** Same harness. (1) .3993 -> .1925, -0.2068 [-0.2397, -0.1766]: pass; (2) -0.0002 [-0.0005, +0.0002]:
  pass; (3) stage 1 44.4% predicted vs 45.5% played: pass; stage 3 60.5% vs 63.9% (3.4 points, bar 3): FAIL (stage 0
  13.6 / 18.6, stage 2 45.3 / 45.5). CONFIRM 2026 .3607 -> .1852. Window open, no status, practiced: 82.9% played,
  77.1% predicted. Both looks put every stage within 3-8 points of the truth on players the site rates 0% today (40%
  of them play); each misses one calibration bar. Owner decision pending: ship one as an owner-design rule, or not.
- **RESULT {#return-role} (BF) a role for players returning to an empty recent window: FAIL.** tools/experiments.py
  baseline,return_role 2021-25 + tools/return_role_eval.py (touched rows: baseline recent shares empty, stored as 0, and
  the variant filled them; first scorer pass matched none and was fixed before any numbers were read). 403 touched rows
  that played, mean actual 2.05 points: MAE 1.975 -> 2.428, +0.453 [+0.319, +0.587]: FAIL; mean projection 0.41 ->
  1.63 (gate 3 pass). All relevant rows +0.000 [-0.001, +0.002]. By kind: mid-season returns 352 (WR 121: actual 1.06,
  today 0.19, variant 1.60), lost-season returns 51 (WR 21: 0.51 / 0.03 / 1.03). Reading: the touched players are
  mostly depth players coming back to small roles, many scoring 0; a share of the old role over-projects them, and
  MAE favors the near-0 projection on such skewed rows. The established starter (Dell) is the rare case here; a
  version for players whose long-window role was large is a new hypothesis, to test on data this one hasn't seen.
- **Owner decision 2026-10-20: (BE2) shipped ("ship be2").** config injuries.reserve_rows = true: tuesday.week_rows /
  week_now_rows reserve=True (reserve inputs, reserve-aware calibration); returns.window_open players are this week's
  candidates (run.py extra_cands) and keep the model's chance in the plan; before his team's first report a
  window-open player is rated by the week model at stage 0 (was: ESPN's IR bucket, 0); the midweek ESPN IR rate (38%,
  built for active players newly placed on IR) no longer overrides them; opened-the-season-on-a-list players get a
  return state for the lookahead (returns._window_states). Live stage-0 rows now set on_now = 0 as the training rows do.
- **Owner decision 2026-10-20 (Vikings: week 5's page said 14th, week 6's arrow implied 15th): Power's history reads
  the archived pages.** tools/build_archive.py rebuilds the current season's pages whenever docs.code_fingerprint
  changes (archive.json "_model/<season>"); run.build_page passes the season's earlier pages (site_dir/<season>/week-NN.json)
  to report.team_tables, whose arrows (vs last week's page), rank trend and net trend read them. Checked locally: all
  32 teams' arrows and week-5 trend points equal the rebuilt week-5 page. Cost: ~5 min per model change in CI.
- **Queued (owner: "up to you"), a new hypothesis after (BF) failed: a role for returning STARTERS.** (BF)'s touched
  rows were mostly depth players; a version limited to players whose long-window role was large (Tank Dell's 14.8%
  target share) is to be pre-registered and judged on 2026's returns as they happen (data (BF) never saw), not on
  2021-25 again.
- **Rollover check 2026-10-20 (owner: "confirm the auto tuesday rollover worked"): it did.** The watcher started the
  build at 06:10 ET (rollover + 10 min); week 7 live; later builds as data landed (archived week 6 with all 14 finals
  incl. MNF by 14:26 UTC); week 7's Power arrows equal the archived week-6 page for all 32 teams. Players: Adams w7 5%,
  w8-10 0, w12 72% (long-date rule); Doubs IR 0 through w10, w12 73%; Deebo w7 5%, w9 65%; Lamar w7 35%. Gap seen:
  Terry McLaurin (knee, left MNF, ESPN Out to Nov 1) reads 100% for week 8: Washington is on bye in week 7, so he is on
  no board this week and nothing starts his chain (status board item (AY), Hockenson / Tank Hudson).
- **PRE-REGISTERED 2026-10-20 (owner: "yes"): (BG) injured right before a bye.** During his team's bye week a player
  is on no board (engine candidates are this week's playing teams), so ESPN's post-game status never reaches him and
  the lookahead reads him healthy for his next game and every one after. Variant: for a team on bye this week, a QB /
  RB / WR / TE whose ESPN status (Out / Doubtful / Questionable / IR) was updated after his last game gets a newly-
  injured state starting at his next game (returns._newly_injured bye_start), that game's chance = the bye rate for his
  ESPN bucket (Out with a return date 7+ days past that game / Out / Doubtful / Questionable), then the chain. The bye
  rates are measured on bye-week cases from seasons before (2022-25 ESPN captures: the latest capture between his last
  game and 4 days before his next game; label = played his next game), shrunk toward the normal-week bridge rate with 10
  pseudo-cases. IR keeps its floor (espn_ir). Test: tools/bye_injury_eval.py, rows = those players 2022-25, walk-
  forward by season (rates from earlier seasons; 2022 uses the normal-week rates). GATE: (1) Brier for his next game vs
  today's 1.0: lower, 95% CI over team-byes with upper < 0, improvement >= 0.01; (2) calibration: mean predicted within 5
  points of the played rate; reported: per bucket played rate before a bye vs in a normal week.
- **RESULT {#bye-injury} (BG) injured right before a bye: FAIL (calibration), and too thin to decide the case that
  matters.** tools/bye_injury_eval.py: 783 player-games 2022-25 with an ESPN status between the last game and 4 days
  before the next (window rule), 49 right after a bye (37 team-byes): Questionable 46 (played 54.3%; normal weeks
  43.6% of 645), Out 2 (0 played; normal 10.3% of 39), Doubtful 1 (0; normal 3.2%). (1) Brier vs today's 1.0 .4898 ->
  .2779, -0.2119 [-0.4001, -0.0203]: pass. (2) predicted 37.6% vs played 51.0%: FAIL (the Questionable bye rate,
  shrunk toward the normal week's, under-predicts: a bye adds a week of recovery). The Wayback archive has almost no
  bye-week Out cases; 2026's daily snapshots will add them.
- **Owner decision 2026-10-20 on (BG): the bridge's rule for bye teams (consistency, not a test pass).** returns.bye_espn:
  a QB / RB / WR / TE on a team with no game this week whose ESPN status (Out / Doubtful) was updated after his last
  game gets, for his next game, the bridge's bucket (Out+ret against that next game, Out, Doubtful) and its learned rate
  (else the prior), via the newly-injured chain's bye_start; IR keeps its floor; Questionable stays display-only. Live
  as of week 7: Terry McLaurin (ESPN Doubtful) week 8 100% -> 4%, then 33 / 49%; Marcus Mariota (already on the chain)
  week 8 32%. Known lean: the normal-week rates are pessimistic before a bye (Questionable played 54% vs 44%); to
  measure on 2026's daily snapshots at season end.
- **PRE-REGISTERED 2026-10-20 (owner: "queue, run it"): (BH) a role for returning STARTERS.** (BF) filled every empty
  recent window (403 returns, mostly depth players) and lost on MAE. Variant (experiments.return_role = "starters"):
  the same fill (long-window shares x the walk-forward first-game-back factor by position) only for a player who was a
  starter in that long window, by rank among his last team's players at his position group: WR / TE top 3 by long
  target share, RB top 1 by long carry share, QB top 1 by long dropback share (ranks, not cutoffs). Data (BF) never
  saw: 2020 (history 9 seasons, so it trains on 2018-19) and 2026 weeks so far. tools/experiments.py
  baseline,return_starters 2020,2026; tools/return_role_eval.py --variant=return_starters --seasons=2020,2026.
  GATE: (1) touched rows (played), MAE lower, 95% CI over season-weeks with upper < 0, improvement >= 0.5 points;
  (2) all relevant rows not worse (CI upper < +0.003); (3) touched rows' mean projection within 1.5 points of the mean
  actual. Reported: by position; the touched players by name. Expected: few touched rows (a few dozen), so (1) may
  fail on width alone; that is a valid outcome.
- **RESULT {#return-starters} (BH) a role for returning starters: FAIL (too few cases).** tools/experiments.py
  baseline,return_starters 2020,2026 (history 9) + tools/return_role_eval.py --variant=return_starters (first attempt
  crashed on a corrupted cache/meta.json from parallel workers, fixed with atomic writes; no result was read). Touched
  rows that played: 9, all 2020 (the 2026 returners named at week 7, Aiyuk / Mixon / Carr / Amari Cooper / Diontae
  Johnson, haven't played yet): MAE 2.193 -> 1.669, -0.524 [-1.764, +1.140]: FAIL on width; all relevant rows +0.001
  [+0.000, +0.002]: pass (< +0.003); mean projection 0.01 -> 1.66 vs 2.20 actual: pass. The rank rule also caught
  short-stint quarterbacks (AJ McCarron, Joe Webb, Brandon Allen: top by dropbacks on their last team's window), so
  "starter" needs a better definition. Next: score the 2026 returners at season end (data that exists then), and
  define a starter by games started, not window rank.
- **PRE-REGISTERED 2026-10-20 (owner: "can we lean more into espn expected return date"; chose B and D): (BI) a return
  date on a Doubtful / Questionable listing.** Today ESPN's date counts only with Out / IR: an early-week Doubtful is the
  4.2% bucket, a Questionable changes nothing (display only). Variant: ESPN Doubtful or Questionable with a return date
  7+ days past his team's next game is the "Out+ret" bucket (1.8%), in the early-week bridge, midweek rulings and the bye
  rule. Test: tools/espn_date_status_eval.py, ESPN captures 2022-25 (return_timing.CAPTURES), the latest capture between
  his last game and his next (that game, played = took a snap). GATE: those rows (n >= 30) played at most 5%, 95%
  Wilson upper bound <= 10%. Reported: the same rows by status, and with the date 1-6 days past the game.
- **PRE-REGISTERED 2026-10-20: (BJ) return timing anchored on ESPN's date.** ESPN's dates run late (players back a
  median 14 days after). Today: no game before the date when it is 14+ days past his next game, else / after it the
  generic chain. Variant: for a state with an ESPN capture (Out / Doubtful / IR) the chain's per-game hazard is the
  measured P(back at this game | not yet back) by days from ESPN's date to the game (before it, 0-6, 7-13, 14-20, 21-34,
  35+), from earlier seasons only, shrunk toward the pooled rate with 20 pseudo-cases; no date = today's chain. Test:
  tools/return_espn_eval.py's harness (states 2023-25, each fit on seasons before; 2022 has no earlier captures), base
  = production (chain + the long-date rule), label = played his team's k-th game after the state, k = 1..6; 2026 so far
  CONFIRM. GATE: (1) states with a capture, Brier over k = 1..6 lower, 95% CI (2,000 state resamples) upper < 0,
  improvement >= 0.003, lower in >= 2 of 3 seasons; (2) all states not worse (CI upper < +0.0005); (3) calibration (k =
  1..6, states with a capture) not above today's + 0.005; CONFIRM same direction. Reported: the measured rates by bucket.
- **RESULT {#espn-date-status} (BI) a return date on a Doubtful / Questionable listing: FAIL (nothing to use).**
  tools/espn_date_status_eval.py, 2022-25 captures: 1 Doubtful / Questionable listing with a date 7+ days past the
  next game (he played); 4 with a date 1-6 days past (1 played). The live feed shows why: all 126 Doubtful /
  Questionable listings carry a return date, and it is the date of his team's next game (bye teams: Nov 1, week 8): a
  placeholder. On those listings ESPN's date carries no information beyond the status; nothing changes.
- **RESULT {#return-anchor} (BJ) return timing anchored on ESPN's date: FAIL.** tools/return_anchor_eval.py, 2023-25,
  9,294 states (3,251 with a dated Out / IR capture; 2025 only 82). Measured hazard by days from the date to the game
  (fit for 2025): before 0.00, 0-6 0.28, 7-13 0.07, 14-20 0.02, 21-34 0.01, 35+ 0.01. (1) dated states k = 1-6 Brier
  .1399 -> .1516, +0.0116 [+0.0060, +0.0171], worse all 3 seasons: FAIL; (2) all states +0.0040 [+0.0020, +0.0060]:
  FAIL; (3) calibration .0459 -> .0822: FAIL. Played vs predicted by game k (dated): k4 .31 / base .27 / variant .19,
  k6 .39 / .34 / .21: anchoring on one snapshot's date reads "still out past the date" as long-term, but ESPN moves
  the date and players come back. CONFIRM 2026 (50 dated states, daily snapshots): -0.2401, the opposite way: with
  fresh dates it may work. Lead, not a result: re-test at season end on 2026's daily snapshots alone (data this test
  never scored), where each build sees the date as of that day.
- **PRE-REGISTERED 2026-10-20 (owner: "so we can't test against vegas" / "sure"): (BK) projected final wins, ours vs
  the market.** Descriptive (reported, not gated: Vegas is a benchmark, nothing ships from it). 2021-25, checkpoints
  weeks 3 / 5 / 9 / 13 (before that week's games), 160 team-seasons each. Ours = production's playoff simulation
  (tools/playoff_odds.simulate: Power's ranks from this week's lineup + Elo + home, this week's Vegas lines for this
  week's games, 2,000 seasons) -> projected wins. MARKET = the same simulation with Power's ranks replaced by market
  ranks: per-team ratings fit by ridge least squares to every closing spread of the season so far through this week
  (spread = home rating - away rating + home field, neutral sites without it, weeks weighted by half-life 4 weeks,
  ridge 1.0), so only lines that existed then; Elo, the win model and this week's lines unchanged. CEILING (not a
  test: uses lines that did not exist yet) = wins so far + the vig-free closing-moneyline chance of every remaining
  game. Scored on final regular-season wins: mean absolute error and mean within-season Spearman; ours - market with
  a 95% CI over 2,000 team-season resamples. Hypothesis: ours ahead of the market early (weeks 3-5) is unlikely; within
  0.1 wins MAE of it would be a strong showing.
- **RESULT {#market-wins} (BK) projected final wins, ours vs the market: TIE.** tools/market_wins_eval.py, 2021-25, 160
  team-seasons per checkpoint. MAE (wins) ours / market / ceiling: week 3 2.10 / 2.08 / 1.51 (ours - market +0.012
  [-0.031, +0.054]); week 5 1.91 / 1.92 / 1.42 (-0.004 [-0.044, +0.036]); week 9 1.55 / 1.55 / 1.25 (-0.008 [-0.038,
  +0.021]); week 13 1.11 / 1.11 / 0.96 (+0.006 [-0.011, +0.024]). Spearman with final wins ours / market: .566 / .552,
  .692 / .677, .795 / .789, .877 / .875 (ours a hair higher at every checkpoint). By season MAE within 0.03 every year.
  Simple baselines (scratch descriptive run): pace 4.52 / 2.68 / 1.88 / 1.25, record + .500 2.38 / 2.18 / 1.81 / 1.31.
  Our ranks and the market's agree only .76-.80 (Spearman) at the same accuracy: different information. Lead, not a
  result: a blend of our ratings and the spread-fit market ratings (pre-register before testing). The ceiling's edge
  comes from lines set later (injuries and form known by then), not a fair comparison.
- **PRE-REGISTERED 2026-10-20 (owner: "worth testing more"): (BL) future-game win chances: our ranks vs market ranks
  vs both.** (BK) tied on season win totals, where luck swamps the signal; this scores every future game instead. For
  each season 2021-25 and as-of week w = 3..17 (before week w's games): our Power rank basis (net from this week's
  lineup, as the playoff simulation uses) and the market rank (tools/market_wins_eval.market_ratings: ridge fit to the
  season's closing spreads through week w). Rows = every regular-season game in weeks w+1 .. 18 (its own line not yet
  posted), label = home won (ties dropped). Arms, each a logistic regression fit walk-forward on seasons before (scored
  2022-25): OURS = home + our rank gap + Elo gap (production's future-game form, refit); MARKET = home + market rank
  gap + Elo gap; BLEND = home + both rank gaps + Elo gap. Also reported: each without Elo, and by horizon (1-4, 5-8, 9+
  weeks ahead). CI = 2,000 resamples of games (a game's rows from every as-of week move together). GATE for BLEND to
  replace OURS in the playoff odds / Power: Brier lower, CI upper < 0, improvement >= 0.002, lower in >= 3 of 4
  seasons; CONFIRM 2026 (games played so far) same direction. Because BLEND makes the market an input to our model,
  a pass goes to the owner before shipping. OURS vs MARKET: reported, not gated.
- **RESULT {#market-games} (BL) future-game win chances, our ranks vs market ranks vs both: FAIL (tie).**
  tools/market_games_eval.py, 2022-25, 893 games / 7,233 game x as-of rows. Brier ours .2314, market .2307, blend .2309;
  BLEND - OURS -0.0005 [-0.0024, +0.0014] (gate needs CI upper < 0 and <= -0.002): FAIL; better 3 of 4 seasons;
  CONFIRM 2026 (42 games) +0.0015, the wrong way. MARKET - OURS -0.0007 [-0.0042, +0.0028]: a tie. Without Elo: ours
  .2341, market .2325, blend .2314 (BLEND - OURS -0.0028 [-0.0054, +0.0001]): the ranks alone carry different
  information, but Elo already supplies most of what the market adds. By horizon (ours / market / blend): 1-4 weeks
  ahead .2279 / .2250 / .2262 (market ahead: spreads know current injuries and news); 5-8 .2314 / .2307 / .2304; 9+
  .2377 / .2410 / .2401 (ours ahead: the market over-reacts to the present). Blend weights (2022-25, reading only):
  our rank gap .0113, market .0168, Elo .263 per 100. Lead, not a result: the horizon split suggests the market's edge
  is short-term news that our injury handling (Power rank C, returns) partly covers already.
- **PRE-REGISTERED 2026-10-20 (owner: "try it"; clarified: market data may be a model input, the aim is to beat
  Vegas on outcomes): (BM) preseason win totals, ours vs Vegas vs both.** Vegas = the preseason over/under win total
  (data/history/preseason_win_totals.csv, tools/win_totals_build.py: Pro-Football-Reference via the Wayback Machine,
  2016-26). Ours = production's playoff simulation as of week 1 with NO Vegas lines (lines_weeks empty; Power's ranks
  from the week-1 lineup + Elo + home), projected wins, 2,000 seasons. Seasons 2021-25 (what the engine backtests),
  160 team-seasons. Outcome: final regular-season wins (ties = 0.5). Arms: VEGAS; OURS; MIX50 = the plain average (no
  fitting, the primary arm); MIXFIT = a + b x Vegas + c x ours, least squares fit walk-forward on earlier seasons
  (scored 2022-25). GATE ("beat Vegas"): MIX50 MAE lower than VEGAS by >= 0.05 wins with the 95% CI (2,000 team-season
  resamples) upper < 0, lower in >= 3 of 5 seasons. Reported: OURS vs VEGAS, MIXFIT vs VEGAS (2022-25), RMSE, and
  rank correlation with final wins.
- **RESULT {#preseason-wins} (BM) preseason win totals, ours vs Vegas vs both: FAIL (Vegas ahead, mix ties it).**
  tools/preseason_wins_eval.py, 2021-25, 160 team-seasons. MAE (wins) Vegas 2.247, ours 2.338, MIX50 2.241; RMSE 2.731
  / 2.851 / 2.722; rank corr with final wins .496 / .417 / .489. OURS - VEGAS +0.091 [-0.083, +0.261]; MIX50 - VEGAS
  -0.006 [-0.094, +0.079] (gate needs <= -0.05 and CI upper < 0): FAIL; better 3 of 5 seasons; MIXFIT (2022-25) -0.006
  [-0.069, +0.062]. Ours and Vegas agree .78 on order. Our biggest misses vs Vegas were rebuilding teams we rated as
  average (2021 HOU 8.1 vs Vegas 4.0, final 4; 2022 DEN 7.3 vs 10.5, final 5 was ours right); preseason is the model's
  weakest point (last season's play + this week-1 lineup, no offseason roster news). Within the noise of 160
  team-seasons; data/history/preseason_win_totals.csv also holds 2016-20 and 2026 for later tests.
- **PRE-REGISTERED 2026-10-20 (owner: "yes"): (BN) Vegas preseason win totals as an early-season prior.** (BM): before
  the season Vegas knows the offseason (departures, coaching, rebuilds) and we don't; (BK)/(BL): by midseason we tie
  or beat market-derived ratings. Test: the Matchups win chance for this week's game (report.win_model week_*: home +
  rank gap of this week's lineup + Elo gap). For every regular-season game 2021-26, as of its own week (Power's "This
  week" rank from tools/market_games_eval's engine path, Elo before the week), vt_gap = home team's preseason win total
  - away team's (data/history/preseason_win_totals.csv). Arms, logistic fit walk-forward on earlier seasons, scored
  2022-25: BASE = home + rank gap + Elo gap (production's form, refit the same way); PRIOR = BASE + vt_gap x [weeks 1-4]
  + vt_gap x [weeks 5-8] + vt_gap x [weeks 9+] (the data picks how fast it fades). Ties dropped. CI = 2,000 resamples of
  games. GATE: (1) weeks 1-8 Brier lower by >= 0.002 with the 95% CI upper < 0; (2) all weeks not worse (CI upper <
  +0.0005); (3) weeks 1-8 lower in >= 3 of 4 seasons; CONFIRM 2026 weeks 1-6 same direction. Reported: Vegas's own
  game-line Brier on the same games (the bar to beat), weeks 1-4 / 5-8 / 9+ separately, the fitted weights. A pass
  ships the term into week_* (fit on 2021-25) and the playoff simulation's future games by the game's band.
- **RESULT {#vegas-prior} (BN) Vegas preseason win totals as an early-season prior: FAIL.** tools/vegas_prior_eval.py,
  2022-25, 1,084 games. Brier base / prior / Vegas lines: weeks 1-4 .2340 / .2308 / .2253; 5-8 .2407 / .2403 / .2185;
  9+ .2150 / .2219 / .2010. (1) weeks 1-8 -0.0019 [-0.0085, +0.0049]: FAIL (short of -0.002, CI spans 0); (2) all weeks
  +0.0030 [-0.0008, +0.0067]: FAIL (weeks 9+ worse: 2022 was fit on 2021 alone, six weights on ~270 games); (3) weeks
  1-8 lower 3 of 4 seasons (2022 worse); CONFIRM 2026 weeks 1-6 (90 games) +0.0024, the wrong way. Weights fit 2021-25
  (reading only): win-total gap .114 per win in weeks 1-4, .134 in 5-8, .014 from 9: the preseason view keeps
  mattering through week 8, then is gone. The bigger finding is the bar: on this week's games Vegas's lines beat our
  win chance by ~.006 in weeks 1-4, ~.02 in 5-8 and ~.014 from week 9 (lines carry this week's injuries, weather and
  news). Lead, not a result: a one-weight version (gap x [weeks 1-8]) fit on more seasons once the engine backtests
  before 2021; the win totals for 2016-20 are on file.
- **Gap split (descriptive, 2026-10-20; tools/gap_split.py): the whole gap to Vegas is game-specific, none of it is
  team strength.** 1,021 games 2022-25, weeks 2-18, walk-forward. Brier: ours .2257; MARKET SEASON VIEW (ratings fit
  to every closing spread through last week, so the market's opinion of the teams with nothing about this game) .2281,
  + Elo .2262; Vegas's line for this game .2099. Market season view - ours +0.0024 [-0.0033, +0.0082] (we judge team
  strength as well as the market does); line - market season view -0.0182 [-0.0248, -0.0117]: all of the .0158 gap is
  what the line knows about THIS game beyond season-long strength (injuries beyond the QB, rest, weather, motivation,
  matchup, news). By weeks, ours / season view / line: 2-6 .2464 / .2431 / .2288; 7-12 .2159 / .2190 / .2040; 13-18
  .2176 / .2240 / .1997 (largest late: resting starters, playoff stakes). Caveat: the season view lags one week of
  results (lines through last week were set before last week's games); adding Elo (which has them) barely moves it.
  Direction: stop guessing at team-strength signals; the missing piece is game-specific, and the win formula's only
  game-specific input today is the starting QB (non-QB absences don't reach it at all).
- **PRE-REGISTERED 2026-10-20 (owner: "yesss lineup value ... get going"): (BO) lineup value: who's missing (or back)
  beyond the QB.** Gap split: the whole gap to Vegas is game-specific; the win formula's only game-specific input is
  the QB. Data (tools/lineup_build.py): snap counts for every position (gsis ids via the players table: the weekly
  rosters carry no PFR id for linemen, which is why availability history has none), weekly roster status, the final
  injury report, contracts. For each team-game 2021-26 and each non-QB player with this team in its previous 8 games
  (weights 0.5^(games ago / 3), the team ratings' recency): recent = weighted mean snap share (0 when he missed),
  role = weighted mean share in the games he played; kept if role >= 0.3. Available now (REPORT, known by Saturday) =
  on the team's roster for that week (ACT or INA) and not Out / Doubtful on the final report. delta = (role if
  available else 0) - recent: a new absence costs his role, a return adds back what the rating missed, a long-gone
  player counts 0 (the ratings already learned without him). Quality q = his cap-share percentile within his position
  group that season (contracts; none on file = 0.5). Features, home minus away: OFF = sum of delta x q over OL / WR /
  TE / RB, DEF = over DL / LB / CB / S. Test = (BN)'s harness (Matchups win chance as of the game's week, logistic fit
  walk-forward on earlier seasons, scored 2022-25, ties dropped): BASE = home + rank gap + Elo; LINEUP = BASE + OFF +
  DEF. GATE: Brier lower by >= 0.002 with the 95% CI (2,000 game resamples) upper < 0, lower in >= 3 of 4 seasons,
  CONFIRM 2026 (games so far) same direction. Reported, not gated: SNAP (q = 1); INACTIVES (also out when on the
  game-day inactive list, known ~90 minutes before kickoff, what the closing line sees); ACTUAL (did not play: a
  ceiling, hindsight); per-group weights (8 groups, fit 2021-25, reading only); weeks 1-4 / 5-12 / 13-18; the gap to
  Vegas's line on the same games. A pass ships into the Matchups win chance (and the playoff simulation's this-week
  games) and is the base for outcome-validated grades for every position.
- **RESULT {#lineup-value} (BO) lineup value beyond the QB: FAIL.** tools/lineup_build.py + tools/lineup_eval.py,
  2022-25, 1,084 games. Brier base .2250; LINEUP (report, cap-weighted) .2255: +0.0005 [-0.0005, +0.0016], better 2 of 4
  seasons, CONFIRM 2026 +0.0009: FAIL. SNAP +0.0010; per-group weights .2264 (overfit, RB / S signs wrong).
  INACTIVES -0.0012 [-0.0031, +0.0007]; ACTUAL (hindsight ceiling) -0.0020 [-0.0043, +0.0003]. By weeks (base /
  inactives / actual / Vegas): 1-4 .2340 / .2337 / .2334 / .2253; 5-12 .2263 / .2265 / .2266 / .2109; 13-18 .2171 /
  .2136 / .2114 / .1997: what signal there is is late-season rest (2024 PHI week 18 is the biggest absence in the
  data). Measured this crudely (snap share x cap share), even perfect knowledge of who played closes ~0.002 of the
  ~0.015 gap. Owner's next idea, the right one: value players by EPA with them on the field (participation data,
  every play's 22 players, 2016-25; not published for the current season).
- **Gap split CORRECTION (2026-10-20, tools/gap_split_loo.py).** "The whole gap is game-specific" overstated it. A
  fairer market view (ratings fit to every closing spread of the season INCLUDING this week's other games, leaving
  out only this game's line) still only ties ours (.2274 vs .2257, +0.0017 [-0.0040, +0.0075]) and the line still
  beats it by .0175; but that reconstruction reproduces the line poorly (corr .83, residual sd 3.3 points), so much
  of the .0175 is strength the line knows and a spread-fit rating loses, not game-specific news. Honest reading: we
  match a simple market-derived rating; how the line's remaining edge splits between better strength and
  game-specific information is NOT determined by this method. (BO)'s ceiling (~0.002 from who played) says absences,
  measured crudely, are a small part.
- **Research 2026-10-20 (owner: "research this first"): per-play participation (all 22 players) for the current
  season has no free source.** nflverse's 2023+ participation is FTN's, published only after the postseason (2025's
  on 2026-02-10; nflreadr's schedule: "does not update during the season"); ESPN's play API names only the players
  involved (passer / receiver / tackler); stat-api.com sells it ($49+/month, current season unconfirmed), as do PFF,
  FTN, Sportradar. Free for 2026: per-game snap counts (every position). Design consequence: player values from
  2016-25 plays; 2026 roles and absences from snap counts and reports; the backtest mirrors that exactly.
- **PRE-REGISTERED 2026-10-20 (owner: "check lineups against EPA on the plays they are on the field for"): (BP)
  on-field player value (ridge plus-minus) in the lineup term.** Player values (tools/rapm_build.py): for each target
  season s (2018-26), every offense / defense play (pass or run, regular season + playoffs) of seasons s-3..s-1
  (weights 0.25 / 0.5 / 1 by age; plays with win probability outside .05-.95 at 0.25), EPA = context (down, log
  distance, field-position bins, home offense) + sum of the 11 offensive players' offense values - sum of the 11
  defenders' defense values; ridge, each player shrunk toward a prior that depends on his position group and how much
  he played (fit from a first pass: lightly used players are not assumed average), lambda per side chosen by
  predicting season s-1's plays from s-4..s-2. Values in EPA per play, positive = good. Lineup term: (BO)'s delta
  (role if available else 0, minus recent, REPORT availability) x the player's value, summed over non-QB offense and
  over defense, home minus away (players without a value: their group's prior at zero plays). Test = (BO)'s harness:
  BASE = home + rank gap + Elo; RAPM = BASE + OFF + DEF; logistic walk-forward, scored 2022-25. GATE: Brier lower by
  >= 0.002, 95% CI upper < 0, lower in >= 3 of 4 seasons, CONFIRM 2026 same direction. Reported: INACTIVES and ACTUAL
  (ceiling) versions; with the QB included; grade validity = rank correlation of a player's value with his value in
  the next season's fit (players with 300+ plays in both), by position group; the top / bottom of each group.
- **RESULT {#lineup-rapm} (BP) on-field player value in the lineup term: FAIL on the gated arm; the strongest lead
  yet.** tools/rapm_build.py (334,409 plays 2016-25; lambdas chosen inside the grid after widening it to 100,000
  before any scoring: off 3,000-10,000, def 1,000-10,000), tools/lineup_build.py, tools/lineup_eval.py --gate=rapm.
  2022-25, 1,084 games, vs BASE .2250: RAPM (Saturday report) .2238, -0.0012 [-0.0032, +0.0008], better 4 of 4
  seasons, CONFIRM 2026 -0.0026: FAIL (size and CI). Reported arms: RAPM + inactives -0.0026 [-0.0049, -0.0003], 4 of
  4, 2026 -0.0003 (90 games); RAPM hindsight -0.0024 [-0.0046, -0.0002]; with the QB term -0.0016. Same lineups
  valued by pay (BO) were +0.0005: valuing players by their on-field EPA is clearly the better measure. Weights (fit
  2021-25, reading only): offense 11.6, defense 1.1 (inactives 14.2 / 3.1). Validity (single-season fits, disjoint
  data, rank corr with next season, 300+ plays both): QB .39, RB .33, OL .30, WR .28, TE .19; LB .16, S .09, DL .04,
  CB .03: offensive values (linemen included) carry over, individual defensive values are noise. The inactives arm
  passing every bar is a reported arm out of nine, not a result: confirm on data it never saw before shipping.
- **OWNER-DESIGN SHIP 2026-10-20 (owner: "you choose") + PRE-REGISTERED confirmation: (BP2) the lineup term (RAPM,
  Saturday-report availability, OFFENSE ONLY) goes live in the Matchups win chance though its gate failed** (OFF + DEF
  -0.0012, CI spans 0). Offense only because individual defensive values don't carry over (validity .03-.16) and the
  defense weight flipped sign when refit on 2021-26 (+1.1 -> -2.7); offense only in the same walk-forward harness
  (production's form, no intercept): -0.0016 [-0.0035, +0.0002], better 4 of 4 seasons, 2026 -0.0043. Coefficients
  refit in production's form on 2021-26 games so far: home .1659, rank gap .0314, Elo .3193/100, lineup 11.79 per EPA
  per play (median game gap .009 -> ~2.5 points of win chance, 90th percentile ~7). Everything below reads "RAPM" as
  this offense-only term.
  CONFIRMATION at season end on games it never saw (2026 weeks 7-18, values for 2026 fixed from 2016-25 plays):
  tools/lineup_eval.py scored on those games only, BASE vs RAPM (report) vs RAPM (inactives), each fit on 2021-25 +
  2026 weeks 1-6. Keep RAPM-report if its Brier is not above BASE's; RAPM-inactives (with a game-day refresh about 90
  minutes before kickoff) replaces it if lower than RAPM-report by >= 0.001; else revert to BASE. Recompute-able from
  history (weekly roster INA status, final injury reports and snaps persist), so no live logging is needed.
- **PRE-REGISTERED 2026-10-20 (owner: "keep drilling ... more accurate independent of vegas"): (BQ) mismatch
  calibration: stretch the rank gap at the extremes.** Upset analysis (2022-26 walk-forward): when Vegas gives our
  favorite 70%+, he won .785 and we said .722; our 80%+ picks won .894 vs .827. The win formula's rank gap treats
  every place alike, so it can't say "far better". Variant QRANK: each team's rank mapped to the normal quantile of
  its place among 32 (z = Phi^-1((32.5 - rank) / 32)), gap = z_home - z_away, replacing the rank gap. Harness = (BN)'s
  (Matchups win chance as of the game's week), production's form (no intercept), arms fit walk-forward on earlier
  seasons, scored 2022-25, ties dropped. BASE = home + rank gap + Elo + lineup (offense, as shipped). QRANK = home +
  z gap + Elo + lineup. GATE: Brier lower by >= 0.001 (the most a calibration fix of this size can gain is about that:
  6 points of bias on a third of games), 95% CI (2,000 game resamples) upper < 0, lower in >= 3 of 4 seasons, and the
  calibration gap in games we price at 70%+ smaller; CONFIRM 2026 same direction. Reported: both gaps together; the
  net-rating gap instead (tested worse before: INSIGHTS power-rank-as-predictor); Vegas on the same games.
- **RESULT {#mismatch-qrank} (BQ) mismatch calibration (normal-quantile rank gap): FAIL, and the premise was mostly an
  artifact.** tools/mismatch_eval.py, 2022-25, 1,084 games, production's form with the shipped lineup term. Brier base
  .2213, QRANK .2217 (+0.0004 [-0.0009, +0.0018]), better 1 of 4 seasons, 2026 -0.0002: FAIL; both gaps .2212
  (-0.0001); net-rating gap .2217. Calibration of the base, binned by OUR chance: 50-60% said .550 won .590, 60-70%
  .646 / .640, 70-80% .746 / .719, 80%+ .828 / .861; 70%+ gap .011 (QRANK .015). The "we said .722, won .785" finding
  binned games by VEGAS's confidence: conditioning on a sharper forecaster's view picks games where he knows more, so
  our numbers look timid there by construction. Binned by our own chance, the model is calibrated. Lesson: judge
  calibration by the model's own bins; the gap to Vegas is resolution (telling games apart), not calibration.
- **Note 2026-10-20:** the "parked" carryover lead (sec. 9, 2026-10-12) was already tested as (X) on 2026-10-17 (FAIL:
  the 2022-23 gain didn't hold in 2024-25). Not re-run.
- **PRE-REGISTERED 2026-10-20 (owner: "investigate it reasonably"): (BR) arrivals in the lineup term.** The early
  season is our weakest stretch and (BM) says Vegas knows the offseason; the shipped lineup term (BP2) sees departures
  (last season's regulars no longer on the roster count as out) but not arrivals (a player new to the team has no
  history with it), and it did nothing in weeks 1-4. Variant: a player on the team's roster that week (ACT / INA, not
  Out / Doubtful) who is not among its regulars but was a regular (role >= 0.3) in his own last 8 games for other
  teams counts with delta = his role there (recent = 0: the team's ratings never saw him) x his on-field value.
  Offense only, as shipped. Harness = (BQ)'s: BASE = home + rank gap + Elo + lineup (shipped); ARRIVE = the same
  with arrivals in the lineup sums; production's form, walk-forward, scored 2022-25. GATE: weeks 1-6 Brier lower by
  >= 0.002 with the 95% CI upper < 0 and lower in >= 3 of 4 seasons; all weeks not worse (CI upper < +0.0005);
  CONFIRM 2026 weeks 1-6 same direction. Reported: weeks 7+, the number of arrivals per team-game by week.
- **RESULT {#lineup-arrivals} (BR) arrivals in the lineup term: FAIL (worse).** tools/lineup_build.py (arrivals:
  3.2 offensive per team in week 1, 0.8 in weeks 2-4) + tools/arrivals_eval.py, 2022-25. Weeks 1-6 (370 games): base
  .2368, arrive .2375, +0.0007 [-0.0010, +0.0024], better 1 of 4 seasons; week 1 alone .2176 -> .2229; weeks 7+ +0.0006
  [-0.0000, +0.0012]; 2026 weeks 1-6 -0.0004 (90 games). A player's on-field value with his old team does not
  transfer to his new one: the plus-minus carries his team's context (QB, line, scheme) as much as his own play,
  which also fits individual values being stable only within a team. Departures (shipped) stay; arrivals don't.
- **Check 2026-10-20 (owner: "aren't sacks allowed, pressures allowed ... measurable?"): pressure-based pass
  protection values are LESS stable than EPA-based ones; not pursued.** tools/ol_build.py: ridge plus-minus on
  "pressured or sacked" over 190,027 dropbacks 2016-25 (participation's was_pressure, number of rushers in the
  context); single-season values' rank corr with next season: OL .15 (EPA-based .30), QB .42, DL .13, LB .20, TE .11.
  Pressure tracks the quarterback (holding the ball, pocket movement) more than any one lineman. Sacks / pressures
  ALLOWED by a named blocker come only from film charting (PFF, SIS, FTN; paid); free FTN charting (in-season via
  nflverse) has QB-fault sacks and rusher / blitzer counts but no blocker. Run-blocking by gap (run_location /
  run_gap + depth-chart slots) remains untested.
- **PRE-REGISTERED 2026-10-20 (owner: "make our model better. you're at the wheel"): (BT) playoff stakes in the game
  win chance.** (L) tested stakes for player availability (fantasy), not the game; weeks 13-18 are where the line beats
  us most. As of before each week (cache/playoff_odds_weekly.parquet, the Playoffs tab's simulation, finished games
  only): SETTLED = playoff chance >= .99 and bye chance >= .99 or <= .01 (in, seed tier fixed: rests starters);
  ELIMINATED = playoff chance <= .01. Features, home minus away, zero before week 15: settled x [week 18], settled x
  [weeks 15-17], eliminated. Harness = (BQ)'s (production's form with the shipped lineup term, walk-forward, scored
  2022-25). GATE: weeks 15-18 Brier lower by >= 0.003 with the 95% CI (2,000 game resamples) upper < 0 and lower in
  >= 3 of 4 seasons (all other weeks unchanged by construction). Confirmation on 2026 weeks 15-18 at season end.
  Reported: the fitted weights, how many teams are flagged per week, Vegas on the same games.
- **RESULT {#stakes-game} (BT) playoff stakes in the game win chance: FAIL; week 18 is a lead.**
  tools/stakes_game_eval.py, weeks 15-18 2022-25, 255 games: base .2135, stakes .2096 (Vegas .1943); -0.0039
  [-0.0190, +0.0106], better 2 of 4 seasons: FAIL. By week (base / stakes / Vegas): 15 .1894 / .1935 / .1820; 16 .2304 /
  .2267 / .2121; 17 .1976 / .2030 / .1848; 18 .2363 / .2152 / .1979. Weights (fit 2021-25, reading only): settled x
  week 18 -1.60 (a settled team's log-odds; ~8 teams settled entering week 18), settled weeks 15-17 +0.48, eliminated
  -0.32 (noise; 9-14 teams flagged). The week-18 effect is large and plausible (rested starters) but picked after
  seeing the split: confirm on data never used (BT2) before shipping.
- **PRE-REGISTERED 2026-10-20: (BT2) final-week "settled" teams, confirmed on 2002-19.** Data never used by (BT): the
  last regular-season week of 2002-2019 (week 17; 2002-19 had 16 games). Settled (as (BT): P(playoffs) >= .99 and
  P(bye) >= .99 or <= .01) from tools/playoff_odds.simulate before that week's games, 2,000 seasons, ranks from Elo
  (our engine doesn't backtest before 2021), no Vegas lines. Base = home + Elo gap (production's Elo settings);
  STAKES = base + settled gap (home minus away). Fit: leave-one-season-out over 2002-19 (each season scored by a fit
  on the other 17). GATE: Brier lower by >= 0.003 with the 95% CI (2,000 game resamples) upper < 0, the settled weight
  negative in every fold, lower in >= 10 of 18 seasons. If it passes: ship a week-18 settled term in the Matchups win
  chance (weight refit on 2021-25 in production's form), confirm on 2026 week 18.
- **RESULT {#stakes-final} (BT2) final-week settled teams, 2002-19: FAIL on the Brier CI; OWNER-DESIGN SHIP (the
  model's driver, owner: "you're at the wheel").** tools/stakes_final_eval.py (tools/playoff_odds.simulate now plays
  the 6-team format with two byes for pre-2020 seasons), 288 final-week games, 96 with a settled team: Brier .2168 ->
  .2076, -0.0092 [-0.0206, +0.0026]: FAIL; settled weight negative in all 18 leave-one-season-out fits (-0.93 to
  -1.24); better 10 of 18 seasons. Settled teams won .511 of 88 games against an unsettled opponent where the base said
  .668 (about 3 standard errors). Two independent samples agree ((BT) week 18 2022-25: .2363 -> .2152). Shipped:
  config final_week_settled = -1.1 (2002-19's size; 2021-25 production-form fit -1.38 on 35 games), Matchups only,
  final regular-season week only, settled from the Playoffs simulation as of before the week (checked on 2025 week 18:
  the same 7 teams as the backtest odds). The model note says "X has nothing left to play for (starters often rest)".
  Confirm on 2026 week 18 (and each season after); revert if settled teams there win at their base rate.
- **PRE-REGISTERED 2026-10-20 (owner: "make our model better. you're at the wheel"): (BU) team-rating shrinkage and
  recency tuned on GAME outcomes.** The ratings' ridge penalties are chosen by predicting next week's per-play EPA (a
  noisy target); half-life 3 was "insensitive" for fantasy and game-tested only inside (X)'s carryover grid. Grid:
  alpha_scale (a multiplier on the CV-tuned penalties, team_model.alpha_scale) {1/3, 1, 3} x half_life_weeks {2, 3,
  4.5}, everything else as shipped. tools/engine_tune_eval.py (tools/rank_predictor.season_ranks: every 2021-26 game
  re-rated with ranks as of the week before). Primary metric: Brier of the win chance (home + rank gap + Elo, refit
  walk-forward on earlier seasons), games with a line, weeks 2+. CHOOSE the lowest Brier on 2022-23; DECIDE on 2024-25:
  Brier lower by >= 0.002 with the 95% CI over season-weeks below 0, margin MAE not worse (CI upper < +0.05); CONFIRM
  2026 weeks so far same direction; before shipping, fantasy MAE (tools/experiments.py 2021-25) CI upper < +0.003. If
  today's setting is the 2022-23 choice, keep it (now tested).
- **RESULT {#engine-tune} (BU) team-rating shrinkage and recency tuned on game outcomes: FAIL (flat), today's settings
  kept (now game-tested).** tools/engine_tune_eval.py, 1,097 games 2022-26. CHOOSE 2022-23 (Brier vs today): alpha
  x1/3 hl 2 -0.0015 [-0.0035, +0.0004] (lowest); every other cell within +-0.0007. DECIDE 2024-25: that choice +0.0003
  [-0.0014, +0.0020], margin MAE +0.063, 2026 +0.0046: FAIL. On 2024-25 every cell is within +-0.0007 of today (best
  alpha x3 hl 3 -0.0005). The win chance is insensitive to how the ratings shrink and forget across a 9x range of
  penalties and 2-4.5 week half-lives: the ratings' tuning is not where accuracy is hiding. team_model.alpha_scale
  stays 1 (the knob remains for future tests).
- **PRE-REGISTERED 2026-10-20: (BV) take luck out of what the team ratings learn.** (BU) showed the ratings' tuning
  is flat; this changes their input. (1) FUMBLE: on a scrimmage play with a fumble (1.6% of plays), who recovers is
  close to a coin flip (lost 46%; EPA lost -4.98 vs kept -0.78): the play's EPA becomes epa - (lost - p) x L with p the
  league's lost share and L the lost-minus-kept EPA gap, both from seasons before the one rated (a fumble still costs
  its expected price; the recovery bounce does not count). (2) CLIP: each play's EPA capped at +-4 (2.1% of plays; a
  tipped pick-six or a blown-coverage bomb says less about a team than its EPA does). Arms: FUMBLE, CLIP, BOTH (config
  team_model.epa_fumble_luck / epa_clip, off by default). Harness = (BU)'s (every 2021-26 game re-rated, win chance
  = home + rank gap + Elo refit walk-forward), scored on all of 2022-25 (no choose / decide split: three fixed arms).
  GATE per arm: Brier lower by >= 0.002 with the 95% CI over season-weeks below 0, lower in >= 3 of 4 seasons, margin
  MAE not worse (CI upper < +0.05), 2026 so far same direction; if more than one passes, the lowest Brier; then the
  fantasy MAE guard (tools/experiments.py 2021-25, CI upper < +0.003) before shipping.
- **RESULT {#epa-denoise} (BV) take luck out of the ratings' input: FAIL (all three arms).** tools/engine_tune_eval.py
  --bv, 1,021 games 2022-25, base Brier .2219. FUMBLE -0.0004 [-0.0015, +0.0006], better 2 of 4, margin MAE -0.015,
  2026 +0.0027; CLIP (+-4) +0.0002 [-0.0006, +0.0009], 1 of 4; BOTH +0.0006 [-0.0005, +0.0017], 0 of 4. The ratings
  already average enough plays that recovery bounces and outlier plays wash out; config switches stay off.
  Pattern across (BU), (BV), (X): the team-strength side is saturated with this data (tuning and input cleaning move
  the win chance by < 0.002); what's left is information the play-by-play doesn't carry.
- **PRE-REGISTERED 2026-10-20 (owner: "nope no money": free data only): (BW) Questionable players at their real
  chance to play in the lineup term.** The shipped term (BP2) counts a Questionable regular as fully available, but
  66.2% of Questionable listings 2018-25 played (64-69% every season). Variant: a Questionable regular's expected role
  = role x q, q = the share of Questionable listings that played in seasons before the one scored (all positions);
  everything else as shipped (report availability, offense, on-field values). Harness = (BR)'s (production's form,
  walk-forward, scored 2022-25). GATE: Brier lower by >= 0.001 (it changes few players: a refinement, not a new
  signal) with the 95% CI (2,000 game resamples) upper < 0, lower in >= 3 of 4 seasons, 2026 so far same direction.
- **RESULT {#lineup-questionable} (BW) Questionable players at their real chance to play: FAIL (too small).**
  tools/lineup_build.py (q from earlier seasons: .656-.665) + tools/questionable_eval.py, 2022-25, 1,084 games: base
  .2213, quest .2210, -0.0003 [-0.0007, +0.0002], better 3 of 4 seasons, 2026 +0.0001. It touches half of team-games
  but moves the lineup term by ~16% of its typical size. Not shipped.
- **PRE-REGISTERED 2026-10-20 (owner: "keep trying"): (BX) two game-specific signals the win chance ignores.**
  (a) QBQ: the team's starting QB (most offensive snaps in its previous game) is Questionable on the week's final
  injury report (the formula assumes he plays at full strength; playing hurt). Feature = home flag - away flag.
  (b) DEFGRP: defensive absences valued by position group, not by player (individual defensive on-field values are
  noise): the lineup term's delta (role if available else 0, minus recent; report availability) summed over DL / LB /
  CB / S regulars, each group with its own fitted weight. Harness = (BW)'s (production's form with the shipped offensive
  lineup term, walk-forward, scored 2022-25). Each arm vs BASE separately. GATE per arm: Brier lower by >= 0.001 with
  the 95% CI (2,000 game resamples) upper < 0, lower in >= 3 of 4 seasons, 2026 so far same direction. Reported: the
  fitted weights, how many games have a Questionable starting QB, whether that QB played.
- **RESULT {#qbq-defgrp} (BX) Questionable starting QB; defensive absences by group: FAIL (both).** tools/bx_eval.py,
  2022-25, 1,084 games, base .2213. QBQ (66 games with the starter Questionable; he played 55% of the time, 88 cases
  2021-26): -0.0003 [-0.0009, +0.0004], better 2 of 4, 2026 +0.0012; weight -0.38; on those games base .2535 vs Vegas
  .2240 (the harness rates last week's starter; production's projected starter already covers the sit case). DEFGRP:
  +0.0005 [-0.0019, +0.0033], 2 of 4, 2026 -0.0066 (90 games); weights DL .05, LB .14, CB .07, S -.07: noise again.
- **PRE-REGISTERED 2026-10-20: (BY) team-specific home field.** One league-wide home term today. Variant: home x
  team indicator for each of the 32 home teams (ridge, shrunk toward the league term: L2 penalty, strength chosen by
  leave-one-season-out on the training seasons), on top of BASE (home + rank gap + Elo + lineup). Harness = (BX)'s,
  walk-forward 2022-25. GATE: Brier lower by >= 0.001 with the 95% CI upper < 0, lower in >= 3 of 4 seasons, 2026 same
  direction. Reported: the teams with the largest fitted home edges.
- **RESULT {#team-hfa} (BY) team-specific home field: FAIL.** tools/hfa_eval.py, 2022-25: base .2213, team .2217,
  +0.0005 [-0.0014, +0.0022], better 1 of 4, 2026 -0.0039 (90 games). (2022's fold had one training season, so its
  penalty was the middle value, 3; later folds chose 30, the strongest offered.) Largest fitted extra home edges (2025
  fit): GB .10, BUF .10, PIT .10, MIN .09; smallest NE -.13, ARI -.11, NO -.11, i.e. recent home records, not stadiums.
- **PRE-REGISTERED 2026-10-20: (BZ) the lineup value in fantasy projections.** Projections already shift pass defenses
  for starting cornerbacks likely out (engine.game_ratings, personnel); offenses get nothing for missing linemen or
  receivers beyond the share redistribution. Variant (experiments.lineup_epa_scale = 1): in project_week only (not the
  Matchups ratings, which have their own term), each team's offensive pass and rush EPA expectation moves by its
  offensive lineup sum (nfledge/lineup.py, report availability; already in EPA per play, so no fitted weight).
  tools/experiments.py baseline vs lineup_epa, 2021-25. GATE (fantasy, sec. 1): overall MAE lower with the 95% CI over
  season-weeks below 0 and >= 0.01 points, no position significantly worse, better in >= 3 of 5 seasons.
  Reported: by position; start/sit accuracy.
- **RESULT {#lineup-fantasy} (BZ) the lineup value in fantasy projections: FAIL (real but negligible).**
  tools/experiments.py baseline,lineup_epa 2021-25 (12,480 player-weeks): MAE 5.177 -> 5.176, -0.001 [-0.001, -0.000]
  (CI below 0 but a tenth of the 0.01 bar); QB / RB / WR / TE all "no difference"; seasons -0.000 / +0.000 / -0.000 /
  -0.003 / -0.001; start/sit +0.004 points per pair [-0.001, +0.009] (WR +0.007 [+0.002, +0.013]). Vegas implied totals
  already carry injuries for nearly every game; the efficiency terms barely move. experiments.lineup_epa_scale stays 0.
- **Official injury tags (owner 2026-10-21: "we should use the official tags"; reverts the 2026-10-20 in-house Q / D /
  O bands for the tag only; our chance to play is unchanged).** InjuryModel.designations / tag_map (every rostered
  player, byes included) + gamecast.js tagOf. Rules: reserve list code; game-day inactive -> O, active -> none; the
  final report's designation; before it, Q if he missed his last game on its report (not rest / personal) or was hurt
  in it and not back (play-by-play notes, "has returned to the game" kept by nfledge/ingame.py since this change), held
  while he's on the week's practice reports; O early only with ESPN's return date past the game; live, Q for a board
  player hurt and not back in this week's games (ESPN play text). Audit tools/tag_audit.py 2022-25, QB/RB/WR/TE:
  missed last game hurt n 1,565 played next game 47.0% (90% on the next report); hurt and not back (2024-25 only:
  nflverse has no return notes before 2024) n 127 played 46.5% -> Q, not O; hurt and back n 223 played 87%; final
  report with no designation n 3,252 played 93.1% (any DNP 90.7%); Out 1.7%, Doubtful 1.6%, Questionable 67.1%.
  Not on the next report after missing hurt (n 157, played 47%): active roster 97 (played 73%: dressed backups), game-
  day inactive 45 (0%: unlisted, so not injured by the NFL's rule; game day makes them O), roster moves 15. Rest /
  personal (n 36, 42%): mostly roster churn (trades, cuts, inactives), small; kept out of the Tuesday Q.
- **Gotcha fixed 2026-10-21: the Tuesday model's current-season in-game notes never refreshed in run.py**
  (tuesday.hurt_notes read the 'ingame' cache with stale=False; only the later player-logs step refreshed it), so a
  Tuesday build's model ran one build behind on the weekend's in-game injuries. Now refreshed when 6+ hours old.
- **Gotcha fixed 2026-10-21 (Tyler Warren): "not listed = practiced fully" filled days whose report hadn't reached us.**
  The health tile took the clock's deadline as "report in" (and a 6-day window took last Friday's entry as this
  week's); the build counted a day once ANY team had filed it. Now per team: the week data's `filed` (report dates in
  our practice data); a day past its deadline that isn't there reads "not in yet".
- **DESCRIPTIVE 2026-10-21 (owner, via a friend: Woody Marks 15.3 over Kenneth Walker 14.4, "is the model worth
  anything?").** Cached baseline backtests 2021-25, weeks 4+, 3+ games (tools/vs_naive.py): MAE model / season FP/G /
  experts (ECR pts): QB 6.09 / 6.30 / 6.12, RB 5.21 / 5.59 / 5.33, WR 5.15 / 5.51 / 5.14, TE 4.37 / 4.67 / 4.40; start /
  sit pairs model / FP/G / experts RB 69.2% / 65.8% / 69.0% (WR 64.7 / 61.3 / 65.0). Season FP/G far above the
  projection does not carry: RBs 6+ above (n 64) FP/G 18.7, projected 11.1, scored 11.8; bellcows (65%+ carries) 4+
  above (n 69) FP/G 20.0, experts 17.5, model 14.2, actual 14.5 (scratch/bellcow.py). Backups turned lead (n 41) model
  14.2, actual 15.2. Big model-vs-expert gaps (scratch/disagree.py): model 5+ below experts (RB n 134) model 13.9,
  experts 20.8, actual 15.6 (truth ~1/4 toward the experts); 5+ above (n 37) model 12.2, experts 5.7, actual 11.0.
  Rushing efficiency is not pulled too far toward average (tools/eff_resid.py: the lowest-efficiency backs ran +0.25
  ypc ABOVE projection; TD/carry calibrated). Volume for backs gaining a sitter's work is calibrated (proj 12.7, actual
  12.7 carries, n 163; only the 10%+ added-share bucket overshoots, n 12). Marks' 15.3 = 10.9 own + 1.75 redistributed
  (Montgomery 32% to play; Jawhar Jordan, practice squad, off the board) + 2.6 team-share normalization, in a game Houston
  is favored by 10.5 (tools/explain_proj.py). Found: midweek the site runs WITHOUT the expert blend (nflverse ECR is
  scraped Fridays; the display's ECR is last week's) - the early-week ECR forward test (sec. 9, tools/ecr_snapshot.py)
  is the path; the backtest accuracy above is the blended Friday-Sunday state.
- **Shipped 2026-10-21: start / bench odds and toss-ups (League lineup).** tools/h2h_curve.py: how often the higher
  projection outscores the other by gap, every same-position same-week pair 2021-25 (238k): 0-0.5 51%, 0.5-1 54%, 1-1.5
  56%, 1.5-2 59%, 2-3 61%, 3-4 65%, 4-6 69%, 6+ 78%. Each suggested swap shows its chance; under 1.5 points: "Toss-up:
  start either".
- **PARKED (owner 2026-10-21: "keep that recorded but obscured from the main list"): show disagreements on the player
  card** - when we differ a lot from the experts or his season form, say so and why (matchup, volume, efficiency
  regressing). Not built.
- **QUEUED (pre-register next): (CA) with-or-without workloads.** Braelon Allen (Breece Hall 40% to play) 10.6 if Hall
  sits, 9.9 if he plays; with Hall wks 1-3 he averaged 5.7 PPR, without (wks 4-6) 13.2. Woody Marks "if Montgomery
  plays" 14.2 vs 7.7 PPR in weeks 1-4 with him. The usage half-life blends games with and without the teammate, and the
  "plays" world never removes the bump. Variant: a player's shares estimated separately from recent games with / without
  a teammate whose availability is uncertain or who returns, shrunk toward the blend by games in each.
- **QUEUED: prospective model-vs-expert disagreement log** (gaps of 3+ points each week, outcomes after), from the
  archived week pages.
- **REMOVED 2026-10-21 (owner: "i don't wanna label them as tossups or obscure the difference"):** the League start /
  bench odds and toss-up labels shipped earlier the same day. tools/h2h_curve.py and its numbers stay as a reference.
- **DESCRIPTIVE 2026-10-21 (owner: "start your studs, matchup proof, those guys exist"): no stud effect beyond the
  projection.** Studs = top 8 RB / 12 WR / 6 QB / 5 TE by season-to-date FP/G (weeks 4+, 3+ games), cached baselines
  2021-25. Raw head-to-heads looked like studs beat the projection gap (RB studs projected 0-1 below a non-stud won 52%,
  4+ below 41%), but that is projection LEVEL: higher projections are noisier, so any gap is closer to a coin flip.
  Logistic model of "the lower-projected player won" on gap, level, gap x level and stud flags (scratch/stud_logit.py):
  at gap 1, level 15 the lower player wins RB 52.3% if neither is a stud vs 51.5% if he is a stud (69,648 pairs); WR
  50.2% vs 47.5% (114,532). At equal projections studs' medians and floors match non-studs' (scratch/stud_dist.py: RB
  proj 14-18 floor p25 9.2 vs 8.2, median residual -0.05 vs -0.24). Season FP/G as a second input to the projection:
  walk-forward MAE worse every season 2022-25 for RB / WR / TE (scratch/form_coef.py).
- **DESCRIPTIVE 2026-10-21 (owner idea): season-average expert rank (mean log weekly ECR, weeks before this one) as a
  blend input** (scratch/avg_ecr.py, linear blends walk-forward 2022-25): RB MAE 5.251 model-only -> 5.254 with the
  season average (this week's ECR 5.268; the site's blend 5.202), WR 5.156 -> 5.150 (this week's 5.100), QB 6.028 ->
  6.001 (5.934). Start / sit RB 0.691 -> 0.691, WR 0.642 -> 0.645. Weaker than this week's ECR everywhere; as a midweek
  stand-in (when this week's isn't out) it would add a little at QB / WR, nothing at RB. Fold into the early-week ECR
  test (sec. 9) as a fallback variant rather than test alone.
- **PRE-REGISTERED 2026-10-21 (before building): (CC) a sitting back's carries split between the rotation and the next
  man up** (owner: "nfl teams don't run a 2 headed RB attack, then skip splitting carries to the next man up").
  Found: when the model gives the remaining lead back 80%+ of his team's RB carries (Woody Marks 91%: Montgomery 32% to
  play, the rest of the room has no history) he got 70% (n 43, 2021-25); no universal ceiling (lead backs 80%+ in 32% of
  team-games 2016-25; James Robinson 2020 95.6% of JAX RB carries over the season). Measured split (tools/
  committee_split.py, nflverse weekly stats; one RB with 30%+ of the last 3 games' RB carries sits): one back left in
  the rotation (15%+): rotation +47-54% of the vacated share, depth / next man up the rest (2016-25 n 254 committee,
  142 bellcow); two left: rotation 63-68%; none: depth all; team RB carries unchanged (1.025x). Variant
  experiments.rb_split: in a team-week where an RB with predicted carry share (carry_share_hat) >= 0.30 sits, every
  remaining RB's carries = (his own predicted share + his part of the vacated share) x team rushes, the vacated share
  split rotation (remaining RBs with predicted share >= 0.15, by share) 0.50 with one rotation back / 0.63 with two or
  more, the rest to the other remaining RBs on the board (by share + 0.02 each); none on the board: unassigned (a
  call-up we don't project). Replaces redistribution + normalization for those RBs' carries only (targets unchanged).
  Constants from 2016-20 only. Walk-forward 2021-25 (`tools/experiments.py baseline,rb_split 2021-2025`). GATE: on RB
  rows whose projection moves > 0.05 pts, MAE lower with a 95% season-week CI excluding 0; carries MAE on those rows
  reported (must not be worse); guards: all rows MAE CI upper < +0.003, no position significantly worse, start / sit
  not significantly worse. Remaining work if it passes: the "if X plays / sits" worlds (injuries.apply cond pairs) still
  come from the old redistribution.
- **PRE-REGISTERED 2026-10-21 (before building): (CA) with-or-without carry shares** (owner: Woody Marks "hasn't pushed
  past 11 all season even in a game where monty was gone"). Historical comparables (scratch/marks_like.py, 2021-25):
  committee backs (30%+ of carries) averaging <= 10, best game <= 13.5, partner out, team favored: n 12, projected 9.2,
  scored 9.4 (median 8.9; 4 of 12 scored 15+); across 108 looser matches the model never projected one above 11.1 -
  Marks' 15.3 is outside its history. Cause: his blended carry share (0.48 of team rushes) leans on weeks 5-6 with
  Montgomery hurt (71-75% of HOU RB carries; weeks 1-4 with him ~37%), and the sitter's vacated share is then added on
  top: the absence counted twice. Variant experiments.rb_wow (with rb_split on): for an RB whose teammate RB with
  predicted carry share >= 0.30 missed some of his recent games, his base carry share = his share over the games
  that teammate played (usage weights as carry_share), shrunk toward his blended share with k = 1 game of weight:
  (W_with x share_with + 1 x blended) / (W_with + 1); used in both worlds (teammate plays: as is; sits: rb_split adds
  the vacated share once). Teammate played all recent games: unchanged. Carries only, RBs only (targets later if it
  passes). Variants: baseline, rb_split, rb_split + rb_wow. GATE (rb_split + rb_wow vs baseline, and vs rb_split
  alone): affected RB rows (projection moves > 0.05) MAE lower with a 95% season-week CI excluding 0; carries MAE on
  those rows not worse; guards as (CC). Walk-forward 2021-25; k fixed in advance (no grid).
- **RESULT {#rb-split} (CC) a sitting back's carries split between the rotation and the next man up: FAIL (not
  significant), not shipped.** tools/experiments.py baseline,rb_split 2021-2025 + tools/affected_eval.py. Affected RB
  rows (n 198): MAE 5.481 -> 5.437, -0.045 [-0.188, +0.101]; carries MAE 4.76 -> 4.66 (-0.10 [-0.35, +0.16]), carries
  bias +1.02 -> -0.01 (fixed); points bias +1.71 -> +1.27. The lead backs it trimmed (n 37) were already UNDER-projected
  (+1.98 -> +2.39): the old concentration was wrong in carries but those leads out-scored their projections anyway.
  Overall RB -0.002 [-0.010, +0.005], start / sit RB +0.010 [-0.004, +0.023]: no difference. Switch stays off; (CA)
  next as pre-registered (its "with rb_split" arm is still run for the record).
- **AMENDMENT to (CA), 2026-10-21, before any (CA) results:** (CC) failed, so the decision arm is rb_wow ALONE vs
  baseline (same gate); rb_split + rb_wow is reported for the record. Implementation note: the qualifying teammate is
  chosen by his blended carry share (the input, available where shares are built: player_model._rb_wow), not the
  predicted share named above.
- **DESCRIPTIVE 2026-10-21 (owner: "how much does each qb latch onto 1 wr ... rb dump offs and whether that follows the
  rb or the qb"): target tendencies belong to the team, not the QB.** tools/qb_tendency.py, 340 QB-team-seasons (200+
  targeted throws) 2016-25, year-to-year correlation same QB+team / QB moved teams (n 33) / same team new QB (n 137):
  top target's share 0.29 / -0.16 / 0.27; top-2 0.26 / -0.09 / 0.28; concentration 0.25 / 0.01 / 0.36; TE share 0.46 /
  -0.08 / 0.33; RB share 0.56 / 0.07 / 0.22. Aaron Rodgers: top-target share percentile 94-97 with prime Davante Adams
  (2018, 2020-21), 12th in 2022 after Adams left, 15th in 2025 with DK Metcalf; career 25% vs league median 24%. The
  receiver drives it; current target shares already carry it. Not pursued; a faster share update for a receiver who
  just broke out is the open (testable) version.
- **RESULT {#rb-wow} (CA) with-or-without carry shares: FAIL (not significant), not shipped.** tools/experiments.py
  baseline,rb_wow,rb_split_wow 2021-2025 + tools/affected_eval.py. Decision arm rb_wow alone, affected RB rows (n 2,581):
  MAE 5.146 -> 5.139, -0.007 [-0.020, +0.006]; carries MAE -0.019 [-0.047, +0.011]; backs it trimmed (n 1,120) MAE
  5.219 -> 5.174, backs it raised (n 1,461) 5.090 -> 5.112. Overall RB -0.004 [-0.012, +0.004], start / sit RB +0.005
  [-0.018, +0.032]. For the record, rb_split + rb_wow: affected RB rows (n 2,590) MAE -0.011 [-0.024, +0.001], carries
  MAE -0.036 [-0.072, -0.001] (significant), RB overall -0.007 [-0.015, +0.001], start / sit RB +0.017 [-0.007, +0.044].
  Both fixes point the same way and fix the carries; neither clears the points gate. Owner's design call pending.
- **Shipped 2026-10-21: practice-squad elevations on the board (nfledge/elevations.py; owner: Jawhar Jordan, elevated
  by Houston for week 6, "seems like a huge gap").** nflverse rosters show an elevated player as practice squad until
  after the game, so call-ups were never projected. Sources researched: ESPN's transactions feed logs few elevations
  (2 league-wide for week 6, 2026; not Jordan's); NFL.com's transactions pages list none and paginate only with the
  site's script; api.nfl.com rosters are a current snapshot (elevated players stay DEV); Spotrac is paywalled.
  ProFootballRumors' daily "Minor NFL Transactions" post lists every team's elevations (2026-10-17: 35, 12 at skill
  positions, Jordan among them): the main source, ESPN a supplement. Parsed days cached (cache/pfr_transactions;
  the site refused connections for hours on 2026-10-21); one failure stops further tries that run. Elevations dated
  after a team's previous game and by this week's game day join Engine.candidates (live builds only; in the cache
  key). Check: week 6's 12 elevations replayed into week 7's board add all 12. REMAINING: before an elevation is
  announced (Tuesday-Saturday), the chance of one isn't modeled (history: nflverse weekly rosters show past
  elevations as one-week ACT rows); the Moves page could switch to the same source (owner asked; recommended for
  the current season, ESPN kept for history).
- **RESULT {#rb-split-wow} SHIPPED AS OWNER-DESIGN 2026-10-21: (CC) + (CA) together** (experiments.rb_split, rb_wow; owner: "i refuse to be
  content assuming marks gets 100% of all texans RB carries this weekend"; "should we just assume a next man up will
  emerge?"). Neither passed its gate alone; together (2021-25) carries MAE -0.036 [-0.072, -0.001], affected-row points
  MAE -0.011 [-0.024, +0.001], start / sit RB +0.017 [-0.007, +0.044]. Week 7: Woody Marks 15.3 -> 14.3 (18.7 -> 17.1
  carries), Dare Ogunbowale 2.1 -> 5.3 (1.7 -> 6.6), Braelon Allen 10.6 -> 9.8, Isaiah Davis 4.1 -> 5.5.
  **PRE-REGISTERED (CD) season-end confirmation:** 2026 weeks 7-18, RB rows whose projection the pair moves > 0.05
  (live archive vs a switches-off rebuild): MAE not worse (CI upper < +0.05) and carries MAE lower; else switch off.
  REMAINING: the "if X plays / sits" pairings still come from the old redistribution.
- **PRE-REGISTERED 2026-10-21 (before building): (CE) practice-squad players as roster players with a chance to play**
  (owner: "can we just track and treat practice squad players normally?"). Precedent (scratch/elev_prec2.py,
  2020-25): skill players elevated and playing, the next week: RB 58% played (n 212), TE 61% (163), WR 57% (353); all
  re-activated ones played. Variant: healthy practice-squad QB/RB/WR/TE on the board with P(plays) from a model fit
  on past seasons (elevated last week, his position room's absences, depth), projected from their own history.
  GATE: Brier of P(plays) on practice-squad rows vs today's implicit 0, walk-forward 2022-25, CI excluding 0; and the
  fantasy MAE guards. Not built yet.
  AMENDED 2026-10-21 (before building or any outcome is looked at). (1) Leak found: nflverse's weekly rosters show an
  elevated player ACT in his elevation week, so backtests already know every elevation, while the live site sees him
  as practice squad until Saturday. Both arms therefore use the live information set: a week-w ACT row that is an
  elevation (DEV at w-1 and again DEV at w+1; w+1 is used only to reconstruct what the live site saw, never as a
  feature) counts as practice squad. (2) The pool: that week's practice-squad QB / RB / WR / TE (DEV at w, or
  elevated at w). Features, all known before Saturday: position, elevations used this season (3 is the league
  limit), elevated last week, his position room's absences on this week's injury report (Out / Doubtful / IR among
  last week's ACT players at the position), prior NFL offensive games. Logistic, refit walk-forward on earlier
  seasons. Label: offensive snaps > 0. Descriptive base rate (2020-25): 4.3% play the next week. (3) GATE, replacing
  "vs implicit 0" (any rate beats 0 when 96% don't play): Brier better than a per-position constant base rate (earlier
  seasons) with the 95% season-week CI excluding 0; teammates whose projection the variant moves > 0.05 (RB / WR /
  TE): points MAE not worse (CI upper < +0.05); all relevant rows not worse.
- **PRE-REGISTERED 2026-10-21 (before building): (CJ) "hurt in the game, then returned" in the Tuesday and week
  models** (owner: Dontayvion Wicks 54% to play: "shouldn't our model downplay 'injured in game, returned'?"). Wicks:
  injury note wk6 Q4 13:02, "has returned to the game" Q4 9:32; on last week's report (L D F, no game status); 62% of
  snaps vs his usual 88%. The models' hurt_in_game counts every injury note, returned or not. Descriptive
  (scratch/hurt_back.py, skill players, REG): next game played after a note with a return 0.859 (n 220, 2024-25), with
  no return 0.517 (n 783; 2024 0.275, 2025 0.365). Gamebooks log returns only from 2024, so earlier notes can't be
  split. Variant (experiments.hurt_back): add hurt_back = 1 returned / 0 no return (2024 on) / missing (a note in a
  season without return logging) / 0 no note; nothing else changes. TEST (tools/hurt_back_eval.py): walk-forward
  (train on seasons before), Tuesday model and week model, test seasons 2025 and 2026 to date (2024's models train on
  seasons without returns). GATE: Brier on rows with an injury note lower with the 95% season-week CI excluding 0;
  all rows not worse (CI upper < +0.0005).
- **RESULT {#hurt-back} PASS, SHIPPED 2026-10-21: (CJ) "hurt in the game, then returned".** 6,269 injury notes
  2016-26, 1,155 with a return (logged 2024 on). Walk-forward, test 2025 + 2026 to date. Tuesday model: injury-note
  rows Brier 0.1662 -> 0.1382, -0.0280 [-0.0345, -0.0214] (n 1,048; 2025 -0.0255, 2026 -0.0365); all rows -0.0040
  [-0.0051, -0.0028]. Week model: injury-note rows 0.1173 -> 0.1007, -0.0166 [-0.0212, -0.0119] (n 3,128); all rows
  -0.0018 [-0.0024, -0.0011]. Returned: played 0.887, predicted 0.753 -> 0.874 (Tuesday); no return: played 0.295,
  predicted 0.478 -> 0.389. experiments.hurt_back = true. The explanation says "injured during it, then returned".
- **FIXED 2026-10-22 (data leak in backtests): NFL.com's practice feed also files in-game rulings** ("out for the
  rest of the game", "questionable to return") under that game's week, as entries with no practice days: 674 in 2024
  (294 Out, 318 Questionable), 329 in 2022, 15-49 in other seasons, 4 in 2026. Backtests read them as the pre-game
  report for the game they happened in (DeVonta Smith, concussed 2024 wk 3, scored 0% for wk 3; also Nabers wk 4,
  Collins wk 5). data.load_all now drops practice entries with no practice days (real report entries always carry
  them). Effect, cached baselines 2021-25 rebuilt: 2024 injury-report Brier 0.1233 -> 0.0903 (60 "Out" players who
  played -> 0), fantasy MAE 5.231 -> 5.240 (the leak flattered it slightly: a player hurt early scores little);
  other seasons within +-0.001 Brier. Live unaffected (2026 had no such Out entries). Training mostly unaffected (past
  seasons' report rows come from nflverse's injury reports, which don't have them).
- **DESCRIPTIVE 2026-10-22 (owner: "test injury model as it is now against history"): tools/avail_track.py rerun**
  (2021-25 walk-forward, 27,831 player-games; data/history/availability_track.json). Final report Brier: Q = 50/50
  0.126, official status rates 0.111, status + Friday practice 0.105, ours 0.086. By stage: Tuesday 0.135 (lean wrong
  19.0%), Wednesday 0.136 (18.5%), Thursday 0.105 (15.0%), final 0.086 (11.4%); calibration bands within ~1 point.
  Too optimistic where a player isn't practicing: Q no practice all week played 24.3% vs predicted 33.8 (n 111),
  Doubtful 3.4 vs 8.9 (n 236), Wednesday DNP after missing his last game 10.1 vs 16.5 (n 685). 2026 weeks 1-6: Brier
  0.100; 30-50% band played 46.2 vs 38.1 (n 171). Candidate next test: calibration by practice pattern.
- **PRE-REGISTERED 2026-10-22: (CK) the week model's calibration step** (owner: "find out what's up with the no
  practice situations"). Found while breaking down the misses (scratch/nopractice.py, walk-forward 2021-25): the
  uncalibrated model is closer in every no-practice spot (Q no practice all week played 24.3 / raw 29.6 / shipped
  33.8; Doubtful 3.4 / 7.0 / 8.9; Wednesday DNP after a missed game 10.1 / 12.9 / 16.5), and pooled Brier is lower
  raw at every stage (Wednesday 0.1335 vs 0.1357, Thursday 0.1040 vs 0.1053, final 0.0860 vs 0.0861). Final report,
  raw 0-5% band: played 1.5, raw 1.9, calibrated 3.4; 5-10%: 8.0 / 7.6 / 12.3. Cause in the code: week_model's
  isotonic maps are fit on season-1 predictions of a DIFFERENT model (trained on seasons before season-1), then
  applied to the current one. (I2) compared old model vs new model + calibration; the calibration was never tested
  alone. Variants (tuesday.WEEK_CALIB): "prev" (shipped), "none", "oof" (isotonic per stage on out-of-fold
  predictions of the same configuration: leave-one-season-out over the training seasons). DISCLOSED: "none" on
  2021-25 has been seen (above). TEST (tools/week_calib_eval.py): 2021-25 walk-forward + the untouched 2026 weeks 1-6.
  GATE: pooled stages 1-3 Brier lower than "prev" with the 95% season-week CI excluding 0 on 2021-25, and not worse on
  2026 wks 1-6 (point estimate); "oof" replaces "none" only if it beats "none" with the CI excluding 0 (else the
  simpler one). Tuesday model (stage 0) has no calibration step; unchanged.
- **RESULT {#week-calib} PASS, SHIPPED 2026-10-22: (CK) no calibration step.** tools/week_calib_eval.py, stages 1-3
  on-report rows: "none" vs "prev" 2021-25 -0.0012 [-0.0018, -0.0006] (n 18,554; stage 1 -0.0022, 2 -0.0013, 3
  -0.0001; 4 of 5 seasons, 2021 +0.0008), 2026 wks 1-6 -0.0009 (n 1,251). "oof" vs "prev" -0.0011 [-0.0016, -0.0006];
  "oof" vs "none" +0.0001 [-0.0004, +0.0005], so the simpler "none". Spots (played / prev / none): Q no practice all
  week 0.243 / 0.338 / 0.296; Doubtful 0.034 / 0.089 / 0.071; Wednesday DNP after a missed game 0.101 / 0.165 / 0.129.
  Owner's question (does the schedule explain it, Thursday games vs practice days?): no; by game day the no-practice
  gaps are as large on Sundays (Q DDD +10 pts, n 90) and not larger on Thursdays (n 9-63). Remaining: the raw model is
  still 3-5 points high in those spots (small groups). config experiments.week_calib = "none".
- **FIXED 2026-10-22 (live timing): a team's report counted as out only once nflverse had it.** Tyler Shough (NO)
  93% "On report last wk" with a full Wednesday practice on his card: NFL.com's practice feed (15-minute refresh) had
  every Sunday team's Wednesday report while nflverse's injury table had only CHI / NE (the Thursday game), so
  availability, tags, the ESPN bridge and the reserve-window check all ran as if no report were out (Tuesday model).
  Interim fix: injuries.published_teams / listed_now = either source. PLANNED (owner: "why are we taking reports from
  more than one source?"): NFL.com as the single source for the current week (out or not, days, game status, injury
  type), nflverse for history only.
- **DATA 2026-10-22: practice history refetched with dates.** NFL.com practice entries 2018-25 refetched with each
  day's date (old caches had the order only): rows and day strings identical every season; 99.98% of 108,932 dated
  entries fall on the team's report days counted back from its game (Sunday game: 2-4 days before; Thursday: 1-3).
- **PRE-REGISTERED 2026-10-22 (owner: "yes do AS next"; queued 2026-10-18): (AS) the week model's stage from the
  calendar.** Today a player's stage is his own listed-day count and his line is only the days he was listed: first
  listed Thursday ("DD" on a Sunday week) he is read at "Wednesday" with Thursday's DNP (training and live alike),
  and a full Wednesday (not listed = practiced fully) is lost. Variant (tuesday.STAGE_FROM = "calendar"): the team's
  report days (dates of every player listed for that team-week; fallback the practice calendar); stage k = its first
  k days; his line = his entry on each of those days, "F" where he isn't listed (the {#off-report} rule); on the
  report at stage k = listed on any of them; the model retrained on that construction. TEST (tools/stage_eval.py),
  walk-forward 2021-25 + 2026 to date, rows = players listed by calendar day k (k = 1, 2, final), each arm fed what
  it would see live by that day: today's arm his listed days so far with stage = his own count (no fill, no later
  days), the variant as above. GATE: pooled stages 1-3 Brier lower with the 95% season-week CI excluding 0 on
  2021-25, not worse on 2026; reported: players first listed after day 1.
  AMENDED 2026-10-22 before anything ran: {#off-report} (AO) already showed padding unlisted days with "F" makes the
  final-report model worse (+0.0019 Brier; off the report before his first listing played 83.9% vs listed FFF 92.0%,
  after his last 70.8%), so the variant marks a day he isn't listed "X" (off the report), not "F": wn_X = days off so
  far, w_first / w_last from listed days only. The calendar stage (the part AO didn't test: AO was the final-report
  model only) is unchanged. Tool: tools/stage_cal_eval.py (tools/stage_eval.py is (AP)'s).
- **RESULT {#stage-calendar} (AS) the week model's stage from the calendar: FAIL (not shipped).**
  tools/stage_cal_eval.py, 2021-25 rows on the report by calendar day k, each arm fed its live view: Brier 0.1082 ->
  0.1077, -0.0006 [-0.0015, +0.0003]; 2026 -0.0019 (n 1,308). Stage 1 -0.0001, stage 2 -0.0014 (rows with a day off
  the report -0.0074, n 880: played 77.5%, own 80.8%, calendar 78.6%), final -0.0001 (with a day off -0.0024, n
  1,249); seasons 4 of 5 better (2025 +0.0007). Helps where it aims, too rare to clear the gate. No-practice spots
  unchanged (Q no practice all week 0.296 -> 0.300, played 0.243). tuesday.STAGE_FROM stays "own"; the "calendar"
  construction is kept for a season-end recheck with 2026 added.
  SHIPPED AS OWNER'S DESIGN CALL 2026-10-22 (owner: "we need to use dates"): the calendar construction removes the
  within-week leak (Thursday's practice trained as Wednesday's) and reads late additions correctly; not worse in any
  measured slice beyond 2025's +0.0007. config experiments.stage_from = "calendar"; live availability builds the same
  line from the team's filed report days. **PRE-REGISTERED (CL) season-end confirmation:** 2026 weeks 7-18, stages
  1-3 rows on the report, live archive vs an "own" rebuild: Brier not worse (CI upper < +0.0005), else switch off.
- **PRE-REGISTERED 2026-10-22 (owner: "our model seems to weight offense more strongly than defense ... why?"):
  (CM) a separate shrinkage for defense.** Descriptive first: this week's power ratings spread (SD, pts/game) offense
  3.23 (pass 3.11, run 0.33), defense 0.89 (pass 0.81, run 0.19). Play-by-play 2016-25, team EPA/play: odd vs even
  weeks r offense 0.59, defense 0.28; season to season 0.42 vs 0.28; SD across team-seasons 0.087 vs 0.068. So
  defense is noisier and the same penalty pulls it in harder; reliability-corrected true spread ~1.8x for offense,
  the ratings show 3.6x (part of the gap: pass offense carries the QB term). Today one ridge penalty per unit covers
  offense and defense alike. Variant (team_model.def_alpha_ratios = [0.33, 1, 3]): the defense penalty a multiple of
  the unit's, tuned jointly in the same time-split CV. TEST: tools/game_eval.py 2021-25 --only=fitted, paired per game
  (--save), model-only margin MAE and total MAE; then tools/experiments.py fantasy MAE. GATE: margin MAE lower with
  the 95% season-week CI excluding 0, total MAE not worse (CI upper < +0.05), fantasy MAE all rows not worse (CI upper
  < +0.003). Reported: the multiplier CV picks per unit and season.
- **RESULT {#def-shrink} (CM) a separate shrinkage for defense: FAIL (worse).** CV chose defense x3 (MORE
  shrinkage) for pass and rush in every season and never x0.33. tools/game_eval.py 2021-25, 1,279 games, paired:
  margin MAE 10.289 -> 10.346, +0.057 [+0.021, +0.092] (worse every season); total MAE +0.013 [-0.023, +0.048].
  Fantasy step not run (game gate failed). Answer to the owner: defense ratings are smaller because defense is less
  predictable (odd/even-week r 0.28 vs 0.59), and freeing its shrinkage made game predictions worse, not better; the
  shared penalty stays. team_model.def_alpha_ratios defaults to [1.0] (off).
- **TOOL 2026-10-22 (owner: "scenarios for hypothetical players that would trip up our model ... have we covered
  them all?"): tools/scenario_audit.py,** 27 synthetic players planted in the live season's data (real teams and
  schedules), each with a scripted history and week state, run through production (availability, designations,
  tag_map) against the owner's rules. First run: 25 pass after harness fixes. Found: (1) ESPN Out with a return date
  past the game showed O but 33% to play when learned ESPN rates were missing (fallback was plain Out's carry-forward):
  FIXED, fallback = the bucket's measured 1.8% (injuries.OUT_RET_PRIOR). (2) S06 hurt, not back, then a bye: 21%
  (same as without the bye). Owner's fair comparison (scratch/bye_fair.py): played the game ~2 weeks after an in-game
  injury, all notes 2016-25: after a bye 65.3% (n 118) vs no bye, two games later 64.8% (n 1,221): the bye is only
  time. The Tuesday model doesn't know time (next game is next game). (3) S11 Q, no practice all week, after a normal
  game: 51% vs 35.4% played for that profile (n 48, 2021-25; model then 45-49%). Not covered yet: Monday-night timing
  and extra report days (both follow the real clock; the harness needs a "now").
- **PRE-REGISTERED 2026-10-22 (owner: "teach it time"): (CN) the Tuesday model learns elapsed time.** Variant
  (tuesday.TIME_ROWS): input days = days from his last team game to the game predicted; training also gets, for every
  Tuesday row whose next team game is under 12 days away, a second row from the same post-game-k information
  predicting his team's first game 12-16 days after k (label: played it), with its days. Prediction rows unchanged
  (the real next game). TEST (tools/time_rows_eval.py): walk-forward, test 2021-25 + 2026 to date, real rows only.
  GATE: Brier on rows whose next game follows a bye lower with the 95% season-week CI excluding 0; all rows not worse
  (CI upper < +0.0005). Reported: calibration on bye rows, hurt-not-back bye rows.
- **RESULT {#time-rows} (CN) the Tuesday model learns elapsed time: FAIL (worse).** tools/time_rows_eval.py, 37,492
  real rows + 25,261 two-week training rows. Bye rows 2021-25 (n 1,774): +0.0022 [-0.0005, +0.0046] (played 0.825,
  base 0.806, time 0.785); all rows +0.0003 [-0.0002, +0.0008]. Why: the two-week rows played 78.5%, bye rows 82.5%:
  without a bye the player usually plays the game in between, and that game carries its own new-injury risk, so "a
  bye = 14 days" is wrong for the general Tuesday population (for players hurt in a game, who mostly sit the game in
  between, the two matched: 65.3% vs 64.8%). Production stays. Remaining, small: players hurt in their last game with
  a bye next played 77.5%, base predicts 69.8% (n 249); hurt-not-back + bye 60% played vs ~21% predicted (n 15, too
  few). tuesday.TIME_ROWS off; scenario S06 stays a known miss.
- **PRE-REGISTERED 2026-10-22 (owner: "if it makes game predictions worse, doesn't it stand to reason the cross
  validation is wrong somehow and we should test pushing defense away from average?"): (CM2) less shrinkage for
  defense, fixed.** The CV loss (next week's team-game EPA/play) chose MORE defense shrinkage while game margins got
  worse with it, so the CV target may not match game outcomes. Variants, no CV on the ratio: def_alpha_ratios = [0.5]
  and [0.33] (one value = fixed; the unit penalty still CV-tuned). tools/game_eval.py 2021-25, paired per game. GATE
  (either variant): margin MAE lower with the 95% season-week CI excluding 0, total MAE not worse (CI upper < +0.05);
  if both pass, the larger gain; then the fantasy MAE guard (experiments.py, CI upper < +0.003).
- **PRE-REGISTERED 2026-10-22 (owner: "have we flat tested if tracking days between injury and game day help?"):
  (CN2) days as an input alone.** CN changed two things (a days input and two-week training rows); the rows failed.
  Variants: (a) Tuesday model + gap_days (days from his last team game to the game predicted), no extra rows;
  (b) week model + onset_days (days from the start of this injury, the first report day of his current run on the
  report or the game he was hurt in, to game day), known at each stage. TEST tools/days_eval.py, walk-forward 2021-25
  + 2026. GATE each: Brier lower with the 95% season-week CI excluding 0 (a: all Tuesday rows; b: stages 1-3 on-report
  rows), not worse on 2026; reported: bye rows (a), by onset bucket (b).
- **RESULT {#def-shrink-2} (CM2) less shrinkage for defense: FAIL.** Paired margin MAE vs production, 1,279 games
  2021-25: x0.5 +0.015 [-0.032, +0.062] (total +0.035 [+0.001, +0.070]); x0.33 +0.038 [-0.020, +0.096]; (CM) x3 +0.057
  [+0.021, +0.092]. Worse both ways: the shared penalty sits at the minimum for game margins, though the CV target
  (team-game EPA/play) alone would have picked x3, so the owner's suspicion about the CV target holds, while its
  choice of the shared value happens to be right.
- **RESULT {#days-alone} (CN2) days as inputs alone: FAIL (both).** (a) Tuesday model + gap_days: 2021-25 -0.0002
  [-0.0004, -0.0001] (4 of 5 seasons), 2026 +0.0003 (n 1,653): fails "not worse on 2026"; bye rows -0.0003, short
  weeks -0.0009. (b) week model + onset_days: -0.0000 [-0.0007, +0.0006]. Timing adds ~nothing beyond the practice
  line, status and weeks on the report, which already carry it. tuesday.TUE_DAYS / ONSET_DAYS off.
- **SHIPPED 2026-10-22 (owner: "make nfl.com the single source for the current week's report ... a class of bugs i
  never want to deal with again"): one source for the current season's report.** data.injuries_from_nflcom builds the
  current season's injury table (game status, practice days with dates, injury type, team) from NFL.com's feed (the
  15-minute practice fetch, now keeping team, name and injury fields) in nflverse's layout; load_all uses it instead
  of nflverse's copy, and tools/depth_build.py / player_logs.py read it through data.season_injuries. nflverse stays
  for past seasons. Check, 2026 weeks 1-6: 1,785 shared rows, game status, practice status and injury type identical
  on every one (the 4 nflverse-only rows are no-practice late additions, now kept: data.drop_ingame drops entries
  with no practice days only once his team's game is final, i.e. the in-game rulings). Week 7 at build: NFL.com 271
  rows, nflverse 23. Rams map to LA. NFL.com unreachable: a logged WARNING and nflverse's table (never a mix).
  injuries.published_teams / listed_now back to one table. tools/scenario_audit.py now builds its report rows the
  same way: 25 of 27 pass (S06, S11 the known model gaps).
- **SHIPPED 2026-10-22 (owner: "if we use a calendar date timeline we can be precise about timing at every point ...
  if anything is missing it's not silent"): the injury chronology,** nfledge/chronology.py. For each team's game at a
  moment `now`: its report days (practice_calendar + any extra day filed) with 4 p.m. ET deadlines, each upcoming /
  due / overdue (deadline + 75 min, not on NFL.com) / filed; stage = filed days; final = every day filed, a game status
  posted, or kickoff. CHANGED RULE: (AP)'s "final once the third deadline passes" made a missing final report read as
  "no game status" (silent); now it's OVERDUE and the team stays at its filed stage. injuries.chrono feeds
  published_teams, final_report_teams (availability, tags, ESPN bridge, reserve windows); InjuryModel.now (default
  the real time) sets the moment. Loud: run.py logs a WARNING per overdue team, index.json "overdue", the health tile
  shows the day as "Overdue" (not "Not in yet"), tools/news_watch.py builds as soon as an overdue report appears on
  NFL.com. Seasons without dated reports (before 2018) keep the old rule. tools/scenario_audit.py takes a moment per
  scenario (hours from kickoff): S28 Monday team Sunday 9 p.m. with Saturday missing (stage 2, overdue, not final),
  S29 Sunday team Saturday 10 a.m. with Friday missing, S30 a travel week's extra report day: 28 of 30 pass (S06, S11).
  Check (scratch/chrono_bt.py): the 2025 backtest run twice in one process, chronology on vs off: all 7,668 rows
  identical (chance to play, projection, status). Past weeks are kicked off, so the change is live-only by design.
- **RESULT {#ps-stage1} (CE) stage 1, P(plays) for practice-squad players: FAIL.** tools/ps_eval.py, nfledge/
  practice_squad.py (logistic with the pre-registered inputs + two products: elevated last week x room absences, room
  absences x experience). Pool 2020-26: 19,515 player-weeks, played 1.8% (the earlier 4.3% read the next week's
  roster); played when elevated 57.4%, never otherwise, so P(plays) = P(elevated) x ~57%. 2022-25 Brier base 0.0155 ->
  0.0152, -0.0002 [-0.0006, +0.0001]; 2026 -0.0006. Calibration: predicted 35-50% played 5.3% (n 19). Stage 2 not run.
- **PRE-REGISTERED 2026-10-22, a second attempt after seeing {#ps-stage1} (weaker evidence, recorded as such):
  (CE2) room size and the team's next man.** Missing inputs: how many healthy players his position room has LEFT (last
  week's active players at the position minus this week's Out / Doubtful / new reserve), by position; and whether he
  is his team's first practice-squad option at the position that week (most elevations used, then most experience).
  Same pool, label, walk-forward and gate as stage 1. If it fails, (CE) closes: the live site keeps adding elevated
  players once announced (nfledge/elevations.py, Saturdays).
- **RESULT {#ps-stage1-v2} (CE2): FAIL; (CE) CLOSED.** Same numbers as stage 1: 2022-25 -0.0002 [-0.0006, +0.0001],
  2026 -0.0007; 35-50% band played 5.6% (n 18). Room size and "first option" add nothing: before Saturday there isn't
  enough public signal to say which practice-squad player gets elevated better than a flat rate (1.8% play). The site
  keeps adding elevated players once announced. Owner 2026-10-22: the Marks case was really Marks / Ogunbowale (an
  active back, handled by {#rb-split-wow}: Ogunbowale 2.1 -> 5.3); Jordan was reverted and put on the practice-squad
  injured list (0%).
- **PRE-REGISTERED 2026-10-22 (owner: Kenneth Walker RB10 at 14.3, 26.2 FP/G, RB3 by the experts: "who gives a damn what
  he did on seattle ... and if we do why are we ignoring his playoff performances?"): two tests.**
  (CO) usage shares from his current team only: once a player has a game for his current team this season, his usage
  shares (recent and long-run windows) count only games with that team; per-play rates (yards per carry, catch rate,
  TD rates) keep his whole history (skill travels, role doesn't). experiments.share_team. Walker: recent carry share
  74% (KC) vs long-run 58% (mostly Seattle).
  (CP) playoff games in a player's history: his postseason games count toward his rates and shares as part of that
  season (today the ledger joins regular-season games only). experiments.playoff_hist.
  TEST each: tools/experiments.py baseline vs variant, 2021-25. GATE: fantasy MAE on the rows the variant changes (proj
  moves > 0.05) lower with the 95% season-week CI excluding 0; all relevant rows not worse (CI upper < +0.003); no
  position significantly worse.
- **PRE-REGISTERED 2026-10-22 (owner: "should we test discounting what happened last year faster once a new season
  starts? seattle k9 feels irrelevant"): (CQ) last season fades as this season's games accumulate.** Today the
  efficiency / long-share weights are fixed by season age (1.0 / 0.6 / 0.3; fixed alternatives were insensitive,
  {#robustness}). Variant: the weight of earlier seasons x exp(-g / k), g = the player's games this season before the
  target week (week 1: unchanged). k = 4 (fast: 6 games -> x0.22) and k = 8 (x0.47). experiments.prior_fade_k. TEST:
  tools/experiments.py 2021-25. GATE (either k): all relevant rows fantasy MAE lower with the 95% season-week CI
  excluding 0; no position significantly worse; if both pass, the larger gain.
- **PRE-REGISTERED 2026-10-22 (owner: "doesn't what happens in week 15-17 give us better indication than weeks 1-3 last
  year? can we treat the offseason as a gate players pass through that dulls the gravity of what happened before it?
  why are we treating the entire season combined as one thing that decays?"): (CR) one game-by-game clock for the
  efficiency / long-share weights.** Today: flat by season (1.0 / 0.6 / 0.3), every game of a season equal (usage
  shares already decay per game, half-life 3 weeks, with a small prior-season block gone by week 8). Variant
  (experiments.eff_clock): weight = 0.5 ^ (age / H), age in weeks before the target week, regular-season weeks
  counted as played (week 18 caps a season) and the offseason a gate of G = 8 weeks between seasons. H = 16 (at
  week 7: last season's week 17 ~0.52, week 1 ~0.26) and H = 32 (~0.72, ~0.51). TEST and GATE as (CQ).
- **PRE-REGISTERED 2026-10-22 (owner, after Walker's NGS numbers: "yards over expected and missed tackles. are those
  stats we can scrape for free?" ... "yes"): (CS) NGS rushing yards over expected per carry as a rushing-yards input.**
  Prior evidence, recorded up front: {#charting-ab} found catches / YAC / completions over expected null (|d MAE| <=
  0.001). NGS weekly lists a back's games with 10+ carries only (~74% of RB carries, 2025). Variant (experiments.ryoe):
  ryoe = his yards over expected per NGS carry (efficiency weights), shrunk toward the league mean like croe (method of
  moments on training seasons), an input to the rush_yd regression. TEST tools/experiments.py 2021-25. GATE: RB
  fantasy MAE lower with the 95% season-week CI excluding 0; all relevant rows not worse (CI upper < +0.003).
  Expected fantasy points (nflverse ff_opportunity): a testing yardstick only, not displayed (owner).
- **PRE-REGISTERED 2026-10-22 (owner: "the ftn stuff sounds worth testing"): (CT) FTN charting target quality for
  receivers.** FTN charts every play from 2022: per target, catchable / contested / screen / created reception.
  Variant (experiments.ftn_targets): a receiver's catchable-target rate and screen-target share (efficiency weights,
  shrunk toward the position means) as inputs to the reception and receiving-yards regressions. Seasons: FTN starts
  2022 and training uses the two seasons before, so the test is 2024-25 (+ 2026 to date reported). GATE: WR / TE / RB
  fantasy MAE on receiving rows lower with the 95% season-week CI excluding 0; all relevant rows not worse.
- **RESULT {#share-team} (CO) current-team usage shares: FAIL.** tools/experiments.py 2021-25, 12,480 relevant rows,
  paired from the cached runs: -0.0005 [-0.0036, +0.0029]; changed rows (4,188) -0.0017 [-0.0112, +0.0081].
- **RESULT {#playoff-hist} (CP) playoff games in a player's history: FAIL (slightly worse).** +0.0010 [+0.0002,
  +0.0018]; changed rows (1,826) +0.0062 [+0.0007, +0.0117].
- **RESULT {#prior-fade} (CQ) last season fades with this season's games: FAIL.** k=4 +0.0020 [-0.0014, +0.0053];
  k=8 +0.0001 [-0.0023, +0.0023].
- **RESULT {#eff-clock} (CR) one game-by-game clock: PASS, SHIPPED (owner's idea).** H=32: -0.0070 [-0.0134, -0.0005],
  changed rows (10,607) -0.0079 [-0.0154, -0.0003], better at every position (QB -0.0040, RB -0.0083, WR -0.0048, TE
  -0.0127), seasons 2021 -0.019, 2022 -0.004, 2023 -0.012, 2024 -0.002, 2025 +0.003; start / sit +0.050 [+0.026,
  +0.076]. H=16: -0.0071 [-0.0142, +0.0000] (borderline). Per the gate the larger clean gain: H=32. config
  experiments.eff_clock. Walker barely moves (14.3 -> 14.2): his shrunk rate is already 4.5 yd/carry (7th of 69 RBs);
  what holds him at 14 this week is KC's implied 20 points (rush_yd regression: +0.077 yd/carry per implied point).
- **ABLATION 2026-10-22 (owner: "does our model become dogshit when we shed those crutches?"),** 2025, 2,496 relevant
  rows, fantasy MAE (scratch/ablation.py): shipped 5.159; no Vegas lines 5.189 (+0.030; RB +0.073); no EPA team ratings
  5.160 (+0.001: redundant with Vegas); neither 5.203 (+0.044); no expert blend AND no calibration step 5.129
  (-0.030, WR 4.977 -> 4.891); naive season FP/G 5.586. Value is mostly the player model; Vegas a small real edge;
  the blend's worth needs a 5-season re-check with calibration separated (queued).
- **SHIPPED 2026-10-22 (owner: hours between builds; "is that worth it?"): event triggers, not a tighter clock.** A build
  every 2 hours would mostly rebuild an unchanged site; the gaps were events the watcher didn't watch. tools/news_watch.py
  now also builds on: a game's spread or total moving 1+ point in nflverse's schedule file (the source the build reads;
  first dry run caught LA @ LV -4.5 -> -3.5), and a relevant player (8+ projected) gaining or losing ESPN Questionable /
  Day-To-Day. The 30-minute cooldown still applies.
- **SHIPPED 2026-10-22 (owner: "would someone else trying to compare to us be able to get results?" / "should we start
  publishing a finalized report of all our projection records at the end of a week?"): the published record.**
  tools/forecast_record.py (CI step "Forecast record", committed to the archive branch): once a week's games are final
  and nflverse has its stats and snap counts, every player the site projected with what it published before his game
  (data/live_inputs snapshots: never recomputed) at five checkpoints on his team's calendar (before its first report
  deadline, before the second, before the third, before inactives, before kickoff, each with the build time), the
  outcome (snap or stat line; half-PPR points), and the week's scorecard: chance-to-play Brier and calibration bands per
  checkpoint (players under 97%), projection MAE / bias by position (top 24 / 48 / 60 / 24 by published projection),
  the 10 biggest misses. data/records/<season>_wkNN.json + .csv + index.json; Model tab area "Published record" with
  the how-to-score rules. Append-only. Week 6 (snapshots from Friday Oct 16): 424 players; projections MAE 4.88, bias
  -0.40 (156 players); chance to play before inactives Brier 0.107 (224), before kickoff 0.072 (208). E.g. Tyler Warren:
  84% before inactives, inactive (Footballguys had him "Projecting Inactive"). Competitor comparison (FantasyPros "Are
  They Playing?", Footballguys labels) would be forward logs only: none publishes a scorable history.
- **DESCRIPTIVE 2026-10-21 (owner's friend: "Pat Surtain's OPRK for WR1 is #1 hardest ... shadow CB can nuke WRs"):
  WR1 suppression is not a lasting defensive trait.** tools/wr1_suppression.py, play-by-play 2016-25, 4,212 team-games:
  WR1 / WR2 = an offense's top two WRs by targets before the game; result = half-PPR points minus his own average over
  his other games. Persistence across 320 defense-seasons, odd vs even weeks / season to season: vs WR1s r +0.04 /
  +0.12, vs WR2s +0.06 / +0.08, WR1 minus WR2 (shadow signature) +0.05 / +0.05 (a real 1-pt effect would show ~0.2-0.3:
  anything there is under ~0.5 pts). Denver with Surtain: WR1s vs their averages 2021 -3.6, 2022 -1.1, 2023 -1.1, 2024
  +1.5 (his DPOY year), 2025 -4.5. Limits: WR1 by targets, not by who the shadow covered (free data has no coverage
  assignments; PFF does). Slot vs outside: no free history of alignment. Not pursued.
- **DESCRIPTIVE 2026-10-21 (owner's friend: outliers aren't equal; do elite pass defenses take more from star WRs?):
  no tier x defense interaction; OPRK barely predicts.** tools/tier_x_defense.py + tools/tier_x_oprk.py, cached
  baselines 2021-25, WRs weeks 4+ (4,408 rows). WR outcome vs his season FP/G by opposing defense third: by fantasy
  points allowed to WRs so far (OPRK) tough -0.66 / middle -0.60 / soft -0.59; by the model's pass-defense rating -0.76
  / -0.60 / -0.50. Model miss by tier (top 12 / 13-36 / 37+ by FP/G rank) x defense third: interaction (stars'
  tough-minus-soft miss beyond everyone else's) OPRK -0.47 [-1.94, +1.00], rating +0.41 [-1.02, +1.75]. Top-12 WRs run
  ~0.6-1.4 under projection at every defense level (the known top-tier over-projection, {#median-calibration}).
  Surtain 2024 (PFR coverage): 65 targets, 40-405-3, 4 INT; in the Jeudy 9-235-1 game 4 targets, 3-25-1 (production
  moved to the receivers he wasn't on). Not pursued.
- **PRE-REGISTERED 2026-10-21 (before the list is built or any outcome is looked at): (CF) shadow corners** (owner's
  friend: "prime surtain was famously a shadow corner"; "make it hyper specific to shadow corners and their fantasy
  impact"; owner: "where does it stop ... at what point does he fall off"). Denver 2021-25 ranked 1st of 32 in opposing
  WR1 points vs their own averages (-1.78/game, SE 0.90; WR2 -0.50), but one team can't validate a model term.
  LIST (built from published reporting only, without fantasy outcomes): data/history/shadow_corners.csv, season x
  corner, 2016-25, criterion fixed now: reporting (PFF, beat writers, team sites) that he followed the opponent's top
  receiver in most of his games that season (a published shadow rate >= 50%, or shadowed in >= 6 games), with source
  URLs. TEST (tools/shadow_eval.py): opposing WR1s (top WR by targets before the game, 3+ games) facing a listed
  corner's team in a game he played (PFR coverage row that week) vs all other WR1-games: (a) actual minus season
  average (descriptive), (b) the model's miss (actual - projected, cached baselines 2021-25). GATE for a model term:
  (b) for listed games below 0 with a 95% CI (season-week bootstrap) excluding 0, the effect present in >= 2/3 of
  listed corners with 3+ such games, and stable split by season halves (2021-23 vs 2024-25, same sign). If it passes,
  a pre-registered term: listed corner active -> opposing WR1 shifted by the fitted amount, scaled by his
  season-to-date coverage yards per target allowed vs the listed group's (aging / form fades it). Else closed.
- **RESULT {#shadow-corners} FAIL 2026-10-21: (CF) shadow corners.** List: 69 corner-seasons 2016-25 at high / medium
  confidence (145 rows incl. low; two research passes per era merged, kept if either pass sourced it high / medium;
  Charvarius Ward 2022 demoted to low: only a per-snap rate, contradicted). Deviation from the registration: "played that
  week" = nflverse snap counts (defense snaps > 0), not a PFR coverage row; fixed before outcomes were seen. 786
  shadowed WR1-games of 4308. (a) WR1 vs his own average: shadowed -0.71 [-1.15, -0.25], others +0.07 -- real, but
  mostly already in the model's team pass-defense term. (b) model miss 2021-25: shadowed -0.50 [-1.20, +0.25] (n 297),
  others +0.11 -- CI includes 0, gate fails. Per corner 13 of 18 negative (passes); 2021-23 -0.60, 2024-25 -0.41
  (passes). Surtain -0.17 over 49 games (the model already prices Denver). Widest per corner: Sneed -3.90 (19), Turner
  -2.95 (13); C. Ward +3.33, Forbes +1.54, Bradberry +1.48. Closed: no corner term. A ~0.5-point WR1 residual is
  plausible but not separable from noise with ~300 games; revisit only with a larger charted list.
- **PRE-REGISTERED 2026-10-21 (after (CF) failed; before any quality split is looked at): (CG) elite shadow corners
  only** (owner's friend: shadow corners who aren't elite dilute it, "taking bottom half and top half"). Same list,
  games and miss as (CF), 2021-25. Quality = the corner's season-to-date yards allowed per target in coverage from
  games BEFORE that one (nflverse PFR weekly advanced defense; 15+ targets so far, else last season's full rate; no
  rate -> dropped). Split shadowed games at the median quality into better / worse halves. GATE: better half's miss
  below 0 with a 95% season-week bootstrap CI excluding 0, at least 0.5 points below the worse half, and negative in
  both 2021-23 and 2024-25. This is a second look at the same games, so a pass needs replication on 2026 before a
  term ships. Splitting by the outcomes themselves is circular and not allowed.
- **RESULT {#shadow-elite} FAIL 2026-10-21: (CG) elite shadow corners.** 285 of 297 shadowed games had a prior
  coverage rate (median 7.07 yds/target). Better half (3.0-7.1): miss -0.61 [-1.64, +0.45] n 143; worse half: -0.33
  [-1.33, +0.78] n 142; gap -0.28 (needed -0.5). Better half 2021-23 -0.84, 2024-25 -0.45. No gradient: the miss by
  sixth of corner quality runs -1.4, +0.5, -0.9, -0.4, +0.8, -1.4 (flat; scratch chart). Surtain 48 games at 6.0
  yds/target, miss -0.03. Closed with (CF): elite or not, a shadow corner adds nothing measurable beyond the team
  pass-defense rating. tools/shadow_quality.py.
  CORRECTION same day: "beyond the team pass-defense rating" overstates it. The model's efficiency matchup term vs
  DEN is ~0 (matchup_pts +0.03); the markdown comes through volume / Vegas implied totals: WR1s vs DEN projected
  0.9 (2024) and 1.1 (2025) points below their season FP/G relative to league. Prime Surtain (2024-25) WR1 miss: 2024
  +1.27 (n 13), 2025 -2.38 (n 14). Owner's friend's valid objection: the list is season-level, so in a season where a
  corner shadowed ~half his games the other half dilute the effect toward 0 (a true -1.0 would read about -0.5).
- **PRE-REGISTERED 2026-10-21 (before the game list is built or any outcome is looked at): (CH) game-level shadow
  matchups 2025.** LIST: data/history/shadow_games_2025.csv (season, week, defteam, corner, receiver, offteam,
  source_url), built only from after-the-fact reporting that a named corner shadowed / traveled with a named receiver
  in a named 2025 regular-season game (Mike Clay's ESPN Playbook shadow reports, free; PFF / beat as support).
  Pre-game projections of shadows ("expect X to shadow Y") do NOT count. TEST (tools/shadow_games.py): the named
  receiver's miss (actual - projected, the cached 2025 baseline, relevant rows) in those games. GATE: mean miss below
  0 with a 95% week-bootstrap CI excluding 0, at least 1.0 point below 0 (a size worth a model term), and negative in
  both weeks 1-9 and 10-18. Comparison reported: the same receivers' miss in their non-shadowed games. A pass needs
  replication on 2026 (a forward log) before any term ships.
- **RESULT {#shadow-games} PASS 2026-10-21 (pending replication): (CH) game-level shadow matchups 2025.** List: 81
  corner-receiver games from Clay's ESPN Playbook after-the-fact recaps (two blind research passes, weeks 1-9 / 10-18;
  one inferred row dropped before scoring: Turner-Odunze wk9). 66 scored (weeks 1-2 have no projection). Named
  receiver's miss -1.68 [-3.33, -0.32], median -1.50; same receivers' other games -0.19 (n 337). Weeks 1-9 -0.90
  (n 45), 10-18 -3.36 (n 21). GATE PASS. Sensitivity (not the gate): full shadows only (16 "partial" rows out) -2.05
  [-3.85, -0.62] n 54, i.e. stronger, as dilution predicts. Per corner (small n): Surtain -4.85 (6), Turner -4.60
  (8), Gardner -3.08 (6), Benford -1.30 (9); Mitchell +4.71 (4), Gonzalez +2.74 (4). Consistent with (CF)/(CG)
  failing from season-level dilution. Caveats: one season; reporting could favor recapping shadows that went well
  (Clay's running counts, e.g. "the seven receivers he has shadowed", limit this); a model term would need to know
  BEFORE kickoff who shadows whom (Clay's pre-game projections), a different, noisier input than these recaps.
  tools/shadow_games.py.
- **PRE-REGISTERED 2026-10-21 (before any 2026 list or outcome is looked at): (CI) replication on 2026 weeks 1-6.**
  Same rules, list data/history/shadow_games_2026.csv (after-the-fact recaps only), live 2026 baseline. PASS: 2026
  point estimate <= -1.0 AND pooled 2025+2026 95% week-bootstrap CI excluding 0. Then a second test of the usable
  input: Clay's PRE-GAME shadow projections as the predictor (what a model term would actually see).
- **RESULT {#shadow-2026} FAIL 2026-10-21: (CI) replication, 2026 weeks 1-6.** Clay's 2026 playbooks named few
  shadows; 15 recaps (mostly FantasyPros / team sites), only 8 scorable (weeks 1-2 have no projection). As delivered:
  2026 miss +0.11 (n 8; needed <= -1.0), pooled 2025+2026 -1.49 [-3.11, -0.03]. FAIL. Disclosed fork: the research
  pass flagged two Benford week-5 rows (Nacua, Adams: "covered on more than 67% of routes", no shadow verb) as
  borderline; without them 2026 is -2.73 (n 6) and pooled -1.77 [-3.36, -0.41], a PASS. Both runs were looked at
  together, so the drop can't be adopted after the fact (Surtain-Adams wk3, "90 percent of his routes", is the same
  kind of row and was not flagged). Honest read: 6-8 games decide nothing either way. Not adopted. FORWARD LOG: keep
  adding 2026 recaps weekly (rule fixed now: a route share >= 50% on the named receiver counts as a shadow, same as
  PFF's definition; all such rows stay) and re-run at season end, plus the pre-game projection test.

- **Trends overhaul + audit (owner, 2026-10-22).** Builder rebuilt as labeled rows + bottom-sheet pickers ("be more
  deliberate and elegant"); then, from a Stathead / Fantasy Points comparison, added: situation type, expected play
  call, play result, yards gained, schedule (bye, rest, prime time, international), game result, opponent (team /
  division / conference), opponent record / playoff team / defense rank, thrown by, with / without a teammate (game
  level: on the roster that week but no snap) and on / off the field (play level, 2016-2025 participation), college,
  draft round / pick, contract AAV and % of cap (OverTheCap), age, career year, weather / kickoff sliders; Is / Is not
  and any-of on every filter; sliders with linked number boxes; Routes measure (YPRR, TPRR; a route = a dropback on the
  field as WR / TE / RB, so blocking snaps count: TE / RB rates run low); game logs, marks with streaks, best N-game
  stretches; CSV export with player IDs. Not possible with free data: plays before 1999, current-season on-field data,
  true route charting.
  - **Audit** (`tools/trends_audit.py`, `docs/trends_audit.md`): page CSV vs nflverse season totals, 1999-2025. Found
    and fixed five counting bugs: TDs credited on defensive returns / after laterals; yards after a lateral given to
    the original carrier; 1999-2000 plays with a post-play penalty filed under a blank play type (~400 a season)
    dropped; a scramble-then-throw counted as a run; plays recorded as attempts but labeled otherwise dropped. After:
    83 of ~64,000 player-season stats differ; traced ones are nflverse season-table corrections (its play-by-play
    matches Trends). nflverse's season table has impossible pre-2009 targets (Welker 2008: 0 targets, 111 catches);
    skipped, counted. Not audited: filters / charting / routes (spot-checked only), playoffs, special teams.
  - **Engine split + CLI (owner: "making the tool usable for llms").** Definitions, loading and counting moved to
    `static/trends_engine.js` (no DOM; `createEngine(load)`); the page keeps only UI. `tools/trends_cli.mjs` runs the
    same engine on a local build or the live site (`--schema`, `--find`, names resolved to ids, share link in every
    answer); CI publishes the schema as `data/plays/schema.json`. Verified after the split: every earlier check
    reproduced, a full UI smoke test (`scratch/ui_smoke.py` pattern) clean, audit 2024-25 identical. Also: Play result
    gained successful / unsuccessful plays, incompletions, sacks, interceptions, fumbles lost; the by-season chart's
    range is the seasons' own (a count's league TOTAL had flattened it) with labeled ends, and the season in progress is
    a hollow point.
  - **Position (owner: "can we sort by positions too? maybe as part of the who filter").** bio.json gains each player's
    position (nflverse's current listing, used for every season: a player who switched is counted at his current one).
    Position filter (QB / RB / WR / TE; Routes keeps its on-field position) as chips in the Who sheet, read into the
    subject ("Every running back", "BUF wide receivers"), plus a Position breakdown.
  - **LLM links (owner: "we have [an llms.txt] already don't we?").** llms.txt gains "Ask the play-by-play (Trends)": the
    `?q=<URL-encoded JSON>` link form (plain JSON, unlike the page's base64 `?t=`, so an assistant can write it), the
    schema, defaults, named players, four worked example links (each opened and checked). Player names are looked up
    by the engine (`resolveNames`; the page takes the most recent player on a tie, the CLI lists the candidates). Fixed:
    a link's query was merged with the viewer's last query; a link is now the whole query.
- **Site readable by visiting assistants (owner, 2026-10-22, "option 2").** An assistant that fetches a URL reads text and
  runs no JavaScript, so the app is an empty frame to it. Added plain-text pages (tools/machine_pages.py, nfledge/machine.py
  write_pages): a page per player on the week page (chance to play with its reasons, status, projection + range + stat
  line, practice and games day by day, recent injuries, durability, game logs this season and last, bio), a page per
  team, injuries.md (ESPN's list with our chance to play), players.md (directory); llms.txt lists them; the app shell
  points to them (head links, <noscript>, footer "For AI assistants"). Option 1 (a hosted query endpoint so an assistant
  can run Trends itself, free on Vercel / Netlify) and precomputed per-player splits pages were offered and declined.

- **PRE-REGISTERED 2026-10-22 (owner: "audit our entire injury model again ... all of it"): (CF) "final report in"
  from the chronology, not "a row exists", in two more places.** (1) lineup.report_available (BP, the lineup term in the
  win chance) switches to this week's report as soon as the team has ANY row this week; Out / Doubtful only come with
  the final report, so on Wednesday and Thursday a player ruled out last week counts as back and the team's lineup term
  swings up, then down again on Friday. (2) InjuryModel.scratch_table carries last week's Out / Doubtful forward only
  for (week, team) pairs with no row yet: same flaw, a backup is scored as a scratch risk midweek while his starter is
  likely out. Change: both use this week's report only once the chronology calls the team's final report in
  (injuries.chrono final_teams); else the latest earlier week's report stands in, as on Tuesday. Seasons without dated
  reports (before 2018) keep "a row exists". Gate: every past team-week is final (kicked off), so the change must be
  live-only: (a) the chronology calls every 2018-25 team-week with a game final (check, all weeks), and (b) the 2025
  backtest rows are identical before and after (chance to play, projection). If either fails, it doesn't ship.
- **SHIPPED 2026-10-22 (owner: "audit our entire injury model again ... identify and consolidate any systems that could
  be combined ... less surface for bugs"): one calendar, one status record, one browser reading.**
  * One report calendar: nfledge/chronology.py now also drives the practice timeline (tools/player_logs.py: "full, not
    on the report" only on a day the team's report is IN, per team and date; the Rashee Rice bug, and a gap the first
    fix left: a team's skipped day before a later filed one) and the model's filed days (injuries.filed_dates removed:
    it credited Dallas week 4 with another team's Monday / Tuesday through a lagging roster). The week JSON carries
    "chrono" (per team: stage, final, [date, state] per day) in place of "filed" / "overdue"; the practice strip, its
    day names and news_watch read it. Real-data effect on the timelines: only removals, every one a calendar day the
    team never filed (2026: 324 rows, 2025: 233, 2019: 217; e.g. week 1's Monday). CHANGED RULE: final = the LAST report
    day filed (or a status, or kickoff), not every day filed (scenario S31: Thursday never came, Friday's final did).
  * One status record: InjuryModel.availability writes what spoke as fields (src / des / days / gd / espn_q) and
    status_label() alone writes the words; report.inactive_why, machine pages, the scenario audit and inj_avail (was
    np.isclose(avail, scratch_avail)) read the fields. Check: every rostered QB / RB / WR / TE, weeks 6 and 7: chance,
    status, tag and why identical for all 1,009 rows before / after.
  * One browser reading: nfledge/static/health.js (NFLE.health): official tag, game day, listed, practice letters,
    the status pill, ros.json's return week and one threshold table (AVAIL). Fixed on the way: the pill read the status
    text (ESPN "Out" showed an Out pill beside a Q badge); the Health tile's regex missed "Hurt last game" and the Tuesday
    Q (read Healthy); "back ~wk N" read the takes-the-field chance (a healthy backup QB read "not back this season"; ros.json
    w[6] = injury only); the Injuries page left off a midweek "(D)" with no game status; a past week's team page showed
    today's tags; the badge tip assumed Wed / Thu / Fri; defenders had no Health tile in later weeks; rankings 10-20% to
    play showed the full if-active line (neither projected 0 nor two worlds); depth charts' live week used ESPN's raw
    list (Q on players who played through) where every other page shows the official tag. tools/health_check.mjs checks
    a built week for agreement.
  * One code table: nfledge/codes.py (team codes; reserve lists IR / PUP / NFI / SSPD, depth charts said SUSP and the
    timeline "Res" for NFI / suspended; ESPN statuses); one ESPN id map (data.espn_gsis); one ESPN injury fetch in the
    browser. injury_history no longer counts this week's unplayed game (played / missed, games total, durability).
  * Kept: practice_prob / partial_models (the older practice model) still give an Out row its 0 and the fallback when
    the week model has no answer, and report_avail feeds the personnel adjustment (switched OFF, kept switchable).
    Retiring them changes a model path: a candidate for its own pre-registered test, not a cleanup.
- **RESULT {#final-in-cf} (CF) "final report in" from the chronology for the lineup term and the scratch carry: PASS,
  shipped (live-only by design).** (a) The chronology calls every completed team-week final: 2019-25 all 3,742, 2026
  so far 186 (the loaded data starts at 2019, not 2018 as written above). (b) The cached backtest (2025-26, 9,634
  rows x 150 columns) before and after the change: identical (every numeric column; text columns differ only as
  missing-value markers). Live effect: from a team's first report of the week until its final one, last week's Out /
  Doubtful players stay out of the lineup term and keep their backups' scratch risk low, instead of reading as back.
- **PRE-REGISTERED 2026-10-23 (owner: "a calculator where you input down, distance, score, team timeouts left and game
  clock ... to make decisions, like whether to take a time out, whether to go for it on fourth down / punt / fg attempt,
  whether to onside kick, and whether to accept or decline a penalty"; "test in-house of course"): (CG) our own
  in-game win probability model, the base of Games > Calc and the gamecast's "what should they do?".** References only
  (not used): nfl4th (Baldwin; 4th downs, 2-pt) and nflfastR's WP model, whose per-play `vegas_wp` in nflverse
  play-by-play is the benchmark.
  * Model: HistGradientBoostingClassifier, P(the team with the ball wins), regulation plays only (overtime rules
    changed 2022 / 2025: out of scope, the page says so), ties dropped. Inputs, from the possession team's side: score
    differential, game seconds left, half seconds left, half, down, yards to go, yards to the end zone, own and
    opponent timeouts, its Vegas expected margin (spread_line signed), spread x share of the game left, home, receives
    the second-half kickoff, score differential / (game seconds left + 1) ratio. Monotonic: score differential +,
    own timeouts +, opponent timeouts -, expected margin +, yards to the end zone -, yards to go -. Fixed settings, no
    tuning on test seasons: learning_rate 0.05, max_iter 400, max_leaf_nodes 31, min_samples_leaf 200,
    l2_regularization 1.0, no early stopping. Rows: every regulation play with a possession team and a down or a
    kickoff, state at the snap.
  * Test: walk-forward, each of 2022, 2023, 2024, 2025 trained on 2006 through the season before. Brier and log loss
    on all rows and on the late-and-close subset (4th quarter, score within 8); calibration by decile of predicted WP.
  * Gate (all four to ship): (1) pooled 2022-25 Brier within +0.003 of nflfastR's vegas_wp on the same rows (theirs is
    fitted on seasons that include these, an in-sample edge, so "close" is the bar, not "better"); (2) late-and-close
    Brier within +0.005 of it; (3) every calibration decile within 3 points; (4) scenario sanity: leading by 3 with the
    ball, 0:30 left, opponent out of timeouts > 97%; down 3 with the ball at the opponent's 20, 0:05 left: between
    the FG make rate's neighborhood (40-60%); 1st & 10 own 25, tied, 15:00 of the 1st quarter, pick'em: 48-55%.
  * The decisions built on it (each a weighted sum of WP over outcomes; their inputs measured, then checked):
    4th down go (conversion probability: logistic on yards to go and field position, 3rd and 4th down runs / passes
    2014 on; gain given success / failure: empirical by distance), field goal (make rate: logistic on distance, 2018
    on), punt (empirical net result by field position, 2021 on: touchbacks, fair catches, returns; blocks and return
    TDs left out, as nfl4th does), 2-pt vs XP (league rates, 2021 on), onside vs kickoff (recovery rate under the
    2024+ kickoff rules, shrunk toward 2018-23), timeout (clock saved = measured run-off to the next snap when the clock
    runs, stopped at the two-minute warning), penalty (WP of the two states the user enters). Each input is checked
    walk-forward on 2024-25 for calibration (conversion within 4 points per distance bucket 1 / 2 / 3 / 4-5 / 6-10;
    FG make within 4 points per 10-yard band) before the page uses it.
- **RESULT {#wp-model} (CG) the win probability model: gates (1)-(3) PASS, (4) FAIL as written; SHIPPED as the
  owner's call ("up to you", 2026-10-23).** tools/wp_eval.py, 2022-25 walk-forward, 175,720 rows: Brier 0.1548 vs
  nflfastR's vegas_wp 0.1540 (+0.0008; theirs is fitted on these seasons), late-and-close 0.1699 vs 0.1697 (+0.0002),
  every calibration decile within 2 points (the ends lean: 3.3% predicted, 5.2% actual; 96.7% / 95.6%). Scenario (4)
  "down 3 at the opponent's 20, 0:05: 40-60%" read 32%; the expectation was wrong, not the model: in 274 such plays
  (0:15 or less, inside the opponent's 35) the team won 27.7% (model 29.3%, nflfastR 30.2%); over 186 games, 42% reached
  overtime and the tying team won 42% of those. A v2 (time monotone by the score, after seeing that the free clock
  wobbles ~2 points between nearby seconds) was REJECTED: it smoothed the clock but underfit the last seconds (down
  1-3 inside the opponent's 35, 0:15 or less: 29% vs 43% actual; tied: 76% vs 86%). Instead the timeout comparison
  averages over nearby clocks and the page calls a gap under 1.5 points a toss-up.
- **RESULT {#calc-inputs} (CG) the calculator's inputs: FAIL as pre-registered; shipped recent-season versions as the
  owner's call ("up to you").** tools/calc_check.py, fit before 2024, test 2024-25. Field goals: a 2018-23 logistic
  missed 50-59 yd by 9.8 points (62% vs 71%); a 1-season half-life still 6.7; recent seasons fixed it but a logistic's
  shape didn't (40s high, 50s low): shipped an isotonic table on the last 2 seasons + 3 earlier at quarter weight,
  within 3.7 points from 20 to 59 yd; 60-69 yd (36 kicks) 16 points low (44% made in 2024-25). Fourth-down conversion:
  every version under-reads 2024-25 at 2-5 yards (4th & 4-5: 41% vs 55%, n 220; 4th & 2: 56% vs 62%) while 1 and
  6-10 yards are within 2 points: conversion rose again in 2024-25. Shipped: 4th-down tries of the last 3 seasons (the
  live fit includes 2024-25). Both rates are shown and editable on the page. Measured as they are (no gate): timeout
  run-off by the offense's situation (39 s between snaps normally, ~21 at a half's end, 44 for a 4th-quarter leader in
  the last two minutes; a play 5 s), punts (2021 on), kickoffs (2025 rules: touchbacks 21%, median start the 30),
  onside 8.1% (2024-25 7.8% of 102, shrunk to 2018-23's 8.5%), XP 95.1%, two-point 47.6% (660).
- **FINDING 2026-10-23 (owner: "research what the end of half drives actually look like ... it's all passes, get out
  of bounds, you can make a lot happen with 30 seconds ... don't use these brainless averages"): the two-minute
  drill.** Offense in a half's last 2:00 (2nd quarter, or 4th quarter tied / behind), 2015-25, 38,849 snaps: 80% passes,
  28% incomplete, 14% out of bounds: the clock stops on its own after 42% of plays. After an in-bounds play the clock is
  stopped by the offense's timeout (median 7 s after the snap: called at once), a spike (15 s, costs a down) or a
  hurried snap (21 s, middle half 11-28; with no timeouts 17-24). Drives starting in a half's last 2:00 (2012-25, 5,977)
  score often: from midfield with 0:31-0:45 left 57% (TD or FG), own 30-39 36%, own 20-29 23%; inside the opponent's 40
  ~75% at any time. Both general WP models miss these moments, out of sample (fit 2006-18, 2019-25 4th-quarter snaps
  in the last 2:00): tied inside the opponent's 35 with 0:30 or less, won 96.7%, ours 88.7%, nflfastR 83.6%; down 1-2
  between the opponent's 35 and own 40, 0:30 or less, won 51%, ours 35%, nflfastR 39% (cells of 100-150 snaps).
- **PRE-REGISTERED 2026-10-23 (owner: "Yes, build it first"): (CH) an end-of-half drive model for the calculator's
  last 3:00 of each half.** nfledge/endgame.py. From every scrimmage snap with 3:00 or less in a half (regular season,
  2012 on): (a) how the drive ends: touchdown / field goal good / field goal missed / no score (HistGradientBoosting,
  multiclass; inputs: half seconds left, yards to the end zone, down, distance, both teams' timeouts, 4th quarter, the
  score differential in the 4th quarter clipped to +-9, seasons weighted 0.5 ** (years before the latest / 3) for
  today's kickers); (b) the seconds left when it ends (quantile regressions 25 / 50 / 75 on the same inputs plus the
  ending). Win probability at such a snap = sum over endings of P(ending) x the win chance after it: in the 4th quarter,
  with no time left the final score decides (a tie: overtime at its measured rate), else the other team's possession
  with the time left (the drive model again, then the general model); in the 2nd quarter the general model at the
  second-half kickoff (whoever receives it). Clock choices in a drill use the measured costs (a spike: a down and its
  measured seconds; a hurried snap: the measured gap by timeouts left; a timeout: one timeout). Test: walk-forward
  2022-2025, each season fit on 2012 through the season before; rows = 4th-quarter snaps with 2:00 or less, score
  within 8. Gate (both): (1) pooled Brier lower than the general model's (CG) on the same rows; (2) the mean absolute
  calibration gap over the time (0:30 / 1:00 / 2:00) x field position (inside the opponent's 35 / to own 40 / deeper)
  cells, tied and behind 1-3 and behind 4-8 separately (cells with 30+ snaps), lower than the general model's. If it
  fails, the calculator's late-game answers say "rough" and use the general model.
- **PRE-REGISTERED 2026-10-23 (owner: "do they detail any parts of their formulas we're ignoring?" ... "your choice"):
  (CI) the calculator's inputs, upgraded with what nfl4th (nflverse/nfl4th source, read 2026-10-23) and the NYT 4th
  Down Bot account for.** (1) Go for it: one model of the yards gained on a 3rd / 4th-down run or pass (classes -10 to
  +40, 40+ pooled; HistGradientBoosting multiclass), inputs down, yards to go, yards to the end zone, the offense's
  Vegas spread, the total, its implied team total, roof (outdoors / dome / retractable), seasons 2014 on weighted
  0.5 ** (years before the latest / 3); a defensive penalty that gives a first down counts as a conversion (gain =
  the distance, or the penalty yards if more, as nfl4th codes it). P(convert) = P(gain >= distance) and the gains after
  success / failure both come from it, so they depend on field position. Check (2024-25, fit before 2024): 4th-down
  P(convert) within 4 points per distance bucket 1 / 2 / 3 / 4-5 / 6-10 (the old model failed 2-5), within 4 points for
  favorites and underdogs separately (spread +-3 or more), and 4th-down Brier lower than the current logistic's. (2) Field
  goal: make rate by distance, roof and wind (outdoors), with the long-range selection correction (only teams that
  trust their kicker try the long ones: where the attempt rate falls below 80% of its plateau the rate blends, in
  log-odds, toward a curve fitted where everyone kicks; it may only lower it; tapered to 0 past 70 yd). Check: 20-59 yd
  within 4 points per 10-yard band on 2024-25, and outdoors with wind 15+ mph within 6 points. (3) Punts: the full
  outcome (blocked, muffed and lost, returned for a touchdown, else the receiving team's spot) by 5-yard band, 2018 on
  (no gate; counts recorded). (4) Kneel-out: after a non-scoring conversion, the game is over if the defense can't stop
  the clock (0 timeouts under 2:00, 1 under 1:20, 2 under 0:40; nfl4th's rule) - and symmetrically after a turnover on
  downs. (5) Field-position-dependent gains: from (1). If a check fails, that piece keeps the current version.
- **RESULT {#endgame-drive} (CH) the end-of-half drive model: FAIL; not shipped (the calculator's late-game answers
  use the general model, marked rough).** tools/endgame_eval.py, 2022-25, 5,508 4th-quarter snaps with 2:00 or less,
  score within 8: Brier 0.1292 vs the general model's 0.1282 (nflfastR 0.1285); mean calibration gap over 27 cells
  0.052 vs 0.051. By season it won 2023 (0.1154 vs 0.1243) and lost 2022 (0.1500 vs 0.1399). The misses all models
  share sit in TIED games with the ball late: inside the opponent's 35 with 0:30 or less, won 98.8% (n 84), drive model
  88.5%, general 88.4%, nflfastR 83.7%; opponent's 35 to own 40 with 0:31-1:00, won 88.9% (n 63), all ~71%. Likely
  today's kickers (a made field goal ends it) against the 2012+ history; (CI)'s field goal model is the next step.
  * (CI) amended before any result: the yards-gained multiclass would ship ~10,000 trees to the browser (51 classes x
    200 iterations). Instead (1) is a binary HistGradientBoosting P(convert) on the same inputs and coding (max_iter
    150, max_leaf_nodes 15) plus gain tables after success / failure by distance bucket x field-position band (5).
    The checks are unchanged.
- **RESULT {#calc-inputs-v2} (CI) the upgraded inputs: conversion FAIL as written, shipped as the owner's call ("your
  choice") because it beats the current model everywhere; field goals PASS on a v3; punts and kneel-out in.**
  tools/calc_check2.py, fit before 2024, 2024-25 4th-down tries. Conversion (HistGradientBoosting on 3rd + 4th downs
  with the spread, total, team total, roof; penalty first downs counted): Brier 0.2249 vs the current logistic's 0.2336;
  every distance bucket closer (4th & 2: 59.7% vs 55.7%, actual 66.5%; 4th & 4-5: 52.2% vs 41.4%, actual 61.7%;
  4th & 6-10: 42.0% vs 31.7%, actual 39.2%), underdogs within 1 point, favorites 6 low. The check was my error in
  part: 4th-down tries are chosen (teams go when they expect to make it; the gap leans to favorites), while the model
  learns from 3rd downs too, where nobody chooses: nfl4th trains on both for that reason. Field goals: a logistic in
  distance with roof / wind and nfl4th's long-range selection correction ran 6.8 points low at 50-59 yd with either
  attempt-rate window (the shape, not the correction); v3 = the recent isotonic table (fg) shifted in log-odds by the
  logistic's roof and wind effects: 20-59 yd within 3 points per band, outdoors with wind 15+ (110 kicks) within 4;
  60-69 yd 15 points low (36 kicks by trusted kickers, no gate). Punts 2018-25 (16,676): blocked, muffed-and-lost and
  returned-for-a-touchdown rates by band (from the own 30: 0.6%, 1.1%, 0.6%). Kneel-out (nfl4th's rule) in the engine.
  The page asks the conversion model at down 3 (an average team in that spot; owner's call delegated): 4th-down tries
  are chosen, so at down 4 the trees answer for teams that chose to go (own 20-45, 4th & 10: 3rd downs 31.5% of 1,287,
  4th-down tries 36% of 61, trees at down 4 42%; at down 3 33%). The rate is editable for a team that knows better.
- **PRE-REGISTERED 2026-10-23 (owner: "how confident are we that this is an accurate model? what data shows we're
  right?" ... "do all 3"): (CJ) validating the calculator's decisions, not just its parts.** Rows: every regulation 4th
  down 2022-2025 that was a go / field goal / punt (kneels, spikes, no-plays out), graded by the browser engine
  (static/calc_engine.js grade) with each season's own walk-forward model file (tools/calc_build.py --through=<season
  before>: win probability and inputs fit only on earlier seasons). nfl4th's own per-play numbers (go_wp / fg_wp /
  punt_wp, nflverse/nfl4th release "nfl4th_infrastructure", pre_computed_go_boost.rds) for the same plays.
  (1) The chosen option's win chance is a forecast of the game: per choice (go / field goal / punt), mean forecast vs
  the share won, and calibration by decile; the same for nfl4th's number for the chosen option. Gate: per choice, the
  mean within 3 points of the actual win rate, and no decile (50+ plays) off by more than 6. A "go" that runs low is
  the selection effect (CI) showing up; that is reported, not explained away.
  (2) Noise: 20 bootstrap refits (games resampled with replacement, 2006 through the season before the test) of the
  win probability model, the conversion trees and the field goal table; for 2025's 4th downs, the spread of the
  best-minus-second gap and how often the recommendation flips. The toss-up band becomes the gap below which the
  recommendation flips in more than 1 refit in 5 (the page used 1.5 points by judgment). No gate: it sets the band.
  (3) Agreement with nfl4th on the same plays: how often the recommended option matches, the correlation of the go-vs-
  best-alternative gap, and the 25 biggest disagreements read one by one. No gate: it shows where to look.
- **RESULT {#calc-decisions} (CJ) (1) the chosen option's forecast: PASS; (3) vs nfl4th: 79% agreement, two bugs found
  and fixed.** tools/calc_validate.py / .mjs, 15,440 regulation 4th downs 2022-25, each graded by the browser engine with
  that season's walk-forward model file. (1) The win chance of the option the team chose, against the share of games it
  won: go 35.2% vs 34.6% (3,151), field goal 56.4% vs 55.6% (3,923), punt 47.3% vs 47.2% (8,366); no decile of 50+ off
  by more than 5.4 points. nfl4th's own numbers on the same plays: 35.0 / 56.1 / 46.9; Brier ours 0.1533 vs nfl4th
  0.1525 (theirs fitted on these seasons). The feared "go reads low" (the conversion asked at down 3, CI) did not show.
  (3) Same recommendation as nfl4th on 78.7% of 15,342 plays, go-minus-best-kick gaps correlated 0.857; the biggest
  disagreements showed two engine bugs: a play that takes the rest of a half didn't end it (4th & 1 at the 22 with
  0:03 before halftime read "go": a conversion just ends the half), and the kneel-out rule applied only after a failed
  4th down (punting while trailing late read too kindly). Fixed in the engine (later() marks the half over; wp() treats
  a leader with the ball who can kneel as a win), after the check: 79.3% agreement, correlation 0.878, (1) unchanged
  (PASS). What remains: late in the 4th quarter, trailing by 1-3 in field goal range, we lean "go" where nfl4th says
  kick for the lead (e.g. down 2, 2:42, 4th & 2 at the 4: ours go +7.4, nfl4th field goal +9.1), the late-game zone
  every model we tested misreads (CH); and we are more aggressive overall (go by 3+ points on 1,575 plays vs nfl4th's
  1,188; teams went on 58% of ours, 71% of theirs).
  (2) Noise: 20 bootstrap refits (games resampled, fit through 2024) of the win probability model, conversion trees and
  field goal table, graded on 2025's 3,765 4th downs: the best-minus-second gap moves by a median 1.02 points (sd; 90th
  percentile 2.0). How often the recommendation flips by the gap: under 0.5 pt 30%, 0.5-1 25%, 1-1.5 19%, 1.5-2 15%, 2-3
  10%, 3-5 4%, over 5 0.6%. The pre-registered rule sets the toss-up band at 1.25 points (was 1.5 by judgment); the
  "questionable" line (3 points) holds in 96% of refits. This is data noise only: the late-game zone's shared blind spot
  (CH) is not in it, so the page keeps its "rough" label there.
- **FINDING + PRE-REGISTERED 2026-10-23 (owner, the try screen at 18-20 with 4:00 left: "go for 2 every time here
  right? ... why would you score a td to get within 2 and then kick an xp to get within 1"): (CK) key-number features
  for the win probability model.** The calculator read XP 31.2% vs two 31.5% (a toss-up) because the model prices points
  almost linearly late: with the ball at its own 30 and 3:55 left it read up 1 61.7%, up 2 71.4%, up 3 80.9%. Real
  games (Q4, 3:00-5:00, 1st & 10 at own 20-40, 2006-25): up 1 won 58.5% (n 41), up 2 58.4% (n 77), tied 52.1% (194),
  up 3 77.8% (171): late, a 1- and a 2-point lead are the same (a field goal beats both) and 3 is different (it only
  ties); nflfastR smooths it the same way (68% / 75%). Change: add indicators of the score's football meaning from
  the side of the team with the ball - lead 1-2 (a field goal beats it), 3 (ties), 4-6 (a touchdown beats it), 7
  (ties), 8 (a touchdown and two ties), and the same five trailing - unconstrained (the score differential stays
  monotone), same settings otherwise. Gate (all to ship): (1)-(3) of (CG) still pass (pooled 2022-25 Brier within
  +0.003 of nflfastR, late-and-close within +0.005, every decile within 3 points); (4) on 2019-25 4th-quarter 1st downs
  in the last 8:00 (fit 2006-18), the mean absolute gap between predicted and actual win rate across leads -3..+4 x
  time bands (1:00-3:00 / 3:00-5:00 / 5:00-8:00, cells of 40+) lower than the current model's; (5) the try, down 2
  after a touchdown with 4:00 left (pick'em, receiving team at its own 30 after the kickoff): going for two ahead of the
  extra point by 3+ points; down 1 after a touchdown, same clock: the extra point ahead. (CJ)'s check (1) is rerun on
  the new walk-forward files before shipping.
- **RESULT {#key-numbers} (CK) key-number features: FAIL (4); not shipped. (CK2) instead, the owner's call: in the 4th
  quarter a 1- and a 2-point lead are one state.** tools/wp_keys_eval.py: with the ten indicators the late cells moved
  nowhere (mean absolute gap 0.042 -> 0.043 over 23 cells; 2019-25, fit 2006-18): the late leads' cells hold 40-100
  games and are noisy themselves (5:00-8:00 up 1 won 56.9% of 51, below tied). (1)-(3) of (CG) still held (Brier 0.1551
  vs 0.1540) but nothing gained. The owner asked "can we treat 1 and 2 point leads as the same thing?": yes, as football
  (a field goal beats both late), not as something the data can teach: the engine's wp() averages the two in the 4th
  quarter (static/calc_engine.js). Check (5): down 2 after a touchdown with 4:00 left, two 33.5% vs the extra point
  27.7% (+5.7); down 1, the extra point ahead (39.1 vs 38.5); down 2 at 1:30 +11.8; down 5 at 4:00 two +3.3 (the chart's
  answer). (CJ) check (1) rerun with it: PASS (go 35.2 vs 34.6 won, field goal 56.4 vs 55.6, punt 47.3 vs 47.2; Brier
  0.1532); same recommendation as nfl4th 79.2%.
- **PRE-REGISTERED 2026-10-23 (owner: "if it's 19-20 and then they score a touchdown/xp the score is then 27-19, that's
  a one score game with a td and 2 pt conversion. if you had gone for 2 earlier and missed it, the score would be 18-27
  ... the time left matters a lot" ... "yes"): (CL) a possessions model for the 4th quarter.** The general model
  prices points smoothly at any clock: at 12:00 with the ball at its own 25 it reads down 1 45.4% vs down 2 37.6% (too
  far apart) and down 8 13.8% vs down 9 12.3% (too close: one score vs two), so key numbers can't come from it.
  nfledge/possessions.py: the win chance of a 4th-quarter state = the remaining possessions played out, alternating:
  (a) the current drive ends in a touchdown / field goal / nothing at rates measured by field position band, down and
  distance bucket (every drive 2012 on, shrunk to the band when a cell is thin); (b) each later drive at league per-drive
  rates for a drive after a kickoff or punt, scaled by its team's Vegas implied total (capped); a touchdown = 7 with the
  measured extra-point rate, else 6; (c) how many possessions remain after the current one: the measured distribution
  given the clock (30-second bins) and whether the team with the ball leads (every 4th-quarter snap 2012 on); (d) at the
  end the score decides, a tie is overtime at 50%. Fit on 2006-18 (drives 2012-18), tested on 2019-25 4th-quarter 1st
  downs. Gate (both): (1) mean absolute calibration gap over lead (-9..+9) x time (0:00-3:00 / 3:00-6:00 / 6:00-10:00
  / 10:00-15:00) cells of 40+ lower than the general model's; (2) Brier on all those snaps no worse than the general
  model's + 0.002. If it passes it replaces the general model in the 4th quarter and the 1-2 rule (CK2) goes; (CJ)
  check (1) is rerun. The try at 18-20 is reported at 12:00, 8:00 and 4:00 as it comes out, no gate on the answer.
- **RESULT {#possessions} (CL) the possessions model: FAIL; not shipped. What it showed fixed (CK2).** tools/poss_eval.py,
  23,604 4th-quarter 1st downs 2019-25 (fit 2006-18): mean calibration gap over 76 lead x time cells 0.043 vs the
  general model's 0.033; Brier 0.1212 vs 0.1205 (nflfastR 0.1192). A plain possession chain (the current drive by field
  position, later drives at league rates scaled by Vegas totals, the measured number of possessions left by clock and
  lead, the better try after each touchdown) misses how teams play late: up 1 with the ball read 81% vs 68% actual with
  3:00-6:00 left; down 1 with the ball 49% vs 63% (it plays for a field goal and the clock). The same table settled the
  owner's point that time decides whether a 1- and a 2-point lead differ: team with the ball, up 1 vs up 2 won 59.5% vs
  72.8% (n 158 / 184) with 10:00-15:00 left, 64.7 vs 78.1 with 6:00-10:00, but 67.9 vs 63.2 with 3:00-6:00 and 94.4 vs
  90.4 inside 3:00. CK2 is now time-faded (the owner's call): the two are one state in full inside 6:00, fading to none
  at 8:00; above that the general model's pricing, which matches those games. The try at 18-20: kick at 12:00 (-1.3,
  inside the toss-up band's edge), 10:00 (-1.8), 8:00 (-1.4); go for two at 7:00 (+3.0), 4:00 (+5.8), 1:30 (+11.6).
  (CJ) check (1) rerun: PASS (Brier 0.1532), 79.3% agreement with nfl4th.
- **PRE-REGISTERED 2026-10-23 (owner: "worth checking why" [4th & 6+ conversion read 30.0% vs 26.9%] ... "are we
  factoring offensive production from that team during that game/season? teams that have proven to themselves they
  can move the ball better are more confident and i assume more successful" ... "is there a certain distance where
  going for it on 4th down tendency drops off hard?"): (CM).** (a) Diagnosis, no gate: 4th-down tries vs 3rd downs vs
  the model (asked at down 3) by distance, and 4th & 6+ split by situation (4th quarter, last 5:00 and behind =
  desperation, vs the rest). (b) Descriptive, no gate: the share of 4th downs where teams go for it, by distance
  (2022-25, excluding the last 5:00 and the 1st half's last 2:00). (c) Offense form, gated: does the offense's yards per
  play so far in this game (its runs and passes before the snap) and so far this season (games before this one,
  shrunk to the league by 200 plays) predict 3rd / 4th-down conversion beyond the current model? Logistic on the
  model's log-odds (offset-style input) + the two form terms, fit 2018-23, tested 2024-25 on 3rd and 4th downs. Gate:
  Brier lower than the model alone by a 95% bootstrap interval (games resampled) that excludes zero; if it passes,
  the form terms join the conversion model with its own check rerun.
- **RESULT {#conv-form} (CM): (a) the long-try "overestimate" was the check, (b) the go rate by distance, (c) offense
  form: FAIL.** tools/conv_form_eval.py. (a) The model counts a defensive penalty that gives a first down as a
  conversion (nfl4th's coding); the (CJ) follow-up check dropped those plays (play_type no_play), and on long 4th
  downs they are a real share of conversions. Counting them (2022-25): 4th & 6+ in desperation (4th quarter, last
  5:00, behind) converted 29.1% (351) vs the model's 27.6%; the other long tries 42.1% (309) vs 33.3%: teams choose
  those (the selection effect, as at short distance). By distance, 3rd downs / 4th-down tries / model: 1-2 65.2 /
  68.1 / 65.2; 3-5 50.1 / 57.8 / 50.8; 6-7 42.1 / 44.1 / 41.1; 8-10 33.8 / 34.5 / 33.2; 11+ 18.3 / 27.9 / 17.8.
  (b) Teams going for it, 2022-25 (not the last 5:00 or the 1st half's last 2:00): 4th & 1 69.5%, 2 36.6%, 3 25.6%,
  4 17.7%, 5 11.5%, 6 7.2%, 7 6.2%, 8 4.5%, 9 2.5%, 12+ 1.8% (in the opponent's half 89 / 58 / 43 / 29 / 18 / 12 / 10
  / 8 / 4%): the steep drop is after 4th & 1, and from 4th & 6 it is the exception. (c) This game's yards per play
  before the snap (shrunk by 20 plays) and the season's (by 200) on top of the model's log-odds, fit 2018-23, 2024-25
  3rd and 4th downs (14,860): Brier 0.2142 -> 0.2141, -0.00006 [-0.00016, +0.00003]: FAIL. Conversion does rise with
  this game's form (worst to best fifth, 4th downs: 50% -> 63%) but the model already follows it (52% -> 61%) through
  field position and the Vegas line (which prices the season); the form terms add nothing.
- **PRE-REGISTERED 2026-10-23 (owner, on ATL tied at its own 45 with 0:08 and no timeouts: "you very clearly want to go
  for overtime here ... the realistic likelihood you will get into fg range from there and be able to kick without a
  timeout must be tiny"): (CN) a last-seconds table.** The calculator said go (55.5% vs the punt's 49.7%) because the
  win model read ATL after a conversion (1st & 10 near midfield, 0:03, tied) at 85%. Real games, 4th quarter, 0:12 or
  less, tied, ball 45-60 yards from the end zone: won 48.5% (33, with a timeout) and 50.0% (40, without); the model
  (fit 2006-18) 65.0% / 62.5%. Change: for 4th-quarter states with 12 seconds or less and the score within 3, the
  win chance is the measured rate for (behind 1-3 / tied / ahead 1-3) x field position (inside the opponent's 25,
  25-35, 35-45, 45-60, own side) x the offense has a timeout, shrunk toward the model by 20 states. Gate: fit on
  2006-18, on 2019-25 such states Brier lower than the model's; if it passes it goes into the engine and (CJ)
  check (1) is rerun.
- **RESULT {#lastsec-table} (CN) the last-seconds table: FAIL.** 2019-25, 549 4th-quarter states with 0:12 or less,
  score within 3: Brier 0.1393 vs the model's 0.1380 (cells of 10-40 games are as noisy as the model). In the owner's
  cell (tied, ball 45-60 yards out) the games did read 45-58% won vs the model's 59-68%.
- **PRE-REGISTERED 2026-10-23: (CN2) the last snap as football rules, not a fit.** When a 4th-quarter state leaves one
  snap (or none), the win chance comes from what that snap can do: a field goal (the page's make rate; the kick
  distance up to 70) or a heave for a touchdown (measured on half-ending passes with 0:06 or less, 2006-25: inside 20
  yards 30%, 20-50 yards 3%, 50-60 1.5%, beyond 0.3%), whichever is better for the team with the ball (a leader takes
  a knee); then the score decides, a tie is overtime at 50%. The number of snaps left: after a change of possession
  (a failed 4th down, a punt, a kick) the clock stops, one snap if 0:12 or less remain; after a conversion in bounds
  with no timeout the clock runs, and a spike or another snap needs about 10 seconds (the measured spike gap), so
  under 0:10 the game ends unless the play went out of bounds (13.6% of late 4th-down conversions); with a timeout,
  one snap. Test: 2019-25 4th-quarter snaps with 0:06 or less and the score within 8 (the last snap): the rule's win
  chance vs the model's (fit 2006-18). Gate: Brier lower than the model's. If it passes it goes into the engine and
  (CJ) check (1) is rerun.
- **RESULT {#last-snap} (CN2) the last snap as football rules: PASS, shipped.** 2019-25, 493 4th-quarter snaps with
  0:06 or less, score within 8: Brier 0.0880 vs the model's 0.1014 (fit 2006-18). Tied, ball 45-60 yards out: won
  50%, rule 51%, model 66.5%; behind 1-3 inside the opponent's 25: won 51.6%, rule 53.4%, model 40.0%. In the engine:
  wp() of a 4th-quarter state with 0:06 or less is its last snap; after a change of possession with 0:12 or less the
  other team gets one snap; after a conversion with 0:12 or less, one snap with a timeout or 10+ seconds (a spike),
  else only if the play ended out of bounds (13.6%). The owner's play (ATL, tied, own 45, 0:08, no timeouts): go now
  40.9% (converts 47.3% -> 53.4%, fails -> 29.8%) vs the punt's 49.7%: the punt is the right call (it read go +5.8).
  (CJ) check (1) rerun: PASS (Brier 0.1533), 79.2% agreement with nfl4th.
- **PRE-REGISTERED 2026-10-23 (owner, on the top-20 list: "lots of them, if you fail the conversion your win chance
  tanks to very low, and if you play conservative ... you retain a reasonable chance to win. it's like teams favor
  prolonging their substantial chance to win over going for the throat" ... "ya"): (CO) the branches as forecasts.**
  (CJ) checked the blended number of the chosen option; a model too kind to failure could still pass there if it were
  also too harsh on success. Here each branch is checked on its own: the same 2022-25 regulation 4th downs and walk-
  forward model files as (CJ), each graded with the current engine; for tries, the play's actual result (converted:
  fourth_down_converted or the offense's touchdown; else failed) picks the branch, and the forecast for that branch
  (win chance if it works / if it fails, as the page shows) is compared with the share of those games won; the same
  for field goals (made / missed). Gate (all): per branch (go-converted, go-failed, fg-made, fg-missed) the mean
  forecast within 3 points of the share won, and no decile of 50+ off by more than 6 (as (CJ)). Reported, no gate:
  the fail branch on the 4th quarter alone and on tries from the own side of the field (the list's typical spot).
  Penalty plays (no_play) are out, as in (CJ). If the fail branch reads high (too kind), the engine's "after a failed
  4th down" state is examined before anything ships.
- **RESULT {#branch-calib} (CO) the branches as forecasts: FAIL (deciles); the fail branch is NOT too kind.**
  tools/calc_validate.py branches, 2022-25 (3,151 tries, 53.9% converted; 3,923 field goals, 85.8% made). Won minus
  forecast, 95% interval by games: go failed +0.5 [-0.9, +2.2] (1,452; 4th quarter +0.1, 4th quarter on the own side
  +1.7 of 283): the owner's worry, that losing the ball on downs is worse than the page says, does not show. Go
  converted -1.0 [-2.8, +0.7] (1,699) but mid-range reads high: forecasts 40-80% -4.6 [-9.2, -0.3] (519; deciles 0.5
  -6.0, 0.7 -8.2): after a conversion the page is too generous by about 4-5 points there, which inflates "go" by
  roughly p x that (2-3 points) on plays like the top-20 list's own-side punts. Field goal missed -3.3 [-6.4, -0.5]
  (558; 20-70% forecasts -6.4): the state after a miss reads too kindly. Field goal made passes (-0.7). Deciles off by
  more than 6 with 50+: go converted 1, go failed 1 (0.6: -11.7 of 64), field goal missed 3. Not shipped (no change was
  proposed); the two over-reads are the next things to examine (the state the engine uses after a conversion: the
  average gain and its clock; after a missed kick: the spot and the clock).
- **FINDING 2026-10-23: (CO2) where the two over-reads come from.** tools/branch_eval.py / .mjs: for converted tries
  and missed field goals 2022-25, the real next snap (its clock, spot, score, timeouts) scored with the same engine
  wp(), beside the branch. Won minus forecast: converted (1,376 with a next snap in the quarter) branch -1.2 [-3.2,
  +0.8], real next state -1.0 [-3.0, +0.9] (forecast 40-80%: -5.1 vs -4.7); missed field goal (532) -3.3 vs -3.2
  (40-80%: -8.5 vs -8.3). The engine's assumed next state is not the cause: the win model itself reads these states
  high (the team after its conversion, the team whose kick missed). The 40-80% slices were picked after seeing the
  deciles, so their intervals overstate the evidence; the missed kick's -3.3 overall is the firmer one. One real
  assumption error did show: after a conversion the engine runs 5 seconds; the real median is 37 (the clock runs
  after an in-bounds play). With 39 s the converted branch reads -0.5 overall, 4th quarter +0.5.
- **PRE-REGISTERED 2026-10-23 (owner: "time outs, 5 seconds would be accurate. spiking also 9-12 or whatever. hurry up
  offense isn't letting 40 seconds burn"): (CO3) the clock after a conversion.** After a converted 4th down (not a
  touchdown) the next snap comes at the offense's measured pace for the situation (runOff: half, time band, leading or
  not; 39 s normally, ~21 trailing inside 2:00, stopping at the two-minute warning), unless the clock stops: an out-of-
  bounds play (13.6%) stops it only where the rules do (a half's last 2:00 in the 1st half, the last 5:00 of the 4th
  quarter) and only for a team not ahead (a leader stays in bounds); in those same windows a team not ahead with a
  timeout takes the better of calling it (the clock at the whistle, one timeout fewer) and letting it run. The last-
  seconds rule (CN2) is unchanged. Gate (both): (1) on the (CO) rows, the converted branch's |won minus forecast| below
  the current 1.0 points and its Brier no worse; (2) (CJ) check (1) still passes. Nothing changes for the win model's
  own over-read (CO2); that needs its own test.
- **RESULT {#conv-clock} (CO3) the clock after a conversion: PASS (narrow), shipped.** On the (CO) rows the converted
  branch's won minus forecast -1.00 -> -0.90 points, Brier 0.13851 -> 0.13810 (1,699 tries, 2022-25); (CJ) check (1)
  PASS (go 35.1 vs 34.6 won, field goal 56.5 vs 55.6, punt 47.3 vs 47.2), same recommendation as nfl4th 78.9%. The win
  model's own over-read of these states (CO2) stays.
  Also fixed (a bug, owner 2026-10-23: "does our engine know the difference between a team winning with 1:59 left,
  defense has 3 timeouts vs 0?"): the kneel-out rule ignored the down. Now each down left after the snap runs ~40 s
  off and each defensive timeout takes one back (1st down: nfl4th's 2:00 / 1:20 / 0:40); up 3 at 1:59, 3rd & 10 at
  the own 30, no defensive timeouts read 100%, now 84.1%. (CJ) check (1) above includes it. The model itself barely
  separates the defense's 3 timeouts from 1 (90.6% vs 90.9%, up 3, 1st & 10 at the own 30, 1:59); 2022-25 games are
  too few to say it should (12-110 per cell, no clear gradient short of 0).
- **AMENDED 2026-10-23: (CO3) the defense's timeout.** As shipped, after a conversion late in a half only the team not
  ahead with the ball could stop the clock; a defense behind could not, so its timeouts let ~40 s run. Now a defense
  behind takes the better (for it) of calling one and letting it run. Converted branch -0.89 (Brier 0.13804); (CJ)
  check (1) PASS, same recommendation as nfl4th 79.0%.
- **PRE-REGISTERED 2026-10-23 (owner: "should we be focusing on the winprobability model itself rather than this
  decision calculator? ... the calculator would benefit if we can calibrate the win probability engine better" ...
  "ya"): (CP) a situational audit of the win model.** The general fit is near nflfastR (CG) and three general changes
  failed (CK, CL, CN); what moves decisions is error in particular states the calculator values, so each is checked on
  its own. Model: the browser engine's wp() (the win model plus its rules: kneel-out, last snap, the late 1-2 rule)
  with a model file fit through 2018 (tools/calc_build.py --through=2018); rows: regular-season snaps 2019-25 (runs,
  passes, kneels, spikes), the team with the ball's win chance vs whether it won. Slices (a state can be in several):
  the next snap after a converted 4th down (same team); the other team's first snap after a failed 4th down, a punt, a
  missed field goal, an interception or lost fumble; a drive's first snap after a kickoff; the 4th quarter's last 5:00
  with the score within 8, split by who has the ball (leading / not) x the other side's timeouts (0-3); the same by the
  offense's own timeouts; the 4th quarter 2:01-2:40 and 1:20-2:00 (either side of the warning); all snaps (reference).
  A slice is FLAGGED only if won minus forecast has the same sign in 2019-21 and 2022-25, the 95% interval (games
  resampled) excludes zero in both, and the pooled gap is 1.5 points or more. Only flagged slices get a fix, each its
  own pre-registered test (football rules first, as CN2); nothing ships from the audit itself. Slices of fewer than
  300 snaps per period are reported but cannot be flagged.
- **RESULT {#wp-audit} (CP) the situational audit: nothing flagged.** tools/wp_audit.py / .mjs, 233,334 snaps 2019-25,
  the engine's wp() with a model fit through 2018 (that file's try rates are placeholders, 0.94 / 0.48: the tries
  table uses only recent seasons and wp() does not read it). Won minus forecast, 2019-21 | 2022-25 | pooled: all snaps
  +0.2 | +0.1 | +0.1; after a converted 4th down -0.3 | -1.0 | -0.7; the other team after a failed 4th down +0.8 | -0.7
  | -0.1; after a punt +0.8 | +0.1 | +0.4; after a missed field goal (the receiving side) +1.4 | +2.6 | +2.0 (n 409 /
  546: (CO)'s over-read of the kicking side, same direction, intervals include zero in both periods); after a turnover
  -0.1 | +0.8 | +0.4; after a kickoff +0.3 | +0.5 | +0.4. Late (last 5:00, within 8) by either side's timeouts: no cell
  consistent across the periods (signs flip in most, cells of 120-2,500 snaps); 2:01-2:40 -1.3 | +0.1, 1:20-2:00 -1.7 |
  +1.0. The win model's errors in the states the calculator values are within what seven seasons can detect; (CO)'s
  over-reads were mostly noise (converted) or small (the missed kick, ~2 points, not established). No fix is proposed.
- **PRE-REGISTERED 2026-10-23 (owner: "do we get more accurate if we factor in our power rankings ... what if it was
  aware that a teams offensive matchup is much better than defense? E.G. punting during a shootout looks worse than
  going for it on 4th in midfield" ... "try it"): (CQ) the game's scoring level in the win model.** Not our power
  rankings: the game model does not beat the lines (above), and the win model already has the spread. What it lacks is
  the over/under: it values a 7-point lead with 8:00 left the same in a 38 and a 54 total game. Variants of the (CG)
  model, same settings and rows: (A) + the total (over/under, 45 if missing) and the points expected in the time left
  (total x game seconds left / 3600); (B) = (A) + this game's pace: points scored so far minus the total's share for
  the time played. Walk-forward, each of 2022-25 fit on 2006 through the season before. Gate per variant: (1) pooled
  2022-25 Brier lower than the comparison (A vs the current model; B vs A) with a 95% interval (games resampled,
  paired) that excludes zero; (2) the late-and-close Brier (4th quarter, within 8) no worse than the comparison's +
  0.001; (3) no calibration decile off by more than 3 points. A passing variant goes into the engine (the page and the
  gamecast supply the total, and for B the score), then (CJ) check (1) is rerun. Reported, no gate: the calculator's
  punt-vs-go at midfield (tied, 4th & 2, own 45, 8:00 in the 4th) at totals 38 and 54.
- **RESULT {#wp-total} (CQ) the game's scoring level in the win model: FAIL (both); not shipped.**
  tools/wp_total_eval.py, 167,680 rows 2022-25 walk-forward. Brier all / late-and-close: current 0.15544 / 0.17137,
  (A) + total and points expected in the time left 0.15477 / 0.17098, (B) + this game's pace 0.15496 / 0.17202
  (nflfastR 0.15431). (A) vs current -0.00067 [-0.00201, +0.00078]: the right direction, inside the noise (late-and-
  close and deciles pass). (B) vs (A) +0.00019 [-0.00035, +0.00075], late-and-close worse (+0.00105), a decile off 3.1:
  the game's scoring so far adds nothing beyond the total (as (CM) found for conversion). What the total does in (A):
  pick'em, ball at the own 25, 4th quarter: up 3 with 8:00 left 71.2% at a 38 total, 71.3% at 46, 66.7% at 54; up 7
  86.0 / 86.3 / 85.2; up 3 with 4:00 left 79.4 / 80.0 / 77.0. The shootout effect is real in football terms but small
  (a few points, only at high totals) and the data can't confirm it. The punt-vs-go scenario was not computed: no
  variant reached the engine. The conversion model already uses the total (CI).
- **FINDING + FIX 2026-10-23 (owner: "let's investigate the biggest differences between nfl4th and our model"): (CR)
  where we and nfl4th disagree.** The 25 largest gaps (calc_validate.py analyze) were nearly all in the last 0:35 or
  trailing 1-3 in field goal range inside 3:00. (a) A bug from (CO3): a team behind with no timeouts that converted
  with ~0:15-0:25 left let the clock run at its pace (~21 s) and lost the game; it can spike (a down for ~10 s). Fixed
  (nextSnap takes the best of running, spiking, a timeout). IND down 1 at the SEA 38 with 0:22 and no timeouts: "if it
  works" 10.6% -> 68.5%; JAX down 3 at the LV 30 with 0:20: 8.0 -> 47.7. (CJ) check (1) PASS; same recommendation 79.0%,
  gap correlation 0.871 (was 0.863); (CO3)'s converted branch -0.92 (Brier 0.13811). (b) Trailing 1-3 in field goal
  range inside 3:00 (e.g. down 2 at the 4 with 2:42: ours go +7.7, nfl4th field goal +9.1): the zone (CH) found every
  model misreads; real games 2006-25 hold 14-28 per timeouts cell (down 1 with the ball, 1:20-3:00, own 20-40: won 14%
  with no timeouts, 54-57% with 2-3), too few to settle it. (c) Where the go-vs-kick gaps differ by situation (15,342
  plays 2022-25): inside the opponent's 30 our "go" reads ~0.8-0.9 points above nfl4th's with the kicks equal; by score,
  down 1-8 +0.5; elsewhere a few tenths. Outcomes cannot settle it: on the plays teams chose, by zone, both forecasts
  are within ~1.5 points of the share won (inside the 30: tries won 43.6% / 40.1%, ours 44.9 / 40.3, nfl4th 44.5 /
  39.5), and nfl4th's Brier is a little lower in most zones (significant only on punts from the own 1-25: +0.0027),
  with its numbers fitted on these seasons and ours walk-forward. The red-zone lean is under the toss-up band (1.25).
- **FINDING 2026-10-23 (owner: "how often does our model disagree with a decision that ends up in a loss for the
  deciding team?"): (CS) teams that defied the calculator.** tools/calc_defied.py, 15,440 4th downs 2022-25 (walk-
  forward). We disagreed with 34.3% of the decisions by teams that lost and 35.2% by teams that won (by 3+ points:
  4.5% vs 4.9%): one 4th down moves a game a few points, so losing says little about the call. Teams we disagreed
  with by 3+ lost 51.3% against the 57.0% our numbers gave their choice. When we said go by 3+: teams that went won
  41.0% vs our go forecast 40.6% (+0.4 [-2.6, +3.6]); teams that kicked won 48.6% vs our kick forecast 42.7%: +5.9
  [+2.8, +9.0] (punts +4.8, field goals +7.4; 2022 +7.9, 2023 +7.7, 2024 +5.9, 2025 +1.4); nfl4th's kick numbers are off
  the same way (+5.4 [+2.1, +8.7]). Two readings, not separable here: coaches who kick in those spots know something
  neither model sees (their own team, injuries, weather, the matchup), which would also make "go" worse for them than
  the forecast; or both models underrate the kick where they most favor going. Either way our largest "go" margins
  are likely overstated by up to several points for the teams that chose to kick. Not tested against a gate; a
  shrinkage of the go-minus-kick edge (fit 2022-23, tested 2024-25) is the obvious next test.
- **PRE-REGISTERED 2026-10-23 (owner: "sure"): (CT) shrinking the calculator's margin toward the team's choice.**
  From (CS): where the calculator prefers one option, teams that chose the other did better than its forecast. Model:
  the chosen-against option's value moves toward the preferred one by a share of the gap: kick' = kick + a x max(0,
  go - best kick) and go' = go + b x max(0, best kick - go), a and b fit by least squares (through zero) on 2022-23 on
  the plays where the team chose that option (won minus forecast against the gap). Test on 2024-25: (1) on the plays
  where teams chose against the calculator (either way), the Brier of the adjusted forecast lower than the unadjusted
  one with a 95% interval (games resampled, paired) that excludes zero; (2) (CJ) check (1) still passes with the
  adjusted numbers. A pass would shrink every displayed margin by the fitted shares and the toss-up band and
  "questionable" line would be re-derived; the page would say the margin is "for a team like this one that has chosen
  otherwise" only if the shares come out materially different (caveat: the fit can only see teams that chose, so it
  cannot separate coaches' private knowledge from a shared blind spot of the models).
- **RESULT {#margin-shrink} (CT) shrinking the margin toward the team's choice: FAIL; not shipped.**
  tools/calc_shrink_eval.py. Fit 2022-23: a = 1.19 (a kick chosen against "go" moved more than the whole gap toward
  go, on 2,367 plays), b = 0.77 (222 tries against "kick"). On 2024-25's 2,536 plays against the calculator the Brier
  got worse, 0.13977 -> 0.14015 (+0.00038 [-0.00036, +0.00106]); teams that kicked when it preferred going won 46.0%
  against its forecast of 46.1%: no shortfall at all in those seasons (any margin; (CS)'s +5.9 was at 3+ points and
  mostly 2022-24). (2) also fails (field goals 57.2% adjusted vs 55.6% won). (CS) reads as mostly 2022-23 and noise,
  not a stable bias; the margins stay as computed.
- **SHIPPED 2026-10-23 (owner: "the tag is just an aesthetic ... i just want it to be realistic, in line with how ESPN
  might list them"): the expected Friday tag (display only; no chance to play changes).** Before a team's final
  report, a player on its practice report shows the designation he most likely gets on it, from 2018-25 3-day report
  weeks (tools/tag_odds_build.py -> data/history/tag_odds.json): keyed by whether he missed his last game while on
  its report and his practice days so far (a day before he was added counted as full), the likeliest official tag
  when it is at least an even bet, else Q. E.g. missed last game, LL: Q (60.5% Q / 25% none / 11% Out, played 61%);
  played last game, F: none (89.5%); missed, DD: O (84%); played, D: Q (mixed: O 35 / none 34 / Q 26). Overrides, in
  order: reserve lists, game-day actives / inactives, the final report, ESPN's fresh Out / Doubtful once reports are
  out (and Out with a return date past the game before them), ESPN's "Active" posted after the team's latest report
  (no designation coming: Judkins, LL after missing week 6, ESPN Active 2:28 pm ET Friday; build_espn_bridge(active)).
  Before the first report the old rule holds (Q if he missed his last game hurt or was hurt in it and not back).
  Our own tags carry tx = 1 in the week data; the card's pill tip says "Expected Friday tag". Measured alongside
  (owner: "how often do players miss last week, get marked active on friday ... and don't actually play"): missed
  his last game, no designation on the final report: played 88.9% (n 2,144; LL 91.7%, LLF 92.3%) vs 98.8% for a
  player who played his last game. ESPN's midweek Active as a chance-to-play input is NOT shipped: past ESPN captures
  (the public page) never list Active players, and our own archive with it starts 2026-10-13; it needs a
  prospective check first.
- **PRE-REGISTERED 2026-10-23, SHIPPED PROVISIONALLY (owner: "can we fix it"): {#espn-active} ESPN's Active before
  the final report moves the chance to play.** A player on his team's practice report whom ESPN marks Active after
  the team's latest report (ESPN update at or after 4 p.m. ET of that report's day; fresh: after his last game,
  before kickoff), while the final report is not out and no game-day ruling stands: P(plays) = the play rate of
  players with NO designation on the final report in his spot (missed his last game while on its report or not,
  practice days so far, a day before he was added counted as full; 2018-25, tag_odds.json "cleared", the longest
  matching start with 50+): missed last game, LL 92.0% (n 564), LF 92.1%, FF 85.9%; played it, LL 98.5%. Measured
  rates, nothing fitted. It can't be backtested (past ESPN captures never list Active players; our archive with it
  starts 2026-10-13), so it is judged going forward: run.py archives each override (data/live_inputs/
  espnactive_<season>_<week>.json: the model's chance before it, the rate set, the ESPN time) and
  tools/espn_active_audit.py scores them against snap counts. GATE once 40+ player-weeks are in: the played rate's
  95% Wilson interval includes the mean rate the rule set, AND the rule's Brier is below the model's pre-override
  Brier on the same players. Fail -> the rule comes out of availability (the tag clearing stays: display only).
  Live: Judkins (CLE, missed week 6, LL, ESPN Active 2:28 pm ET Friday) 77% -> 92%.
- **PRE-REGISTERED 2026-10-24 (owner: "shouldn't every guy dealing with injury be comparing his record, the practice/
  game participation of the last 2 weeks AND this week, or maybe even total practice record since the injury ...
  also considering espn return date?" ... "yes"): two inputs for the one week model (I2), tested separately against
  it as shipped, same rows, labels, settings and per-stage calibration (tools/week_avail_eval.py harness).**
  (CU) ESPN's estimated return date: ret_gap = days from ESPN's return date to this game (negative: the date is before
  the game; positive: after), and ret_out = ESPN's status bucket (Out / Doubtful / Questionable / IR / none), both as
  known at the row's stage (the latest ESPN capture before that stage's cut: Tuesday 23:59 ET, Wednesday / Thursday
  report day 22:00 UTC, final report day 22:00 UTC; captures from cache/espn_injury_history + espn_injury_midweek
  (Wayback, 2022-24) and the live archive (2025-26)); NaN where no capture exists. Rows without any capture keep NaN
  (the trees route them as missing). Today ESPN reaches availability only through fixed rules on top of the model
  (midweek Out / Doubtful rates, Out with a return date past the game, the early-week bridge, game day, Active);
  a return date ON or BEFORE the game is used nowhere. Test seasons: those with captures for both training and test
  (walk-forward 2023-25 if 2025's archive covers it; else 2023-24, stated).
  (CV) week by week since the injury: last week's practice counts (D / L / F) and his final tag there, and the week
  before's, as separate inputs (the model now sees last week's counts and one total over the whole run, so order
  across weeks - improving vs worsening - is lost except last week's last day). ep_* totals stay.
  GATE (each, as (J)): final-report Brier lower with the 95% interval over season-weeks excluding 0; Wednesday and
  Thursday interval upper < +0.002; no position significantly worse; calibration deciles within 4 points; the same
  direction on the untouched 2026 weeks 1-6. A pass ships into the week model; (CU) also replaces the fixed ESPN
  rules it covers only if a follow-up shows the rules add nothing on top of it.
- **PRE-REGISTERED 2026-10-24 (owner: "take a player who was dnp dnp dnp missed game lp lp full, find all players who
  had that exact pattern, take the historical rate they played and use it as a base weight for the model"): (CW) the
  exact-pattern prior.** Each row's pattern = his run on the reports since it began (consecutive report weeks, a bye
  bridged): every past week's practice letters + whether he played that week's game, then this week's letters so far
  (at the row's stage; game status not part of the key). Measured first (2023-25 rows vs 2018-22 history): the whole
  run has 50+ exact matches for 47% of rows and none for 27%; last week + this week has 50+ for 71% (the owner's
  example DDDM|DLLM|LLF: 4 matches 2018-25, 3 played). Input pat_rate: the played rate of the longest key with 50+
  matches among (whole run, last two weeks + this week, last week + this week, this week + games missed in a row),
  each level shrunk toward the next shorter one by 20 pseudo-cases; computed for season s from seasons before s only.
  Added to the one week model (I2) as shipped, same rows / labels / settings / calibration. Same GATE as (CU) / (CV).
  Also reported, no gate: pat_rate alone (no model) vs the model, by stage.
- **PRE-REGISTERED 2026-10-24 (owner: "considering differing practice schedules before thursday/monday games we need a
  way to normalize those schedules right?" ... "whatever you think"): (CX) rest and estimated reports in the week
  model.** The calendar stages (AS) already align report 1 / 2 / final across Thursday, Sunday and Monday games; what
  they don't carry: (a) rest = days from his team's previous game to this one (bye weeks capped at 14); (b) est = the
  share of this week's report days so far that came within 2 days after his team's previous game (a Thursday team's
  Monday / Tuesday entries are typically estimates of a walkthrough, not a practice; NFL.com's feed has no estimated
  flag, so the timing is the proxy). (AQ)'s short-week flag gained accuracy (short-week rows -0.0068 [-0.0099, -0.0034])
  but couldn't rule out a 2-point calibration loss on 1,079 rows; this is the continuous version with 2026's short
  weeks added. Added to the one week model (I2) as shipped; same GATE as (CU) / (CV) / (CW), plus on short-week rows
  (rest <= 5): Brier lower with the CI excluding 0 and calibration error (10-bin ECE) not worse than the shipped
  model's by more than 0.01.
- **INCIDENT + FIX 2026-10-24 (owner: Saquon Barkley "match up with what you think?"): the live injury model had
  drifted from a local build of the same code.** Barkley (missed 2 games, LL) 32.6% live vs 65.2% local (history:
  missed 2+ then LL played 60.5%, n 1,121); ~20 report players off by 3-25 points (Lamar Jackson QLLL 15% vs 37%,
  Baker Mayfield QFFF 60% vs 84%). Cause: the history tables the engine trains on are cached per season and never
  refetched; the live cache's 2018-25 practice tables had different practice DATES (the letters and outcomes were
  identical), and since the calendar stage construction (AS, shipped 2026-10-22) places each day on its team's report
  calendar by date, the live engine trained on a different week layout than it was fed. The engine's cache key held
  only row counts, so nothing noticed (likely since 2026-10-22). Fixed: the history refetched (undated seasons now
  refetch automatically, data.py), live numbers identical to local; the engine key now includes a fingerprint of the
  training history (run.training_data), and every build stops if that fingerprint differs from the committed lock
  (data/history/training_fingerprint.json; tools/training_lock.py --bless to accept a deliberate change). Every
  build also prints the history column by column (tools/cache_fingerprint.py).
- **SHIPPED 2026-10-24 (owner: "can't we just compare exact matches to practice participation patterns?"): the
  availability check in every full build.** tools/avail_check.py: the one week model as the site builds it, trained on
  seasons before the last complete one, predicts that season's rows; each exact pattern (stage x game status x report
  line so far) with 100+ rows must sit within 3.29 standard errors (99.9%) + 3 points of the share who played, else
  the build stops before deploying. First run (2025 rows, 29,042): 22 patterns, all pass; overall 77.0% predicted vs
  76.3% played; widest gaps stage-1 D +3.8 (allowed 6.9) and stage-2 DD +4.6 (allowed 6.3). Deterministic for a given
  history. It checks the model; the training-data lock checks the data (the 2026-10-24 drift was a data problem the
  model check alone would not have seen: training and test rows were built the same wrong way).
- **RESULT {#weekly-history} (CV) week by week since the injury: FAIL; not shipped.** tools/cv_weekly_eval.py (branch
  test/cv; flag tuesday.CV_WEEKS, off): the one week model + the week before last's practice counts and final tag
  (last week's were already inputs: n_D/n_L/n_F, status), walk-forward 2021-25, 75,489 on-report rows (38.5% also on
  the report the week before last). Final report 0.08749 -> 0.08789, +0.00040 [-0.00006, +0.00090], better 1 of 5
  seasons; Wednesday +0.00022, Thursday +0.00044 [-0.00002, +0.00091]; worst final decile 4.0 points (over the gate);
  TE significantly worse Wednesday and Thursday; 2026 weeks 1-6 worse at every stage (+0.00019 / +0.00001 / +0.00005).
  Last week + the totals since the injury already carry what the earlier weeks add.
- **RESULT {#pattern-prior} (CW) the exact-pattern prior: FAIL; not shipped.** tools/cw_pattern_eval.py (branch test/cw;
  flag experiments.pat_prior, off). Coverage 2021-25 (level used: whole run / last 2 weeks / last week / missed run /
  none with 50+): Tuesday 69 / 10 / 17 / 4 / 0%, final report 45 / 5 / 14 / 27 / 9%. One week model + pat_rate vs as
  shipped: final report 0.0875 -> 0.0882, +0.0007 [+0.0001, +0.0014] (significantly worse), better 2 of 5 seasons,
  worst decile 4.9 points; Wednesday +0.0001, Thursday +0.0001; no position significantly worse; 2026 weeks 1-6
  Thursday +0.0003 (wrong way), Wednesday / final better. pat_rate alone vs the model (Brier): Tuesday 0.163 vs 0.142,
  Wednesday 0.163 vs 0.135, Thursday 0.128 vs 0.110, final 0.111 vs 0.088. The model already reads the run (games
  missed in a row, the practice totals since the injury) with role, injury and the rest; the exact-key rate is a
  noisier copy of it.
- **RESULT {#rest-est} (CX) rest and estimated reports: FAIL; not shipped.** tools/cx_rest_eval.py (branch test/cx;
  flag experiments.rest_est, off). 75,489 on-report rows 2019-26; 5,024 short-week (rest <= 5), 11,075 with est > 0.
  Final report 0.0875 -> 0.0879, +0.0004 [-0.0000, +0.0008], better 2 of 5 seasons, worst decile 5.1 points;
  Wednesday +0.0003, Thursday +0.0004; no position significantly worse; 2026 weeks 1-6 better at every stage
  (-0.0007 / -0.0011 / -0.0013). Short-week rows (3,849 scored): 0.0979 -> 0.0979, +0.0000 [-0.0019, +0.0020] (no
  gain); ECE 0.0157 -> 0.0149. (AQ)'s short-week gain (-0.0068 on the old practice model) is gone under the one week
  model, which already reads the calendar stages and days off the report. 2026's improvement is worth a season-end
  recheck; nothing ships on it.
- **RESULT {#espn-return} (CU) ESPN's return date in the week model: FAIL (data-limited); not shipped.**
  tools/cu_espn_return_eval.py (branch test/cu; flag experiments.espn_ret, off). Captures: Wayback 2022-24 (rows with a
  capture within 7 days of the stage cut: 2022-23 100%, 2024 93-94%), 2025 only 4 captures (9-13%), 2026 from the
  live archive from week 6 on; seasons before 2022 none. So walk-forward 2023-24 only, trained on 2022(-23) ESPN rows.
  Final report 0.0898 -> 0.0891, -0.0006 [-0.0016, +0.0003]; Wednesday -0.0015 [-0.0033, +0.0003]; Thursday -0.0006;
  deciles 4.2 / 4.7 points over the 4-point gate; QB -0.0060 [-0.0143, +0.0015]; Questionable rows slightly worse;
  2026 weeks 1-6 worse at every stage (+0.0012 / +0.0002 / +0.0007). The right direction 2023-24 but inside the
  noise with two ESPN training seasons. RETEST when the live archive holds a full season (2027), with ESPN's live
  feed wired into the model's live rows (not wired in the test branch).
- **FINDING + PRE-REGISTERED 2026-10-24, SHIPPED PROVISIONALLY (owner: "lamar just got downgraded. don't fix, let's
  test our auto system" ... "you call"): {#late-downgrade} ESPN's downgrades after the final report.** The watcher test
  worked end to end (ESPN Out 19:35Z; a news build started by the watcher at 20:06Z after two queued full builds, live
  20:12Z with the site's ESPN copy reading "downgraded to out"), but the page kept Lamar Jackson at Q / 37%: once a
  team's final report is filed it outranks ESPN until game day, so a Saturday downgrade was ignored. Rule: a player on
  a team whose final report is out, whom ESPN lists Out or Doubtful with an update at or after 4 p.m. ET of that
  final report's day (and before kickoff), takes ESPN's tag and the measured rate: Out 0 (official Out 0.4% played,
  n 2,417 after missing his last game; the team has ruled him out), Doubtful 2.8% (the midweek Doubtful rate,
  espn_midweek.json). Game-day rulings still win. Each override is archived (data/live_inputs/espnlate_<season>_<week>
  .json: the chance before it, the rate set, ESPN's time) and tools/espn_late_audit.py scores them against snap counts.
  GATE once 30+ player-weeks are in: no Out override played more than 1 time in 30 (else the rule comes out), and the
  overrides' Brier below the pre-override chances' on the same players.
- **PRE-REGISTERED 2026-10-24 (owner: "those tests i wonder if we framed them correctly, as parts of the model itself
  rather than a replacement of the entire model?" ... "you call"): (CW2) the exact-pattern rate as the model's starting
  point, (CW3) as a blend.** (CW) gave pat_rate to the one week model as an input; the owner's "base weight" reads as a
  starting point. (CW2): the gradient boosting starts from logit(pat_rate) per row (an offset: the trees learn only
  the correction from it); (CW3): final = w x model + (1 - w) x pat_rate, w fit by least squares on the season before
  each test season's out-of-fold predictions. pat_rate exactly as (CW) built it (branch test/cw). Same rows, labels,
  walk-forward and GATE as (CW). Expectation stated before running: pat_rate alone is far weaker (final report Brier
  0.111 vs 0.088), so (CW2) likely does worse and (CW3)'s w likely near 1.
- **RESULT {#pattern-prior-2} (CW2) pattern rate as the starting point: FAIL; (CW3) as a blend: FAIL.** tools/cw2_eval.py
  (branch test/cw, untracked). (CW2): sklearn GradientBoostingClassifier with a per-row init = pat_rate (xgboost /
  lightgbm not installed; HistGradientBoosting has no per-row start). Final report 0.0875 -> 0.0891, +0.0016 [+0.0006,
  +0.0026], 1 of 5 seasons better, worst decile 4.2 points, 2026 worse at all stages (+0.0028 / +0.0025 / +0.0029).
  An ungated control (same booster, constant start) split it: the booster swap +0.0008 [-0.0001, +0.0017], the
  starting point a further +0.0008 [+0.0002, +0.0015]. (CW3): least-squares blend fit on the season before (out of
  sample): w on the model 0.74 (2021), 0.83, 0.93, 0.91, 0.95, 1.00 (2026); final report -0.0001 [-0.0004, +0.0002]
  (not lower), Thursday -0.0005 [-0.0008, -0.0002], 2026 unchanged (w = 1). Expectation stated before running held:
  three framings (input, starting point, blend), none adds to the one week model.
- **FINDING + PRE-REGISTERED 2026-10-24, SHIPPED PROVISIONALLY (owner: "go look at dylan sampson"): {#activated}
  activated off a reserve list.** Sampson (CLE RB) was activated from IR Saturday (ESPN: Active, "activated from
  injured reserve Saturday", 16:52Z), final report Questionable LLF; the page showed tag IR (weekly rosters still list
  him RES) and 44% (the week model's reserve-row inputs: an IR player practicing in his window plays ~38%).
  Measured (weekly rosters RES at the previous game -> ACT for this one, QB/RB/WR/TE 2019-25, played = any snap):
  played 88.9% of 521; final status none 100% (61), Questionable 97.0% (101; LLF 6 of 6, LLL 96%, FFF 95%), not on
  the report 84.7% (359). Rule: a player our rosters list on a reserve list whom ESPN marks Active after his last game
  (build_espn_bridge active, the freshness filter) is activated: his tag is his official one (not the reserve code);
  once his team's final report is out, his chance is the measured rate for his final status (none 0.99 capped,
  Questionable 0.97); Doubtful / Out on the final report and game-day rulings keep theirs; before the final report the
  week model's chance stands (tag only). Each override archived (data/live_inputs/activated_<season>_<week>.json:
  the chance before it, the rate set) and scored by tools/activated_audit.py. GATE once 30+ player-weeks: the played
  rate's 95% Wilson interval includes the mean rate set, and the overrides' Brier below the pre-override chances'.
- **PRE-REGISTERED 2026-10-24, SHIPPED PROVISIONALLY (owner: "what reasons do we have to not lean more heavily on espn?"
  ... "ya"): {#late-upgrade} ESPN's Active after the final report: the designation removed.** Mirror of {#late-downgrade}.
  Christian Kirk, Jordan Mason, Tank Dell: "activated ... and removed his questionable designation" (ESPN, Saturday)
  while NFL.com's copy still read Questionable. Rule: a player Questionable or Doubtful on his team's final report whom
  ESPN marks Active at or after 4 p.m. ET of the final report's day (before kickoff) has had the designation removed:
  no tag, and the measured play rate of players with no designation on the final report in his spot (cleared_rate:
  missed his last game or not x practice days; 85.9-98.5%); if he was also activated off a reserve list
  ({#activated}), activated with no designation: 0.99. Game-day rulings still win. Archived
  (data/live_inputs/upgraded_<season>_<week>.json) and scored by tools/upgraded_audit.py; GATE once 30+ player-weeks:
  the played rate's 95% Wilson interval includes the mean rate set, and the overrides' Brier below the pre-override
  chances'.
- **PRE-REGISTERED 2026-10-24 (owner, on the calculator's weakest zone, the last 3:00 trailing 1-3 in field goal range:
  "worth investigating further, agreed. ideas?" ... "looks good i think"): (DE) an endgame solved from football rules
  and measured play outcomes.** (CH)'s learned drive model failed; (CN2), rules + measured pieces for the last snap,
  passed (Brier 0.0880 vs 0.1014). DE extends that to the 4th quarter's last 3:00. State (team with the ball): seconds
  left 0-180, margin -8..+8, field position (5-yard bands), down, distance (6 buckets), both teams' timeouts, clock
  running or stopped. Offense actions: run, short pass, deep pass, spike, kneel, field goal, punt, each optionally after
  a timeout. Outcomes per action from 2006-18 play-by-play in like situations (yards, completion, sack, turnover, out of
  bounds, seconds the play takes, the clock after it: incompletions / out of bounds stop it, out of bounds only inside
  2:00, the 2:00 warning, a spike costs a down); field goals by the calculator's make-rate table; a touchdown takes the
  try (extra point / two at their measured rates; the better per the same table); a change of possession or score
  continues from the other team's side (kickoff spots as the calculator's). Values by backward induction from 0:00
  (score decides, tie = overtime 0.5). Policy: the EMPIRICAL mix of actions teams chose in like states (for the win
  chance; best actions reported separately for decisions). Check before the test: simulated drives from the own 25
  with 2:00 and with 1:00 left match real drives' seconds used and score rates within 10% each. Test: 2019-25 4th-
  quarter snaps with 3:00 or less, score within 8, vs the engine's wp() (the general model + kneel-out + last-snap +
  late 1-2 rule), model fit on 2006-18. GATE (both): (1) Brier lower with a 95% bootstrap interval over games excluding
  0; (2) mean absolute calibration gap over (CH)'s cells (time 0:30 / 1:00 / 2:00 / 3:00 x field position inside the
  opponent's 35 / to own 40 / deeper x tied, behind 1-3, behind 4-8, ahead 1-3, ahead 4-8; cells of 30+) lower than
  wp()'s. Pass -> wp() uses it inside the last 3:00 of the 4th quarter, the "rough" note goes, the Decisions pane grades
  two-minute choices; (CJ) check (1) is rerun.
- **RESULT {#endgame-dp} (DE) the endgame solved from rules and measured plays: FAIL (pre-check and both gates); not
  shipped.** Branch test/de (untracked: nfledge/endgame_dp.py, tools/de_eval.py, tools/de_wp.mjs), runtime ~80 s.
  Pre-check (2006-18 drives from the own 20-30, within 8, 200 simulations per start): 2:00 seconds used 73.4 vs 70.6
  real (+4%), score rate 0.222 vs 0.197 (+13%); 1:00 seconds 48.4 vs 51.1 (-5%), score rate 0.141 vs 0.210 (-33%):
  FAIL. Per-play outcomes matched real drill plays (completion, interception, sack, touchdown rates); the coarse
  empirical policy lacked urgency (spikes 28% vs 40% with no timeouts, slower hurry-up, stray calls), so simulated
  drives ran out of clock 34% vs 18%. Test 2019-25 (12,318 snaps, 1,117 games): Brier 0.1312 vs wp() 0.1317 (nflfastR
  0.1300), -0.0005 [-0.0041, +0.0034], better 2 of 7 seasons; calibration gap over 59 cells 0.0392 vs 0.0344 (worse).
  Largest cells (actual / DE / wp()): tied, 0:31-1:00, opponent's 35 to own 40: 0.835 / 0.679 / 0.716; tied 1:01-2:00
  same field: 0.821 / 0.676 / 0.709; behind 1-3, 0:30 or less, same field: 0.431 / 0.220 / 0.236. Same blind spot as
  (CH) and wp(): late tied / close teams with the ball win more than any average-behavior model expects. Sensitivity
  (out of bounds stops the clock inside 5:00): identical. A DE2 would model hurry-up play-calling finely (spike / hurry
  / timeout by seconds x timeouts x margin); not pre-registered.
- **PRE-REGISTERED 2026-10-24 (owner: "de2"): (DE2) the endgame with hurry-up play-calling.** (DE)'s plays matched
  real two-minute plays; its coarse empirical policy lacked urgency (spikes 28% vs 40%, slower hurry, clock ran out 34%
  vs 18%; from 1:00 it scored 14% vs 21%). Change ONLY the policy and the pre-snap runoff: both measured in hurry-up
  cells, seconds left (0:10 / 0:20 / 0:30 / 0:45 / 1:00 / 1:30 / 2:00 / 3:00) x the offense's timeouts (0 / 1 / 2 / 3) x
  margin (behind 4-8 / behind 1-3 / tied / ahead) x clock running or stopped x field zone (3), for: spike, timeout
  (offense), the play mix (run / short / deep / field goal / kneel / punt), and the seconds before the snap; thin cells
  shrink toward the same cell without field zone, then without timeouts (k = 30). Everything else as (DE). Tuning is
  allowed ONLY against the 2006-18 pre-check (drives from the own 20-30 at 2:00 and 1:00 left, within 8: seconds used
  and score rate within 10% each, and clock-run-out share within 5 points of real); the 2019-25 test runs ONCE, after
  the pre-check passes, with (DE)'s GATE unchanged (Brier lower with a 95% interval over games excluding 0; mean
  calibration gap over (CH)'s cells lower than wp()'s). If the pre-check can't be passed, DE2 stops there (FAIL)
  without touching the test.
- **RESULT {#endgame-dp2} (DE2) the endgame with hurry-up play-calling: FAIL at the pre-check; the 2019-25 test was
  not run.** Branch test/de (untracked; tools/de2_eval.py refuses the test unless the pre-check passes; iterations in
  scratch/de/de2_iterations.log). Real 2006-18: 2:00 70.6 s / score 0.197 / clock ran out 0.091 (132 drives); 1:00
  51.1 s / 0.210 / 0.269 (119). Iteration 1 (as pre-registered): 2:00 65.0 / 0.160 / 0.143, 1:00 44.9 / 0.086 / 0.381.
  Best (8: down as a dimension, behind 9+ left out of the measurement, shrink order changed): 2:00 71.4 / 0.188 /
  0.154 (passes seconds and score, run-out 1.3 points over), 1:00 48.6 / 0.101 / 0.430 (fails). No combination of
  policy and runoff moved the 1:00 score rate past 0.10-0.15. Diagnosis: from real 2006-18 snap states the simulator
  under-scores everywhere late (behind 1-3 inside the 20 with 0:07-0:15: real 96%, simulated 73%, with field goals
  chosen 87%): the measured late pass outcomes mix in-bounds completions that run the clock with the end-zone /
  sideline throws teams actually make there. The outcome model, not the play-calling, is what's missing; DE2 could
  not change it. The calculator keeps the general model with its "rough" note in the last 3:00.
- **PRE-REGISTERED 2026-10-24 (owner: "de3"): (DE3) the endgame with hurry-up play outcomes.** (DE2) traced the 1:00 miss
  to the outcome tables: late passes by a team not ahead are end-zone / sideline throws (stop the clock or score),
  not the average late pass. DE3 = (DE2)'s policy as its pre-check-tuned iteration 8 + outcome tables for HURRY
  plays: snaps in the 4th quarter's last 2:00 by an offense not ahead (margin -8..0), measured 2006-18 per play type
  (run / short / deep) x time band (0:30 or less / 0:31-1:00 / 1:01-2:00) x field zone ((CH)'s three): yards, completion,
  sack, turnover, out of bounds, touchdown, seconds; each cell shrunk toward (DE)'s general late table for the same play
  type and zone by k = 50 pseudo-plays (cell sizes reported). Other snaps keep (DE)'s tables. Tuning ONLY against the
  2006-18 pre-check ((DE2)'s three conditions at 2:00 and 1:00, plus the start-state check: from real 2006-18 snaps
  behind 1-3 inside the opponent's 20 with 0:15 or less, simulated score rate within 10 points of real); only the
  shrinkage weight and the band edges may be tuned. The 2019-25 test runs ONCE if the pre-check passes, (DE)'s GATE
  unchanged. Pre-check not passed -> FAIL, test untouched.
- **RESULT {#endgame-dp3} (DE3) the endgame with hurry-up play outcomes: FAIL at the pre-check; test not run. Also a
  CORRECTION to (DE2)'s diagnosis.** Hurry tables 8,256 plays 2006-18 (cells: runs 13-454, short 282-1,064, deep
  116-339). Real: 2:00 70.6 s / 0.197 / run-out 0.091; 1:00 51.1 / 0.210 / 0.269; start state (behind 1-3 inside the 20,
  0:15 or less) 0.960 (99 snaps). Iterations (k 1-200, band edges): 2:00 ~70.4 s / 0.185 / 0.149 (run-out +5.8 points
  over the 5-point limit), 1:00 ~49.1 s / 0.107 / 0.43 (fails), start state 0.773 -> 0.868 after a SIMULATOR BUG fix:
  a real snap with a running clock was simulated as if before the snap, charging the runoff twice (the solved values
  were not affected). With it fixed, (DE2)'s "96% vs 73%" start-state gap was mostly that bug (corrected: 96% vs
  ~87%), and the hurry outcome tables move nothing (k and band edges barely change any number). So (DE2)'s diagnosis
  (the outcome tables) does not hold; the 1:00 drive miss is unexplained by policy, runoff or outcomes. Untested:
  the play seconds and the clock rules (fixed under (DE)-(DE3)). The calculator keeps the general model with its
  "rough" note in the last 3:00; the endgame work rests until the season-end recheck.
- **FINDING 2026-10-25 (owner: "i want this calculator to be something we're proud of ... what else you got?" ... "yes"):
  (DF) the late-game blind spot is mostly noise, and not era drift.** tools/late_era_check.py / .mjs: 2022-25 4th-
  quarter snaps with 3:00 or less, score within 8 (6,771 snaps, 640 games), the engine's wp() fit on 2006-18 (as every
  late test so far) vs walk-forward (fit through the season before): Brier 0.1375 vs 0.1382 (+0.0007 [-0.0009,
  +0.0022]); calibration gap over 56 cells of 30+ 0.0420 vs 0.0405. So recency doesn't help. And that 0.0405 is close
  to what binomial noise alone gives with these cells (games as the unit): 0.0364. By field zone overall the model is
  right (own territory -0.001, midfield +0.028, inside the opponent's 35 +0.001). The one consistent signal: the team
  with the ball TIED late is under-read (midfield +0.088, n 273 snaps; inside the opponent's 35 +0.081, n 264; own
  territory -0.054, n 349), and behind 1-3 at midfield +0.069 (n 578). The calculator's "rough" note in the last 3:00
  is broader than the evidence; the targeted fix is a tied / behind-1-3-with-the-ball correction (to be pre-registered).
- **PRE-REGISTERED 2026-10-25 (owner: "yes"): (DG) a late correction for the team with the ball tied or behind 1-3.**
  From (DF): the one consistent late signal is the team with the ball tied (midfield +8.8, inside the opponent's 35
  +8.1) or behind 1-3 (midfield +6.9) winning more than wp() says. Rows: the 4th quarter's last 3:00, team with the
  ball tied or behind 1-3. Cells: margin (tied / behind 1-3) x time (0:30 / 1:00 / 2:00 / 3:00) x field zone (inside
  the opponent's 35 / to the own 40 / deeper). Correction per cell = the mean of (won - wp()) on 2006-18 rows scored
  by the model fit on 2006-18, in log-odds, shrunk toward 0 by 30 games (the cell's games / (games + 30)); applied in
  wp() to those states only. Test once on 2019-25 (model fit on 2006-18): GATE (all): (1) on the targeted rows, Brier
  lower with a 95% bootstrap interval over games excluding 0; (2) the targeted cells' mean calibration gap lower;
  (3) all late rows (last 3:00, within 8) Brier not worse (interval upper < +0.0005). Pass -> wp() applies it (fit on
  every season through the latest), the "rough" note narrows; (CJ) check (1) rerun.
- **RESULT {#late-corr} (DG) the late tied / behind-1-3 correction: FAIL; not shipped.** tools/late_corr_eval.py / .mjs
  (29,138 late snaps 2006-25). 2019-25 targeted rows (3,972, 496 games): Brier 0.1929 -> 0.1934, +0.0006 [-0.0008,
  +0.0019]; targeted cells' calibration gap 0.0605 -> 0.0617; all late rows +0.0002 [-0.0003, +0.0007]. The 2006-18
  corrections were near 0 or negative where 2019-25 is under-read (tied, midfield: 2:00 raw -0.22 in 2006-18 vs 2019-25
  actual 0.803 / model 0.705; 1:00 -0.03 vs 0.840 / 0.717): the tied-with-the-ball under-read is a RECENT pattern the
  2006-18 rows could not teach. Design flaw stated: the corrections were measured on the rows the model was fit on
  (in-sample residuals shrink toward 0); held-out residuals were the right design. Leads: field goal range has moved
  with kickers (a tied team at midfield is ~20 yards from a makeable kick now); a recent-era correction (fit on 2019-22
  residuals of the 2006-18 model, tested on 2023-25) or kicker-aware range in the model.
- **FINDING + PRE-REGISTERED 2026-10-25 (owner: "ya" ... "yes"): (DH) the field goal's make chance from the spot as a
  win model input.** Measured: make rates rose most at long range (50-54 yd 60% in 2006-12 -> 72% in 2019-25; 55-59
  46% -> 61% on 4x the attempts; 60+ 24% -> 41%), and the late under-read for a team with the ball tied or behind 1-3
  sits where that matters: by field goal distance from the spot, actual minus model (fit 2006-18): 55-64 yd -2.3 in
  2006-18 vs +6.4 in 2019-25 (n 461); 45-54 -1.7 vs +1.8; under 35 +3.2 vs +1.6. The model learned old ranges. Change:
  input fgp = P(make) of a kick from this spot (distance = yards to the end zone + 17), from a logistic curve in
  distance fit on the THREE seasons BEFORE the row's season (known before it starts; no leakage of its own kicks; the
  live season uses the three before it); the browser engine gets the current curve in the model file. Everything else
  as the (CG) model. Test: walk-forward 2022-25 (each season fit on 2006 through the season before), current model vs
  + fgp, same rows. GATE (all): (1) pooled Brier not worse (95% interval over games, upper < +0.0005); (2) late-and-close
  (4th quarter, within 8) Brier lower; (3) calibration deciles within 3 points; (4) late (last 3:00) team with the ball
  tied or behind 1-3: the mean calibration gap over (CH)'s cells lower, and the 55-64 yd band's gap smaller. Pass ->
  the live model gets fgp; (CJ) check (1) rerun; the calculator's last-3:00 "rough" note is re-judged on (DF)'s cells.
- **RESULT {#fg-input} (DH) the field goal's make chance as a win model input: PASS (all four, small); shipped.**
  tools/dh_eval.py (walk-forward 2022-25, 175,720 rows, 1,136 games; 2003-05 attempts fetched for the first curves).
  Curves (make % at 40 / 50 / 55 / 60 yd): 2006 (fit 2003-05) 79 / 57 / 44 / 31; 2014 85 / 69 / 58 / 47; 2022 87 / 68 /
  55 / 41; 2025 (fit 2022-24) 89 / 74 / 63 / 51. (1) pooled Brier 0.15478 -> 0.15480, +0.00002 [-0.00008, +0.00012]
  (not worse); (2) late-and-close 0.16991 -> 0.16980, -0.00011 [-0.00045, +0.00023] (lower, inside the noise); (3) worst
  decile 2.01 -> 2.04 points; (4) late, team with the ball tied or behind 1-3 (2,816 snaps, 332 games, 24 cells): mean
  gap 0.0581 -> 0.0532 (tied 0.0731 -> 0.0685, behind 1-3 0.0431 -> 0.0378); 55-64 yd band +0.099 -> +0.070, 45-54
  +0.037 -> +0.007. Kickoffs get no fgp (missing); fgp monotone +1. Tied teams late are still under-read, less. In the
  model file as wp_fg (the curve of the season it serves); calc_engine.js computes fgp from it. Also fixed with it:
  calc_build's model cache key now includes calc_build.py (a change to make() alone had reused a stale model).
  (CJ) check (1) on the rebuilt walk-forward files (2026-10-25): PASS. Chosen option vs won: go 35.2 vs 34.6, field
  goal 56.2 vs 55.6, punt 47.1 vs 47.2; no decile of 50+ off by more than 6 points (worst fg 0.65 decile, 4.6). Brier
  0.1534 (nfl4th 0.1525). Same recommendation as nfl4th 78.2% (was 79.0% after the clock fixes), gap correlation 0.867
  (was 0.857 at (CJ)). The rebuild first failed: a split separating kickoffs (fgp missing) from the rest carries an
  infinite threshold, which JSON can't hold; export now writes the largest finite double (same routing), and
  calc_build writes model files with allow_nan=False (fails at build, not in the browser).
- **FINDING + PRE-REGISTERED 2026-10-25 (owner: "yes"): (DI) the win model's home / possession skew.** Found grading a
  penalty choice: a home team tied in the 2nd quarter (8:00) at 4th & 5 on the opponent's 15, line 0, reads 56.3%; a
  MADE field goal (97%) leaves it 47.1%, below the moment before it, and the engine's best option (go, 51.3%) is far
  below the model's value of the moment. Cause: with an even line the model rates the team with the ball much better
  away than at home: Q2 7:55, tied, 1st & 10 at its own 30: home 51.6% vs away 60.1% (DH model; pre-DH 49.2 / 58.3, so
  not DH); widest for lines -3..+3 (line +7: 72.5 / 69.9). Real games agree in direction, not size: |line| <= 1.5,
  2006-24, 583 games, the away team won 52.8% (the line already carries home field; in pick'em games the away team is
  the better one); in the cell above (n ~250 per side) away with the ball won 55.0% vs home 51.6%. Every change of
  possession in a close-line game is priced through this, so home teams are nudged toward go and away teams toward
  kicks; (CJ)'s overall calibration hid it (the two sides cancel). Candidates (the owner approved both): (a) drop
  `home` (exp_margin already carries home field); (b) possession-symmetric training: every row also from the defense's
  side (score, timeouts, line, home and second-half receiver flipped, y = 1 - y, ball = 0; the ball team's yards to
  the end zone, yards to go and fgp entered negated on those rows, so the monotone directions hold for both), and the
  engine reads wp = (f(ball side) + 1 - f(defense side)) / 2, so the two teams' chances at one moment sum to 1 exactly.
  Both keep DH's fgp. Test: tools/di_eval.py, walk-forward 2022-25 as (DH), current vs (a) vs (b) on the same rows.
  GATE per candidate (all): (1) pooled Brier not worse (95% interval over games, upper < +0.0005); (2) calibration
  deciles within 3 points; (3) home split: team with the ball at home / away x |line| <= 3 / > 3 (four groups), the
  worst |actual - model| lower than current's and every group within 2 points; (4) the field goal check, engine on each
  variant's through-2024 model file, 480 states where kicking is the standard play (Q1 10:00, Q2 8:00, Q3 8:00, Q4
  10:00; score -3 / 0 / +3; line -7 / -3 / 0 / +3 / +7; home / away; 4th & 8 at the 5 / 10 / 15 / 20): a made field goal
  worth more than 1 point less than the moment before it on at most 1% of them (4) and on fewer than current. (Owner,
  2026-10-25: "FGs can realistically lower win chance?" Yes, against a better option, e.g. down 7 late or handing back
  time; this grid excludes those: short kicks, not late, within 3.) Both pass -> the one with fewer (4) cases, then the
  lower pooled Brier. Pass -> the live model changes; (CJ) check (1) rerun before shipping. Fail -> recorded either way.
- **RESULT {#home-skew} (DI) the home / possession skew: FAIL, both candidates; nothing ships. Gate (4) was mis-aimed.**
  tools/di_eval.py + tools/di_grid.mjs, walk-forward 2022-25, 175,720 rows, 1,136 games. Current model, home split
  (actual - model): away |line| <= 3 -1.81, > 3 -1.39; home <= 3 +1.50, > 3 +0.80 (the skew is real in held-out games:
  away teams with the ball read ~1.5 points too high, home ~1.5 too low, in close-line games). (a) no `home`: (1)
  Brier 0.15480 -> 0.15484, +0.00005 [-0.00079, +0.00088]: FAIL (upper over +0.0005; the interval is 8x DH's: dropping
  an input moves many predictions); (2) worst decile 2.10 (PASS); (3) home split worst 1.81 -> 0.59, all four groups
  within 0.6 (PASS); (4) FAIL. (b) symmetric: (1) +0.00025 [+0.00001, +0.00048] (PASS, barely; worse in all four
  seasons); (2) 2.53 (PASS); (3) 1.81 -> 2.34 (FAIL: away <= 3 got worse); (4) FAIL. (4): a made field goal worth 1+
  point less than the moment before on cur 330 / a 369 / b 360 of 480 states (worst 12.6 / 12.3 / 17.8). That check
  never measured the home skew: (a) reads home and away identically (the original example: 61.0 / 61.0 now, 54.0 made)
  and still shows a ~7 point drop. Where the drop comes from (measured after, not gated): real made field goals inside
  the 20, Q1-Q3, within 3, 2022-25 (687): the model before the kick 58.7%, at the kickoff after it 57.1%, actually won
  55.5%: the model's value of a 4th down near the goal line is high (~3 points over the results, ~1.6 over its own
  after-kick value); the engine's after-kick state adds 2025 kickoff spots (opponent at its 29.3 on average vs 25:
  ~0.7 of the 4.6 points in one probed state) and the snap's clock. Consequences: the engine's decisions compare
  options with each other (all after-states), so they are not hit; anything that compares the RAW value of a moment
  with option values is (the page's "now" next to the options; the penalty demo of 2026-10-25, which valued a 3rd down
  raw against a 4th down's best option and so leaned to "decline"). Leads, each its own test: (a) again with a gate
  sized to its interval (a re-run of this exact test after seeing it is the forking path; a new pre-registration must
  say so); value every penalty branch the same way (step 2 of the penalty grading); the raw 4th-down value near the
  goal line. The engine keeps reading both file shapes (no `home`; W.sym) so tools/di_grid.mjs reproduces this.
- **FINDING (PA) 2026-10-25: penalty census (owner: "do we grade those? can we fold them into our graded calls
  list?").** tools/penalty_census.py, regular seasons 2022-25, 3,740 plays a season with a foul in the text (nflfastR's
  `penalty` flag misses most declined fouls: 76 of 511 in 2025). Per season: 2,244 single fouls during a run or pass
  (declined 357; accepted, play wiped 1,411; accepted, play stands + yards 442; after the play 34), 932 pre-snap (no
  real choice; but Delay of Game was declined 39 times in four seasons), 413 on kicking plays, 151 with two or more
  fouls (43% offsetting). 16% of declines had a turnover or score on the play; 396 a season come late in a half.
  Declines by down: 1st 336, 2nd 416, 3rd 615, 4th 60 (four seasons).
- **PRE-REGISTERED 2026-10-25 (owner: "penalty step 2 now?"): (PB) the penalty rules table, checked against real
  plays.** A choice has two branches; a game shows only one. The table (nfledge/penalties.py, from the 2026 rulebook,
  scratch/rulebook/review.md) must rebuild the other: (A) the PENALTY branch (for a declined foul): from the snap's
  down, distance and spot, the foul (type, side) and the play (pass incomplete / complete / sack / run, yards), where
  it is enforced (previous spot; end of a run for the defense's fouls past the line; better of previous spot and end
  of play for the defense's personal fouls after a completion; half the distance), automatic first down, loss of down,
  replay of the down, a turnover on downs. A foul whose spot the play text can't give (pass interference: the spot of
  the foul; the offense's holding on a run that gained: three-and-one) is out of scope, not a miss. Checked on
  ACCEPTED fouls, whose next snap is the truth. (B) the PLAY branch (for an accepted foul): the play's own result from
  its text (yards; first down; down + 1; turnover on downs). Checked on DECLINED fouls, whose next snap is the truth.
  Scope: single fouls during a run or pass; no turnover or score on the play; not at a half's end. A match: same team
  with the ball, same down, yards to the end zone and yards to go within 1 (half-the-distance rounding). Rules are
  built and tuned on 2022-23 (every change after a first look logged in the tool); the GATE is on 2024-25 only, untouched
  until then: (A) units (foul x side x play kind) with 20+ accepted fouls in 2024-25 that match 95%+ are in scope; PASS
  if they cover 70%+ of 2024-25's declined fouls in scope; (B) 95%+ of 2024-25's declined fouls match. Pass -> step 3
  (both branches valued the same way, through the engine; the clock per 4-3-2(e) and runoffs), then the graded list.
  Fail -> recorded; the failing units are named.
  AMENDMENT 2026-10-25, before 2024-25 was read (development only had been run): the units change to foul x side x HOW
  it's enforced (from the previous spot, the play wiped / from the end of the play, which stands). Why: by play kind,
  a foul the other side almost always declines can never gather 20 accepted cases to be checked, though its rule is
  the same as a checked one (the offense's holding on a sack: 39 declines in 2022-23, 6 accepts; enforced from the
  previous spot exactly as holding on an incomplete pass, which matched 86 of 86). What is verified is the rule path, so
  the path is the unit. Development (2022-23, rules frozen after 8 logged changes in tools/penalty_check.py): (A)
  0.967 match over 1,995 accepted; pre-registered units cover 0.648 of declines, amended 0.814; (B) 0.996 of 560. The
  gate run reports both; the amended units decide.
- **RESULT {#penalty-rules} (PB) the penalty rules table: PASS on the amended units (FAIL on the pre-registered ones).**
  tools/penalty_check.py --gate, 2024-25 (first read after the rules were frozen): 3,550 accepted and 621 declined
  single scrimmage fouls. (A) the penalty branch matched the next snap on 0.971 of 2,163 accepted fouls whose spot the
  text gives (1,387 can't: pass interference, the offense's fouls after a catch or on a run that gained); amended
  units: 19 in scope, covering 0.889 of declines (PASS); pre-registered units: 28 in scope, 0.573 (FAIL: the declined
  fouls sit in units the other side rarely accepts, e.g. holding on a sack 37 declines). Every in-scope unit matched
  96-100%. Out of scope: Intentional Grounding (0.57: enforced from the spot of the pass when the passer is 10+ yards
  back, not in the text), the offense's Unnecessary Roughness after the play (0.86), and units under 20 accepts. (B)
  the play branch matched 0.998 of 621 declines (PASS). What can be graded: a declined foul in an in-scope unit (89%
  of declines), and every accepted foul (its play branch, 99.8%); declined pass interference and the offense's holding
  on a run that gained stay out (the spot of the foul). Spot rounding: a 5-yard foul against 3rd & 5 is rebuilt both
  ways and graded only when both agree. Next: step 3 (both branches valued the same way, the clock), then the list.
- **PRE-REGISTERED 2026-10-25 (owner: "ya" to valuing both branches with the raw model, behind a calibration check):
  (PC) grading accept / decline calls.** Each in-scope choice (PB) gets two states at the next snap: the branch taken
  (the real next snap) and the one rebuilt (nfledge/penalties.py). Clock and timeouts: the real next snap's for both
  (4-3-2(e): after a penalty is enforced or declined the clock runs as if there had been no foul; inside the last 5:00
  and after the 2:00 warning it starts on the snap either way); score: unchanged (plays with a score or turnover are
  out). Value: the browser engine's win chance of each state (the same model and overrides for both: never a 4th
  down's best option against a raw value, (DI)'s lesson), from the side of the team that chose (the one that didn't
  foul); a turnover-on-downs branch is valued from the new team's side and flipped. Each season graded with the model
  fit on the seasons before it (as Graded calls). Verdicts as the 4th-down grades (fine under 1.25 points, debatable
  under 3, questionable past). Spot-rounding cases (two rebuilt states): graded only when both give the same best.
  GATE (all, 2022-25): (1) TRUST: the engine's win chance on every real snap 2022-25 (walk-forward), by down (1-4) x
  zone (opponent's 30 and in / 31-70 / own 30 and back), cells of 500+ snaps: a cell is trusted if |won - model| <= 2
  points; a choice is graded only if both branch states sit in trusted cells; (2) SANITY: accepted defensive fouls with
  an automatic first down on an incomplete pass (accepting is plainly right) come out "accept" in 99%+ of graded cases;
  (3) SANITY: declined defensive offside on a play that gained a first down by 6+ yards past the line to gain come out
  "decline" in 99%+. Pass -> Graded calls gets a 4th downs / Penalties toggle (the same week grouping and sort).
  Reported either way: graded count by season, the share questionable, the 25 costliest calls.
- **RESULT {#penalty-grade} (PC) grading accept / decline calls: FAIL (3); not shipped. And a deeper problem the gate
  didn't test.** tools/pc_check.py + .mjs, 2022-25: 7,809 choices (963 declined); (1) all 12 down x zone cells
  trusted (|won - model| 0.2-1.5 points; worst 4th down inside the opponent's 30, -1.50); graded 7,804 (5 left out:
  spot rounding changes the answer); (2) accept on the defense's automatic-first-down fouls on incomplete passes 99.4%
  of 1,749 (PASS; the misses are lopsided games, 0.1-0.4 apart); (3) decline on defensive offside when the play gained a
  first down by 6+: 97.2% of 72 (FAIL: 2 misses, both exact ties, 2.2 / 2.2 and 40.9 / 40.9: the gate counted "best",
  not "within the noise"; a design flaw, but the gate stands). Reported: questionable (3+ points) 6 / 0 / 6 / 5 a season,
  11 of 1,010 declines and 6 of 6,794 accepts. The costliest list is the real finding: the top declines are "decline
  the offense's holding on 3rd down, force 4th" called wrong by 4-7.5 points (e.g. LA 2024 wk 15, SF 3rd & 9 at its
  31, Q1: decline 47.5 vs accept 55.0). The model's value of 4th & 9 at the own 31 (52.5) vs 3rd & 19 at the own 21
  (45.0), Q1 tied, is a 7.5-point gap. nflfastR's model has these about level (real snaps 2019-25, Q1-2, within 3, line
  within 4: 3rd & 15-22 at own 16-26 45.2%, 4th & 7-11 at own 26-36 44.5%); real outcomes side with ours (41.2% of 85 vs
  49.7% of 187) but carry in-game evidence: an offense at 3rd & 19 got there through a sack, loss or penalty and is
  having a worse day. In an accept / decline choice the same offense is on the same drive either way, so a raw value
  that learned that evidence overstates the gap between the two states: the trust cells (calibration by cell) can't
  see it. Lead (its own pre-registration): value both branches forward to the next change of possession, where states
  are fresh (the 4th-down engine already works this way): a 3rd-down branch by measured 3rd-down play outcomes (first
  down, yards, turnover) then the engine's 4th-down options, so neither branch reads raw mid-drive evidence.
- **FINDING + PRE-REGISTERED 2026-10-25 (owner: "these thresholds of 0-2:00 and 2:00-5:00 seem so crude, isn't it more
  like an exponential slope ... something we can pin to a line as defined by plotted data?" ... "your call"): (DJ) the
  clock's pace as a curve.** The engine's pace (seconds between snaps on a running clock; what a timeout saves and what
  a play costs) is a step table: half x (last 2:00 / 2:00-5:00 / earlier) x lead or not. Measured 2018-25 (median, 30 s
  bins): a plateau then a ramp whose start depends on the margin: Q4 trailing by 9+ slows from ~10:00 (38 s -> 27 at
  3:00), by 4-8 from ~3:30, by 1-3 from ~3:00, tied from ~2:30, leaders 43 s throughout; Q2 everyone from ~2:30 (37 ->
  30 -> 24 -> 21 -> 16 -> ~8 in the last 30 s). The table's 5:00 edge matches nothing, one median covers 2:00 -> 0:00,
  and trailing by 2 = trailing by 14. Change: a smoothed surface, pace(half, seconds left in the half, margin): the
  median of a Gaussian-kernel-weighted histogram of gaps over 15-second x 1-point cells (margin clamped to +-21), the
  engine interpolating between cells (bilinear). Bandwidths picked on 2022-23 from (10, 20, 40 s) x (1, 2, 4 points),
  fit on 2018-21; then refit on 2018-23. Test: 2024-25, running-clock gaps as calc_inputs.clock() selects them; the
  table refit on 2018-23 as the baseline. GATE (all): (1) inside the last 5:00 of either half, mean absolute error
  lower, the 95% interval over games of the difference below 0; (2) all gaps: not worse (upper < +0.1 s); (3) no
  cliffs: no step of more than 4 s between neighbouring cells (time 15 s apart or margin 1 apart) within the last
  10:00; (4) the engine on the curve passes (CJ) check (1). Pass -> the live engine's runOff reads the curve (the
  table stays as the fallback). Next candidates, each its own test: yards gained by distance bucket x field band,
  the 40 s-per-down run-out rule, the 1-2 point lead ramp.
- **RESULT {#pace-curve} (DJ) the clock's pace as a curve: FAIL (3), not shipped.** tools/dj_eval.py: 150,669 gaps
  2018-25. Bandwidth picked 10 s x 4 points (the smallest time bandwidth offered: an edge of the grid). Test 2024-25:
  (1) last 5:00 MAE 9.687 -> 8.156 s, -1.531 [-1.650, -1.401] (PASS); 2:00 and in 11.22 -> 9.21, 2:01-5:00 8.32 ->
  7.22; (2) all 5.479 -> 5.125, -0.354 [-0.383, -0.326] (PASS); (3) a 37.2 s cliff (FAIL): Q4 leaders at 2:30 read 6-12
  s, at 2:00 43. Cause: the cells hold few gaps (62 in Q4 2:05-2:50 leading by 4-10) and many are the trailing
  defense's timeouts that the play-by-play has no row for ("(2:18) ... (2:15)"), so the clock stopped, not the pace;
  the table hides them in a band median, the narrow kernel shows them. Shape as measured: Q4 trailing by 14 slows
  from ~10:00 (36 s) to 26 by 3:00; tied / within 3 hold ~40 to 3:00 then ~23 inside 2:30; leaders 42-44.
- **PRE-REGISTERED 2026-10-25 (re-test of (DJ) after reading its test seasons: the forking path, stated): (DJ2) the
  pace curve with timeout gaps removed and a minimum mass per cell.** Two changes, both from (DJ)'s diagnosis, not
  tuning: (a) a gap is dropped when either team's timeouts remaining fell before the next snap (a timeout the rows
  don't show), for the table AND the curve; (b) each cell's time bandwidth widens (10, 20, 40, 80, 160 s) until the
  kernel holds 300+ gaps (so sparse cells borrow from neighbours, dense ones stay sharp); margin bandwidth picked on
  2022-23 (fit 2018-21) from (1, 2, 4); (c) snaps between 2:00 and 3:00 left in a half are not fit (found before
  this run, reading (DJ)'s cliff: the data drops gaps that cross the two-minute warning, so a 2:10 snap is seen only
  if the next came within 10 s: those cells are biased short, the table's 2:01-5:00 band too); their cells borrow from
  both sides through (b) (the engine stops the clock at 2:00 there anyway, so the value matters little). GATE as (DJ): (1) last 5:00 MAE lower, interval < 0; (2) all: upper < +0.1 s;
  (3) no step over 4 s between neighbouring cells within a half's last 10:00, EXCEPT across the two-minute warning
  (2:00, where the clock stops by rule); (4) (CJ) check (1). The exception in (3) is new and stated: the rule makes a
  real break at 2:00 (a 2:05 snap's gap can't cross it, the data excludes those), so a step there is the rule's.
- **RESULT {#pace-curve-2} (DJ2): FAIL (3) again; not shipped.** tools/dj_eval.py --dj2: 146,299 gaps (4,370 timeout
  gaps dropped). Margin bandwidth 4 points. Test 2024-25 (timeout gaps out of both): (1) last 5:00 MAE 6.283 -> 5.506,
  -0.777 [-0.882, -0.679] (PASS); 2:00 and in 7.29 -> 6.29, 2:01-5:00 5.69 -> 5.05, 5:01-10:00 4.92 -> 4.59; (2) all
  4.789 -> 4.584, -0.205 [-0.228, -0.181] (PASS); (3) a 17.3 s step (FAIL), all in a half's last 75 s: Q4 leading by
  2-4 (e.g. +2 -> +3 at 0:00 17.3, +3 -> +4 at 1:15 14.2: a leader with the ball that late mostly kneels, kneels are
  not running-clock snaps, so the few left are odd ones) and Q2's last 15 s (a gap there can't exceed the time left).
  The 2:30 cliff of (DJ) is gone: the timeout and warning fixes worked. The curve now (Q4): trailing by 14 36 s at
  10:00 -> 27 at 3:00 -> 23 at 1:00; trailing by 3 40 -> 37 -> 21; tied 40 -> 40 -> 22; leading by 7+ 41-44 throughout.
  Two fails on 2024-25: a third try there would be fitting the test. Lead: (DJ3) on unseen data (2026 to date, fit
  2018-25), the cliff check defined where pace means something (60+ s left; margin steps across 0 -> +1, lead vs not,
  exempt as the 2:00 one is; cells holding 300+ gaps).
- **PRE-REGISTERED 2026-10-25 (owner: "ya"): (DJ3) the pace curve on unseen games.** (DJ2)'s curve exactly (timeout
  gaps dropped, adaptive time bandwidth, 2:00-3:00 not fit, margin bandwidth 4 as (DJ2) picked), fit on 2018-25; the
  table refit on 2018-25 with the same timeout filter. Test: 2026's completed regular-season games to date (weeks 1-7;
  no pace test has read them). GATE (all): (1) last 5:00 of either half: MAE lower, 95% interval over games < 0; (2)
  all gaps: upper < +0.1 s; (3) no step over 4 s between neighbouring cells where pace means something: 1:00 to 10:00
  left in a half, cells whose kernel holds 300+ gaps, not across the two-minute warning (2:00 -> 2:15) and not across
  tied -> leading by 1 (the switch from hurrying to milking), both real breaks; (4) (CJ) check (1) with the engine on the
  curve. A small sample: if (1)'s interval straddles 0 the result is "not shown", not a pass.
- **PRE-REGISTERED 2026-10-25 (owner: "dst: yes do it"): (DK) D/ST projections for 3-and-outs, 4th-down stops and
  special-teams fumbles.** A Sleeper league (the owner's) scores def_3_and_out, def_4_and_stop, def_st_ff and
  def_st_fum_rec; the D/ST model (nfledge/defenses.py) projected none of them (0), and the league import never read
  them (fixed 2026-10-25). Change: four components from play-by-play (pbp_calc): three_out = opponent drives of 3 or
  fewer runs / passes ending in a punt; fourth_stop = opponent 4th-down tries that failed; st_ff / st_fum_rec = kick
  plays (kickoff, punt) with a lost fumble recovered by the kicking team. Same form as the others: the defense's
  rate x the opponent offense's rate allowed (three_out, fourth_stop; K_COMMON) or the defense's rate alone (st_*;
  K_RARE), over its last 16 games shrunk to the league. Test: tools/dk_eval.py, walk-forward 2023-25 (each week fit
  on the games before it), every defense-game. GATE per new stat: (1) calibrated: mean projection within 10% of the
  mean actual; (2) its MAE lower than the league rate's (a constant: what team and opponent add). A stat that fails
  (2) ships as the league rate. (3) Overall, the owner's league scoring: D/ST points MAE with the new stats lower than
  without (0). Pass (3) -> the build's kdst.json carries them (rankings, the Fantasy tab).
- **RESULT {#dst-pbp-stats} (DK) D/ST 3-and-outs, 4th-down stops, special-teams fumbles: PASS, shipped.**
  tools/dk_eval.py, 1,440 defense-games 2023-25 weeks 3+. Per game (2021-25): 3-and-outs 2.23, 4th-down stops 0.68,
  special-teams forced fumbles / recoveries 0.059. (1) calibrated: actual vs projected 2.210 / 2.290, 0.692 / 0.666,
  0.058 / 0.060 (both st); (2) MAE vs the league rate: 1.1628 vs 1.1704, 0.7241 vs 0.7355, 0.1108 vs 0.1115 (st: corr
  -0.03, so in effect the league rate). (3) the owner's scoring: MAE 4.935 -> 4.922, -0.014 [-0.088, +0.058]; the real
  gain is the bias: projected 5.66 vs actual 7.22 per game before (1.6 points low every week in a league that scores
  these), 7.25 after. kdst.json d_keys carry them; the site reads lines by key (no page change).
- **FINDING (DL) 2026-10-25: the home-screen app's height on iOS (owner: "instead of more guesses, research").** The
  bottom bar's icons were cut off below the screen after the app shell sized its column from 100lvh, then from
  screen.height. Research (sources): the site sets no apple-mobile-web-app-status-bar-style, so the installed app has
  the default opaque status bar; WebKit draws the page below it (innerHeight = screen - status bar, ~873 on a Pro
  Max), while 100vh / 100lvh and screen.height report the full screen: WebKit 316008 "Incorrect 100vh and -lvh in
  standalone web apps without apple-mobile-web-app-status-bar-style" (https://bugs.webkit.org/show_bug.cgi?id=316008);
  frappe-ui https://github.com/frappe/frappe-ui/pull/1284, /1289 (a 100lvh shell clipped: "WebKit stops drawing fixed
  content at the short edge"); WebKit 301994 comment 12 (screen.height 874 vs innerHeight / dvh 812). With
  black-translucent the drawn area is also short until the document is taller (WebKit 301108, open, iOS 26). In
  standalone the keyboard can leave innerHeight short by a status bar for good (WebKit 254868; dev.to/cederhook
  "Fixing the iOS standalone PWA keyboard bug"; lifekit-hq/lifekit-common #215); a fixed bar drifting after a long
  background (developer.apple.com/forums/thread/744327, no fix). The status-bar style is fixed at install time
  (WebKit 260508). Change (shell.js (0b)): the column is fixed, inset 0 (the drawn area), never sized from lvh / vh /
  screen; heal() re-measures (hide / show the column) when innerHeight is short of the tallest seen with no keyboard
  up, after a field loses focus, on pageshow and on return. A readout (5 taps on the header) shows the device's
  measures. Source quality: the iOS 26 evidence is mostly 2026 GitHub reports, several simulator-only; the WebKit
  bugs are firmer.
- **RESULT {#pace-curve-3} (DJ3): FAIL (3) a third time; not shipped. Accuracy wins again.** tools/dj_eval.py --dj3,
  2026 to date (94 games, 6,334 gaps): (1) last 5:00 MAE 6.236 -> 5.213, -1.022 [-1.305, -0.764] (PASS; 2:00 and in 7.40
  -> 6.00, 2:01-5:00 5.61 -> 4.79); (2) all 4.592 -> 4.349, -0.243 [-0.295, -0.194] (PASS); (3) a 15.7 s step (FAIL) at
  Q4 1:00 between leading by 4 (~24 s) and by 5 (~40), in cells holding 300+ gaps. Three test sets (2024-25 twice,
  2026) agree the curve predicts the clock better everywhere, most in the last 5:00; each time the smoothness rule
  failed in the late cells of a team leading with the ball, at a different place. That rule was an assumption (pace is
  smooth in time and margin); where leaders are concerned the data says otherwise (a 4-point and a 5-point lead late
  are different situations), or those cells are too thin to tell. Not settled by a fourth try: next is a look at what
  those snaps are (descriptive, no gate), then the owner's call on what the check should be.
  The look (same day, descriptive): Q4 snaps with 0:30-1:40 left, 2018-25, running clock, timeout gaps out: leading by
  1-3 n 24, median gap 45 s; by 4 n 8, 44; by 5-8 n 31, 44; by 9+ n 98, 44. Leaders MILK at every margin. The curve's
  ~23 s for +1..+4 is the margin kernel (sd 4 points) borrowing the dense tied / trailing cells (hurrying, ~21 s)
  across 0 into near-empty small-lead cells; past ~+5 the leaders' own data wins: the cliff. So the check caught a real
  flaw (a curve that thinks a team up 3 with 1:00 left snaps every 23 s would misprice the trailing team's timeouts),
  and the 0 -> +1 exemption in (DJ3) would have hidden its cause. Fix for a (DJ4): no smoothing across the lead / no-lead
  boundary (each side's kernel reflects at it). Its test needs games no pace test has read: 2026 weeks 8 on.

- **PRE-REGISTERED 2026-10-26 (owner: "yes but i suspect some position groups deal with injuries/vary recovery times
  by position group a bit"): (DM) chance to play and return week for every position, by position group.** The team
  page's Injuries tile (2026-10-26) lists every player on the report, but our numbers cover fantasy positions only:
  the board is QB/RB/WR/TE/K, the status table (InjuryModel._fit_status) is fit on QB/RB/WR/TE, and the return model
  is applied only to fantasy players (returns.py lines 80, 257, 277). What the code already has: the practice model
  (_fit_practice) trains on avail_hist, which is NOT position-filtered (2018-25: 31,034 rows, DB 7,231, DL 6,149,
  LB 4,796, WR 5,508, RB 3,104, TE 2,546, QB 1,400, ST 278), with only a skill yes/no input; the return model
  (ReturnModel) trains on every rostered position with a position-group input (pos_code, POS_GROUP). DATA GAP found
  doing this: offensive linemen are 10 rows of avail_hist (practice / snap / roster join drops them); fixed and
  re-counted first, or OL is reported as not covered. A first look (descriptive, no gate): Questionable, share who
  played, 2018-25: QB .49 (n 270), DB .65 (2,122), RB .66 (894), TE .71 (618), WR .72 (1,544), DL .74 (1,512), LB .74
  (1,248), ST .82 (92); raw, before practice is accounted for.
  Arms, walk-forward 2021-25 (each test season fit on 2018 through the season before), every final-report row:
  game week: A0 = today's model as is (skill flag); A1 = the skill flag replaced by the position group (QB, RB, WR, TE,
  OL, DL, LB, DB, ST); A2 = A1 plus group x game status. Return: R0 = the return model as is (pos_code in);
  R1 = without pos_code (does position carry anything?).
  GATE, game week (all): (1) fantasy positions: Brier of the adopted arm no worse than A0 (difference upper 95% bound
  < +0.001), the guard: the board's numbers must not get worse; (2) every group with 300+ test rows: calibrated, mean
  predicted within 3 points of the share who played, and in each predicted-decile within 5 points; (3) A1 or A2 beats
  A0 on Brier for the non-fantasy groups pooled (upper bound < 0); the simplest arm that passes is adopted. If (2)
  fails for a group, that group shows a dash on the site, not a number.
  GATE, return: (4) per group with 300+ states, P(back next game) calibrated within 3 points; (5) report R0 vs R1 log
  loss per group (the owner's question: does position change recovery?); R0 stays unless R1 is no worse, then the
  simpler. Groups passing (4) get "Back wk N" on the Injuries tile for every player, not only fantasy ones.
  Ship: the Injuries tile reads the new per-player numbers (a team file: every listed player's chance and return week);
  the board's fantasy numbers change only if the adopted arm passes (1).
- **RESULT {#all-positions-play} (DM) game week, every position by position group: FAIL (calibration), nothing shipped.**
  tools/dm_eval.py, walk-forward 2021-25, 23,000+ final-report rows (game status Out excluded). The lineman fix works:
  avail_hist with the players-table id map, 2018-25: OL 10 -> 7,946 rows, ST 278 -> 623, DB 7,231 -> 8,956 (the old
  map missed some of every group). Brier fantasy / rest: A0 0.1034 / 0.1035, A0f (fixed rows only) 0.1035 / 0.1031,
  A1 (group input) 0.1034 / 0.1026, A2 (+ group x Q / D) 0.1032 / 0.1025. (1) fantasy guard: all arms ok (A1 +0.0000
  [-0.0006, +0.0007]); (3) the rest vs A0: A1 -0.0009 [-0.0013, -0.0006], A2 -0.0010: position helps. (2) calibration
  by group (mean within 3, every decile within 5 points): FAIL in every arm. A1: DL predicted .840 vs played .862
  (worst decile 9.4), LB .821 / .848 (8.3), QB .746 / .709 (18.5), ST .850 / .874 (22.3, n 334), WR / TE deciles 5.0-5.1;
  OL, RB, DB pass. TODAY'S MODEL on QBs (A0f): .776 predicted vs .709 played, worst decile 21 points: the board
  overstates quarterbacks' chance to play. Played when Questionable: QB .45, OL .67, DB .67, RB .69, TE .71, WR .73,
  ST .75, DL .75, LB .75 (2021-25).
- **RESULT {#all-positions-return} (DM) return model, every position by group: FAIL (calibration).**
  tools/dm_return_eval.py, walk-forward 2021-25, 16,793 injured-out player-weeks (all positions; this model already
  trains on them). (5) position input: no difference overall (Brier 0.1283 both; per group mixed, small). Within an
  injury, return rates barely differ by group (back after one missed game, ankle 27-37%, knee 30-37% across groups;
  concussion DB 67 vs OL 59%). (4) calibration: R0 too LOW in 8 of 9 groups (predicted .17-.20 vs back .20-.25; QB the
  exception). Where: by season 2021 -10.6 points (the COVID reserve list: desig reserve_other -37 points), 2022-25
  -0.4 to -2.8; by designation active roster -5.6, inactive -16.2, IR +0.9; after 1 missed game -7.1, 2 -5.7. The
  shipped model's "back wk N" for fantasy players inherits this.
- **PRE-REGISTERED 2026-10-26 (owner: "continue as you would if you were in charge"): (DM2) return model without
  the COVID reserve stints, and (DM3) the practice model calibrated per position group.** Both from (DM)'s failures.
  DM2: train ReturnModel without 2020-21 reserve_other states (the COVID-19 list: quick returns no feature can see).
  Test 2022-25 walk-forward (2021 excluded from scoring: its COVID states are not what the model faces now) + 2026 so
  far as the untouched check. GATE: (a) Brier vs the model as is, upper 95% < 0 OR no worse (upper < +0.0005) with
  (b) every group of 300+ states calibrated within 3 points; (c) fantasy groups' (QB RB WR TE) Brier no worse (upper
  < +0.0005). If the active-roster bias remains (b fails), it is reported, not tuned away inside this test.
  DM3: (DM)'s A1 (fixed history, group input) plus a per-group isotonic calibration fit on out-of-fold predictions of
  the training seasons only (leave-one-season-out within 2018 .. s-1), applied to season s. Same gates as (DM) (1)-(3)
  on 2021-25; plus the untouched check on 2026 weeks 1-7: Brier no worse than A0 for fantasy positions. Pass: the
  board's practice model becomes A1 + calibration (the QB fix rides on it), and every group that passes (2) gets its
  chance to play on the team page.
- **RESULT {#return-no-covid} (DM2) return model without the COVID reserve stints: FAIL; the model stays as is.**
  tools/dm2_eval.py, scored 2022-25 (11,754 states) + 2026 weeks 2-7. Dropping 1,261 reserve_other states of 2020-21
  made it worse: Brier 0.1131 -> 0.1149 (+0.0018 [+0.0003, +0.0035]); fantasy groups +0.0013. CORRECTION to (DM)'s
  reading: with 2021 out of the scoring the model as is is calibrated within 3 points for DB, OL, QB, RB, WR, ST;
  DL (.174 vs .200), LB (.180 / .206), TE (.198 / .234) run low; and 2026 so far runs HIGH (.234 predicted vs .184
  back, n 850). The (DM) pessimism was mostly 2021 (COVID list); what is left drifts by season in both directions:
  no stable bias to correct. Return weeks for defenders / linemen: DB, OL pass (4) on 2022-25; DL, LB do not.
- **RESULT {#play-group-calib} (DM3) practice model + per-group isotonic calibration: FAIL; nothing shipped.**
  tools/dm3_eval.py, 2021-25 + 2026 weeks 1-7. Brier fantasy / rest: A0 0.1034 / 0.1035, A1 0.1034 / 0.1026, A1c
  0.1046 / 0.1031: the calibration made both worse ((1) +0.0012 [+0.0002, +0.0023] FAIL; (3) -0.0004, interval
  straddles 0); 2026 fantasy 0.0705 -> 0.0709. (2) only OL calibrated. Group-level misses change from season to season
  (as the return model's did, (DM2)), so a map learned on past seasons does not carry. WORTH NOTING for any rerun: the
  (DM) calibration bar (every decile within 5 points, every group) is stricter than what the shipped fantasy numbers
  meet (A0 fails it for QB, RB, TE). Owner's call (2026-10-26, asked): hold non-fantasy positions to the shipped
  model's standard (A1: discrimination better than A0, fantasy guard passed) and show their chance, or keep the dash.
  Separately, QBs: A0 predicts .776 vs .709 played (2021-25): a QB-specific look before season end.
- **PRE-REGISTERED 2026-10-26 (owner: "if we have the game data we shouldn't wait to factor it in"): (DN) refit the
  team ratings after Thursday's (and any Friday / Saturday) games instead of waiting for Sunday's.** Today a week's
  early games enter the ratings only with Sunday's (team_model.sunday_refit, all or nothing), because refitting midweek
  moves the weekend's win chances and projections before lineups lock, never tested. Test (tools/thursday_refit_eval.py,
  walk-forward 2021-25, weeks 2-17 with early games): arms on identical rows, stale = games before week N (what the site
  has Friday today), early = also week N's games before its Sunday, Elo the same way; the model-only win chance as in
  (BA). Scored: week N's Sunday and Monday games (the games the change moves before they're played). Brier, paired by
  game, 95% CI from a bootstrap over season-weeks. GATE (owner-design rule, as (BA)): early - stale, CI upper < +0.005
  (no measurable harm). Reported, not gated: the mean difference (gain), games involving a Thursday team vs not,
  week N+1. Ship if PASS: sunday_refit also takes a week's early games once they are final with their plays in;
  the news watcher builds when they land; Power's label reads "Week N in progress · X of Y games in".
- **RESULT {#thursday-refit} (DN) refit after a week's Thursday (Friday / Saturday) games: PASS, shipped.**
  tools/thursday_refit_eval.py, walk-forward 2021-25, 1,052 Sunday / Monday games of weeks with early games. Brier stale
  0.2204 -> early 0.2186, -0.0018 [-0.0024, -0.0012]; every season better (2021 -0.0022, 2022 -0.0020, 2023 -0.0022,
  2024 -0.0011, 2025 -0.0014); win chances on those games move 0.8 points on average. Week N+1 (reported): -0.0003
  [-0.0014, +0.0007]. A first run read league play volume at week N+1 (it counted the masked Sunday games' plays); the
  rerun with week N's volume in both arms gives the same answer (above). Thursday teams play no second game that week,
  so the gain comes through their opponents' opponent-adjusted ratings and Elo, league-wide. Shipped:
  team_model.sunday_refit takes the week in groups (the games before Sunday once all are in, then the weekend through
  its last Sunday, then a Monday game as soon as it lands); tools/news_watch.py builds when a group completes (not on
  a partial Sunday); Power reads "Week N in progress · X of Y games in" / "After week N" / "Going into week N".
- **PRE-REGISTERED 2026-10-26 (owner: "i'm suspect of our calc / win prob models if every single coach is less
  aggressive than us"): (DO) why the calculator says "go" more than nfl4th.** Measured first (scratch/calc_val rows,
  2022-25, 19,083 4th downs with both models): we recommend going for it on 50.0%, nfl4th 40.4%, coaches went 20.8%
  (own side 42.6 / 31.5 / 8.1). On the 2,885 plays where we say go and nfl4th kicks, both forecast the chosen option
  within a point of the share won (went: ours 34.1, nfl4th 33.3, won 33.3; kicked: ours 52.4, nfl4th 53.4, won 53.0;
  Brier ours 0.0863 / 0.1312, nfl4th 0.0848 / 0.1308): close calls (our go edge there +0.9 points, nfl4th's -0.8), where
  we sit ~0.8 points higher on go and 0.6-1.1 lower on the kicks. Overall levels match (go +0.4, punt +0.1, fg -0.2).
  Stage 1 (diagnostic, no gate; tools/do_eval.py): each part of the decision against what happened, 2022-26 walk-
  forward graded rows (site data/calc/graded_<season>.json, each season graded with a model fit on earlier ones),
  overall and on the disputed region (our best go, our go edge 0 to 3 points): (a) P(convert) on tries by distance and
  field zone; (b) P(field goal good) by distance; (c) each branch's win chance (converted, failed, made, missed) and the
  punt's, won minus forecast with 95% intervals by games; (d) which parts, moved to match their outcomes, close the gap
  to nfl4th's recommendation rate. Stage 2 (pre-registered after stage 1, from what it finds): a fix for any part off
  by 2+ points where it matters, gated on (CJ) check (1) still passing and the disputed plays' chosen-option Brier no
  worse. The Staff tile's 0-99 aggressiveness (2026-10-26) compares coaches with a typical-coach model, not with the
  calculator, so it does not wait on this.
- **FINDING 2026-10-26: (DO) stage 1, tools/do_eval.py (16,804 graded 4th downs 2022-26, walk-forward).** No single part
  is far off; three small ones all lean "go" on close calls. Actual minus forecast, 95% by games: field goals of 50+
  yards +3.3 [+0.1, +6.5] (811; kickers make more long ones than the model expects: kicking undervalued); 4th & 1
  conversions -1.5 [-4.2, +1.1] overall, -3.6 [-7.4, +0.0] in the disputed region (our go edge 0-3 points: going
  overvalued); the converted branch's win chance -0.7 overall, -1.5 [-3.5, +0.5] disputed ((CO2): going overvalued). The
  other way: missed field goal -2.8 [-6.0, +0.2] ((CO2): kicking overvalued). Punts -0.3, failed tries +0.2, made field
  goals -0.7, conversions by zone within 2. Each 1-3 points, together enough to flip coin-flip calls (our go rate 50% vs
  nfl4th's 40%). Firmest: long field goals (kicking improves season by season; the field goal model weighs 2006 on).
  Stage 2 candidates, to pre-register one at a time: (A) field goal make probability with a season trend / recency
  weight; (B) 4th & 1 conversion (the disputed-region read is borderline: re-check on 2026 weeks 8+ before fixing);
  (C) the win model's post-conversion and post-miss over-reads (CO2).
- **FINDING 2026-10-26 (owner: "why are we saying go for it on 4th and 8 so much more often than everyone else? ... is
  the probability you convert on 4th and 8 that we're working with real? does the context matter?"): (DO) where coaches
  and nfl4th part ways with us, tools/do_disagree.py (19,083 4th downs 2022-25).** Go rate ours / nfl4th / coaches by
  distance: 1 yd 91 / 93 / 71; 2 83 / 81 / 40; 3 74 / 67 / 30; 4-5 64 / 51 / 18; 6-7 52 / 35 / 10; 8-10 35 / 21 / 8;
  11+ 15 / 6 / 6. Coaches part with both models at 4th & 2-3 in their own 21-40 and at midfield (models 60-85% go,
  coaches 4-19%); with us alone at 4th & 4-5 inside the opponent's 35 (61% vs nfl4th 41-43%). Of the 2,885 plays where
  we go and nfl4th kicks, 66% are 4+ yards and 74% are within 1.25 points; the widest split is a 9+ point lead before
  the last 10:00 (43% vs 22%; both put go and punt within a point, ~90%). 4th & 7-9: ours 40%, nfl4th 25%, coaches 7%;
  of our go calls there 44% lead by under 0.5 points, 61% under 1, 80% under 2. (a) The conversion odds hold up: a
  first pass compared them with tries that leave out defensive penalties giving a first down (the graded rows' conv)
  and read 3-6 points high at 8-10 yards; counted as the model counts them (calc_inputs._gain_rows, as (CM) found),
  2022-25 3rd & 8-10 converted 33.8% (5,787) and 4th & 8-10 34.5% (229) vs the model's ~34; 6-7 yards 42.1 / 44.1 vs
  ~42. No conversion fix. (b) Context: 3rd & 8-10 converts 30-32% in every score and time cell (penalties out) except
  protecting a late lead (24-26%); it moves the value of going, which the win model carries, not the odds. (c) The
  split at 4th & 7-9 where we go and nfl4th kicks (744): our go +0.9 points over nfl4th's, our punt -1.0, field goal
  -0.9; on the 446 punts there won 54.3%, ours 54.9, nfl4th 55.8 (ours closer). So the gap is a ~1.5-point lean on
  toss-ups from the win model's branches (stage 1: converted branch -1.5 disputed, 50+ yd field goals +3.3), not the
  conversion odds. Next: stage 2 (A) field goals, (C) the converted branch; a "toss-up" label under ~1 point.
- **SHIPPED 2026-10-27 (owner: "tame our own aggression a little bit by deferring very close decisions"; then, shown
  the cost: "neutral toss up, but we want to track coach decisions within that band"): toss-ups have no best call.**
  Deferring close calls to the kick was measured first and dropped: deferring under 1.5 points takes our go rate
  50% -> 22% (nfl4th 40%, coaches 21%) and 4th & 1 91% -> 63% (below coaches' 71%); even 0.25 points takes 4th & 1 to
  82%, and agreement with nfl4th falls at every threshold (79.4 -> 78.9 at 0.25, 75.1 at 1.5). Early-game edges are
  small in win-chance terms, so a deferral flips short-yardage calls as much as long ones. Shipped instead: under the
  engine's TOSS (1.25 points, (CJ)) between the top two options, grade() returns toss, nothing is marked best, and
  either call reads "Toss-up" (calculator, graded calls, gamecast decisions). Staff tile: "On toss-ups" (went for it vs
  the typical-coach model in the band: leans aggressive / conservative / down the middle) and "Wrong on clear calls"
  (the share of non-toss-ups where the coach chose another option). 2022-25: 46.2% of 4th downs are toss-ups; there
  coaches went 20.9% while go was narrowly on top in 55.4%; on clear calls coaches chose otherwise 27.0%, 93.8% of
  those kicking when going was clearly better; our clear-call go rate 45.3%. Same day (owner: "veer away from right
  and wrong and stick strictly to more or less aggressive ... what's wrong is losing"): the Staff tile shows no
  verdicts. "On toss-ups" and "Against our model" (on clear calls: went when it said kick vs kicked when it said go) are
  bars centered on a reference, not league ranks: a team has ~15-25 toss-ups where the typical coach goes ~4 times
  (MIN: 0 of 15, typical 0.4), so a rank there is noise; the toss-up dot is (went - typical) in SDs of chance, named a
  lean only past 1.5 (4 teams in 2026); the model row's middle is in step with the model (ranked against a league that
  kicks more than the model says, MIN with 0 bolder and 6 more conservative read 4th boldest). 2026 so far: 8 bolder,
  241 more conservative than the model league-wide. Then (owner: two-point rates "without game situation in the
  formula ... 24-26 with 30 seconds left. DUH you're going for 2"; and "45/99 reads like he went for it on 4th almost
  half the time"): two-point tries and the 4th-down rating use the same centered bar, each against its typical-coach
  model (two-point: score after the touchdown, time, quarter, line, every try 2022 on). Raw two-point share ranked LV
  1st (26%); against the spots it went 5 vs 4.4 expected. 2026 week 7: 6 teams lean on 4th downs past 1.5 SD (NE, PHI,
  DET, CHI aggressive; DEN, HOU conservative), none on two-point tries. Then pace and no-huddle rows dropped; added
  pass rate over expected (nflverse xpass, win chance 10-90%, outside a half's last 2:00; replaces the raw early-down
  share) and early 2nd-half timeouts (3rd / 4th quarter before the last 2:00, per game vs the league, Poisson z).
  Checked first, 2014-25: a team's rate predicts its next season's under the same head coach (r 0.49, 273 pairs) more
  than across a coaching change (0.33, 76): a coach's habit. Rejected for clock management: timeouts left at the end
  of one-score losses (most ended on kneels nothing could stop) and letting the clock run on defense late with
  timeouts in hand (under one case per team-season, 2022-25).
- **PRE-REGISTERED 2026-10-28 (owner: "among the players that are in the HOF, what are trends among them? ... can we
  test that categorically? ... can we create a hall of fame calculator? what's the recipe as defined by history for
  getting in?"): (DP) a Hall of Fame model.** Descriptive first (nflverse draft picks, Pro Football Reference's career
  columns): of 8,032 players drafted 1980 on whose careers ended by 2020, 102 are in. By first-team All-Pros: 0 ->
  0.1%, 1 -> 6%, 2 -> 25%, 3 -> 69%, 4 -> 89%, 5+ -> 93%; Pro Bowls 0-2 -> ~0%, 3-4 5%, 5-6 25%, 7-8 67%, 9+ 93%;
  a typical inductee 3 AP1, 7 PB, 12 seasons as a starter, ~100 career AV; QBs get in on volume (median 1 AP1, 9 PB,
  AV 145). Rows: drafted 1980 on, career over by 2015 (6+ ballots by the 2026 class); outcome PFR's hof flag (current
  through the 2026 class). Undrafted inductees (Warner, Gates, Randle) are outside the data. Inputs: first-team
  All-Pros, Pro Bowls, career AV (w_av), seasons started, games; major awards (MVP, OPOY, DPOY, Super Bowl MVP: ESPN's
  award history, 1980 on, matched by name); Super Bowl titles (on a champion's season roster: nflverse rosters, 1980
  on, matched to the draft rows by name and team); position group; and the position's main career stat as a
  percentile among that group's players (QB pass yards, RB rush yards, WR / TE receiving yards, DL / LB sacks, DB
  interceptions; OL / K / P none). Models: (A) first-team All-Pro count alone (logistic on its bins); (B) a ridge
  logistic on everything above, the penalty chosen inside the folds. TEST: 5-fold cross-validation grouped by draft
  class; mean log loss per player, out of fold; 95% bootstrap interval over players. GATE: B ships if its log loss is
  lower than A's with the interval excluding 0; else the calculator is A's table. Reported either way: each input's
  worth (B's out-of-fold log loss with that input group dropped, minus B's, with interval: "does a ring matter once
  the All-Pros are known?"); calibration by decile; the recipe by position (what the median inductee had); and, held
  out, players whose careers ended 2016-20 (most still on the ballot: their predictions next to the classes to come).
  Ships as: a Hall of Fame chance on each player card's Honors sheet ("if his career ended today" for active players)
  and a Hall of Fame watch list.
- **RESULT {#hof-model} (DP) a Hall of Fame model: PASS, shipped.** tools/hof_eval.py, 7,011 careers over by 2015 (92
  inductees), 5 folds by draft class. Log loss A (first-team All-Pro count) 0.0212, B (full) 0.0117, B - A -0.0095
  [-0.0148, -0.0050]; AUC 0.952 vs 0.998. Calibration (B, out of fold): top 25 predicted 24.8 / actual 25; 26-50 23.6
  / 24; 51-100 28.3 / 28; 101-300 13.1 / 14; the other 6,711 2.1 / 1. Each input's worth (dropped from B, log loss
  up by): All-Pro +0.0027 [+0.0004, +0.0054], Pro Bowl +0.0024 [+0.0006, +0.0046], career (AV, starts, games) +0.0008
  [+0.0001, +0.0015]; awards +0.0004 [-0.0000, +0.0009], rings +0.0003 [-0.0006, +0.0012], position and the career
  stat percentile ~0. So the recipe is All-Pros and Pro Bowls, then a long career as a starter; MVP / Player of the
  Year awards and rings add a little at the margin (positive in the fit: OPOY +0.81, SB MVP +0.85, rings +0.52, MVP
  +0.20 per award) but nothing the selections don't mostly carry already. By position (inductees' median AP1 / PB /
  starter seasons / AV): QB 2 / 9 / 16 / 142, OL 4 / 9 / 12 / 100, LB 5 / 8 / 12 / 117, DB 3 / 8 / 13 / 103, DL 3 / 7 /
  12 / 100, WR 3 / 6 / 13 / 104, RB 2 / 6 / 10 / 107, TE 5 / 11 / 14 / 88. Inductees it missed (lowest out of fold):
  Jimbo Covert (2 AP1, 2 PB, 57 AV), Steve McMichael, Isaac Bruce, Edgerrin James, Rickey Jackson, Andre Tippett; not
  in, rated highest: Kevin Williams .92, Darren Woodson .90, Mike Alstott .83, Torry Holt .71, Steve Wisniewski .69.
  Held out, careers over 2016-20 (1,021): 10 in so far, 19.6 predicted (most still on the ballot); its top 20 hold
  all 10 (Brees, Peppers, Ware, Joe Thomas, Revis, Freeney, Kuechly, Fitzgerald, Andre Johnson, ...) and next Earl
  Thomas .88, Shane Lechler .83 (specialists: one inductee in training, so a punter with 6 AP1 reads high), Jahri
  Evans .80, Witten .79. Limits: drafted players only (Warner, Gates, Randle outside); on-field resume only (Antonio
  Brown reads .96). Shipped: tools/hof_eval.py --export (CI step "Hall of Fame") -> data/hof_chance.json; the
  Honors sheet's Hall of Fame chance and watch list. Awards and champion rosters through 2025 committed
  (data/history/hof_inputs.json).
- **PRE-REGISTERED 2026-10-28 (owner: "i don't see why we're ignoring undrafted players ... any other way to get our
  main model more accurate? what other trends are there among guys who got in? among guys who didn't that we thought
  should?"): (DP2) the Hall of Fame model, extended.** Measured first (out of fold, DP's B): among players with 3+ Pro
  Bowls (300, 90 in) AUC 0.961, 89.7% right at 50%, 69 of 90 inductees called in, 10 called in who aren't; with 5+
  (146, 81 in) 0.927, 82.9%. Inductees it rated under 50% (23) waited a median 9 years past eligibility (those over 90%:
  1), many as seniors; they cluster as receivers with few All-Pros but big career totals (Bruce, Tim Brown, Reed,
  Monk, Irvin), All-Decade selections (Covert, Stephenson, Easley, Boselli) and dynasty rings (Aikman, Irvin, Haley).
  Rated over 50% and not in: still-eligible receivers and linemen (Holt, Wayne, K. Williams, Woodson), a fullback
  (Alstott: All-Pro as a fullback), 80s-90s linemen and linebackers (Wisniewski, Mecklenburg, L. Brown). Candidate
  inputs, each tested on DP's rows and folds (careers over by 2015, 5 folds by draft class, out-of-fold log loss,
  95% bootstrap over players): (1) All-Decade team, first or second (Wikipedia's NFL 1980s / 1990s / 2000s / 2010s
  All-Decade Team pages); (2) all-time career rank at the position among every player in the data (QB pass yards, RB
  rush yards, WR / TE receiving yards and receptions, DL / LB sacks, DB interceptions), as top-5 / top-10 / top-25
  flags replacing DP's percentile; (3) years eligible (the class year minus the first eligible class; censoring: a
  non-inductee eligible 3 years is not a non-inductee eligible 20), with predictions read at 20 years eligible as the
  eventual chance; (4) fullback as its own position. GATE per input: added to B, out-of-fold log loss lower with the
  interval excluding 0; the inputs that pass ship together (and the set refit and re-checked against B). Separately,
  (5) undrafted players: a model C without the career-value inputs (AV, starts, games: Pro Football Reference's,
  drafted players only), All-Pro and Pro Bowl counts from Wikipedia's yearly pages (extended back to 1980), checked on
  the drafted rows' folds against A (All-Pro count alone); GATE: C's log loss lower than A's with the interval
  excluding 0; then C scores every undrafted player since 1980 (outcome from data/history/hof.csv).
- **RESULT {#hof-model-2} (DP2) the Hall of Fame model, extended: All-Decade and all-time rank PASS; years eligible and
  fullback FAIL; model C PASS. Shipped.** tools/hof_eval.py --dp2=1. Added to B (log loss 0.0117), new - B, 95%:
  All-Decade -0.0012 [-0.0023, -0.0001] PASS; all-time rank at the position (top 5 / 10 / 25) -0.0010 [-0.0019,
  -0.0001] PASS; years eligible -0.0004 [-0.0008, +0.0001] FAIL; fullback +0.0000 FAIL. The two together -0.0020
  [-0.0035, -0.0004]; among players with 3+ Pro Bowls AUC 0.961 -> 0.975, right at 50% 89.7% -> 91.3%. C (B without
  career value, starts, games, the stat percentile and rank; with All-Decade) vs A on the drafted rows: -0.0097
  [-0.0150, -0.0053] PASS (C 0.0116, about B's). Outside the draft table (players since 1980 not in nflverse's draft
  picks: undrafted and the 1984 / 1987 supplemental drafts; 11 of 112 inductees whose careers began 1980 on): All-Pro
  and Pro Bowl counts from Wikipedia's yearly pages 1980-98 (three layouts: "Name, Team", "Name – SF", AFC / NFC lists)
  and our honors data 1999 on; careers over by 2015: 9 in, 12.9 predicted, AUC 0.998. Inductees: Reggie White 1.00,
  Steve Young 1.00, Randle .97, Zimmerman .95, Gates .89, Cris Carter .87, Vinatieri .79, Warner .55, Moon .39 (a QB
  with no AP1: his case was volume, which C can't see), Sam Mills .07 (a seniors pick). With the new inputs, Harrison
  Smith .13 -> .03 (no All-Decade, outside the top 25 in interceptions); Darren Sharper .90 (All-Decade, interceptions:
  his convictions are off the field). Specialists still read high (Lechler .95, Landeta .85: one or two inducted to
  learn from); the card says so. Shipped: export fits B (with All-Decade and rank) for drafted players and C for
  everyone else; inputs committed (data/history/hof_inputs.json: awards, champion rosters, All-Decade, 1980-98
  selections).
- **SHIPPED 2026-10-28 (owner: "add the threshold summary"): the wait by chance band** on the Honors sheet (inductees
  whose careers ended by 2015, out-of-fold chance, years past first eligibility: 95%+ 69% first ballot, median 0;
  80-95% median 4 (1-6); 60-80% 2.5 (1-7); 40-60% 8 (6-13); 20-40% 8 (3-9); 5-20% 9 (6-14); wait ~ 13.5 - 11.9 x
  chance), with the year on the ballot for eligible players and "waiting longer than most" past the band's range.
  High-chance inductees who waited 4+ years: Terrell Davis .98 (10 years: four great seasons), Russ Grimm .86 (13),
  Zach Thomas .93 (9), Doleman, Dawson, Kennedy, Faneca, Tim Brown, Barber; linemen, front seven, position logjams,
  short careers. Also (owner): an asterisk and "on the field only; off-field matters can weigh on the vote" for a
  short hand-kept list (Sharper, Antonio Brown), no specifics.
- **PRE-REGISTERED 2026-10-28 (owner: "you can test backlogs too can't you? ... i hypothesize the backlog matters less
  when our model gives a certain percentage"): (DP3) what sets the wait.** Rows: every eligible ballot year of every
  drafted player (careers over by 2015) with a DP2 out-of-fold chance of 2%+, from his first class (last season + 6)
  until he is inducted or through 2026; outcome: inducted that year. A discrete-time hazard (logistic per ballot
  year). Base: logit(chance) and log(1 + years already waited). Candidates: (1) backlog: the sum of the chances of
  the other players at his position group still waiting that year (eligible, not in), standardized; (2) the owner's
  hypothesis: backlog x logit(chance), backlog mattering less the higher the chance; (3) career length: log of his
  seasons in the league. TEST: 5 folds grouped by player, out-of-fold log loss over ballot rows, 95% bootstrap over
  players. GATES: (1) base + backlog beats base (interval below 0) and its coefficient is negative (a crowd slows
  him); (2) adding the interaction beats base + backlog, and the fitted interaction is positive (bootstrap interval
  above 0: at high chance the backlog's drag shrinks); (3) base + career length beats base. Reported: the backlog's
  effect at chance 50% / 80% / 95% (the wait it adds); limits: inductees and candidates from before 1980 crowd ballots
  too and aren't in the data. If any pass, the Honors sheet's wait line uses the fitted hazard (expected wait given
  his chance and today's backlog at his position) instead of the band table.
- **RESULT {#hof-wait} (DP3) what sets the wait: backlog FAIL, backlog x chance FAIL, career length FAIL; the band
  table stays.** tools/hof_wait_eval.py: 199 players, 2,326 ballot years, 91 inductions. New - old, out-of-fold log
  loss per ballot year: + backlog +0.00115 [+0.00038, +0.00203] (worse); + backlog x chance +0.00079 [-0.00054,
  +0.00243]; + career length -0.00022 [-0.00183, +0.00132]. The fitted directions are the expected ones but small:
  backlog -0.11 per SD (a crowd slows him), interaction +0.05 [-0.05, +0.14] (the owner's hypothesis: less drag at
  high chance), career length +0.98 per log-season (longer careers in sooner). In years: at a 50% chance a light vs
  heavy backlog (-1 / +1 SD) waits 8.3 vs 8.5 years, at 80% 6.6 vs 6.7, at 95% 3.6 vs 3.2. So the backlog as we can
  measure it doesn't move the wait: position groups are coarse (LB and DL apart, but every OL together), and the
  ballot's other crowd (seniors, pre-1980 careers, undrafted players) is outside the data. Long waits stay mostly
  unexplained beyond the chance itself (Davis, Grimm, Z. Thomas): voters' case-by-case judgment. Also shipped (owner):
  the off-field asterisk.
- **PRE-REGISTERED 2026-10-28 (owner: "something seems off about our player durability percentiles ... josh allen ...
  missed 4 games in like his rookie year, then became iron man ... 85th percentile somehow seems low"): (S3)
  durability, counted by episodes, re-shrunk, recency-weighted.** Measured first: Allen 4 games missed (one episode,
  2018 elbow) in 8,481 snaps, 0.47 per 1,000, 15th of 94 QBs; ranked above him: Cam Ward 1,343 snaps, Cooper Rush
  1,336, Ridder 1,253, Cassel 1,216, Mills 2,015, all 0 missed. Three causes: games missed are the events (one injury
  that costs four games counts four times); (S)'s shrink, 250 snaps (about four QB games), was never re-chosen for
  (S2)'s target; every past season counts the same. Candidates on (S2)'s harness (tools/durability_snaps_eval.py:
  player-seasons 2014-25, target snaps survived before the first game missed injured, C-index within group, weighted
  by rows), each against today's B: (E) injury episodes that cost a game instead of games missed; (K) the shrink
  re-chosen on 2014-19 from 250 / 500 / 1,000 / 2,000 / 4,000 snaps (one value for all groups but TE, kept at 2,000
  unless the grid says otherwise); (R) each past season weighted 0.5^(age / h), h chosen on 2014-19 from 2 / 3 / 5
  seasons (snaps and events alike). The combinations of those that pass are tested together. GATE (2020-25): C-index
  better than B, 95% player-cluster bootstrap interval excluding 0, better in 4+ of 6 seasons. Ships to the card's
  durability (tools/player_logs.py) if it passes; reported: where Allen and the 1,000-1,500-snap zeros land.
- **RESULT {#durability-episodes} (S3) durability by episodes, re-shrunk, recency-weighted: episodes PASS, shipped;
  re-shrink and recency FAIL.** tools/durability_s3_eval.py. Chosen on 2014-19 (mean C-index): episodes best at K
  2,000 (0.5958; games at K 250 0.5877), games best at K 250 (re-shrinking games changes nothing), recency best at h 3
  (games, 0.5890). 2020-25 against today's B: (E) episodes, K 2,000 +0.0068 [+0.0017, +0.0116], better 5 of 6 PASS;
  (K) +0.0000, 0 of 6 FAIL; (R) h 3 +0.0010 [-0.0012, +0.0034], 4 of 6 FAIL (a first run's interval read 0: its
  bootstrap compared the weighted history with itself; fixed, the old score now from the unweighted rows). Shipped
  (tools/player_logs.py): injuries that cost a game, from 2013, per 1,000 unit snaps, shrunk 2,000 snaps for every
  group; the card shows injuries per 1,000 snaps. QBs, 94 ranked: Allen 15th (85th pct) -> 4th (97th), behind Brady,
  Rivers, Eli Manning (no injury-missed games in 6,539-10,879 snaps); the one-season zeros fall from 11th-14th to
  26th-30th (Ward, Rush, Ridder, Cassel, ~70th pct); Mahomes 25th, Burrow 40th, Lamar Jackson 54th.
