# nfl-edge: guide for agents

Weekly opponent-adjusted NFL analytics (fantasy QB/RB/WR/TE projections + team ratings) built in Python, rendered
to one static HTML page, deployed to GitHub Pages: https://chefjulio.github.io/nfl-edge/ (repo ChefJulio/nfl-edge).

**Read `docs/INSIGHTS.md` before changing the model or the page** (section 9 = current open threads and pending
owner decisions). It records every data quirk, every backtest
result (including ideas that were tested and rejected, with numbers), and the owner's preferences. Do not re-try
a rejected idea without new data or a new angle, and do not "fix" a deliberate choice listed there.

`MODEL.md` is the public model description rendered into the site's Model tab (with live values). Keep it true.

## Commands
```
.venv\Scripts\python run.py                 # full build -> report/nfl_edge_week{N}.html (auto-detects week)
.venv\Scripts\python run.py --no-backtest   # skip the backtest (faster when only checking the page)
.venv\Scripts\python run.py --week 7        # project a specific week using only data before it
.venv\Scripts\python tools/experiments.py baseline,<variant> 2025   # walk-forward A/B of config variants
.venv\Scripts\python tools/model_doc.py --check | --stamp           # MODEL.md staleness check / re-stamp
.venv\Scripts\python run.py --lookahead --out site/index.html      # + the rest of the season's weeks
.venv\Scripts\python tools/experiments.py A,B 2021-2025 --history=8 --jobs=6   # 5-season A/B with CIs (cached)
.venv\Scripts\python tools/game_eval.py 2021-2025                 # game-model (margin/total) walk-forward
.venv\Scripts\python tools/error_breakdown.py "cache/experiments/baseline_20*.parquet"  # where error comes from
.venv\Scripts\python tools/returns_eval.py 2021-2025              # injury return-timing model walk-forward
.venv\Scripts\python tools/build_archive.py --out=site --missing-only   # archived week pages
.venv\Scripts\python tools/screenshot.py teams/power [--device=desktop] [--url=URL] [--el=CSS]  # visual QA (WebKit iPhone)
.venv\Scripts\python tools/dev.py --site=scratch/site [--port=8765]   # DEV LOOP: serves a built folder with assets/
#   read live from nfledge/static/ (no cache): JS/CSS edits show on browser refresh, no re-render. Build the folder
#   once with `run.py --out scratch/site/index.html`; re-run only for Python / model changes (pages are static
#   shells; every tab renders in the browser from the week JSON). screenshot.py opens the dev server by default;
#   other pages: --url=http://127.0.0.1:8765/game.html?d=index.json&g=<game_id> [--wait=4000] [--click=CSS]; ?sim=1 fakes live
.venv\Scripts\python tools/win_prob.py                            # Vegas win-prob calibration; prints tossup_below
.venv\Scripts\python tools/darts.py                               # 28 pre-game signals vs rank / Vegas (cached base)
.venv\Scripts\python tools/elo_eval.py                            # fits Elo + our win-chance blend; prints [report.win_model]
.venv\Scripts\python tools/carryover_eval.py --quick              # prior-season carryover vs game outcomes (parked)
.venv\Scripts\python tools/referees.py                            # referee effects vs spread / totals (none found)
.venv\Scripts\python tools/vegas_compare.py                       # model vs Vegas: picks, blends, ATS by edge
.venv\Scripts\python tools/residual_fix.py                        # walk-forward game-margin handicap tests
```
Python 3.12 venv in `.venv`. Set `PYTHONIOENCODING=utf-8` when printing polars/pandas frames on Windows.
CI: `.github/workflows/deploy.yml` builds on every push to main and daily (14:00 UTC), caching `cache/`.
Site layout: `index.html` = current week (stays on the week being played until Tue 06:00 ET); `<season>/week-NN.html`
= archived weeks (built once, stored on the `archive` branch, which CI checks out into `site/` and appends to) and
lookahead weeks (rebuilt every run, not committed); `weeks.json` feeds the pickers; `data/espn_injuries/` is the
daily ESPN injury archive (evidence for a future return-model test, not used yet).
Git hooks: `git config core.hooksPath .githooks` (pre-commit blocks commits when MODEL.md is stale).

