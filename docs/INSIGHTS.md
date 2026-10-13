# nfl-edge: accumulated insights

Everything learned building this project (Oct 2026, through week 6 of the 2026 season). Organized as: owner
preferences, data quirks, model findings with numbers, rejected ideas, engineering gotchas, UI decisions, open
threads. Numbers are walk-forward backtest results (train on earlier seasons, test 2025 and 2026) unless noted.

## 1. Owner preferences (Hunter, GitHub ChefJulio)
- **Data-driven or nothing.** Every model change must beat the current model out of sample. If it doesn't, it
  stays off (switchable in config) and gets documented as rejected. Report losses plainly.
- **Free data only.** No paid sources (player props, PFF, etc.).
- **Full transparency.** Formulas and fitted weights are public (Model tab section 10 is generated from the model).
- **NFL availability is binary.** A Questionable player either plays his normal role or sits; never discount a
  projection by play probability. Show "if active" projection + separate Inactive%; teammates get contingent
  "+X if he sits". Players under 50% are treated as out and their volume redistributed.
- **Default scoring: half PPR.**
- **Presentation: elegance and readability first.** Minimal, sleek, dark. Important values easy to find. All
  reasonable columns sortable. He reviews screenshots closely and dislikes clutter, light pills on dark rows,
  inconsistent signals, and anything that looks "mashed together".
- Works by pointing at a topic and asking the agent to do the thinking; propose a plan, then execute.

## 2. Data quirks (nflverse / nflreadpy and others)
- **Scrambles are `pass=1, rush=0`** in nflverse pbp. Any rushing filter must include `qb_scramble==1` or QB
  rushing collapses (this bug once cut projected QB rush yards from ~17 to ~4).
- **Roster status `INA` = that week's game-day inactive list** (the outcome). Use `ACT` + `INA` as "53-man roster"
  for membership; using only `ACT` leaks the answer into availability models and drops last week's inactives.
- **Rosters are per team-week; teams on bye or still to play (MNF) lack the latest week.** Use each team's own
  latest roster week. Using the league-wide max week once dropped entire teams (KC, CAR) from projections.
- **Franchise codes changed over time** (OAK->LV 2020, SD->LAC 2017, STL->LA 2016; LAR vs LA by source).
  `Data.__post_init__` maps every team column to current codes; game_id strings keep the originals.
- **Pending games:** the target week is the first week with no final games. A pending Monday game in the prior
  week must not be treated as played (it once made Allen/Stafford look like scratch risks). Count only games with
  a final score as history.
- **Snap counts are keyed by PFR id**; map to gsis via rosters `pfr_id` (about 19% of rows unmapped, mostly
  non-skill). Availability models train only on "observable" players (those with a mapping).
- **Depth charts changed schema in 2025**: <=2024 weekly (`club_code`, `depth_team`, `formation`); 2025+ daily
  snapshots (`dt`, `pos_abb`, `pos_rank`). `data.depth_for_week` normalizes both. Injured players drop off the
  depth chart, so "players ahead of him" uses snap share, not depth rank.
- **Participation (routes) only through 2025**; not published for the current season, so route-based features are
  unusable live.
- **Team codes:** `LA` (Rams) in pbp vs `LAR` in some sources; normalize to `LA`.
- **Schedules `spread_line` > 0 = home favored.** Wind is null for domes/closed roofs (treat as 0); upcoming
  games have no wind, so `data.forecast_wind` uses Open-Meteo at kickoff (neutral sites skipped).
- **Injury reports (nflverse): one row per player-week with only the final practice status.** Daily Wed/Thu/Fri
  participation comes from NFL.com's API (`api.nfl.com/football/v2/injuries`, token via the public web client key
  in `data.py`), seasons 2016+, ~12 requests per season. Unofficial (may break / ToS gray area); toggle
  `nfl_api_practice`. Each run also archives the live injury report to `cache/injury_snapshots/`.
- **FantasyPros ECR** (via nflverse `load_ff_rankings`): weekly positional ranks scraped Fridays, i.e. after
  Thursday games. Only use a rank if scraped before that player's kickoff. `fantasypros_id` in the ID map is a
  float (cast to int string). PPR pages only.
