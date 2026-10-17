# INSIGHTS.md testing-hygiene audit (power and multiple comparisons)

Source: docs/INSIGHTS.md as of 2026-10-16 (1,875 lines). Made for the thread 8 methods note (INSIGHTS sec. 9).

**How MDE is computed.** SE = (CI upper - CI lower) / 3.92 and MDE = 2.80 x SE, which works out to 0.714 x the CI width. That is the true effect a test of this precision detects 80% of the time (two-sided alpha .05).

**How "plausible effect" is chosen.** Where the notebook states an expected size, that size is used and cited. Where it doesn't ("none stated"), the benchmark is the notebook's own "practically negligible" margin for that metric:

| Metric | Benchmark used when none is stated | Where it comes from |
|---|---|---|
| Fantasy MAE | 0.003 | the +0.003 non-inferiority margin |
| Game margin MAE | 0.02 | the +0.02 margin |
| Availability Brier | 0.0005 | the (L) +0.0005 bar (job_security shipped at -0.0002) |
| Make-playoffs / division Brier | 0.001 | the (N) +0.001 bar |
| P(1+ TD) Brier | 0.0002 | gl_struct's shipped -0.000214 |
| Spearman | 0.005 | the (M) -0.005 bar |

**Labels:**
- **unresolved (underpowered)**: MDE > the plausible effect, i.e. the CI spans both 0 and a meaningful effect.
- **rejected (adequately powered)**: MDE <= the plausible effect, or the CI excludes a meaningful gain (including verdicts where harm was significant).
- **n/a**: no 95% CI is stated, or the test failed on a calibration or subgroup criterion rather than on its primary CI.

**Sign convention.** For MAE and Brier, negative = better. For accuracy, Spearman and rank correlation, positive = better.

## (a) All verdicts

### Section 3 / 4: shipped findings and game-model work

| Name | id | Seasons | Metric | Diff [95% CI] | Gate | Verdict | MDE | Relabel |
|---|---|---|---|---|---|---|---|---|
| Playoff-odds drift 0.9 | - | pick 2021-23, hold-out 2024-25 | make-playoffs Brier | 0.1344 -> 0.1273 (hold-out); 2021-23 0.1480 -> 0.1455; no CI | best on 2021-23 grid AND beats no drift on 2024-25 (point estimate) | SHIPPED | - | n/a |
| Training window 2 seasons | - | n/s | - | no numbers | - | fixed | - | n/a |
| Points formula 6 prior seasons | - | n/s (backtest) | game margin MAE | 10.71 -> 10.68, never worse per season; no CI | none stated | SHIPPED | - | n/a |
| Fixed ST weights 0-2.5 | - | n/s | margin | "within noise of the fit"; no CI | - | fit kept | - | n/a |
| Vegas implied total (ablation) | - | 2021-25 | fantasy MAE | +0.036 without; no CI | - | KEPT | - | n/a |
| ECR blend RB/WR/TE | - | 2021-25 | fantasy MAE | +0.013 without; no CI | - | KEPT (hurts QB) | - | n/a |
| Usage half-life 3 | - | 2021-25 | fantasy MAE | -0.004 vs 5; no CI | - | SHIPPED | - | n/a |
| Team-share normalization | - | 2021-25 | fantasy MAE | -0.017 (RB -0.043); no CI | - | SHIPPED | - | n/a |
| Wind penalty grid | - | 2021-25 | fantasy MAE | -0.011 vs old; no CI | grid | SHIPPED | - | n/a |
| No range widening | - | 2021-25 | coverage | 78.3/49.5% -> 80.0/50.2% | - | SHIPPED | - | n/a |
| Availability GB / healthy-scratch GB | - | n/s | Brier | .1026 vs .1081; .0532 vs .0678; no CI | - | SHIPPED | - | n/a |
| Return-timing model | - | 2021-25 | Brier | .132 vs .137 vs .178, 4/5 seasons; no CI | - | SHIPPED | - | n/a |
| Isotonic calibration of return model | - | LOSO | Brier | .132 -> .136; no CI | - | rejected | - | n/a |
| Least-squares recalibration of extremes | - | n/s | fantasy MAE | "hurt MAE"; no number | - | rejected | - | n/a |
| Depth by playing time | - | 2025-26 | accuracy | 87.7% vs 76.4%; no CI | - | adopted | - | n/a |
| Model-Vegas margin blend | - | 2021-25 | margin MAE | best w=0; no CI | - | rejected | - | n/a |
| Residual corrections (flat recal / mistake memory) | - | 2022-26 | margin MAE | 10.40 vs 10.37; -0.03; no CI | - | rejected | - | n/a |
| Win-prob blend model+Vegas | - | 2022-26 | Brier | 0.2115, w=0-0.15; no CI | - | rejected | - | n/a |
| Rank gap vs net gap | - | 2022-26 | Brier | 0.2291 vs 0.2316, "CI excludes 0" (CI not written) | - | not adopted, later superseded | - | n/a |
| Darts: Elo on top of rank | - | 2022-26 | Brier | -0.0065 [-0.0110, -0.0024], 5/5 | none pre-set | helps | - | - |
| Darts: referee x team | - | 2022-26 | Brier | +0.0043, "noise"; no CI | - | rejected | - | n/a |
| Darts: ~25 other signals | - | 2022-26 | Brier | "nothing"; no CI | - | rejected | - | n/a |
| Elo win chance | - | 2022-26 | Brier | -0.0125 [-0.0174, -0.0077] vs model margin; -0.0064 [-0.0108, -0.0023] vs rank+home | none pre-set | SHIPPED | - | - |
| Referees vs market | - | 2017-26 | shuffle p | p=0.09 / 0.99, r=-0.05 / 0.00 | - | no effect | - | n/a |
| Opponent defense terms "drop" | - | 2021-2026 | fantasy MAE | -0.002 [-0.004, -0.000]; QB -0.008 [-0.016, -0.000]; 6/6 | MAE "not worse (CI includes 0 or favors it)" + TD Brier | ADOPTED | - | - |
| Drop implied total instead | - | 2021-2026 | fantasy MAE | +0.029 [+0.020, +0.038] | same | rejected | 0.013 | rejected (harm significant) |

