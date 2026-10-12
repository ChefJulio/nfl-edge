---
documented_code_hash: eec2b8e8c037b71f
---
# How the model works

NFL Edge projects weekly fantasy points for QBs, RBs, WRs and TEs and rates every team, using only free data. Every number on this site comes from the pipeline below. Values shown in **bold blue** are filled in live from the current build, so they always match what produced this week's report.

**Pipeline, start to finish:** load and cache data, then fit opponent-adjusted team ratings. From those, predict each game's volume and score, project each player's share of that volume and his efficiency, and adjust for availability and injuries. Finally, blend with the expert consensus where that has been shown to help, and attach calibrated ranges. Everything learned from history is trained only on the **{{ L.train_seasons }}** seasons *before* the one being projected or tested (a fixed window, so every backtest season is trained exactly like the live site).

## 1. Data and refresh

| Source | Used for |
|---|---|
| nflverse play-by-play (via `nflreadpy`) | Every play's expected points added (EPA), win probability, players involved, field position, air yards |
| nflverse schedules | Results, Vegas spread and total, roof, kickoff time |
| nflverse rosters, snap counts, injury reports, depth charts, draft picks | Who is on the team, who played, roles, statuses, draft capital |
| NFL.com injury API | Day-by-day Wed/Thu/Fri practice participation |
| FantasyPros expert consensus (via nflverse) | Weekly positional ranks, published Fridays |
| PFR advanced defensive stats | Tested for defender values (not used, see section 8) |
| Open-Meteo | Wind forecast at kickoff for outdoor stadiums |

Seasons loaded: **{{ L.seasons }}**. Completed seasons are downloaded once and cached. The current season is refetched only when a new game goes final, and injury reports, rosters and depth charts are refreshed every few hours. The site rebuilds on every code push and once a day. The trained model is cached and only retrains when data, configuration or model code changes.

## 2. Team ratings

Each play's EPA (how much the play changed the expected score) is modeled as

> EPA = league average + offense strength + defense strength + home edge

fit separately for **passing** (dropbacks, including sacks and scrambles), **rushing** (designed runs) and **special teams** (punts, kickoffs, field goals, extra points). Kneels, spikes and two-point tries are removed, and so is garbage time: passing and rushing plays count only when the offense's win probability is between **{{ L.wp_min }}** and **{{ L.wp_max }}**.

- **Opponent adjustment.** Solving for all teams at once (ridge regression) means a defense that faced weak offenses gets less credit than its raw numbers suggest. Ridge regression shrinks each team toward average by an amount (alpha) chosen by **time-split cross-validation**: fit on weeks 1 through N, predict week N+1, repeat, and never shuffle. Current alphas: pass **{{ L.alpha_pass }}**, rush **{{ L.alpha_rush }}**, special teams **{{ L.alpha_st }}**.
- **Recency.** Plays from this season are weighted with a half-life of **{{ L.hl_team }}** weeks. Last season's plays start at weight **{{ L.prior_weight }}** and fade to zero by week **{{ L.prior_decay }}**.
- **Quarterbacks.** Passing offense = the team (line, receivers, scheme) + its quarterback + a penalty for inexperienced quarterbacks (fewer than **{{ L.qb_cut }}** career dropbacks). The team and QB shrinkage amounts are tuned jointly. QB shrinkage alpha **{{ L.alpha_qb }}**, inexperienced-QB effect **{{ L.qb_inexp }}** points per 100 dropbacks. Highest current QB effects: {{ L.top_qbs }}.
- **Home field.** One league-wide edge per unit, learned from recent seasons (currently pass **{{ L.home_pass }}**, rush **{{ L.home_rush }}** points per 100 plays). Neutral-site games get none.
- **Certainty.** Ratings are refit on **{{ L.bootstrap }}** resamples of games (a cluster bootstrap). The Power tab turns that spread into a rank range: the middle 80% of simulated rankings.

Ratings are estimated per play. On the Power tab they are shown as **points per game versus an average team** (per-play rating x a league-average number of those plays), so the units add up; per-play values appear on hover. Higher is better for both offense and defense, because the defense number is flipped so "good" always reads positive.

**Field position is already accounted for.** EPA judges every play against what was expected from that exact down, distance and field position. A defense handed a short field by its offense's turnover starts the drive already "owing" the high expected points of that spot, and is charged only for what happens beyond that; the turnover itself counts against the offense that committed it. Raw points-allowed would wrongly blame the defense.