- **PFR advanced defensive stats** (`load_pfr_advstats(stat_type="def")`) exist 2018+ weekly, joinable to snaps
  by pfr id. Tested for defender values; did not help (section 4).
- **QB career history:** `load_player_stats` 2006+ gives pre-window career attempts so veterans are not flagged
  as inexperienced at the start of the loaded window.
- `nflreadpy.load_teams()` has team colors and ESPN logo URLs (`team_logo_espn`).

## 3. Model findings that shipped (with evidence)
- **Team ratings:** ridge on play EPA per unit (pass/rush/ST), WP 10-90% filter, recency half-life 3 weeks,
  prior season 0.3 decaying to 0 by week 8, alpha by time-split CV.
- **QB-aware pass offense:** offense = team + QB effect + inexperienced-QB indicator (<150 career dropbacks).
  Team and QB penalties must be tuned **jointly** (team alpha fixed first left Lamar vs Huntley at ~0.6 pts/game).
  Pass CV loss 3017.2 -> 2974.5; game-margin MAE 2025 10.75 -> 10.40 (Vegas 10.08); fantasy neutral on normal
  weeks; matters on backup-QB weeks. Inexperienced-QB effect about -13 pts per 100 dropbacks.
- **Vegas implied team total as an efficiency input:** biggest single gain (QB rank corr 0.20 -> 0.38 on 2026).
- **Half-lives:** usage shares 5 weeks, team ratings 3 weeks (small, consistent gains).
- **ECR blend:** helps RB/WR (and TE on 2025), hurts QB; blend RB/WR/TE only. Model alone beats experts at QB.
- **Empirical-Bayes shrinkage** by position x draft tier, prior strength k estimated by method of moments; TD
  shrinkage estimated on expected TDs (role), not noisy actual TDs.
- **Ranges:** empirical quantiles of outcomes by projection size; 77-82% of actuals inside 10th-90th (target 80%),
  50-54% inside 25th-75th. **TD odds:** Poisson on expected TDs is well calibrated (1 TD 20.7% vs 20.2% actual).
- **Availability:** gradient-boosted P(play) on Wed/Thu/Fri practice sequence + game status, trained 2018+:
  Brier 0.1026 vs 0.1081 for status x final-practice table. Questionable DDD ~26-29%, LLF ~85-87%.
  Healthy-scratch GB model: Brier 0.0532 vs 0.0678 (own active rate) vs 0.1211 (base rate).
- **Redistribution** of vacated volume: near neutral overall (helps RB, slightly hurts WR) -> applied at 0.5.
  Required fixes: count only players who appeared for the team THIS season (offseason departures were being
  redistributed), scale by (1 - share of recent games already missed) to avoid double counting, and subtract
  per-position baseline drift (players who suit up beat projected share slightly) before fitting weights.
- **Field position:** EPA already handles short fields and turnovers (defense charged only beyond expected points;
  turnover charged to the offense). Do not switch to points allowed.
- **Power tab units:** points per game vs average at league-average volume so units add up; using league-average
  (not actual) volume keeps defenses from being punished for facing more plays behind a bad offense.
- **Strength of schedule:** unit-aware (team's actual dropbacks vs each opponent's pass D, runs vs run D, plus
  offenses faced), re-scored weekly with current ratings. (A separate Schedule luck tab duplicated Power's
  "Schedule played" and was removed; player schedule-adjusted FP/G lives in the Rankings detail row.)
- **Matchup ranks:** opponent-adjusted defense-vs-position: position starters projected against all 32 defenses.
  Grade/meter/takeaway all derive from this rank (an earlier separate grade contradicted it).

- **Training window is fixed** (`[data] train_seasons = 2`): learned components train on the 2 seasons before
  the target. It used to be "every loaded season", so loading 2018+ for a long backtest trained a different
  (and far slower: alpha tuning re-solves the ridge per week per grid point) model than the site runs.
- **Points formula weights:** points = a + 0.80 x offensive EPA (volume x expected EPA/play) + 2.5 x net
  special-teams EPA (2026 fit; both weights are OLS on ~1,100 training team-games, never hand-set). The ST weight
  is large: SEA's 1st-ranked ST is worth ~5 pts vs DEN. Open data questions (do not override it by judgment):
  is it stable across seasons' fits, and does the free fit beat alternatives on out-of-sample margins? One
  testable explanation: ST ratings are heavily ridge-shrunk (alpha 300), and a regression on a shrunk predictor
  scales it back up, so the weight may simply undo the shrinkage.

