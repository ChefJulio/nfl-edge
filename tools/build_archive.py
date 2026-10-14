"""Archived week pages: every regular-season week from 2021 to the week before the current one, each exactly as
the model would have shown it before that week's games (walk-forward: every input from earlier weeks, learned
pieces trained on earlier seasons), with what actually happened alongside.

Usage: python tools/build_archive.py [SEASONS] [--out=site] [--missing-only] [--jobs=N]
  SEASONS         e.g. 2021-2026 (default: 2021 to the current season)
  --out=DIR       site folder; pages go to DIR/<season>/week-<NN>.html (default: site)
  --missing-only  skip pages that already exist (CI uses this: only the newly finished week is built), except
                  ones whose week has gained data since (DIR/archive.json records what each page was built from)
  --jobs=N        seasons in parallel (each process holds ~1.5 GB of data)

Also writes DIR/weeks.json, the season / week list every page's picker reads, so pages built earlier still list
weeks added later.
"""
import copy
import json
import os
import sys
import time
from pathlib import Path

_jobs = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--jobs=")), 1)
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
  os.environ.setdefault(_v, str(max(1, (os.cpu_count() or 4) // max(_jobs, 1))))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import run  # noqa: E402
from nfledge import report as rp  # noqa: E402
from nfledge.config import load_config, load_scoring  # noqa: E402
from nfledge.data import load_all  # noqa: E402
from nfledge.engine import POSITIONS, Engine  # noqa: E402

HISTORY = 8  # load from 2018 so 2021 still has two prior training seasons plus their prior seasons


def load(cfg):
  c = copy.deepcopy(cfg)
  c["data"]["history_seasons"] = max(int(c["data"]["history_seasons"]), HISTORY)
  return c, load_all(c)


def archive_weeks(data, current_week: int) -> dict:
  """season -> weeks to archive (every completed week before the current one)."""
  s = data.schedules
  reg = s[s.game_type == "REG"]
  out = {}
  for yr in range(run.FIRST_ARCHIVE_SEASON, data.current_season + 1):
    last = current_week - 1 if yr == data.current_season else int(reg[reg.season == yr].week.max())
    out[yr] = list(range(1, last + 1))
  return out


def coverage(data, season: int, week: int) -> list[int]:
  """How much of a week's game data a page was built from: games with plays, team stat lines, games with snaps.
  nflverse publishes a late game (Monday night) hours after the schedule marks it final, so a page built in
  between is missing it; a higher count later means the page is stale."""
  pbp = data.pbp[(data.pbp.season == season) & (data.pbp.week == week)]
  st = data.stats[(data.stats.season == season) & (data.stats.week == week)]
  sn = data.snaps[(data.snaps.season == season) & (data.snaps.week == week)]
  return [int(pbp.game_id.nunique()), int(st.team.nunique()), int(sn.game_id.nunique())]


def build_season(season: int, out_dir: str, missing_only: bool, built: dict) -> dict:
  """Builds the season's pages that are missing (or, without missing_only, all of them) plus any whose week has
  more data now than when it was built. Returns {"season/week": coverage} for every page that exists afterwards."""
  cfg, scoring = load_config(), load_scoring()
  cfg, data = load(cfg)
  current_week = run.display_week(data)
  weeks = archive_weeks(data, current_week).get(season, [])
  cov = {w: coverage(data, season, w) for w in weeks}
  todo = []
  for w in weeks:
    was = built.get(f"{season}/{w}")
    exists = (Path(out_dir) / str(season) / f"week-{w:02d}.html").exists()
    # A page with no record predates the manifest: take it as complete rather than rebuild every page once.
    if not (missing_only and exists) or (was is not None and any(n > o for n, o in zip(cov[w], was))):
      todo.append(w)
  done = {f"{season}/{w}": cov[w] for w in weeks}
  if not todo:
    return done
  t0 = time.time()
  eng = Engine(data, cfg, scoring, POSITIONS).train(season)
  for w in todo:
    proj = eng.project_week(season, w, use_injuries=True, quiet=True)  # realized game wind for past games
    ctx = run.build_page(eng, data, cfg, scoring, season, w, proj,
                         nav=run.week_nav(data, season, w, current_week, prefix="../"), archive=True)
    path = rp.render(ctx, Path(out_dir) / str(season) / f"week-{w:02d}.html")
    run.check_script(path)
    print(f"  {season} week {w}: {path.stat().st_size / 1e6:.1f} MB", flush=True)
  print(f"[archive] {season}: {len(todo)} weeks in {time.time() - t0:.0f}s", flush=True)
  done["_built"] = len(todo)
  return done


def main():
  args = [a for a in sys.argv[1:] if not a.startswith("--")]
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  out_dir = opt.get("out", str(ROOT / "site"))
  missing_only = "--missing-only" in sys.argv
  cfg, data = load(load_config())
  current_week = run.display_week(data)
  if args:
    a, _, b = args[0].partition("-")
    seasons = list(range(int(a), int(b or a) + 1))
  else:
    seasons = list(range(run.FIRST_ARCHIVE_SEASON, data.current_season + 1))
  write_weeks_json(data, current_week, out_dir)
  manifest_path = Path(out_dir) / "archive.json"
  built = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
  n_s = len(seasons)
  if _jobs > 1:
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(max_workers=_jobs) as ex:
      results = list(ex.map(build_season, seasons, [out_dir] * n_s, [missing_only] * n_s, [built] * n_s))
  else:
    results = [build_season(s, out_dir, missing_only, built) for s in seasons]
  n = sum(r.pop("_built", 0) for r in results)
  for r in results:
    built.update(r)
  lines = [f"{json.dumps(k)}: {json.dumps(v)}" for k, v in sorted(built.items())]
  manifest_path.write_text("{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8")
  print(f"[archive] built {n} pages into {out_dir}")


def write_weeks_json(data, current_week: int, out_dir: str):
  """Season / week list for the pickers, with paths relative to the site root."""
  nav = run.week_nav(data, data.current_season, current_week, current_week, prefix="")
  Path(out_dir).mkdir(parents=True, exist_ok=True)
  (Path(out_dir) / "weeks.json").write_text(json.dumps(nav["seasons"], separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
  main()
