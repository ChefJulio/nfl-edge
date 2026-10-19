"""(BB) Is the quarterback swing too small? (pre-registered 2026-10-19, docs/INSIGHTS.md (BB)).

Usage:
  python tools/game_eval.py 2021-2025 --only=fitted --jobs=5 --save=cache/bb_base.parquet
  python tools/game_eval.py 2021-2025 --only=fitted --jobs=5 --save=cache/bb_a100.parquet --set="team_model.qb_alpha_grid=[100]"
  python tools/game_eval.py 2021-2025 --only=fitted --jobs=5 --save=cache/bb_a30.parquet --set="team_model.qb_alpha_grid=[30]"
  python tools/game_eval.py 2021-2025 --only=fitted --jobs=5 --save=cache/bb_qbrun.parquet --set="team_model.qb_rush_effects=true"
  python tools/qb_swing_eval.py                 (scores every cache/bb_*.parquet against bb_base)

QB-change team-games: the game's starter (most dropbacks, the ledger's qb) is not the team's usual starter (most
starts this season before that week, ties to the earlier starter), or he is the usual starter back after missing his
team's previous game. Kinds: backup in (experienced: 150+ career dropbacks, 150+ for this team), new arrival (150+
career, under 150 for this team), inexperienced (under 150 career), starter back. A game is a QB-change game when
either team's row is.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

CUT = 150


def boot_ci(e: np.ndarray, keys: np.ndarray, n: int = 4000) -> tuple[float, float, float]:
  u = np.unique(keys)
  idx = [np.flatnonzero(keys == x) for x in u]
  rng = np.random.default_rng(0)
  bs = [e[np.concatenate([idx[i] for i in rng.integers(0, len(u), len(u))])].mean() for _ in range(n)]
  return float(e.mean()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def team_games() -> pd.DataFrame:
  """One row per team-game 2019+: season, week, game_id, team, starter, usual, kind."""
  from nfledge import data as D
  from nfledge.config import load_config
  from nfledge.team_model import qb_experience, qb_team_experience, team_game_ledger
  cfg = load_config()
  d = D.load_all(cfg)
  led = team_game_ledger(d.pbp, d.schedules).reset_index()
  led = led[led.qb.notna()].sort_values(["season", "week"])
  exp = qb_experience(d.pbp, d.qb_career).set_index(["qb", "season", "week"]).prior
  tex = qb_team_experience(d.pbp).set_index(["qb", "team", "season", "week"]).prior
  rows = []
  for (s, t), g in led.groupby(["season", "team"]):
    seq = []
    for x in g.itertuples():
      usual = None
      if seq:
        cnt = pd.Series(seq).value_counts()
        usual = min(cnt[cnt == cnt.max()].index, key=seq.index)
      back = bool(seq) and x.qb == usual and seq[-1] != usual
      kind = "same"
      if usual is not None and x.qb != usual:
        car = float(exp.get((x.qb, s, x.week), 0.0))
        own = float(tex.get((x.qb, t, s, x.week), 0.0))
        kind = "inexperienced" if car < CUT else "new arrival" if own < CUT else "backup in"
      elif back:
        kind = "starter back"
      rows.append({"season": s, "week": int(x.week), "game_id": x.game_id, "team": t, "starter": x.qb, "usual": usual,
                   "kind": kind if usual is not None else "no usual"})
      seq.append(x.qb)
  return pd.DataFrame(rows)


def main():
  arms = {p.stem[3:]: pd.read_parquet(p) for p in sorted((ROOT / "cache").glob("bb_*.parquet"))}
  if "base" not in arms:
    sys.exit("run the base arm first (see the usage)")
  arms = {k: v[v.variant == "fitted"].set_index("game_id") for k, v in arms.items()}
  tg = team_games()
  base = arms["base"]
  ids = base.index
  tgg = tg[tg.game_id.isin(ids)].copy()
  side = np.where(tgg.team.to_numpy() == base.home_team.reindex(tgg.game_id).to_numpy(), 1.0, -1.0)
  tgg["gap"] = side * (base.model_margin.reindex(tgg.game_id).to_numpy() - base.spread_line.reindex(tgg.game_id).to_numpy())
  tgg["wk"] = tgg.season.astype(str) + "-" + tgg.week.astype(str)
  print(f"{len(ids)} games 2021-25; team-games by kind: " + ", ".join(f"{k} {n}" for k, n in tgg.kind.value_counts().items()))
  print("\nDiagnosis (base): model margin - Vegas margin from the team's side (+ = we rate them better than the market)")
  for k in ("same", "backup in", "starter back", "new arrival", "inexperienced"):
    m = (tgg.kind == k).to_numpy()
    if m.any():
      mu, lo, hi = boot_ci(tgg.gap.to_numpy()[m], tgg.wk.to_numpy()[m])
      print(f"  {k:14s} n {m.sum():5d}  {mu:+.2f} [{lo:+.2f}, {hi:+.2f}]")
  chg = set(tgg.game_id[~tgg.kind.isin(["same", "no usual"])])
  g = base.assign(chg=base.index.isin(chg), wk=base.season.astype(str) + "-" + base.week.astype(str),
                  actual=base.home_score - base.away_score)
  wk = g.wk.to_numpy()
  print(f"\nQB-change games: {g.chg.sum()} of {len(g)}")
  for name, a in arms.items():
    if name == "base":
      continue
    a = a.reindex(g.index)
    gv_b, gv_a = (g.model_margin - g.spread_line).abs(), (a.model_margin - a.spread_line).abs()
    er_b, er_a = (g.model_margin - g.actual).abs(), (a.model_margin - g.actual).abs()
    c = g.chg.to_numpy() & gv_b.notna().to_numpy() & gv_a.notna().to_numpy()
    t1 = boot_ci((gv_a - gv_b).to_numpy()[c], wk[c])
    t2 = boot_ci((er_a - er_b).to_numpy()[g.chg.to_numpy()], wk[g.chg.to_numpy()])
    allm = er_a.notna().to_numpy()
    t3 = boot_ci((er_a - er_b).to_numpy()[allm], wk[allm])
    ok1, ok2, ok3 = t1[2] < 0, t2[2] < 0.10, t3[2] < 0.02
    fmt = lambda t: f"{t[0]:+.3f} [{t[1]:+.3f}, {t[2]:+.3f}]"  # noqa: E731
    print(f"\n[{name}]")
    print(f"  (1) QB-change |model - Vegas|: {gv_b[c].mean():.3f} -> {gv_a[c].mean():.3f}, {fmt(t1)}  {'PASS' if ok1 else 'FAIL'}")
    print(f"  (2) QB-change margin MAE vs results: {er_b[g.chg].mean():.3f} -> {er_a[g.chg].mean():.3f}, {fmt(t2)}  {'PASS' if ok2 else 'FAIL'}")
    print(f"      all games margin MAE: {er_b[allm].mean():.3f} -> {er_a[allm].mean():.3f}, {fmt(t3)}  {'PASS' if ok3 else 'FAIL'}")
    print(f"  games gates: {'PASS' if ok1 and ok2 and ok3 else 'FAIL'} (fantasy gate (3): tools/experiments.py)")
    for s in sorted(g.season.unique()):
      m = c & (g.season == s).to_numpy()
      print(f"    {s}: QB-change |model - Vegas| {(gv_a - gv_b).to_numpy()[m].mean():+.3f} ({m.sum()} games)")
    side_a = side * (a.model_margin.reindex(tgg.game_id).to_numpy() - a.spread_line.reindex(tgg.game_id).to_numpy())
    for k in ("backup in", "starter back", "new arrival", "inexperienced"):
      m = (tgg.kind == k).to_numpy()
      print(f"    gap to Vegas, {k:14s}: base {tgg.gap.to_numpy()[m].mean():+.2f} -> {np.nanmean(side_a[m]):+.2f}")


if __name__ == "__main__":
  main()
