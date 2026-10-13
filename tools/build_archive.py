"""Archived week pages: every regular-season week from 2021 to the week before the current one, each exactly as
the model would have shown it before that week's games (walk-forward: every input from earlier weeks, learned
pieces trained on earlier seasons), with what actually happened alongside.

Usage: python tools/build_archive.py [SEASONS] [--out=site] [--missing-only] [--jobs=N]
  SEASONS         e.g. 2021-2026 (default: 2021 to the current season)
  --out=DIR       site folder; pages go to DIR/<season>/week-<NN>.html (default: site)
  --missing-only  skip pages that already exist (CI uses this: only the newly finished week is built)
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


def build_season(season: int, out_dir: str, missing_only: bool) -> int:
  cfg, scoring = load_config(), load_scoring()
  cfg, data = load(cfg)
  current_week = run.display_week(data)
  weeks = archive_weeks(data, current_week).get(season, [])
  todo = [w for w in weeks if not (missing_only and (Path(out_dir) / str(season) / f"week-{w:02d}.html").exists())]
  if not todo:
    return 0
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
  return len(todo)


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
  if _jobs > 1:
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(max_workers=_jobs) as ex:
      n = sum(ex.map(build_season, seasons, [out_dir] * len(seasons), [missing_only] * len(seasons)))
  else:
    n = sum(build_season(s, out_dir, missing_only) for s in seasons)
  print(f"[archive] built {n} pages into {out_dir}")


def write_weeks_json(data, current_week: int, out_dir: str):
  """Season / week list for the pickers, with paths relative to the site root."""
  nav = run.week_nav(data, data.current_season, current_week, current_week, prefix="")
  Path(out_dir).mkdir(parents=True, exist_ok=True)
  (Path(out_dir) / "weeks.json").write_text(json.dumps(nav["seasons"], separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
  main()
