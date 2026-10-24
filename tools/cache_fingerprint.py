"""Fingerprint of the cached history tables the injury model trains on, column by column and season by season, with
the practice-day strings' make-up (2026-10-24: the live build and a local build of the same code trained different
models; their avail_hist / practice tables matched in rows and outcomes but not in content).

  python tools/cache_fingerprint.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402


def h(s: pd.Series) -> str:
  return f"{int(pd.util.hash_pandas_object(s.astype(str), index=False).sum() % (2 ** 61)):x}"[:8]


def main():
  for name in ("availhist", "practice"):
    for p in sorted((ROOT / "cache").glob(f"{name}_*.parquet")):
      d = pd.read_parquet(p)
      cols = " ".join(f"{c}={h(d[c])}" for c in sorted(d.columns))
      ds = d.days.fillna("").astype(str) if "days" in d else pd.Series([], dtype=str)
      mix = {c: int(ds.str.count(re.escape(c)).sum()) for c in "DLF?X-"}
      lens = ds.str.len().value_counts().sort_index().to_dict()
      dt = d.dates.fillna("").astype(str) if "dates" in d else pd.Series([], dtype=str)
      print(f"[fp] {p.stem}: rows {len(d)} | {cols} | days chars {mix} lens {lens}")
      print(f"[fpd] {p.stem}: dates empty {dt.eq('').mean():.3f} sample {dt[dt.ne('')].head(3).tolist()}")


if __name__ == "__main__":
  main()