- **Full audit 2026-10-12 (39 settings x 2021-25, 12,480 player-weeks, week-clustered CIs; tools/experiments.py
  with --history=8):** changed: share half-life 5 -> 3 (-0.004; RB -0.012), range-widening multipliers removed
  (coverage 78.3/49.5% -> 80.0/50.2%), small-rate priors fitted. Confirmed: implied total (+0.036 without), ECR
  blend RB/WR/TE (+0.013 without), fixed wind penalty (no-wind TE +0.008, fitted wind TE +0.012: it learned a
  positive TE effect), redistribution 0.5, starter share 0.96. Insensitive (within noise): train window 2/3/4,
  prior weight/decay, eff season weights, WP window, QB-inexperience cutoff/penalty, TD k, GB size, redistribution
  trigger, team half-life, QB effects (fantasy), ECR for QB. Bias: actuals exceed projections by +0.25 to +0.49
  for relevant RB/WR/TE (unexplained; partly selection of "relevant" rows?).
- **Usage-share normalization (item 3, 2026-10-12):** projected team totals of target shares vary 1.5x as much as
  actual (sd .110 vs .076); players on over-subscribed teams over-projected (team sum > 1.0: -1.4 pp share).
  `Engine._normalize_shares` pulls each team's totals (players expected to play) toward the training-measured typical
  total. Grid: carries 0.7 + targets 0.3 best (-0.017 MAE, RB -0.043, RB rank .507 -> .525); carries drive it,
  targets alone no difference; full strength over-corrects. Returning-from-injury teammates: real but small
  (-0.9 pp when a 25%+ target earner returns, ~2% of rows) and largely absorbed by normalization.
- **Model vs Vegas on games:** when they pick different winners (367 games 2021-25) Vegas is right 59%; blending
  any weight of the model's margin into Vegas makes margin MAE worse (9.764 at w=0). The game model adds nothing
  over closing lines; its value is structure (battles), and fantasy already uses Vegas implied totals.
- **Rounds 2-4 (2021-25):** wind grid -> 10 mph / 3% / 25% cap adopted (-0.011). No difference: per-position
  share half-life, spread-aware shares (game script already in recent usage), finer draft-pick tiers. Rejected:
  final linear calibration (+0.013, CI excludes 0): projections ARE too extreme at the ends (20+ pt projections
  ~1 pt high) but least-squares correction of the mean hurts MAE on skewed fantasy outcomes.
- **Error breakdown (tools/error_breakdown.py, 2021-25):** share of squared error removed by fixing each layer
  alone: team volume ~0-10%, player share 10/30/34/38% (QB/RB/WR/TE), efficiency 21-31%, TDs 28-50%. Share is the
  largest fixable layer for RB/WR/TE; TDs/efficiency are mostly game-level noise.
- **Game model (tools/game_eval.py):** points formula trained on 6 prior seasons (`points_seasons`): with 2 the
  ST weight drifted 0.9 -> 3.3; with 6 it is ~2 (margin MAE 10.71 -> 10.68, never worse per season, winners
  59.2 -> 61.4%). Fixed ST weights 0-2.5 all within noise. Model-only margin MAE ~10.7 vs Vegas 9.8. Fitted home
  effect on special-teams plays is slightly negative (home ST worse), so 'Home & pace' can favor the visitor.
- **Power = the game model's margin vs an average team** (units x fitted points-formula weights; ST x 2c) so it
  agrees with the Matchups bars exactly; it used to be face-value EPA (an untested display assumption).