## Layout
| Path | What |
|---|---|
| `run.py` | Orchestration, model/backtest caching (`cache/model_*.pkl`, `cache/backtest_*.parquet`), render, JS syntax check |
| `config.toml` / `scoring.toml` | Every model knob and toggle (documented inline) / scoring (default half PPR) |
| `nfledge/data.py` | Loading + caching (nflreadpy, NFL.com practice API, ECR, teams, QB career), pbp prep, depth charts, wind forecasts |
| `nfledge/team_model.py` | Ridge EPA ratings (pass/rush/ST, QB effects), CV tuning, bootstrap, team ledger, volume + points models |
| `nfledge/player_model.py` | Player ledger, xTD, EB priors, as-of features, share + efficiency regressions, projection |
| `nfledge/injuries.py` | Availability (practice-sequence GB model, healthy-scratch GB model), redistribution, QB handoff |
| `nfledge/engine.py` | Train/project/blend: ECR blend, quantile ranges, uncertainty, candidates (rosters) |
| `nfledge/personnel.py` | Defensive personnel adjustment: tested, OFF (kept switchable) |
| `nfledge/returns.py` | Injury return-timing model (feeds lookahead weeks) |
| `nfledge/backtest.py` | Walk-forward evaluation vs raw stats, Vegas-scaled, ECR |
| `nfledge/report.py` | Builds each week's numbers (presentation only): `week_data` = the week JSON every tab renders from (`"v": 3`), `render` = page shell + JSON + site files |
| `nfledge/docs.py` | Model tab text: MODEL.md with live values (`{{ L.name }}`, strict regex fill) -> HTML in `data/model.json`; generated formulas section; code fingerprint |
| `nfledge/pages/{week,game}.html` | Page shells (plain HTML, `%TOKENS%` filled by `report.page_html`; no Jinja): every week page is the same shell + its `<page>.json` |
| `nfledge/static/site.css` | Site-wide styles (tokens, header, tables, rankings, badges, model doc) |
| `nfledge/static/gamecast.{js,css}` | Player / team pages, live scores (ESPN), gamecast page, loads the week JSON (`NFLE.weekData`); every `static/` file is copied to the site's `assets/` on every render |
| `nfledge/static/shell.{js,css}` | App shell: 4 parents (Players, Teams, Games, Model) + sub-tab chips, bottom tab bar on phones, hash routing (#players/rankings; old #games etc. mapped), `NFLE.load` (cached JSON), `NFLE.week()` (the week data), `NFLE.fmt` (shared cell helpers), the week page header (picker from `weeks.json`, details popover), area loader (`AREAS`) |
| `nfledge/static/table.{js,css}` | `NFLE.Table`: the shared table component for client-rendered tabs (sort, pinned column, sticky header, header strip on phones) |
| `tools/dev.py` | Dev server: built site + live `nfledge/static/` assets |
| `nfledge/standings.py` | Standings + NFL tiebreaking procedures (division, wild card, seeds); presentation-side (not in the model fingerprint) |
| `tools/standings_build.py`, `nfledge/static/standings.{js,css}` | Teams > Standings: `data/standings/<season>.json` (2002 on, CI step) rendered in the browser; area modules load on first open (shell.js AREAS) |
| `tools/stats_build.py`, `nfledge/static/{teamstats,playerstats}.{js,css}` | Teams > Stats + Players > Stats: `data/stats/{teams,players}_<season>.json` (1999 on, CI step; aggregates cached in `cache/seasonstats_*`) |
| `tools/draft_build.py`, `nfledge/static/draft.{js,css}` | Teams > Draft: `data/draft/<year>.json` (1980 on, PFR via nflverse; CI step) |
| `tools/playoffs_build.py`, `nfledge/static/playoffs.{js,css}`, `data/history/` | Teams > Playoffs: brackets 1920 on (`data/playoffs/<season>.json`) + team page Playoffs tab (`data/playoffs/teams.json`: per-franchise history, records by round, titles, rate since 1970; 538 file + Wikipedia seeds kept in `data/history/`) |
| `tools/playoff_odds.py` | Teams > Playoffs odds: `data/playoffs/odds.json` (Monte Carlo + tiebreakers; CI step). `--backtest` rewrites the COMMITTED track record `data/history/playoff_odds_backtest.json` (needs the archive worktree); `--fit-drift` = the pre-registered drift fit |
| `tools/player_logs.py` | Player pages for EVERY player (`data/players/<gsis>.json`, ~16k): QB/RB/WR/TE since 1999 in the fantasy format; everyone else (`other_logs`: defense, line, K, P, LS; 1999 stats / 2002 rosters / 2012 snaps) with a `kind` + stat keys, drawn without fantasy parts; team logs (`data/teams/`) |
| `tools/depth_build.py` | Team page > Depth: `data/depth/<season>/<TEAM>.json` (2001 on, every week, with that week's official tags; from 2012 also "u" = depth by playing time, the tab's default after a team's first game; tested in tools/depth_accuracy.py) + `index.json`; finished seasons built once into `cache/depth_site/`; CI step after Player game logs; drawn by gamecast.js (season / week pickers; current week uses ESPN's live injury list) |
| `tools/trends_build.py` | Players > Trends: `data/plays/<season>.json` (every run / pass play since 1999 + per-game roof, surface, weather, line, coaches) + `<season>_x.json` (NGS participation 2016-2025, FTN charting 2022+; loaded only when a query uses it) + `index.json` (`cov`: per season, columns charted on >= 90% of the plays they apply to; `tracked`). Column keys and sentinels in its docstring. Finished seasons cached in `cache/plays_site/v<V>`; CI step "Trends". Queried in the browser by `static/trends.js`: every filter / metric / group-by declares the columns it needs and a query only counts covered seasons (saying which it dropped). Player / coach search; `?t=` share link read once then stripped |
| `tools/grade_build.py` | NFL Edge grade (owner 2026-10-14): `data/grades/<season>.json` (2018 on) + `index.json`. PER PLAY (dropbacks + designed carries + targets) value over replacement (replacement = backups' per-play EPA; receivers credited only with their part of a target: depth worth + catches over expected + YAC EPA over expected, the throw is the QB's; fumbles count), shrunk toward the position mean by method-of-moments k. Graded only if the NFL's qualifying minimum was met that season (per team game: 14 att / 6.25 carries / 1.875 catches; QUALIFY), percentile among the qualified. [0] current form = this + 2 prior seasons (1/.6/.3); [6] that season only (history). `--eval`, `--eval2`, `--eval11` = research tests (see INSIGHTS). CI step "Edge grades". Shown by gamecast.js (EDGE chip + Grade tab) |
| `tools/transactions_build.py`, `nfledge/static/moves.{js,css}` | Players > Moves: ESPN transactions parsed into moves, `data/transactions/<season>.json` (2002 on; CI step, raw pages cached) |
| `nfledge/static/{rankings,injuries,roles,power,matchups,model}.js` | Week tabs from the week JSON: Rankings, Injuries (ESPN list + our inactive %), Roles, Power, Matchups (tiles; live paint via `NFLE.paintTiles`), Model (`data/model.json`) |
| `nfledge/elo.py` | Elo from final scores (part of our win chance) |
| `exclusions.csv` | Manual injury-shortened games to drop from usage/efficiency |
| `scratch/` | Throwaway experiment scripts (gitignored) |

## Rules of the road
1. **Walk-forward only.** Anything learned from history trains on seasons strictly before the season it projects
   or tests. Decide on 2025, confirm on 2026 (`tools/experiments.py`). Report results honestly, including losses.
2. **Data-driven, free data only.** The owner wants claims tested and nothing paid. Rejected ideas stay off.
3. **Model vs presentation.** Model code = everything in `nfledge/` except `report.py` and `docs.py`. Changing
   model code or `config.toml` invalidates caches (full retrain ~3-6 min) and makes MODEL.md stale: update the
   doc, run `--stamp`. Presentation-only changes reuse the cached model (~10-30 s builds).
4. **Verify the page visually** before claiming a UI change works: `python tools/screenshot.py TAB` renders in
   WebKit with an iPhone profile (the owner tests on Brave/iPhone, which is WebKit; headless Chrome misses WebKit
   bugs), `--device=desktop` for Chromium. Options for position tab and page/table scrolling are in the script.
   `run.py` fails the build if the page script has a JS syntax error (needs `node` on PATH).
5. **Commits:** plain ASCII messages, no emojis. Push to main deploys.
6. **Code style:** 2-space indent Python, ~120 char lines, match surrounding idiom.
