# Hand-set values audit (2026-10-17)

The owner's rule (INSIGHTS sec. 1): every model number is fitted from data or chosen by walk-forward test. An audit
of config.toml and the model code's constants found 22 values without that evidence (HAND-SET), or with only
coarse evidence (WEAK: one alternative tried, a package-only test, or only the INSIGHTS sec. 5 "Insensitive (kept) ...
within noise" row, which has no numbers; docs/verdict_audit.md records it as "no CI"). About 62 other values checked
out as fitted or tested. Each item gets its own pre-registration in INSIGHTS before it is run; results go there and
in MODEL.md "What we tried".

Done: #8 shrinkage cap 2000, TESTED (INSIGHTS {#shrink-cap}: binds in 9-15 of 22 cells; 500 chosen, mixed 2024-25; lower bound never binds). #7 `newcomer_scale` 0.5, TESTED (INSIGHTS {#newcomer-scale}: .7 chosen, worse 2024-25). #6 `eff_season_weights` [1, .6, .3], TESTED (INSIGHTS {#eff-season-weights}: grid flat within +-0.003). #5 `half_life_weeks` 3, TESTED (INSIGHTS {#half-life}: 8 chosen, failed 2024-25; 4 vs 3 rechecked on full 2026). Range calibration, TESTED (INSIGHTS {#range-oos}: out-of-sample offsets no better; coverage 76-82% in starting tiers). (AB) penalties in team ratings, TESTED: penalty unit, DPI as a pass, called-back results all FAIL (INSIGHTS {#pen-unit} {#dpi-pass} {#called-back}). #4 `redistribute_min_share` tgt .08 / carry .15, now TESTED (INSIGHTS (AC) {#redist-min-share}: grid flat within +-0.0007). #3 availability model settings, TESTED (INSIGHTS (AA): week model's alternative passed 2024-25 but not 2026 so far, recheck at season end; Tuesday's alternative worse). #2 `td_blend_k` 150, now TESTED (INSIGHTS (Z) {#td-blend-k}: 25-600 and xTD-only within +-0.0012). #1 `prior_weight` / `prior_decay_week` 0.3 / 8, now TESTED (INSIGHTS (X) {#prior-season-weight}). `injuries.redistribution_scale` = 0.5, now TESTED (INSIGHTS (V) {#rb-redist-scale}: RB 0.65 / 0.8 / 1.0 no better).
Related open decision: redistribution trades MAE for bias (INSIGHTS sec. 5, 2026-10-15: on the 1,825 rows it changes,
MAE +0.031 [+0.019, +0.042] with it, while teammates of a sitting player go from -0.15 to +0.01 bias); "Owner's call
(pending)".

| # | Impact | Parameter (file:line at audit) | Value | What it does | Evidence | Suggested test |
|---|---|---|---|---|---|---|
| 1 | high | `team_model.prior_weight` / `prior_decay_week` (config.toml:22, 24) | 0.3, fading to 0 by week 8 | Last season's weight in every team rating; weeks 1-7 of every projection | Initial commit; line-288 row only; a 3-season game test (INSIGHTS ~1199) favored 0.6 in weeks 2-8 (margin MAE -0.13 [-0.24, -0.01]), parked | weight {0, .3, .6, 1} x fade week {6, 8, 10, 13}; margin MAE 2021-25, fantasy MAE guard |
| 2 | high | `player_model.td_blend_k` (config.toml:66) | 150 | How fast TD rates move from expected to actual TDs (n / (n + k)) | Initial commit; "k 50 / 400: no effect", no numbers | k {25, 50, 100, 150, 300, 600, xTD only}; fantasy MAE + P(1+ TD) Brier by position |
| 3 | high | Tuesday / week availability model settings (tuesday.py:190, 342) | 300 iters / 15 leaves / min leaf 40 / l2 1; 400 / 31 leaves | P(plays) on the site; who sits (triggers redistribution) | Never searched (gb_* audit covered practice / scratch only) | leaves {7, 15, 31, 63} x iters {200, 400} x min leaf {20, 40, 80}; Brier per stage, pick 2021-23, confirm 2024-25 |
| 4 | high | `injuries.redistribute_min_share` (config.toml:214) = `SIGNIFICANT` (injuries.py:29) | tgt 0.08, carry 0.15 | Smallest share of an absent player whose volume is handed out | "lower / higher within noise", no numbers | jointly with redistribution_scale; tgt {.04, .06, .08, .12} x carry {.08, .15, .25}; MAE on teammates of absent players |
| 5 | medium | `team_model.half_life_weeks` (config.toml:26) | 3.0 | Within-season recency in team ratings | line-288 row; "6 no help" on games, no numbers | {2, 3, 4, 6, 8}; margin + fantasy MAE |
| 6 | medium | `player_model.eff_season_weights` (config.toml:76) | [1, .6, .3] | This / last / two seasons back in player efficiency | "flat and steep within noise", no numbers | last {.3, .6, 1} x two back {0, .3, .6}; fantasy MAE by position |
| 7 | medium | `experiments.newcomer_scale` (config.toml:171) | 0.5 | Volume multiplier in a player's first game with a new team | "a round value set before the run"; only 0.5 vs off | {.3, .4, .5, .6, .7}; newcomers + teammates MAE, pick 2021-23, confirm 2024-25 |
| 8 | medium | Shrinkage-strength bounds (player_model.py:224, 521, 683) | clip [5, 2000], fallback 100 | Bounds on the fitted prior strength of every efficiency rate | Initial commit, never examined | count binding cells first; [1, 1e5] vs current on fantasy MAE |
| 9 | medium | `GL_RATIO_K` (player_model.py:90), ratio cap 4 (:642), team share clip .5 (:829) | 10, 4, 0.5 | Goal-line share shrinkage | gl_struct passed as a package with K = 10 only | K {3, 10, 30, 100}; RB P(1+ rush TD) Brier + RB MAE |
| 10 | medium | D/ST `WINDOW`, `K_COMMON`, `K_RARE` (defenses.py:17) | 16, 8, 30 | Defense stat-rate window and shrinkage | Package-only test vs season average | window {8, 16, 32} x K_COMMON {4, 8, 16} x K_RARE {15, 30, 60}; D/ST MAE |
| 11 | medium | Kicker `K_MIX`, `K_RATE`, `K_PAT` (kickers.py:18) | 30, 10, 20 | Kicker FG mix / make rate / PAT shrinkage | Package-only test | each x {.5, 1, 2, 4}; kicker MAE |
| 12 | medium | Durability shrink (tools/player_logs.py:708) | 17 games; fallback .95 | Shrinks availability before the Injuries tab percentile | "one season of games" | {4, 8, 17, 34, 68}; durability_eval.py Spearman, choose 2014-19, confirm 2020-25 |
| 13 | medium | Grade `SEASON_W` (tools/grade_build.py:32) | (1, .6, .3) | Season weights in the Edge grade | Copied from #6; never varied | as #6; next-season rank correlation |
| 14 | medium | Return models (returns.py:217, return_timing.py:31) | 200 / .05 / depth 3; 300 / .05 / depth 4 | P(back next game), IR horizon; lookahead weeks, Power C | Hand-set | depth {2, 3, 4, 5} x iters {150, 300, 500}; return Brier by horizon |
| 15 | low | `data.train_seasons` (config.toml:11) | 2 | Seasons of training data | "2 / 3 / 4 within noise", no numbers | {2, 3, 4}; fantasy MAE + availability Brier |
| 16 | low | `qb_inexp_dropbacks` / `qb_inexp_alpha` (config.toml:40, 51) | 150 / 1.0 | Inexperienced-QB cutoff and penalty | "within noise", no numbers | cutoff {75, 150, 300, 500} x penalty {.1, 1, 10}; pass CV loss + margin MAE |
| 17 | low | `starter_db_share` (config.toml:84) | 0.96 | Starting QB's minimum dropback share | One alternative (.97: +0.001) | {.92, .94, .96, .98, 1}; QB MAE |
| 18 | low | Share-normalization clamp (engine.py:148) | 0.6-1.6 | Limit on team-share rescaling | Never tested | count binds; {.8-1.25, .6-1.6, none} on MAE |
| 19 | low | Elo margin multiplier (elo.py:29) | 2.2, 0.001 | Margin-of-victory scaling in Elo | FiveThirtyEight's formula; only on / off tested | {1.5, 2.2, 3} x {.0005, .001, .002} in elo_eval.py |
| 20 | low | Tuesday "hurt, not listed" group (tuesday.py:154), clip (:371) | usual snaps >= 30%, drop >= 20 pts; .01-.99 | Who gets a Tuesday P(plays) | Pre-registered definition, never varied | {.2, .3, .4} x drop {.1, .2, .3}; Tuesday-group Brier |
| 21 | low | Confidence label (engine.py:441), low-data flag (:399) | cv .55 / .8; < 40 opportunities | Low confidence / boom-bust / low data labels | Never calibrated | cut at terciles of realized spread; check labels sort actual spread |
| 22 | low | ESPN early-week `PRIOR_WEIGHT` / `PRIOR_CAP` (espn_calib.py:47, 45) | 5 / 50 | Pseudo-counts for early-week ESPN status rates | Hand-set; archive from 2026-10-13 only | {2, 5, 10} x {25, 50, 100} at season end, or "unresolved" |

Queue order (2026-10-17): #3 availability settings (running, INSIGHTS (AA)) -> #4 redistribution trigger -> **(AB)
penalties in team ratings** -> range calibration -> the medium items.

**(AB) penalties in team ratings** (owner 2026-10-17: "are we accounting for a team's penalties in their rankings?").
Penalties on plays that stand are inside those plays' EPA, but plays a penalty wipes out (false starts, holding, DPI,
offsides: play_type no_play) are not rated: 2025, 2,240 of 2,583 (87%) left out; their net EPA per team-game has sd
0.80 (-1.54 to +1.37) against ~6 for offenses overall. Test: a fourth unit (penalty-nullified plays: offense and
defense ratings, its own fitted ridge penalty, so a hot streak shrinks), pen_net in the points model; gate on game
margin MAE walk-forward (tools/game_eval.py), fantasy MAE guard. Open question it answers: does flag-proneness persist?
Second variant (owner 2026-10-17: "plays negated by penalty ... do we ignore those plays completely too?"): yes, the
negated action (the called-back 40-yard catch, the sack erased by offsides) never reaches the ratings; its result
exists only in the play description (yards_gained is 0). (AB-b): also rate the negated play's would-be result, parsed
from desc ("for N yards", "sacked ... for -N"), as unit-strength evidence (a play that worked despite a flag still
shows the unit's skill; one caused by the foul, like an offsides sack, is noise). Both variants gated the same way,
so the test shows which signal matters, if either.

Done (2026-10-17, owner's question on distance vs goal-line TDs): **(AK) explosiveness in WR receiving TDs** FAIL on
MAE (INSIGHTS {#wr-td-explosive}); WR start / sit better, rechecked as its own test on full 2026.

Also queued (2026-10-17, owner: scoring by year / rule changes): **(AL) in-season calibration of the projection level**,
pre-registered in INSIGHTS; tools/env_eval.py.

Also queued (2026-10-17, found on Hockenson): **injured right before a bye.** A player hurt in the game before his bye is
on no injury report until the week after (nflverse lists nobody on a bye team), so the return chain never starts:
every later week reads 100%. ESPN's feed knows (status, return date). Test: seed the chain for bye-week teams from
ESPN's post-game status the way the current week's early-week bridge does (MODEL.md "Early-week injury news"), scored
on 2022-25 players hurt before a bye (ESPN captures archive). The site already avoids showing the 100% as a return
estimate (gamecast.js backWeek).

Also queued (2026-10-17, owner kept the single-number display; this is accuracy plumbing): **range calibration.**
The p10 / p90 ranges feed the Floor / Middle / Ceiling row, the confidence label and the Fantasy win chance. A look
at 2021-25 backtests: 10-90% ranges hold 73-75% of outcomes for top-tier RBs / QBs (should be 80%), and bottom tiers
are lopsided (0-3% below p10, ~10% above p90). Score with quantile (pinball) loss + coverage by tier; fix only if it
beats today ("range-widening multipliers" were rejected earlier, sec. 5). Display stays a single number.

Duplicates to remove when touched: `SIGNIFICANT` (injuries.py:29) repeats `redistribute_min_share`; a season-weight
map in player_model.py:574 (grade_prior experiment, off) repeats `eff_season_weights`.