## 3. Game lines

- **Volume.** Each team's expected plays and pass rate come from regressions learned on past games: its own pace, the opponent's pace allowed, and (for player projections only) the Vegas total and spread. Pass rate uses the team's neutral-situation pass rate over expected (PROE) and the game script implied by the spread.
- **Points.** Expected offensive EPA per game (dropbacks × pass EPA + rushes × rush EPA, against this opponent), plus the special-teams edge, converts to points through a calibration learned on history: {{ L.points_model }}.
- **Model lines** (Matchups tab) use team ratings and the projected starting quarterbacks only, never Vegas, so a disagreement with Vegas is a real second opinion. Edges appear at 1+ point on the spread or 1.5+ on the total, and are highlighted at **{{ L.margin_disagree }}+** and **{{ L.total_disagree }}+**.

## 4. Player projections

**Projection = projected volume × efficiency per opportunity × matchup**, computed stat by stat (passing yards, TDs and interceptions; rushing yards and TDs; catches, receiving yards and TDs; fumbles) and then scored with the scoring file (default half-PPR).

**Volume.** Usage shares are recency-weighted (half-life **{{ L.hl_share }}** weeks) over games the player actually played: dropbacks for QBs, share of designed carries, and targets per team dropback. A learned calibration pulls each share toward the player's longer-run average, because recent spikes partly regress. The team's projected dropbacks and rushes then turn shares into opportunities.

**Efficiency.** For each stat per opportunity (yards per target, catch rate, TD rate and so on):

1. *Empirical-Bayes shrinkage.* The player's rate is pulled toward the average for his position and draft-round tier. How hard depends on how noisy that stat is, estimated from data as a "prior strength" k in pseudo-opportunities. Examples: WR catch rate k ≈ **{{ L.k_wr_catch }}**, WR yards per target k ≈ **{{ L.k_wr_ypt }}**, RB yards per carry k ≈ **{{ L.k_rb_ypc }}**. A small k means the stat is mostly real skill; a large k means it is mostly noise.
2. *Expected touchdowns.* Instead of raw TDs, each touch and target carries the historical TD rate for its field position (and end-zone targets). The player's TD rate blends toward his actual TDs as his sample grows (weight n / (n + **{{ L.td_k }}**)).
3. *Learned efficiency regressions* combine the shrunk rate, the player's opponent-adjusted EPA, this opponent's defensive rating (the matchup), his own team's offensive rating including its quarterback (the supporting cast), home field, and the Vegas implied team total. **{{ L.n_eff_models }}** regressions are fit, one per stat and position group, on as-of features from earlier seasons.

**Weather.** Wind above **{{ L.wind_thr }}** mph cuts passing efficiency by **{{ L.wind_pen }}** per mph, capped at **{{ L.wind_cap }}**. Domes and closed roofs are always calm.

**Expert blend.** Once the FantasyPros consensus is published (Fridays), RB/WR/TE projections blend it in with learned weights. QBs stay model-only because the model alone beats the experts there. Only rankings published before the player's kickoff are used. Current blends: {{ L.blend }}.

**Ranges and touchdown odds.** The floor, middle and ceiling are the 10th / 25th / 75th / 90th percentiles of what actually happened after past projections of the same size at the position, widened for players with little data or injury-driven roles. Backtest coverage: **{{ L.coverage }}** of actual scores landed between floor and ceiling (target 80%). Touchdown odds (exactly 1, 2, 3+) treat the expected-TD rate as a Poisson count, which matched real frequencies closely in testing.

## 5. Availability and injuries

- **Chance to play.** Gradient-boosted trees on the Wed/Thu/Fri practice sequence (did not practice / limited / full) and game status, trained on 2018+ seasons. Example: Questionable players who went did-not-practice three days played about 26% of the time, versus about 87% for limited, limited, full. Before Wednesday's report, last week's status carries forward using learned week-to-week rates.
- **Healthy scratches.** For players not on the report, a second model uses how often the player has been active this season, whether he played last week, snap share, depth-chart rank, rookie status, and how many teammates at his position ahead of him are out.
- **Scenarios, not discounts.** NFL availability is yes or no, so every projection is "if active", with Inactive% shown separately. Players below 50% are assumed out and their volume moves to teammates. Teammates of Questionable players show a contingent "+X if he sits".
- **Redistribution.** Where vacated targets and carries actually went in past absences, learned by position pair, depth-chart rank and current share, and corrected so a player who has already missed several games is not double-counted (currently applied at **{{ L.redist_scale }}** strength). When a starting QB sits, the backup inherits his dropbacks and the whole passing offense uses the backup's quarterback rating.

