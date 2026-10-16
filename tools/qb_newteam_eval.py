"""New-to-the-team QB term, game gate (pre-registered 2026-10-16, docs/INSIGHTS.md (R)).

Usage: python tools/qb_newteam_eval.py BASE.parquet VARIANT.parquet
  both from tools/game_eval.py 2021-2025 --only=fitted --save=..., the variant with
  --set="team_model.qb_newteam_dropbacks=150"
Flags each team-game whose starter (most dropbacks) had >= 150 career dropbacks but < 150 for this team entering the
game, and compares margin MAE on games where either side is flagged (95% CI over games) and on all games.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

CUT = 150


def main():
  from nfledge import data as D
  from nfledge.config import load_config
  from nfledge.team_model import prior_dropbacks, prior_team_dropbacks, qb_experience, qb_team_experience, team_game_ledger
  base, var = (pd.read_parquet(p) for p in sys.argv[1:3])
  base, var = (x[x.variant == "fitted"].set_index("game_id") for x in (base, var))
  d = D.load_all(load_config())
  led = team_game_ledger(d.pbp, d.schedules)
  qe, qt = qb_experience(d.pbp, d.qb_career), qb_team_experience(d.pbp)
  flag = {}
  for (s, w), gg in base.groupby(["season", "week"]):
    car, tm = prior_dropbacks(qe, s, int(w)), prior_team_dropbacks(qt, s, int(w))
    now = led[(led.season == s) & (led.week == w)].dropna(subset=["qb"])
    qb = dict(zip(now.team, now.qb))
    for gid, x in gg.iterrows():
      f = False
      for t in (x.home_team, x.away_team):
        q = qb.get(t)
        f |= bool(q) and car.get(q, 0.0) >= CUT and tm.get((q, t), 0.0) < CUT
      flag[gid] = f
  df = pd.DataFrame({"e0": (base.model_margin - base.actual_margin).abs(),
                     "e1": (var.model_margin.reindex(base.index) - base.actual_margin).abs(),
                     "flag": pd.Series(flag)}).dropna()
  rng = np.random.default_rng(0)

  def ci(v):
    v = v.to_numpy()
    b = rng.choice(v, (4000, len(v))).mean(1)
    return v.mean(), np.percentile(b, 2.5), np.percentile(b, 97.5)
  f = df[df.flag.astype(bool)]
  m, lo, hi = ci(f.e1 - f.e0)
  ma, la, ha = ci(df.e1 - df.e0)
  print(f"games with a starter new to his team: {len(f)} of {len(df)}")
  print(f"  margin MAE {f.e0.mean():.3f} -> {f.e1.mean():.3f}  diff {m:+.3f} [{lo:+.3f}, {hi:+.3f}]  {'ok' if hi < 0 else 'FAIL'}")
  print(f"all games: {df.e0.mean():.3f} -> {df.e1.mean():.3f}  diff {ma:+.3f} [{la:+.3f}, {ha:+.3f}]  {'ok' if ha < 0.02 else 'FAIL'}")
  print("GAME GATE:", "PASS" if hi < 0 and ha < 0.02 else "FAIL")


if __name__ == "__main__":
  main()
