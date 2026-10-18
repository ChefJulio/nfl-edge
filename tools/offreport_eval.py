"""(AO) days off the practice report (pre-registered 2026-10-18, docs/INSIGHTS.md).

Usage: python tools/offreport_eval.py
Refetches NFL.com practice weeks with their dates (2018-25; cached as cache/practice_dated_<season>.parquet),
joins the played labels of data.avail_hist, rebuilds each player's week on his team's practice dates ('F' where he
was not listed), and compares the full-week practice model (nfledge/injuries.py, same features and settings):
A listed days only (production), B padded, C padded + days off the report. Walk-forward 2021-25.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from nfledge import data as D  # noqa: E402
from nfledge.config import load_config  # noqa: E402
from nfledge.injuries import InjuryModel, practice_features  # noqa: E402

TEST = [2021, 2022, 2023, 2024, 2025]


def dated(cache_dir: Path, season: int) -> pd.DataFrame:
  p = cache_dir / f"practice_dated_{season}.parquet"
  if p.exists():
    return pd.read_parquet(p)
  x = D.fetch_practice_days(season)
  x.to_parquet(p)
  return x


def pad(rows: pd.DataFrame) -> pd.DataFrame:
  """Adds pdays (his status on every team practice date, 'F' when not listed), n_off, pos_off ('before' / 'after' /
  'mid' / '')."""
  rows = rows.copy()
  rows["dl"] = rows.dates.fillna("").str.split(",").map(lambda v: [d for d in v if d])
  tdates = rows.groupby(["season", "week", "team"]).dl.agg(lambda s: sorted({d for v in s for d in v})[-3:])
  pd_, off, where = [], [], []
  for x in rows.itertuples():
    td, dd = tdates.get((x.season, x.week, x.team), []), str(x.days or "").replace("?", "")
    if not td or len(x.dl) != len(dd):
      pd_.append(dd); off.append(0); where.append(""); continue
    on = dict(zip(x.dl, dd))
    s_ = "".join(on.get(d, "F") for d in td)
    miss = [i for i, d in enumerate(td) if d not in on]
    pd_.append(s_); off.append(len(miss))
    lst = [i for i, d in enumerate(td) if d in on]
    where.append("" if not miss else "before" if lst and all(i < lst[0] for i in miss) else "after" if lst and all(i > lst[-1] for i in miss) else "mid")
  rows["pdays"], rows["n_off"], rows["pos_off"] = pd_, off, where
  return rows


def main():
  cfg = load_config()
  d = D.load_all(cfg)
  cdir = ROOT / cfg["data"]["cache_dir"]
  ah = d.avail_hist
  pr = pd.concat([dated(cdir, s) for s in sorted(ah.season.unique())], ignore_index=True)
  pr = pr.drop_duplicates(["season", "week", "gsis_id"], keep="last")[["season", "week", "gsis_id", "dates", "days"]].rename(columns={"days": "days_api"})
  A = ah.merge(pr, on=["season", "week", "gsis_id"], how="left")
  print(f"[AO] {len(A)} labelled practice weeks, dates for {A.dates.notna().mean():.0%}")
  A = pad(A)
  ch = A.pdays != A.days.fillna("").str.replace("?", "", regex=False)
  print(f"[AO] strings changed by padding: {ch.mean():.1%} ({ch.sum()})")
  # descriptive: listed-F days vs days off the report
  B_ = A[A.game_status != "OUT"]
  for w in ("before", "after", "mid"):
    s = B_[B_.pos_off == w]
    print(f"[AO]   off the report {w:6s}: n {len(s):5d}, played {s.played.mean():.1%}")
  allF = B_[B_.days.fillna("") == "FFF"]
  print(f"[AO]   listed FFF all week: n {len(allF)}, played {allF.played.mean():.1%}; never listed would be ~99%")

  im = InjuryModel(d, None, cfg)  # features only need the data (role, rest)
  def X_of(rows, col, extra):
    r = rows.assign(days=rows[col])
    X = im._with_rest(im._with_role(practice_features(r), r), r)
    if extra:
      X = X.assign(n_off=rows.n_off.to_numpy())
    return X
  from sklearn.ensemble import HistGradientBoostingClassifier
  out = []
  for s in TEST:
    tr, te = A[(A.season < s) & (A.game_status != "OUT")], A[(A.season == s) & (A.game_status != "OUT")].copy()
    for name, col, extra in (("A", "days", False), ("B", "pdays", False), ("C", "pdays", True)):
      m = HistGradientBoostingClassifier(**im._gb_params(), random_state=0).fit(X_of(tr, col, extra), tr.played)
      te[name] = m.predict_proba(X_of(te, col, extra))[:, 1]
    te["changed"] = (te.pdays != te.days.fillna("").str.replace("?", "", regex=False))
    out.append(te)
  T = pd.concat(out)
  y = T.played.astype(float)
  for n in "ABC":
    T[f"b{n}"] = (T[n] - y) ** 2

  def cmp(a, b, rows, label):
    dd = rows[f"b{b}"] - rows[f"b{a}"]
    g = rows.season.astype(str) + "-" + rows.week.astype(str)
    gs = pd.DataFrame({"d": dd.to_numpy(), "g": g.to_numpy()}).groupby("g").d.agg(["sum", "size"])
    idx = np.random.default_rng(0).integers(0, len(gs), (4000, len(gs)))
    bt = gs["sum"].to_numpy()[idx].sum(1) / gs["size"].to_numpy()[idx].sum(1)
    lo, hi = np.percentile(bt, [2.5, 97.5])
    per = rows.groupby("season")[[f"b{a}", f"b{b}"]].mean()
    better = int((per[f"b{b}"] < per[f"b{a}"]).sum())
    print(f"[AO] {label}: Brier {rows[f'b{a}'].mean():.4f} -> {rows[f'b{b}'].mean():.4f}, {dd.mean():+.4f} [{lo:+.4f}, {hi:+.4f}], better {better}/5")
    return hi, better

  hiB, nB = cmp("A", "B", T, "B vs A, all")
  cmp("A", "B", T[T.changed], "B vs A, changed rows")
  hiC, nC = cmp("A", "C", T, "C vs A, all")
  cmp("A", "C", T[T.changed], "C vs A, changed rows")
  hiCB, _ = cmp("B", "C", T, "C vs B, all")
  for n in "BC":
    T["dec"] = pd.qcut(T[n].rank(method="first"), 10, labels=False)
    c = T.groupby("dec").agg(p=(n, "mean"), y=("played", "mean"))
    print(f"[AO] {n} calibration: max decile gap {100 * (c.p - c.y).abs().max():.1f} points")
  print("[AO] GATE B:", "PASS" if hiB < 0 and nB >= 4 else "FAIL", "| C:", "PASS" if hiC < 0 and nC >= 4 else "FAIL",
        "| C over B:", "yes" if hiCB < 0 else "no")


if __name__ == "__main__":
  main()