### Section 5: "Tested and rejected" table

| Name | id | Seasons | Metric | Diff [95% CI] | Gate | Verdict | MDE | Relabel |
|---|---|---|---|---|---|---|---|---|
| Team-specific HFA | - | 2005-25 | persistence corr | -0.02; no CI | - | rejected | - | n/a |
| Recency by games played | - | 2021-25 | fantasy MAE | within +-0.001, "CIs straddle 0" (not written) | - | null, calendar KEPT | - | n/a (CI not stated) |
| Travel / tz HFA | - | n/s | - | "No effect" | - | rejected | - | n/a |
| Division HFA | - | n/s | play CV | worse CV | - | off | - | n/a |
| Shared stadium | - | - | - | 7 games | - | rejected | - | n/a |
| Air-yards share / aDOT | - | n/s | fantasy MAE | +0.004; no CI | - | rejected | - | n/a |
| Snap share input | - | n/s | fantasy MAE | "No gain" | - | rejected | - | n/a |
| Route share input | {#route-input} | 2021-25 | fantasy MAE | ALL -0.002 [-0.007, +0.003]; TE -0.021 [-0.036, -0.007] post hoc | ALL CI upper < 0, no position CI lower > 0 | FAIL | 0.0071 | unresolved (underpowered); none stated, MDE > 0.003 |
| TD blend k 50/400 | - | n/s | - | "No effect" | - | rejected | - | n/a |
| PFR defender values | - | n/s | OOS | "worse OOS" | - | rejected | - | n/a |
| Defensive / OL / CB absences | - | n/s | - | "No reliable signal" | - | rejected | - | n/a |
| Pace / drive sustainability | - | n/s | plays MAE | "No gain" | - | rejected | - | n/a |
| Fitted wind term | - | n/s | TE MAE | +0.012; no CI | - | rejected | - | n/a |
| Per-position share half-life; spread-aware shares; finer draft tiers | - | n/s | fantasy MAE | "No difference"; no CI | - | rejected | - | n/a |
| Final linear calibration | - | n/s | fantasy MAE | +0.013; no CI | - | rejected | - | n/a |
| Starter QB share 0.97 | - | n/s | fantasy MAE | +0.001; no CI | - | rejected | - | n/a |
| Range-widening multipliers | - | n/s | calibration | worse | - | rejected | - | n/a |
| Game-margin handicaps | - | 2022-26 | ATS / MAE | "No ATS gain" | - | rejected | - | n/a |
| Coach 4th-down aggressiveness | - | 2021-26 ("all 6 seasons") | fantasy MAE / TD Brier | MAE "identical"; raw offensive TDs +0.08 [-0.03, +0.18] ns | - | rejected ("real but too small") | 0.15 (TDs/game, descriptive) | n/a for the MAE (no CI); notebook's own size estimate +0.03 TDs/game < 0.15, so the TD leg is unresolved (underpowered) |
| QB-specific target shares | - | n/s | share error (pts) | k=10 +0.7 [+0.5, +0.9]; k=200 +0.1 ns | - | rejected | 0.29 | rejected (harm significant) |
| RZ target role x team RZ volume | - | n/s | fantasy MAE / TE TD Brier | MAE "no difference"; TE -0.0001 [-0.0003, +0.00005]; WR -0.00003 | - | rejected | 0.00025 | unresolved (underpowered, marginal); none stated, MDE > 0.0002 |
| Passing-down back x trailing | - | n/s | target share | +0.06 pts, CI "~[-0.2, +0.2]" | - | rejected | ~0.29 | unresolved; none stated, CI approximate |
| RB workload / short rest | - | n/s | share per touch per day | +0.03 [-0.02, +0.08] | - | rejected | 0.071 | n/a (descriptive, no benchmark) |
| Age x cumulative touches | - | n/s | yds/touch per yr per 100 touches | +0.015 [-0.016, +0.043] | - | rejected | 0.042 | n/a (descriptive) |
| Garbage-time share | - | n/s | next-week error | +0.002 [-0.06, +0.07] | - | rejected | 0.093 | n/a (descriptive) |
| Revenge games | - | n/s | pts vs proj | -0.04 [-0.76, +0.64] | - | rejected | 1.00 | unresolved (MDE 1 pt; none stated) |
| Primetime | - | n/s | pts vs proj | -0.19 [-0.53, +0.16] | - | rejected | 0.49 | unresolved (none stated) |
| Primetime persistence | - | n/s | corr | +.04 [-.06, +.15] | - | rejected | 0.15 | n/a |
| Division familiarity: rematch ATS | - | 2006-25 | pts vs spread | -0.11 [-0.93, +0.70] | - | rejected | 1.16 | unresolved (none stated) |
| Division unders since 2020 | - | 2020-25 | pts vs total | -0.09 [-1.41, +1.20] | - | "market corrected" | 1.86 | **unresolved (underpowered)**: the pre-2020 effect was 1.5-1.8 pts, which is below the 1.86 MDE |
| Age input (linear) | - | 2021-26 ("2026 worse") | fantasy MAE | ALL -0.000 [-0.004, +0.003]; RB -0.004 [-0.008, +0.001]; QB +0.010 [-0.001, +0.022] | overall MAE better | rejected | ALL 0.0050; RB 0.0064 | unresolved (underpowered); none stated at MAE level |
| Age RB/WR linear+quadratic | - | 2021-26 | fantasy MAE | RB -0.004 [-0.009, +0.001] | same | rejected | 0.0071 | unresolved (underpowered) |
| 2-pt conversions | - | 2022-25 | descriptive | no star premium | - | parked | - | n/a |
| Insensitive knobs | - | 2021-25 | fantasy MAE | "within noise" | - | kept | - | n/a |

### Section 7: owner model ideas (2026-10-13)

| Name | id | Seasons | Metric | Diff [95% CI] | Gate | Verdict | MDE | Relabel |
|---|---|---|---|---|---|---|---|---|
| Elite-unit weighting top-8 x2 | - | 2021-25 | next-week EPA/play MSE x1000 | +0.556 [+0.19, +0.94] | none pre-set | rejected | 0.54 | rejected (harm significant) |
| Elite top-3 1.25x (and the other mild arms) | - | 2021-25 | same | +0.035 [-0.07, +0.15] | - | rejected | 0.157 | n/a (no benchmark; 0.19% of the 80.995 baseline) |
| RB committee (rbbc) | - | 5 seasons, likely 2021-25 [Inferred] | RB MAE | -0.001 [-0.003, +0.001] | - | rejected | 0.0029 | rejected (adequately powered, borderline: MDE ~ 0.003) |
| Goal-line tilt (gl_share) | - | same | RB MAE | -0.002 [-0.005, +0.001] | - | rejected | 0.0043 | unresolved (underpowered) |
| rbbc + gl_share | - | same | RB MAE | -0.003 [-0.006, +0.000] | - | rejected | 0.0043 | unresolved (point estimate = 0.003 benchmark) |
| gl_share on P(1+ rush TD) | - | same | RB TD Brier | -0.0003 [-0.0007, +0.0001] | metrics fixed beforehand | no difference | 0.00057 | unresolved (underpowered vs 0.0002) |
| gl_struct | - | 5 seasons (4/5) | RB TD Brier | -0.000214 [-0.000434, -0.000004]; RB MAE -0.0004 [-0.0018, +0.0009] | pre-set gate | ADOPTED | - | - (small ship) |
| qb_rush_split | - | n/s | QB rush-TD Brier / QB MAE | -0.0002 [-0.0006, +0.0002]; +0.0013 [-0.0032, +0.0056] | set in advance | OFF | 0.00057; 0.0063 | unresolved (underpowered) on both |

### Section 9: open threads

| Name | id | Seasons | Metric | Diff [95% CI] | Gate | Verdict | MDE | Relabel |
|---|---|---|---|---|---|---|---|---|
| Newcomer discount (v1 discarded as a bug) | - | 2021-25 | fantasy MAE | ALL -0.002 [-0.004, 0.000]; WR -0.006 [-0.011, -0.002]; target rows -0.009 [-0.011, -0.007]; 4/5 | (i) target CI excl 0, (ii) ALL CI upper < +0.003, (iii) no position worse | PASS, SHIPPED | - | - |
| Journeyman | - | fit 2021-23, test 2024-25 | fantasy MAE | k>=1 -0.108 [-0.125, -0.090]; all -0.039 [-0.045, -0.033]; QB -0.011 [-0.059, +0.040] | same 3-part | PASS, SHIPPED | - | - |
| QB rushing on leg injury | - | 2021-25 | rush yds | -2.5 +- 10.5 (n 14) | - | no adjustment | ~7.5 (if +-10.5 is a 95% half-width) | unresolved (stated as "too few cases") |
| redist_conserve | - | 2021-25 | fantasy MAE | ALL +0.001 [-0.001, +0.003]; affected +0.035 [+0.020, +0.049] | (i) affected CI excl 0, (ii) +0.003 | FAIL | affected 0.021 | rejected (harm significant) |
| Redistribution | - | 2021-25 | MAE by boost size | 3.94/3.90, 4.95/4.82, 12 rows 1.5+; no CI | owner delegated | KEPT | - | n/a |
| Kicker projections | - | 2021-25 | K MAE | -0.293 [-0.389, -0.204], 5/5 | CI excl 0 + >=3/5 | PASS, SHIPPED | - | - |
| D/ST projections | - | 2021-25 | D/ST MAE | -0.337 [-0.417, -0.258], 5/5 | CI excl 0 + >=3/5 | PASS, SHIPPED | - | - |
| Removal: WP filter | - | 2021-25 | fantasy MAE / margin MAE | -0.001 [-0.002, +0.001] / -0.090 [-0.158, -0.019], 4/5 | REMOVE if CI upper < +0.003 and no position worse | REMOVED | fantasy 0.0021 | - (removal; passes NI) |
| Removal: QB effects | - | 2021-25 | fantasy / margin | +0.000 [-0.001, +0.002] / +0.011 [-0.075, +0.096] | same | KEPT | games 0.122 | unresolved on games (MDE 0.122 >> 0.02) |
| Removal: prior-season carryover | - | 2021-25 | fantasy MAE | +0.000 [-0.006, +0.008] | same | KEPT (fails 0.003 bound) | 0.0100 | unresolved: CI width 0.014 makes the +0.003 bound unreachable |
| Removal: redistribution | - | 2021-25 | fantasy MAE | overall +0.000 [-0.001, +0.001]; changed rows +0.031 [+0.019, +0.042] | same | owner call; later KEPT | 0.0014 | adequately powered overall |
| Return-game adjustment | - | 2021-26 | residual | +0.14 +- 0.59 | - | none | - | n/a |
| Return timing v2 | - | 2023-25 | Brier | +0.014 [+0.009, +0.020], 0/3 | CI excl 0, >=2/3, calibration bounds | FAIL | - | rejected (harm significant) |
| Return timing v3 | - | 2023-25 | Brier | -0.005 [-0.010, -0.000], 2/3 | same | FAIL (calibration ii) | - | n/a (failed calibration, not power) |
| Hybrid on 2021-22 | - | 2021-22 | IR-row Brier | 0.1727 -> 0.1578 [-0.028, -0.002] (diff not written) | CI excl 0, both seasons, calibration | PASS, SHIPPED | - | - |
| IR minimum rule on chain alone | - | 2023-25 | Brier | +0.0071 [+0.004, +0.011] | - | FAIL | - | rejected (harm significant) |
| IR minimum as a hard rule | - | 2023-25 | Brier | **no result recorded** | ships unless CI excludes a 0.005 loss | (gate written, outcome not recorded) | - | n/a |
| Returned player = healthy | - | 2022-25 | play rates | descriptive; no CI | owner design + data check | SHIPPED | - | n/a |
| Midweek ESPN Out v1 | - | 2022-24 | Brier | 0.863 -> 0.028, 3/3 | CI excl 0, >=2/3, n>=100 | formal PASS, judged INVALID | - | n/a |
| Midweek ESPN Out v2 | - | 2022-24 | Brier | -0.254 [-0.297, -0.209], 3/3 | same + calibration within 10 | PASS, SHIPPED (not blind) | - | - |
| ESPN Doubtful midweek | - | 2022-24 | play rate | n 67 < 100 | n>=100 rule | inconclusive; SHIPPED by owner, ungated | - | unresolved (by its own n rule) |
| ESPN Questionable on report | - | 2022-24 | play rate | 63.2% vs 58.3% | - | CLOSED, no rule | - | n/a |
| Lookahead (A) | - | 2022-25 | Brier k=2..6 | -0.034 [-0.039, -0.029], 4/4 | CI excl 0, >=3/4 | PASS, SHIP | - | - |
| Lookahead (B) | - | 2022-25 | Brier | 0.215 -> 0.150, 4/4; CI not written | same | PASS on paper, NOT SHIPPED | - | - |
| B' | - | 2022-25 | Brier | 0.460 -> 0.226 [-0.256, -0.211], 4/4 | + fairness + calibration within 5 | FAIL (iii by 1.1 pts) | - | n/a (calibration) |
| Unified lookahead v1 | - | 2022-25 | Brier | 0.2395 -> 0.1526 [-0.095, -0.080], 4/4 | CI, >=3/4, calibration | PASS, NOT SHIPPED | - | - |
| Unified lookahead v2 | - | 2022-25 | Brier | [-0.098, -0.082], 4/4 | + cells within 5 | FAIL (iv) | - | n/a (calibration) |
| Unified lookahead v3 | - | 2023-25 | Brier | [-0.096, -0.077], 3/3 | >=2/3 + cells | FAIL, STOPPED | - | n/a (calibration) |
| Partial-week practice models | - | 2021-25 | Brier | -0.044 [-0.046, -0.042], 5/5 | CI excl 0, >=4/5, calibration within 3 | PASS, SHIPPED | - | - |
| Charting A/B (croe / yacoe / cpoe / oe_all) | {#charting-ab} | 2021-2026 | fantasy MAE | abs d <= 0.001, "every CI spans 0" (not written) | ALL CI upper < 0 etc. | null, off | - | n/a (CI not stated) |
| RB via NGS RYOE (guardrail) | {#rb-ryoe} | 2019-2025 | next-season rank corr | RB +0.021 [-0.092, +0.129]; WR -0.033 [-0.087, +0.026]; TE -0.036 [-0.115, +0.056] | not significantly below | passed, superseded | 0.158 / 0.081 / 0.122 | n/a (non-inferiority; the bar was weak) |
| pbp injury notes in depth | {#depth-pbp-notes} | 2019-2026 | depth accuracy | note50 -0.0001 [-0.0002, -0.0000]; note80 -0.0001 [-0.0005, +0.0002] | CI above 0 | rejected | note80 0.0005 | note50 rejected (harm); note80 rejected (adequately powered); none stated |
| healthy3 | {#depth-healthy3} | 2019-2026 | depth accuracy | +0.0003 [-0.0006, +0.0012] vs "both" | owner rule: ship unless significantly worse | SHIPPED | 0.0013 | - |
| Depth window "both" | {#depth-window} | 2019-2026 | depth accuracy | +2.0 [+1.8, +2.1] | CI above 0 | ADOPTED | - | - |
| Edge grade v1.2 | {#edge-grade-v1-2} | 2021-2025 | next-season fpts/g rank corr | -0.013 [-0.028, +0.005] | CI not entirely below 0 | PASSED guardrail, LIVE | 0.024 | - (non-inferiority, weak) |
| Edge grade v1.1 | {#edge-grade-v1-1} | 2021-2025 | same | -0.026 [-0.045, -0.007] | same | FAILED | - | rejected (harm significant) |
| Edge grade v2 | {#edge-grade-v2} | 2021-2025 (movers n=486) | rank corr | +0.014 [-0.082, +0.115]; fpts/g -0.013 [-0.120, +0.085] | CI above 0 | FAILED | 0.141 | unresolved (underpowered): the MDE exceeds the ~.13 total predictability the notebook reports |
| Learned Edge grade | - | 2021-2025 | rank corr vs last value | ALL +0.030 [-0.002, +0.066] | CI excl 0 | FAILED | 0.049 | unresolved (point estimate 0.030 < MDE) |
| Snap pfr->gsis map fix | - | 2021-25 | fantasy MAE | -0.003, **90% CI** [-0.005, -0.001] | n/s | ADOPTED | - | - (small ship) |
| "Not extended" rookie-deal year | - | n/s | pts vs proj | -0.60 [-1.21, -0.03] | - | suspect, retest 2026 | - | possible chance pass (flagged by the notebook) |
| Sleeper blend (original) | {#sleeper-blend} | fit 2021-23, test 2024-26 | fantasy MAE | -0.020 [-0.039, -0.002] | CI upper < 0, no position worse | PASS, then INVALID (leak) | - | n/a |
| Sleeper blend leak-free | {#sleeper-blend} | 2024-26 | fantasy MAE | -0.011 [-0.029, +0.007]; zero-skip -0.014 [-0.032, +0.004] | same | FAIL; forward test pending | 0.026 | unresolved (underpowered) |
| debut_prior v1 | {#debut-prior-v1} | wk 1-2 2021-26 | debut-row MAE | +0.096 [-0.229, +0.411] | (i) CI excl 0 | FAIL | 0.457 | rejected (adequately powered): plausible ~1 pt (rookie bias +1.27 RB / +1.64 WR; v2 later found -1.023) |
| debut_prior v2 on weeks 3+ | - | 2021-25 | debut rows | +0.40 [-0.84, +1.63] (5 rows) | same | "NO POWER", amended | 1.76 | unresolved (underpowered; the notebook says so) |
| debut_prior v2 "d12" | {#debut-prior-v2} | wk 1-2 2016-20 | debut-row MAE | -1.023 [-1.699, -0.318]; all -0.070 [-0.102, -0.038] | (i)-(ii) | PASS, SHIPPED | - | - |
| Blowout filter 2-98 | {#blowout-filters} | 2021-25 | margin MAE | +0.025 [-0.022, +0.076], worse every season | beat none, CI excl 0 | FAIL | 0.070 | unresolved by rule (borderline: CI just admits a 0.02 gain), though worse in 5/5 |
| Blowout filter 5-95 | {#blowout-filters} | 2021-25 | margin MAE | +0.082 [+0.023, +0.143] | same | FAIL | - | rejected (harm significant) |
| practice_role (all positions) | {#practice-role-all} | 2021-25 | avail Brier | -0.0037 [-0.0047, -0.0027]; QB +0.0033 [+0.0008, +0.0059] | CI excl 0 + MAE +0.003 | written PASS, not shipped | - | - |
| practice_role RB/WR/TE | {#practice-role-skill} | 2021-25 | avail Brier | -0.0056 [-0.0068, -0.0044]; MAE -0.000 [-0.002, +0.001] | + QB CI lower <= 0 | PASS, SHIPPED | - | - |
| scratch_carry v1 | {#scratch-carry-v1} | wk 1-2 2021-26 + wk 3+ 2021-25 | wk 3+ fantasy MAE | +0.003 [-0.000, +0.006]; QB +0.020 [+0.003, +0.043]; wk 1-2 -0.0017 [-0.0069, +0.0043] | (iii) CI upper < +0.003 | FAIL | 0.0043; 0.0080 | rejected (QB harm significant) |
| scratch_carry v2 | {#scratch-carry-v2} | wk 1-2 2021-26 | Brier / MAE | -0.0074 [-0.0118, -0.0031] / +0.0012 [-0.0050, +0.0091] | (ii) MAE CI upper < +0.003 | FAIL | MAE 0.0101 | unresolved: a CI 0.0141 wide can't meet a +0.003 bound |
| QB2 plays when QB1 sits | - | fit 2021-23, test 2024-25 | Brier | -0.0326 [-0.0562, -0.0093] | CI excl 0 | SHIPPED | - | - |
| job_security (A) | {#job-security} | 2021-25 | avail Brier (non-report) | -0.0002 [-0.00045, -0.00001]; MAE -0.000 [-0.001, +0.001] | CI excl 0 + MAE +0.003 | PASS, SHIPPED | - | - (small ship) |
| share_quality (B) | {#share-quality} | 2021-25 | fantasy MAE | +0.002 [0.000, +0.003] | ALL CI upper < 0 | FAIL | 0.0021 | rejected (adequately powered; a gain is excluded) |
| practice_rest (C) | {#practice-rest} | 2021-25 | avail Brier | -0.0001 [-0.0005, +0.0004] | CI excl 0 | FAIL | 0.00064 | unresolved (marginal vs 0.0005; none stated) |
| practice_rest_age (C) | {#practice-rest} | 2021-25 | avail Brier | +0.0005 [-0.0002, +0.0013]; RB MAE significantly worse | same | FAIL | 0.00107 | rejected (RB harm significant); primary unresolved |
| Tuesday model (G) | {#tuesday-model} | 2021-25 | Brier | -0.0135 [-0.0160, -0.0110], 5/5 | CI excl 0, >=4/5, deciles within 4 | PASS | - | - |
| Tuesday G2 | {#tuesday-hurt-unlisted} | 2021-25 | Brier | -0.0501 [-0.0553, -0.0448], 5/5 | same | PASS, SHIP | - | - |
| One model (I) | {#one-model-v1} | 2021-25 | Brier by stage | final -0.010 [-0.012, -0.008]; Tuesday +0.0018 [+0.0012, +0.0025] | stage gates + deciles | FAIL (calibration, Tuesday) | - | n/a (calibration/harm) |
| One model (I2) | {#one-model-v2} | 2021-25 + 2026 wk 1-6 | Brier | final -0.0104 [-0.0124, -0.0084], 5/5 | (I) gate + 2026 direction | PASS | - | - |
| grade_prior (D) | {#edge-grade-prior} | 2021-25 | fantasy MAE | +0.003 [+0.000, +0.007]; worse 3/5 | ALL CI upper < 0 | FAIL | 0.0050 | rejected (adequately powered; a gain is excluded) |
| I2 step 2 fantasy MAE | {#one-model-mae} | 2021-25 | fantasy MAE | +0.001 [-0.004, +0.004] | CI upper < +0.003 | FAIL by letter, SHIPPED (owner-design rule) | 0.0057 | unresolved: a CI 0.008 wide can't meet a +0.003 bound |
| Team habits (J) | {#team-habits} | 2021-25 + 2026 | avail Brier final | -0.0003 [-0.0010, +0.0004]; QB +0.0074 [+0.0034, +0.0113] | CI excl 0, no position worse | FAIL | 0.0010 | rejected (QB harm); primary unresolved (MDE > 0.0005) |
| Three inputs (K) | {#blind-spots-k} | 2021-25 + 2026 | avail Brier final | -0.0004 [-0.0012, +0.0004]; calendar alone -0.0007 [-0.0014, -0.0001] | same | FAIL | 0.0011 | unresolved (underpowered; none stated) |
| Stakes in one model (L1) | {#stakes-injured} | 2021-25 | Brier wk 15-18 | -0.0020 [-0.0047, +0.0003], 4/5; wk 1-14 Wed +0.0005 [-0.0005, +0.0016] | CI excl 0; wk 1-14 CI upper < +0.0005 | FAIL (narrowly) | 0.0036; NI leg 0.0015 | **unresolved (underpowered)**: point -0.0020 < MDE; the NI leg can't be met at that width |
| Stakes in healthy-scratch (L2) | {#stakes-healthy} | 2021-25 | Brier wk 15-18 | -0.00001 [-0.00042, +0.00037] | same | FAIL | 0.00056 | unresolved: the plausible effect is the "~2 points" week-18 gap, worth far less than 0.0005 Brier |
| Power rank C (M) | {#power-rank-c} | 2021-25 | Spearman | +0.0102 [+0.0016, +0.0193]; all weeks +0.0083 [+0.0002, +0.0163] | CI excl 0; overall CI lower > -0.005 | PASS, SHIPPED | - | - (small ship, near the CI edge) |
| Weekly injury-aware odds (N) | {#odds-weekly-c} | 2021-25 | make-playoffs Brier | +0.00007 [-0.00022, +0.00038]; C const +0.00005 [-0.00024, +0.00035] | CI excl 0; div/bye CI upper < +0.001 | FAIL | 0.00043 | rejected (adequately powered); none stated, MDE < the 0.001 bar |
| QB blend win chance (O) | {#qb-blend-winchance} | 2021-25 (204 games) | win Brier | -0.0000 [-0.0026, +0.0025] | CI over games excl 0 | FAIL | 0.0036 | **unresolved (underpowered)**: the blend "moves the chance a point or two" [Inferred: worth about 0.0004 Brier or less] |
| Skill-position absences (P) | {#skill-absence-margin} | 2022-25 | margin MAE (311 games) | +0.034 [-0.179, +0.250]; rerun +0.019 [-0.198, +0.239]; all +0.015 [-0.053, +0.084] / +0.006 [-0.061, +0.075] | CI excl 0; all CI upper < +0.02 | FAIL | 0.306 / 0.312; all 0.098 / 0.097 | **unresolved (underpowered)**: see note P |
| Harness fix (game_eval starter) | {#game-eval-starter} | 2021-25 | margin MAE | 10.547 -> 10.428; no CI | bug fix | fixed | - | n/a |
| Matchups rank N vs C (Q) | {#win-rank-this-week} | 2022-26 | win Brier | C-N +0.0011 [-0.0007, +0.0030]; N-A -0.0017 [-0.0033, -0.0001] | switch to N unless C beats N | N SHIPPED | C-N 0.0026 | - (default-wins gate) |
| New-to-team QB (R) | {#qb-newteam} | 2021-25 | margin MAE | flagged -0.077 [-0.232, +0.072]; all -0.023 [-0.061, +0.013]; fantasy +0.001 [0.000, +0.001] | CI excl 0; all +0.02; fantasy +0.005 | FAIL | 0.217; all 0.053 | **unresolved (underpowered)**: see note R |
| Kickoff-rule / FG in ST | - | 2017-26 | descriptive | FG effect ~0.1 pt | - | not tested (power) | - | unresolved (notebook says so) |
| Change events vs excess miss | - | 2021-25 | excess miss | QB change +0.47 [-0.13, +1.12] | - | parked | 0.89 | unresolved (descriptive) |
| Breakout recency (thread 4) | - | 2021-26 | MAE vs ECR | +0.010 [-0.083, +0.101] | - | "no recency test warranted" | 0.13 | n/a (descriptive) |
| QB-only wind strength (thread 5) | - | 2021-26 | - | not run, "far below what... can show" | - | not tested (power) | - | unresolved (notebook says so) |
| Carryover in team ratings | - | 2022/23/25 | margin MAE | -0.13 [-0.24, -0.01] early weeks variant | - | PARKED | - | n/a (exploratory) |

**Notes on the headline cases (their CIs and MDEs are in the table above):**
- **P (`{#skill-absence-margin}`).** The notebook states the plausible effect on the margin: "a team missing a 25%-target WR is about 2 points worse", called "a 1-2 point nudge". [Inferred] Taking the miss sd as about 1.25 x MAE (~13.7), correcting a bias of d points cuts MAE by about d^2 / (13.7 x 2.51): roughly 0.12 for d = 2 and 0.03 for d = 1. The MDE is therefore 3-10x the plausible gain. This test could never have passed even if the idea were right.
- **R (`{#qb-newteam}`).** The effect behind the idea is new arrivals overrated by +6.07 on 65 games, plus a smaller one for experienced backups, all inside 281 flagged games. [Inferred, rough] At best that is worth about 0.2 MAE on the flagged set, which is about the MDE of 0.217. The point estimate is in the helpful direction.
- **N (`{#odds-weekly-c}`) is the one headline FAIL that is adequately powered.** The CI excludes any gain larger than 0.00022 Brier.
- **O (`{#qb-blend-winchance}`).** 204 games give an MDE of 0.0036 Brier. Shifting a probability by 1-2 points can gain at most about 0.0001-0.0004, so the test could not see the effect.

## (b) Count of verdicts on the 2021-25 window (item 3)

There are **50 significance-style verdicts** (primary gate = 95% CI excluding 0 in the helpful direction) decided on seasons within 2021-2025. Subsets such as 2021-22, 2021-23 with 2024-25, 2022-24, 2022-25 and 2023-25 count. J, K and I2 also used a 2026 direction check. The section 7 tests (rbbc, gl_share, gl_struct, qb_rush_split) are assumed to be 2021-25 [Inferred].

**21 passed** (as registered):
- newcomer, journeyman, kicker, D/ST, hybrid (2021-22), midweek v1 (later invalidated), midweek v2
- lookahead A, lookahead B (not shipped), unified v1 (not shipped), partial-week
- practice_role all (not shipped), practice_role RB/WR/TE, QB2 rule, job_security
- Tuesday G, G2, I2, M (Power C), gl_struct, snap-map fix (90% CI)

**29 failed:**
- redist_conserve, return v2, return v3, IR-min chain, B', unified v2, unified v3
- route_input, blowout 2-98, blowout 5-95, share_quality, practice_rest, practice_rest_age
- I, D grade_prior, J, K, L1, L2, N, O, P, R
- qb_rush_split, gl_share, rbbc, elite weighting, learned Edge grade, Edge v2

Five of the fails (return v3, B', unified v2, unified v3, I) passed their primary CI and failed on calibration, so 26 of 50 primary CIs excluded 0 in the helpful direction.

**Expected chance passes = 0.025 x 50 = 1.25.** snap-map used a 90% CI, which gives a 5% one-sided false-pass rate instead of 2.5%.

Most passes are far from the boundary: kicker, D/ST, Tuesday, partial-week and lookahead all clear 0 by many SEs. Four passes sit at the CI edge:
- gl_struct: upper -0.000004
- job_security: upper -0.00001
- M: lower +0.0016 (all weeks +0.0002)
- hybrid: upper -0.002 on a 0.026-wide CI

With about 1.25 false passes expected, roughly one of these four could be chance. The "not extended rookie deal" finding (-0.60 [-1.21, -0.03]) is a descriptive near-edge result the notebook already flags as suspect.

**Why the effective number of comparisons is larger than 50:**
- **Several attempts at the same question:** return v2 / v3 / hybrid, unified v1 / v2 / v3, practice_role v1 / v2, midweek v1 / v2, debut v1 / v2 (gate moved to 2016-20), scratch v1 / v2, I / I2, two blowout windows, two practice_rest variants.
- **Extra significance legs per test:** most gates add "no position significantly worse" (about 4 more tests each) and subgroup reports.
- **Many descriptive scans** in sections 5 and 9 with 95% CIs (folklore, job security, return games, blind spots). K itself notes "scanning many groups finds the biggest misses, which shrink back".

**7 "not worse" (non-inferiority) verdicts on 2021-25.** These are not significance tests, so the 2.5% rate doesn't apply. A wide CI makes them fail by default (KEEP), or they ship under the owner-design rule.
- WP-filter removal: REMOVED
- QB effects: KEPT
- prior carryover: KEPT (CI width 0.014, so the bound was unreachable)
- redistribution removal: owner call, then KEPT
- I2 MAE step: FAIL by letter, shipped
- Edge v1.1: FAIL
- Edge v1.2: PASS

The secondary NI legs inside the sig tests (CI upper < +0.003 / +0.02 / +0.005) are also not significance tests.

**About 15 more verdicts on 2021-25 have no stated CI** and cannot be scored: sections 3 and 5 entries such as half-life 3, share normalization, wind grid, return-model ship, isotonic, recency-by-games, charting (2021-26), points formula and lookahead B's CI. They are listed in (a) as n/a.

**Excluded from the window:** tests that include 2026 or pre-2021 data in the deciding seasons. These are def_terms (2021-26), age_input, coach aggressiveness, charting, Sleeper (2024-26), Elo / darts / Q (2022-26), depth tests (2019-26), debut v1 (2021-26) and v2 (2016-20), scratch_carry v1 / v2 (weeks 1-2 2021-26), RB RYOE (2019-25), and drift (point estimates only).

## (c) Small ships to re-confirm on 2026 at season end (item 4)

| Ship | Effect as written | Why recheck |
|---|---|---|
| Newcomer discount | ALL -0.002 [-0.004, 0.000] (targeted rows -0.009) | overall effect at CI edge |
| Opponent defense terms "drop" | -0.002 [-0.004, -0.000] | tiny; gate was "not worse" with no margin |
| Snap pfr->gsis map fix | -0.003, 90% CI [-0.005, -0.001] | 90% CI, not 95% (a bug fix, low risk) |
| Usage half-life 3 | -0.004 vs 5, no CI | no CI ever stated |
| gl_struct | RB TD Brier -0.000214 [-0.000434, -0.000004]; MAE -0.0004 [-0.0018, +0.0009] | CI touches 0 |
| job_security | avail Brier -0.0002 [-0.00045, -0.00001]; MAE -0.000 | CI touches 0 |
| Power rank C (M) | Spearman +0.0102 [+0.0016, +0.0193]; all weeks +0.0083 [+0.0002, +0.0163]; 2025 -0.005 | near edge; the odds also read C |
| Matchups rank N (Q) | N-A -0.0017 [-0.0033, -0.0001]; C-N +0.0011 ns | default-wins gate, CI at edge |
| I2 one availability model, fantasy leg | MAE +0.001 [-0.004, +0.004] (missed the +0.003 bar) | shipped under the owner rule; WR +0.002 [+0.000, +0.004] |
| healthy3 depth | +0.0003 [-0.0006, +0.0012] vs "both" | owner rule (ship unless worse) |
| Edge grade v1.2 (live) | -0.013 [-0.028, +0.005] | guardrail only |
| WP-filter removal (fantasy side) | -0.001 [-0.002, +0.001] (games -0.090 [-0.158, -0.019]) | fantasy effect nil; recheck the game effect |
| Points formula 6 seasons | margin MAE 10.71 -> 10.68, no CI | no CI |
| ESPN midweek Doubtful 2.8% | ungated (n 67 < 100) | owner-direction ship; the notebook already plans a live recheck |
| Hybrid return timing | Brier CI upper -0.002 | already pre-registered for the fresh-2026 check (week 14+) |

## (d) Gate conventions in use (item 5)

**1. Non-inferiority margins on fantasy MAE**
- +0.003: newcomer, journeyman, redist_conserve, the removal tests, debut_prior (ii)-(iii), practice_role, scratch_carry, job_security, practice_rest (C), practice_reason (E), (F), (H), (I) step 2, blowout follow-up.
- +0.005: (R) fantasy guard only.
- 0 (no margin, "CI includes 0 or favors it"): def_terms.
- "Overall MAE better" (point estimate): age_input.

**2. Non-inferiority margins on other metrics**
- Game margin MAE +0.02: (P), (R) all games.
- Availability Brier +0.002: (I) stages 0-2; (J) and (K) Wednesday / Thursday.
- Availability Brier +0.0005: (L) weeks 1-14.
- Division / bye Brier +0.001: (N).
- IR Brier, "CI excluding a 0.005 loss": IR minimum as a hard rule.
- Spearman, CI lower > -0.005: (M).
- Edge guardrail, "CI not entirely below 0" (zero margin, weak): v1.1, v1.2, RB RYOE.
- TD Brier "no difference" with no margin given: def_terms, coach_aggr.

**3. Superiority gates**
- "CI excludes 0" (most tests).
- "CI upper < 0", the same rule stated for share inputs: charting, route_input, share_quality, grade_prior, Sleeper.
- Default-wins gates: Q (switch unless C beats N); owner-design "ship unless significantly worse" (healthy3, I2 MAE, IR hard rule).

**4. Seasons-better rules**
- >= 3 of 5: kicker, D/ST.
- >= 4 of 5: partial-week, Tuesday (G).
- >= 4 of 6: charting position-specific.
- >= 2 of 3: return v2 / v3, midweek ESPN, unified v3.
- >= 3 of 4: lookahead A / B / B', unified v1 / v2.
- "Both seasons": hybrid 2021-22.
- No seasons rule, though seasons are reported: newcomer (4/5), journeyman, practice_role, job_security, J / K / L, M, N, O, P, R, the removal tests.
- "Better in all 6 seasons" reported informally: def_terms.

**5. CI resampling unit**
- Season-weeks: fantasy experiments.py tests, availability tests, M, N, L, blowout margin test (paired by game but CI over season-weeks), Q.
- Games: (O), (P), (R).
- Team-weeks: debut weeks 1-2, scratch_carry, QB2 rule, early-week ECR.
- Team-games: depth window.
- Player-week resamples (2,000): midweek ESPN, partial-week.
- Player-episodes: lookahead A / B. Episodes: return v2 / v3 / hybrid.
- Player-seasons: unified lookahead.
- Unspecified bootstrap over players: Edge grade tests.
- 90% CI: snap-map fix, tossup line.

As a result, margin-MAE tests use season-week CIs in one place (blowout, Q) and game CIs in another (P, R).

**6. Holdout scheme**
- Full 2021-25 walk-forward: most tests.
- Fit 2021-23, test 2024-25: drift, journeyman, QB2, Sleeper (2024-26).
- Untouched older seasons: hybrid 2021-22, debut d12 2016-20.
- Decide 2025, confirm 2026: thread 6.
- Forward 2026 only: hybrid fresh check, non-contact jersey, Sleeper forward test, early-week ECR.
- Some decisions mix in 2026 partial weeks: def_terms, charting, age_input, Q, Elo.

**7. Calibration bounds stacked on Brier gates**
- 3 points: unified lookahead by k / groups, partial-week.
- 4 points: deciles in (G), (I), (J), (K), (L).
- 5 points: return v2 / v3 / hybrid cells, B', unified (iv) cells and the Hurts group.
- 10 points: midweek ESPN v2.

Several fails come from these bounds, not the primary CI: return v3, B', unified v2 / v3, (I).

**8. Sample-size floors**
- n >= 100: midweek ESPN.
- n >= 150 per cell: return v2.
- n >= 300 per cell: unified v2.
- 40-row trigger: jersey.
- Others have no floor (for example O at 204 games, P at 311 games).
