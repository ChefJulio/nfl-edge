"""Blend an uncertain QB into win chances (pre-registered 2026-10-16, docs/INSIGHTS.md (O)).

Usage: python tools/qb_blend_eval.py [--jobs=5]
Games 2021-25 where a team's usual starting QB is on the final injury report with P(plays) 5-95% (the one
availability model, walk-forward). Binary: rate the team with the starter if P >= 0.5 else the backup. Blend: P x win
chance with the starter + (1 - P) x with the backup. Win chance = Phi(model margin / sigma), sigma = the spread of the
game model's misses in the other seasons (cache from tools/game_eval.py --save, else 13.5). Scored by Brier on those
games; Vegas (the closing spread through the same normal) as a reference.
"""
import copy
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import norm  # noqa: E402

SEASONS = list(range(2021, 2026))


def qb_play_probs() -> dict:
  """(season, week, gsis) -> P(plays) at the final report for QBs on it (walk-forward one model; Out -> 0)."""
  from nfledge import data as D
  from nfledge import tuesday as T
  from nfledge.config import load_config
  cfg = load_config()
  d = D.load_all(cfg)
  rep, hurt = T.report_rows(d), T.hurt_notes(d, D.Cache(ROOT / cfg["data"]["cache_dir"]))
  w = T.week_rows(d, rep, hurt)
  out = {}
  for g, s, wk in zip(*[w[(w.stage == 3) & (w.gs_now == "Out") & (w.pos == "QB")][c] for c in ("gsis_id", "season", "week")]):
    out[(int(s), int(wk), g)] = 0.0
  wl = w.dropna(subset=["y"])
  wl = wl[~((wl.stage == 3) & (wl.gs_now == "Out"))]
  for s in SEASONS:
    te = wl[(wl.season == s) & (wl.stage == 3) & (wl.on_now == 1) & (wl.pos == "QB")]
    if len(te):
      p = T.week_predict(T.week_model(wl, s), te)
      out.update({(int(a), int(b), g): float(v) for a, b, g, v in zip(te.season, te.week, te.gsis_id, p)})
  return out