## 4. Tested and rejected (do not retry without new data/angle)
| Idea | Result |
|---|---|
| Team-specific home field | No persistence: corr -0.02 over 567 team-seasons (2005-25). Seattle +5.7 (2005-12) vs -0.3 (2019-25) |
| Travel distance / time zones in HFA | No effect |
| Division-game HFA term | Real in results (-0.8 pts, p=0.03) but worsened play-level CV (4698 vs 4676); off |
| Shared stadium (LA, NY) adjustment | Only 7 games ever; no evidence either way; treated as normal home games |
| Air-yards share / aDOT | No consistent gain |
| Snap share as a volume input | ~no gain (also owner spec: snap trend is an alert, not an input) |
| TD blend strength (k 50 / 400) | No effect |
| Stat-weighted defender values (PFR) | Overfit, unstable signs, worse OOS |
| Defensive absences (all groups), O-line absences | No reliable pre-game signal |
| Cornerback absences | Looked real only when counting in-game snap losses; with pre-game-knowable absences the sign flips |
| Pace (seconds/play) and drive sustainability in volume model | Plays MAE no better (6.88 -> 6.87-6.92 on 2025; 6.75 -> 6.78-6.80 on 2026) |
| Gradient border / white logo circles / light pills on dark rows | Owner rejected visually |

## 5. Engineering gotchas
- **Windows shell + heredocs mangle backslashes** (`\n`, `\r`). For any file content with escapes (JS regex,
  Python string escapes), use the Write/Edit tools or a patch script written with Write, not inline heredocs.
  A literal newline once broke the whole page script (all tabs dead); `run.py` now node-checks the script.
- **Bash tool cwd resets** each call; always `cd /c/Dev/BosDev/nfl-edge && ...`.
- **pandas 3:** `Series.map` with a datetime Series as mapper can fail (use merge); `fillna` needs a Series not an
  ndarray; string dtype is Arrow-backed.
- **CSS on table rows:** never decorate rows with pseudo-elements. `tr::before` becomes an extra cell; `tr::after`
  with `tr { position: relative }` works in Chrome but NOT on iPhone (every iOS browser is WebKit, which doesn't
  reliably position rows): the overlay detached and floated as a stray colored line. Row trim is now inset
  box-shadows on the cells (`--top` / `--side` / `--extra` variables). Owner tests on Brave/iPhone = WebKit;
  headless Chrome can't reproduce WebKit bugs.
- **Class-name collisions:** the Model banner's `.stale` styled `td.ecr.stale` cells for weeks unnoticed; scope
  generic class names to their element (`div.stale`).
