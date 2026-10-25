"""Games > Calc's model file (owner 2026-10-23; (CG) in docs/INSIGHTS.md): data/calc/model.json = the win probability
trees (nfledge/winprob.py, every completed regulation play 2006 on) + the decision inputs (nfledge/calc_inputs.py),
read by static/calc_engine.js. Cached by code and data (cache/calc_<key>.json): rebuilt when either changes.

  python tools/calc_build.py --site=site      (CI step "Calculator", after run.py)
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import calc_inputs as C  # noqa: E402
from nfledge import winprob as W  # noqa: E402
from nfledge.data import Cache  # noqa: E402

FIRST = 2006


def load(cur: int) -> pd.DataFrame:
  import nflreadpy as nfl
  cache = Cache(ROOT / "cache")
  fr = []
  for s in range(FIRST, cur + 1):
    # the current season refetches (new games); finished seasons are read once
    d = cache.get("pbp_calc", s, lambda s=s: nfl.load_pbp([s]).select(W.PBP_COLS), stale=(s == cur))
    if d is not None:
      fr.append(d)
  return pd.concat(fr, ignore_index=True)


def early_fg() -> pd.DataFrame:
  """Field goal attempts of the FG_LAG seasons before FIRST (the first seasons' make curves need them; (DH))."""
  import nflreadpy as nfl
  cache = Cache(ROOT / "cache")
  fr = []
  for s in range(FIRST - W.FG_LAG, FIRST):
    d = cache.get("fg_attempts", s, lambda s=s: nfl.load_pbp([s]).select(
      ["season", "field_goal_attempt", "kick_distance", "field_goal_result"]), stale=False)
    if d is not None:
      fr.append(W.fg_attempts(d))
  return pd.concat(fr, ignore_index=True) if fr else pd.DataFrame(columns=["season", "dist", "made"])


def make(done: pd.DataFrame, curve_season: int | None = None) -> dict:
  """The model file from completed games' play-by-play: win probability trees, decision inputs, conversion trees, the
  browser's self-check rows (and the export's own check against the fitted model). (DH, {#fg-input}) the win model
  reads each row's field goal make chance from the spot (its season's lagged curve); the file carries the curve of
  `curve_season`, the season it is used for (default: the one after its data, as walk-forward copies are)."""
  fg = pd.concat([early_fg(), W.fg_attempts(done)], ignore_index=True)
  r, _ = W.add_fgp(W.rows(done), fg)
  m = W.fit(r, fgp=True)
  cs = int(curve_season if curve_season is not None else done.season.max() + 1)
  out = {"v": 1, "built": pd.Timestamp.now().strftime("%Y-%m-%d"), "seasons": [FIRST, int(done.season.max())],
         "rows": int(len(r)), "wp": W.export(m, W.FEATURES_FGP), "wp_fg": {**W.fg_curve(fg, cs), "season": cs,
                                                                         "snap": W.FG_SNAP},
         "inputs": C.build(done)}
  cm = C.conversion_gb(done)
  out["conv"] = W.export(cm, C.CONV_FEATURES)
  g = C._gain_rows(done).sample(20, random_state=0)
  out["conv_check"] = [{"x": [float(v) for v in row], "p": float(p_)} for row, p_ in
                       zip(C.conv_features(g).to_numpy(float), cm.predict_proba(C.conv_features(g))[:, 1])]
  # the export evaluates as the model does (a sample of rows)
  smp = r.sample(min(2000, len(r)), random_state=0)
  diff = np.abs(W.predict_exported(out["wp"], W.features(smp, True)) - m.predict_proba(W.features(smp, True))[:, 1]).max()
  if diff > 1e-4:
    raise SystemExit(f"[calc] exported trees disagree with the model by {diff:.6f}")
  # a few rows for the browser engine's self-check (tools/calc_cli.mjs --check): features and the model's P
  chk = smp[smp.fgp.notna()].head(20)  # (DH) kickoffs carry no fgp (NaN), which JSON can't hold
  out["check"] = [{"x": [float(v) for v in row], "p": float(p)} for row, p in
                  zip(W.features(chk, True).to_numpy(float), m.predict_proba(W.features(chk, True))[:, 1])]
  print(f"[calc] trained on {len(r):,} plays ({out['seasons'][0]}-{out['seasons'][1]}); export check max diff {diff:.2e}", flush=True)
  return out


ROOF = {"outdoors": "outdoors", "open": "outdoors", "dome": "dome", "closed": "retractable"}
GRADED_FROM = 2022  # Model > Calc > Graded calls covers these seasons on (owner 2026-10-23: "2022 to now")


def fourth_rows(d: pd.DataFrame) -> pd.DataFrame:
  """Every regulation 4th down of finished regular-season games that was a go / field goal / punt (kneels, spikes and
  penalty no-plays out): the engine's state, the choice and what happened. Shared by the site's graded calls and the
  validation tools (tools/calc_validate.py)."""
  d = d[d.season_type == "REG"]
  ko = d[(d.kickoff_attempt == 1) & (d.qtr == 1) & d.posteam.notna()].sort_values(["game_id", "play_id"])
  first_rec = ko.drop_duplicates("game_id").set_index("game_id").posteam
  x = d[(d.down == 4) & (d.qtr <= 4) & d.play_type.isin(["run", "pass", "punt", "field_goal"]) & d.result.notna()
        & d.ydstogo.notna() & d.yardline_100.notna() & (d.qb_kneel != 1) & (d.qb_spike != 1)]
  home = x.posteam == x.home_team
  return pd.DataFrame({
    "game_id": x.game_id, "play_id": x.play_id.astype(float), "season": x.season.astype(int), "week": x.week.astype(int),
    "qtr": x.qtr, "desc": x.desc.str.slice(0, 140), "diff": x.score_differential.fillna(0), "sec": x.game_seconds_remaining,
    "togo": x.ydstogo, "yl": x.yardline_100, "to": x.posteam_timeouts_remaining.fillna(3),
    "oppTo": x.defteam_timeouts_remaining.fillna(3), "line": np.where(home, x.spread_line, -x.spread_line),
    "total": x.total_line.fillna(45), "home": home.astype(int), "rec2h": (x.game_id.map(first_rec) != x.posteam).astype(int),
    "roof": x.roof.map(ROOF).fillna("outdoors"), "wind": x.wind,
    "choice": x.play_type.map({"run": "go", "pass": "go", "punt": "punt", "field_goal": "fg"}),
    "result": np.where(home, x.result, -x.result), "won": np.where(home, x.result > 0, x.result < 0).astype(int),
    "team": x.posteam, "opp": x.defteam, "pts": x.posteam_score.fillna(0).astype(int), "opp_pts": x.defteam_score.fillna(0).astype(int),
    # (CO) which branch happened: a try converted (first down or the offense's touchdown), a field goal made
    "conv": ((x.fourth_down_converted == 1) | ((x.touchdown == 1) & (x.td_team == x.posteam))).astype(int),
    "fgm": (x.field_goal_result == "made").astype(int)})


def graded_inputs(d: pd.DataFrame, cur: int, code: bytes, dst: Path) -> None:
  """Model > Calc > Graded calls: each season's 4th downs (data/calc/plays_<season>.json) and the model each is graded
  with, fit only on the seasons before it (data/calc/wf/through_<year>.json; cached by code and year: past seasons'
  data doesn't change). tools/calc_grade.mjs grades them with the browser engine, in the full build and in the UI-only
  path (so an engine change regrades)."""
  (dst / "wf").mkdir(parents=True, exist_ok=True)
  done = d[d.result.notna()]
  seasons = []
  for s in range(GRADED_FROM, cur + 1):
    rows = fourth_rows(done[done.season == s])
    if rows.empty:
      continue
    yr = s - 1
    key = hashlib.sha1(code + f"through:{yr}".encode()).hexdigest()[:12]
    cp = ROOT / "cache" / f"calc_wf_{yr}_{key}.json"
    if not cp.exists():
      cp.write_text(json.dumps(make(done[done.season <= yr]), separators=(",", ":"), allow_nan=False), encoding="utf-8")
    (dst / "wf" / f"through_{yr}.json").write_bytes(cp.read_bytes())
    rows = rows.replace({np.nan: None})
    (dst / f"plays_{s}.json").write_text(json.dumps(rows.to_dict("records"), separators=(",", ":")), encoding="utf-8")
    seasons.append(s)
  print(f"[calc] graded-calls inputs: {seasons}", flush=True)


def resample_games(done: pd.DataFrame, seed: int) -> pd.DataFrame:
  """A bootstrap copy: games drawn with replacement (each draw keeps all its plays, under its own game id)."""
  rng = np.random.default_rng(seed)
  ids = done.game_id.unique()
  pick = rng.choice(ids, size=len(ids), replace=True)
  by = dict(tuple(done.groupby("game_id")))
  return pd.concat([by[g].assign(game_id=f"{g}#{k}") for k, g in enumerate(pick)], ignore_index=True)


def main():
  """--site=DIR: the live model file into DIR/data/calc/model.json (cached by code and completed weeks).
  --through=YEAR --out=FILE [--boot=SEED]: a validation copy fit only on seasons up to YEAR, optionally on games
  resampled with replacement (tools/calc_validate.py; (CJ) in docs/INSIGHTS.md)."""
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  if "through" in opt:
    yr = int(opt["through"])
    d = load(yr)
    done = d[d.result.notna() & (d.season <= yr)]
    if "boot" in opt:
      done = resample_games(done, int(opt["boot"]))
    out = make(done)
    Path(opt["out"]).parent.mkdir(parents=True, exist_ok=True)
    Path(opt["out"]).write_text(json.dumps(out, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    print(f"[calc] wrote {opt['out']}", flush=True)
    return
  site = ROOT / opt.get("site", "site")
  cur = json.loads((site / "index.json").read_text(encoding="utf-8"))["season"] if (site / "index.json").exists() else 2026
  d = load(int(cur))
  done = d[d.result.notna()]
  # this file too (2026-10-25: make() itself shapes the model; a change here alone reused a stale cached one)
  code = b"".join((ROOT / "nfledge" / f).read_bytes() for f in ("winprob.py", "calc_inputs.py")) + Path(__file__).read_bytes()
  # retrained when the code changes or a week is complete (not after every game of a Sunday)
  last = done[done.season == done.season.max()]
  wk_done = int(last.groupby("week").game_id.nunique().pipe(lambda g: g[g >= 13].index.max() if (g >= 13).any() else 0))
  key = hashlib.sha1(code + f"{int(done.season.max())}:{wk_done}".encode()).hexdigest()[:12]
  cp = ROOT / "cache" / f"calc_{key}.json"
  if cp.exists():
    out = json.loads(cp.read_text(encoding="utf-8"))
    print(f"[calc] cached model {key}", flush=True)
  else:
    out = make(done, curve_season=int(cur))  # (DH) the live season's make curve
    # (DH) NaN/Infinity is invalid JSON: fail here, not in the browser
    cp.write_text(json.dumps(out, separators=(",", ":"), allow_nan=False), encoding="utf-8")
  dst = site / "data" / "calc"
  dst.mkdir(parents=True, exist_ok=True)
  (dst / "model.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
  print(f"[calc] wrote data/calc/model.json ({(dst / 'model.json').stat().st_size / 1024:.0f} KB)", flush=True)
  graded_inputs(d, int(cur), code, dst)


if __name__ == "__main__":
  main()
