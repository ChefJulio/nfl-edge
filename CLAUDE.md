# nfl-edge: guide for agents

Weekly opponent-adjusted NFL analytics (fantasy QB/RB/WR/TE projections + team ratings) built in Python, rendered
to one static HTML page, deployed to GitHub Pages: https://chefjulio.github.io/nfl-edge/ (repo ChefJulio/nfl-edge).

**Read `docs/INSIGHTS.md` before changing the model or the page.** It records every data quirk, every backtest
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
```
Python 3.12 venv in `.venv`. Set `PYTHONIOENCODING=utf-8` when printing polars/pandas frames on Windows.
CI: `.github/workflows/deploy.yml` builds on every push to main and daily (14:00 UTC), caching `cache/`.
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
| `nfledge/backtest.py` | Walk-forward evaluation vs raw stats, Vegas-scaled, ECR |
| `nfledge/report.py` | Builds every page section (presentation only) |
| `nfledge/docs.py` | Model tab: renders MODEL.md, live values, generated formulas section, code fingerprint |
| `nfledge/templates/report.html.j2` | The whole page: CSS, tabs, tables, sorting JS |
| `exclusions.csv` | Manual injury-shortened games to drop from usage/efficiency |
| `scratch/` | Throwaway experiment scripts (gitignored) |

## Rules of the road
1. **Walk-forward only.** Anything learned from history trains on seasons strictly before the season it projects
   or tests. Decide on 2025, confirm on 2026 (`tools/experiments.py`). Report results honestly, including losses.
2. **Data-driven, free data only.** The owner wants claims tested and nothing paid. Rejected ideas stay off.
3. **Model vs presentation.** Model code = everything in `nfledge/` except `report.py` and `docs.py`. Changing
   model code or `config.toml` invalidates caches (full retrain ~3-6 min) and makes MODEL.md stale: update the
   doc, run `--stamp`. Presentation-only changes reuse the cached model (~10-30 s builds).
4. **Verify the page visually** before claiming a UI change works (headless Chrome screenshots; see INSIGHTS).
   `run.py` fails the build if the page script has a JS syntax error (needs `node` on PATH).
5. **Commits:** plain ASCII messages, no emojis. Push to main deploys.
6. **Code style:** 2-space indent Python, ~120 char lines, match surrounding idiom.