- **Opacity on `<td>` dims its background** (dark blocks in colored rows); fade text with `color-mix` instead.
- **Tab deep links:** section ids are `tab-<name>` so `#power` doesn't trigger the browser's native anchor jump.
- **Markdown tables in generated docs need blank lines around them** (`docs._blocks`); verify by screenshot, not
  by stripping HTML (a text dump hid that tables weren't rendering).
- **Visual QA:** headless Chrome:
  `chrome.exe --headless=new --disable-gpu --hide-scrollbars --force-dark-mode --blink-settings=preferredColorScheme=0 --window-size=1440,900 --force-device-scale-factor=1.5 --virtual-time-budget=4000 --screenshot=<png> file:///.../report/nfl_edge_week6.html#<tab>`
  then Read the PNG. Headless Chrome will not lay out narrower than ~500px and renders a scrolled window badly:
  for phone width or scrolled states, load the page in a 375px (or 1440px) iframe inside a wrapper HTML and
  scroll from an injected script.
- **Caches:** `cache/model_<key>.pkl` (engine + projections; raw data detached to keep it ~36 MB) and
  `cache/backtest_<key>.parquet`; keys hash config (minus display-only `[tiers]`/`[report]`, see
  `docs.model_config`), scoring, data state and model code. Delete them to force a
  retrain. `cache/logo_bg.json` stores per-team logo circle color choices.
- **Sorting convention:** sortable cells carry `data-v` (raw value); headers take `data-first="asc"` for rank-like
  columns and `class="nosort"` for unsortable ones.
- **MODEL.md fingerprint** covers `nfledge/*.py` except `report.py`/`docs.py`, plus `config.toml`, with CRLF
  normalized (Windows and the Linux CI agree).

## 6. UI decisions (current state)
- Team rows are dark tiles (#171a20), white text, 2px border in the team primary, a full-height 3px secondary
  stripe just inside the left and right edges (owner found centered notches "silly"), 6px radius, 3px gaps. Very dark team colors are lightened just enough to show (`TeamStyle.visible`).
- Logo circles: team primary or secondary, chosen per team by measuring which hides less of the logo's pixels.
- Position badges: QB rose, RB green, WR blue, TE amber, everywhere a position appears.
- Rankings: Matchup = opponent logo + 5-bar meter + DvP rank colored red (1st, toughest) to green (32nd);
  projection range bar; TD donuts; Inactive%; ECR shows last week's rank faded with "lw" until Friday.
- Matchups: model vs Vegas lines in betting notation first; plain-English edge pills ("Model likes X by 1.1 more
  than Vegas"); "Who wins each battle" tug-of-war bars in the two teams' colors (offense fills from the left,
  defense from the right, winner + points this game on the right). Centered +/- bars were too hard to read.
  `battle_colors` swaps to a secondary when both primaries look alike.
  Current card: away team always left, home right; Overall (model margin) on top, then the two
  offense-vs-defense matchups (tap for Pass/Run), then Special teams and Home & pace. Bars are the margin split
  exactly along the points formula (sum = margin to the decimal; the report warns if not), with Power ranks.
  Model box reads "SEA by 4.1 points" (owner's wording); Vegas keeps betting notation.
- Power: points per game, 7 ranked units, rank range (10th-90th pct simulated rank), schedule played/left.
- Tabs: Rankings, Matchups, Power, Role changes, Model. (Track record folded into Model section 7; Schedule luck
  folded into Power + the Rankings detail row.)
- Tiers: league-size buckets (QB1 = QB 1-10 in a 10-team league), pill color = roster slot (starter / flex range /
  bench) for 1QB 2RB 2WR 1TE 1FLEX; `[tiers]` in config.
- Tables are full length; only the page scrolls (owner rejected tables scrolling inside their own box). A table that
  fits its width gets `.fits` (desktop) and its real header sticks natively; a wider one (phone) scrolls sideways,
  which traps sticky, so a header copy rides in a sticky strip under the tabs synced to the sideways scroll. The
  pinned name column is native sticky. Tab bar is opaque (WebKit needs -webkit-backdrop-filter; translucent bars
  let rows ghost through). Owner prefers no dependencies.
- Compact pinned column: once a table scrolls sideways the name cell shows logo + last name at 11px; scrollLeft
  is compensated so content doesn't jump; expands back only at the far left (hysteresis).
- Phone (<=640px): Rankings folds projection + matchup into the pinned player cell and hides those columns;
  name/team columns are pinned (`.stick`) on every wide table; grids use `minmax(0, 1fr)` so content can't widen
  the page.

## 7. Open threads / ideas not yet done
- **Play-caller / coordinator effects** (owner suggestion: Flores, Reid): test whether a coach's effect follows him
  across teams beyond roster; on hold at owner's request.
- **IDP fantasy scoring** (tackles/sacks/INTs) was asked about but the owner never answered whether they play IDP.
- **Next Gen Stats** (separation, RYOE, CPOE) and **FTN charting** (screens, box counts) are free and untested.
- **Daily practice archive:** `cache/injury_snapshots/` accumulates our own Wed/Thu/Fri history going forward.
- Light mode has had little visual review (phone layouts reviewed 2026-10-12).
- The 2026 test season is small (weeks 3-5 at time of writing); re-run experiments as it grows.
- **Return-timing model (nfledge/returns.py, tools/returns_eval.py):** P(plays next game | out injured) from games
  missed, designation (R01 IR / R48 IR-return / R04 PUP / other RES / active), report status, body part, position,
  week; chained for k games ahead with a measured stay-active rate after return. Walk-forward Brier 0.132 vs 0.137
  (designation x missed table) vs 0.178 (rate); wins 4/5 seasons. Isotonic calibration made it worse (rejected).
  No severity data: injury reports say "Knee", not "torn ACL". ESPN's public feed has diagnosis detail + an
  estimated return date (after season end = effectively season-ending) but NO history, so CI archives it daily to
  site/data/espn_injuries/ (archive branch) to test as an input once enough injuries resolve (owner: use it only
  as a data-driven feature, never as truth). Not yet wired into lookahead weeks.
- **Queued:** wire the return model into lookahead weeks; ESPN feature test once data accrues; (designation, weeks missed, injury type, position -> P(active) k weeks
  out; feeds lookahead weeks); rookie / low-data priors from free data (college production, preseason usage);
  expected fantasy points per opportunity; NGS / FTN inputs.
- **Speed:** experiment batches recompute identical stages per variant (e.g. team ratings); stage caching and
  per-worker data windows (5 seasons instead of 9) would cut batch time further.