## 6. What the report numbers mean

| Number | Definition |
|---|---|
| Matchup rank | The opponent's defense vs the position, 1st (toughest) to 32nd (easiest): the position's fantasy starters projected against every defense, ranked by points allowed. Opponent-adjusted, so not skewed by which offenses a defense has faced. The meter (1-5 bars) and grade follow the rank |
| Matchup bars (Matchups) | The model margin split exactly along the points formula: each offense-vs-defense battle (per-play edge x projected plays x the fitted points per EPA), special teams (net special-teams EPA x its fitted weight), and home field plus play volume / pass-run mix. Overall = the sum, to the decimal |
| Matchup points (hover) | Projection against this defense minus projection against an average defense |
| Tier | League-size buckets for a {{ L.tier_teams }}-team league: QB1 = QB ranks 1-{{ L.tier_teams }}, QB2 = the next {{ L.tier_teams }}, and so on for every position. Pill color is the roster slot the player fills with {{ L.tier_roster }}: green = starter, amber = flex range (best remaining RB/WR/TE), plain = bench |
| Power values | Points per game vs an average opponent: each unit's per-play rating x league-average plays of that type (pass offense includes the starting QB). Offense = Pass O + Run O, Defense = Pass D + Run D, Net = Offense + Defense + ST. League-average volume means a defense is judged on per-play quality, not on how many plays its own offense left it facing |
| Rank range (Power) | 10th-90th percentile rank when every team's net rating is resampled within its bootstrap uncertainty |
| Schedule played / left (Power) | Points per game the opponents took away (played) or would take away (left), unit by unit: the team's actual dropbacks against each opponent's pass defense and runs against its run defense, plus the offenses its defense faced (incl. their QBs). Re-scored weekly with current ratings; 1st = hardest |
| Rank movement (Power) | Change in net-rating rank since ratings as of last week |
| Schedule-adjusted FP/G (Rankings, tap a player) | Each past game rescaled by how easy that defense is for this player's profile; a gap of 1+ FP/G from the raw average is called out as a soft or tough schedule |
| Role changes | Latest game vs the previous three, snap share +{{ L.snap_jump }} or opportunity share +{{ L.opp_jump }} |

## 7. Validation

Every validation number on this site is **walk-forward**: projections for a week use only data available before it, and every learned component is trained only on earlier seasons. Changes are decided on one season and confirmed on the next. Current results on fantasy-relevant players who played:

{{ L.bt_table }}

## 8. Tested and left out

Ideas that sounded right but did not improve out-of-sample accuracy are switched off, not shipped:

- **Team-specific home field.** Team home edges do not persist year to year (correlation -0.02 over 567 team-seasons from 2005-25; Seattle's edge was +5.7 points in 2005-12 and about zero since 2019). Travel distance and time zones showed no effect. A division-game term made cross-validation worse.
- **Defensive and offensive-line absences.** Stat-weighted defender values overfit. Counting only absences knowable before kickoff, no position group (cornerbacks included) or offensive line showed a reliable effect beyond the team rating.
- **Air-yards share, and snap share as an input.** No consistent gain (snap share stays as a role-change alert).
- **Route participation.** Not published for the current season.
- **Time of possession / pace and drive sustainability in the volume model.** Neutral-situation seconds per play and expected EPA per play (offense vs this defense, both ways) did not improve out-of-sample team play counts (plays MAE 6.88 -> 6.87-6.92 on 2025, 6.75 -> 6.78-6.80 on 2026). Drive outcomes are already inside EPA, and time of possession mostly reflects game script, which the Vegas spread captures.

## 9. Keeping this page current

This page is generated from `MODEL.md` in the repository, and the bold values are filled in live at every build. The document carries a fingerprint of the model code and configuration. If either changes without the document being reviewed:

- **On commit:** the git pre-commit hook stops the commit.
- **On build:** GitHub flags a warning.
- **On the page:** this tab shows an "out of date" notice.

After updating the text, run `python tools/model_doc.py --stamp` to record the new fingerprint.

## 10. Formulas and fitted weights

Everything below is generated from the trained model on every build: these are the exact equations and numbers that produced this week's projections. Ratings and EPA are per play unless noted ("per 100 plays" = x100).

{{ L.formulas }}