def season_games(args):
  season, probs, sigma = args
  for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(v, "2")
  from nfledge import data as D
  from nfledge.config import load_config
  from nfledge.team_model import GameModel, TeamModel, game_lines, team_game_ledger, team_volume_features
  cfg = load_config()
  data = D.load_all(copy.deepcopy(cfg))
  train = [s for s in data.seasons if s < season and s - 1 in data.seasons][-int(cfg["data"].get("train_seasons", 2)):]
  tm = TeamModel(data.pbp, cfg, data.qb_career)
  tm.tune_alphas([(s, w) for s in train for w in range(4, data.completed_weeks(s) + 1)])
  ledger = team_game_ledger(data.pbp, data.schedules)
  rows = GameModel(cfg).training_rows(tm, ledger, train)
  prior = [s for s in data.seasons if s < season and s - 1 in data.seasons]
  n_pts = int(cfg["team_model"].get("points_seasons", 6))
  extra = [GameModel(cfg).training_rows(tm, ledger, [s]) for s in prior[-n_pts:] if s not in train]
  gm = GameModel(cfg).fit(rows, pd.concat(extra + [rows]) if extra else None)
  sched = data.schedules
  sched = sched[(sched.season == season) & (sched.game_type == "REG") & sched.home_score.notna()]
  out = []
  for wk in sorted(sched.week.unique()):
    if wk < 2:
      continue
    games = sched[sched.week == wk]
    r = tm.fit(season, int(wk))
    vf = team_volume_features(ledger, season, int(wk), cfg)
    past = ledger[((ledger.season == season) & (ledger.week < wk)) | (ledger.season < season)]
    recent = past.dropna(subset=["qb"]).sort_values(["season", "week"]).groupby("team").qb.last().to_dict()
    cur = ledger[(ledger.season == season) & (ledger.week < wk) & ledger.qb.notna()].sort_values("week")
    usual = {}
    for t, g in cur.groupby("team"):
      seq = list(g.qb)
      cnt = pd.Series(seq).value_counts()
      usual[t] = min(cnt[cnt == cnt.max()].index, key=seq.index)
    dc = D.depth_for_week(data, season, int(wk))
    q2 = dc[(dc.pos == "QB") & (dc["rank"] == 2)]
    qb2 = {D.RELOCATED.get(t, t): g for t, g in zip(q2.team, q2.gsis_id)}

    def margin(game, starters):
      gl = game_lines(gm.predict(game, r, vf, use_vegas=False, starters=starters), game)
      return float(gl.model_margin.iloc[0])
    for g in games.itertuples():
      game = games[games.game_id == g.game_id]
      sides = {}
      for t in (g.home_team, g.away_team):
        t = D.RELOCATED.get(t, t)
        q = usual.get(t)
        p = probs.get((season, int(wk), q)) if q else None
        back = recent.get(t) if recent.get(t) not in (None, q) else qb2.get(t)
        sides[t] = (q, back, p)
      unsure = {t: v for t, v in sides.items() if v[2] is not None and 0.05 <= v[2] <= 0.95 and v[1]}
      if not unsure:
        continue
      base = {t: (v[0] if (v[2] is None or v[2] >= 0.5) else v[1]) or recent.get(t) for t, v in sides.items()}
      m_bin = margin(game, {**recent, **base})
      # every combination of the uncertain teams' QBs, weighted by their chances
      combos = [({}, 1.0)]
      for t, (q, back, p) in unsure.items():
        combos = [({**c, t: q}, w * p) for c, w in combos] + [({**c, t: back}, w * (1 - p)) for c, w in combos]
      p_blend = sum(w * norm.cdf(margin(game, {**recent, **base, **c}) / sigma[season]) for c, w in combos)
      out.append({"season": season, "week": int(wk), "game_id": g.game_id, "home_win": float(g.home_score > g.away_score) if g.home_score != g.away_score else 0.5,
                  "p_binary": float(norm.cdf(m_bin / sigma[season])), "p_blend": float(p_blend),
                  "p_vegas": float(norm.cdf(g.spread_line / sigma[season])) if pd.notna(g.spread_line) else np.nan,
                  "qb_p": ";".join(f"{t}:{v[2]:.2f}" for t, v in unsure.items())})
  print(f"[qb blend] {season}: {len(out)} games with an uncertain usual starter", flush=True)
  return pd.DataFrame(out)


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  gp = Path(r"C:\Users\hunte\AppData\Local\Temp\claude\C--Users-hunte\e847d357-6c86-407f-8c67-67c02542deb8\scratchpad\games.parquet")
  gp = Path(opt.get("games", gp))
  sigma = {s: 13.5 for s in SEASONS}
  if gp.exists():
    gg = pd.read_parquet(gp)
    gg = gg[gg.variant == "fitted"]
    sigma = {s: float((gg[gg.season != s].model_margin - gg[gg.season != s].actual_margin).std()) for s in SEASONS}
  print("sigma by season:", {k: round(v, 2) for k, v in sigma.items()}, flush=True)
  probs = qb_play_probs()
  print(f"QB play chances: {len(probs)}", flush=True)
  with ProcessPoolExecutor(int(opt.get("jobs", len(SEASONS)))) as ex:
    df = pd.concat(list(ex.map(season_games, [(s, probs, sigma) for s in SEASONS])), ignore_index=True)
  df.to_parquet(ROOT / "cache" / "qb_blend_eval.parquet", index=False)
  y = df.home_win
  bb, bl = (df.p_binary - y) ** 2, (df.p_blend - y) ** 2
  d_ = (bl - bb).to_numpy()
  boot = np.random.default_rng(0).choice(d_, (4000, len(d_))).mean(1)
  lo, hi = np.percentile(boot, [2.5, 97.5])
  print(f"\ngames with an uncertain usual starter: {len(df)}")
  print(f"win-chance Brier: binary {bb.mean():.4f} -> blend {bl.mean():.4f}  diff {d_.mean():+.4f} [{lo:+.4f}, {hi:+.4f}]  "
        f"{'PASS' if hi < 0 else 'FAIL'}")
  v = df.dropna(subset=["p_vegas"])
  print(f"(reference) Vegas on the same games: {((v.p_vegas - v.home_win) ** 2).mean():.4f} (n {len(v)})")
  for s, g in df.groupby("season"):
    print(f"  {s}: n {len(g):3d}  binary {((g.p_binary - g.home_win) ** 2).mean():.4f}  blend {((g.p_blend - g.home_win) ** 2).mean():.4f}")


if __name__ == "__main__":
  main()
