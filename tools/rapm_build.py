"""(BP) On-field player value: ridge plus-minus on every play's 22 players (pre-registered 2026-10-20, docs/INSIGHTS.md (BP)).

Usage: python tools/rapm_build.py            build values for target seasons 2020-26 + single-season validity fits
For a target season s: every pass / run play of seasons s-3..s-1 (weights 0.25 / 0.5 / 1; win probability outside
.05-.95 at 0.25). EPA = context + sum(offense values of the 11 on offense) + sum(defense effects of the 11 on
defense); ridge, each player shrunk toward a prior mu = a_group + b_group x log(1 + his weighted plays) (fit from a
first pass with mu = 0), lambda per side picked by predicting season s-1's plays from s-4..s-2.
Output data/history/rapm_values.parquet: target, gsis_id, side (off / def), grp, value (EPA per play, + = good), plays.
Participation (cache/participation_<y>.parquet) is FTN's via nflverse, 2016-25 (none in-season).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import scipy.sparse as sp  # noqa: E402
from scipy.linalg import cho_factor, cho_solve  # noqa: E402

OUT = ROOT / "data" / "history" / "rapm_values.parquet"  # read by nfledge/lineup.py (live) and the backtests
VALID = ROOT / "cache" / "rapm_single.parquet"
FIRST, LAST = 2016, 2025
TARGETS = list(range(2020, 2027))
AGE_W = {1: 1.0, 2: 0.5, 3: 0.25}
LAMBDAS = [300.0, 1000.0, 3000.0, 10000.0, 30000.0, 100000.0]
GROUP = {"QB": "QB", "T": "OL", "G": "OL", "C": "OL", "OL": "OL", "OT": "OL", "OG": "OL", "WR": "WR", "TE": "TE",
         "RB": "RB", "HB": "RB", "FB": "RB", "DE": "DL", "DT": "DL", "NT": "DL", "DL": "DL", "LB": "LB", "ILB": "LB",
         "OLB": "LB", "MLB": "LB", "CB": "CB", "S": "S", "FS": "S", "SS": "S", "DB": "S", "SAF": "S"}


def load_plays() -> pd.DataFrame:
  out = []
  for y in range(FIRST, LAST + 1):
    p = pd.read_parquet(ROOT / "cache" / f"pbp_{y}.parquet",
                        columns=["game_id", "play_id", "season", "posteam", "home_team", "epa", "play_type", "down", "ydstogo", "yardline_100", "wp"])
    p = p[p.play_type.isin(["pass", "run"]) & p.epa.notna() & p.down.notna()]
    pa = pd.read_parquet(ROOT / "cache" / f"participation_{y}.parquet")
    p = p.merge(pa, left_on=["game_id", "play_id"], right_on=["nflverse_game_id", "play_id"])
    p = p[(p.n_offense == 11) & (p.n_defense == 11)]
    out.append(p)
  p = pd.concat(out, ignore_index=True)
  p["off"] = p.offense_players.str.split(";")
  p["dfn"] = p.defense_players.str.split(";")
  return p


def context(p: pd.DataFrame) -> np.ndarray:
  yl = p.yardline_100.to_numpy()
  cols = [np.ones(len(p)), (p.down == 2).to_numpy(), (p.down == 3).to_numpy(), (p.down == 4).to_numpy(),
          np.log(p.ydstogo.clip(lower=1).to_numpy()), yl <= 10, (yl > 10) & (yl <= 20), (yl > 50) & (yl <= 80), yl > 80,
          (p.posteam == p.home_team).to_numpy()]
  return np.column_stack(cols).astype(float)


def design(p: pd.DataFrame, oi: dict, di: dict) -> sp.csr_matrix:
  r_o = np.repeat(np.arange(len(p)), p.off.str.len())
  c_o = np.array([oi.get(x, -1) for xs in p.off for x in xs])
  r_d = np.repeat(np.arange(len(p)), p.dfn.str.len())
  c_d = np.array([di.get(x, -1) for xs in p.dfn for x in xs])
  ko, kd = c_o >= 0, c_d >= 0
  m = sp.csr_matrix((np.ones(ko.sum() + kd.sum()), (np.r_[r_o[ko], r_d[kd]], np.r_[c_o[ko], len(oi) + c_d[kd]])),
                    shape=(len(p), len(oi) + len(di)))
  return m


class Fit:
  def __init__(self, p: pd.DataFrame, w: np.ndarray, grp: dict):
    self.oi = {x: i for i, x in enumerate(sorted({x for xs in p.off for x in xs}))}
    self.di = {x: i for i, x in enumerate(sorted({x for xs in p.dfn for x in xs}))}
    C, Z = context(p), design(p, self.oi, self.di)
    self.nc, self.no = C.shape[1], len(self.oi)
    X = sp.hstack([sp.csr_matrix(C), Z]).tocsr()
    Xw = X.multiply(w[:, None]).tocsr()
    self.A = (X.T @ Xw).toarray()
    self.b = Xw.T @ p.epa.to_numpy()
    n = np.asarray(Z.multiply(w[:, None]).sum(0)).ravel()  # weighted plays per player column
    self.n = n
    ids = list(self.oi) + list(self.di)
    self.g = np.array([grp.get(x, "OTH") for x in ids])
    self.side = np.array(["off"] * self.no + ["def"] * len(self.di))
    self.ids = ids

  def solve(self, lam_o: float, lam_d: float, mu: np.ndarray | None = None) -> np.ndarray:
    k = len(self.ids)
    lam = np.r_[np.full(self.nc, 1e-6), np.full(self.no, lam_o), np.full(k - self.no, lam_d)]
    mu_full = np.r_[np.zeros(self.nc), mu if mu is not None else np.zeros(k)]
    beta = cho_solve(cho_factor(self.A + np.diag(lam)), self.b + lam * mu_full)
    return beta

  def prior(self, beta: np.ndarray) -> tuple[np.ndarray, dict]:
    """mu = a_group + b_group x log(1 + plays), per side, fit on the first pass (weighted by plays)."""
    pl = beta[self.nc:]
    x = np.log1p(self.n)
    mu, coef = np.zeros(len(pl)), {}
    for s in ("off", "def"):
      for gname in np.unique(self.g):
        m = (self.side == s) & (self.g == gname)
        if m.sum() < 20:
          coef[(s, gname)] = (0.0, 0.0)
          continue
        Xg = np.c_[np.ones(m.sum()), x[m]]
        wg = np.sqrt(self.n[m] + 1)
        a_, b_ = np.linalg.lstsq(Xg * wg[:, None], pl[m] * wg, rcond=None)[0]
        coef[(s, gname)] = (float(a_), float(b_))
        mu[m] = a_ + b_ * x[m]
    return mu, coef


def weights(p: pd.DataFrame, target: int) -> np.ndarray:
  age = target - p.season.to_numpy()
  w = np.array([AGE_W.get(a, 0.0) for a in age])
  return w * np.where(p.wp.between(0.05, 0.95).to_numpy(), 1.0, 0.25)


def predict(fit: Fit, beta: np.ndarray, coef: dict, q: pd.DataFrame, grp: dict) -> np.ndarray:
  """EPA prediction for plays q from a fit; players the fit never saw get their group's prior at zero plays."""
  pv = {}
  for i, x in enumerate(fit.ids):
    pv[(fit.side[i], x)] = beta[fit.nc + i]
  def val(side, x):
    if (side, x) in pv:
      return pv[(side, x)]
    return coef.get((side, grp.get(x, "OTH")), (0.0, 0.0))[0]
  base = context(q) @ beta[:fit.nc]
  return base + np.array([sum(val("off", x) for x in xs) for xs in q.off]) + np.array([sum(val("def", x) for x in xs) for xs in q.dfn])


