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

## 9. Open threads / next steps (as of 2026-10-12)
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