def fit_target(p: pd.DataFrame, target: int, grp: dict, lam: tuple | None = None):
  tr = p[p.season.between(target - 3, target - 1)]
  f = Fit(tr, weights(tr, target), grp)
  if lam is None:
    lam = (1000.0, 1000.0)
  b0 = f.solve(*lam)
  mu, coef = f.prior(b0)
  beta = f.solve(*lam, mu=mu)
  return f, beta, coef


def tune(p: pd.DataFrame, target: int, grp: dict) -> tuple:
  """Pick (lambda_off, lambda_def) by predicting season target-1 from a fit on target-4..target-2."""
  v = target - 1
  tr = p[p.season.between(v - 3, v - 1)]
  if tr.season.min() > v - 3 and v - 3 < FIRST:
    tr = p[p.season.between(max(FIRST, v - 3), v - 1)]
  f = Fit(tr, weights(tr, v), grp)
  te = p[p.season == v]
  y, wt = te.epa.to_numpy(), np.where(te.wp.between(0.05, 0.95), 1.0, 0.25)
  best, loss = None, np.inf
  for lo in LAMBDAS:
    for ld in LAMBDAS:
      b0 = f.solve(lo, ld)
      mu, coef = f.prior(b0)
      beta = f.solve(lo, ld, mu=mu)
      e = float(np.sum(wt * (y - predict(f, beta, coef, te, grp)) ** 2) / wt.sum())
      if e < loss:
        best, loss = (lo, ld), e
  return best, loss


def main():
  pl = pd.read_parquet(ROOT / "cache" / "players_all.parquet")[["gsis_id", "position"]].dropna()
  grp = dict(zip(pl.gsis_id, pl.position.map(GROUP).fillna("OTH")))
  p = load_plays()
  print(f"{len(p)} plays {FIRST}-{LAST}", flush=True)
  rows, lams = [], {}
  for t in TARGETS:
    if t - 4 >= FIRST:
      lam, loss = tune(p, t, grp)
    else:
      lam = lams[min(lams)] if lams else (1000.0, 1000.0)
      loss = float("nan")
    f, beta, coef = fit_target(p, t, grp, lam)
    lams[t] = lam
    pv = beta[f.nc:]
    for i, x in enumerate(f.ids):
      val = pv[i] if f.side[i] == "off" else -pv[i]
      rows.append({"target": t, "gsis_id": x, "side": f.side[i], "grp": f.g[i], "value": float(val), "plays": float(f.n[i])})
    for (s, g), (a_, b_) in coef.items():  # the group's prior at zero plays (for players with no value)
      rows.append({"target": t, "gsis_id": f"__prior_{g}", "side": s, "grp": g, "value": float(a_ if s == "off" else -a_), "plays": 0.0})
    print(f"[rapm] target {t}: lambdas off/def {lam}, tune MSE {loss:.5f}, players {len(f.ids)}", flush=True)
  pd.DataFrame(rows).to_parquet(OUT, index=False)
  # validity: single-season fits (disjoint data), same lambdas as the latest target
  lam = lams[max(lams)]
  single = []
  for y in range(FIRST, LAST + 1):
    tr = p[p.season == y]
    f = Fit(tr, np.where(tr.wp.between(0.05, 0.95), 1.0, 0.25), grp)
    b0 = f.solve(*lam)
    mu, _ = f.prior(b0)
    beta = f.solve(*lam, mu=mu)
    for i, x in enumerate(f.ids):
      v = beta[f.nc + i]
      single.append({"season": y, "gsis_id": x, "side": f.side[i], "grp": f.g[i], "value": float(v if f.side[i] == "off" else -v), "plays": float(f.n[i])})
    print(f"[rapm] single season {y}", flush=True)
  S = pd.DataFrame(single)
  S.to_parquet(VALID, index=False)
  a = S.merge(S.assign(season=S.season - 1), on=["season", "gsis_id", "side"], suffixes=("", "_next"))
  a = a[(a.plays >= 300) & (a.plays_next >= 300)]
  print("\nvalidity: rank corr of a player's single-season value with his next season's (300+ plays both):")
  print(a.groupby(["side", "grp"]).apply(lambda t: pd.Series({"n": len(t), "corr": t.value.corr(t.value_next, method="spearman")})).round(3).to_string())


if __name__ == "__main__":
  main()
