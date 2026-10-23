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


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = ROOT / opt.get("site", "site")
  cur = json.loads((site / "index.json").read_text(encoding="utf-8"))["season"] if (site / "index.json").exists() else 2026
  d = load(int(cur))
  done = d[d.result.notna()]
  code = b"".join((ROOT / "nfledge" / f).read_bytes() for f in ("winprob.py", "calc_inputs.py"))
  # retrained when the code changes or a week is complete (not after every game of a Sunday)
  last = done[done.season == done.season.max()]
  wk_done = int(last.groupby("week").game_id.nunique().pipe(lambda g: g[g >= 13].index.max() if (g >= 13).any() else 0))
  key = hashlib.sha1(code + f"{int(done.season.max())}:{wk_done}".encode()).hexdigest()[:12]
  cp = ROOT / "cache" / f"calc_{key}.json"
  if cp.exists():
    out = json.loads(cp.read_text(encoding="utf-8"))
    print(f"[calc] cached model {key}", flush=True)
  else:
    r = W.rows(done)
    m = W.fit(r)
    out = {"v": 1, "built": pd.Timestamp.now().strftime("%Y-%m-%d"), "seasons": [FIRST, int(done.season.max())],
           "rows": int(len(r)), "wp": W.export(m), "inputs": C.build(done)}
    cm = C.conversion_gb(done)
    out["conv"] = W.export(cm, C.CONV_FEATURES)
    g = C._gain_rows(done).sample(20, random_state=0)
    out["conv_check"] = [{"x": [float(v) for v in row], "p": float(p_)} for row, p_ in
                         zip(C.conv_features(g).to_numpy(float), cm.predict_proba(C.conv_features(g))[:, 1])]
    # the export evaluates as the model does (a sample of rows)
    smp = r.sample(min(2000, len(r)), random_state=0)
    diff = np.abs(W.predict_exported(out["wp"], W.features(smp)) - m.predict_proba(W.features(smp))[:, 1]).max()
    if diff > 1e-4:
      raise SystemExit(f"[calc] exported trees disagree with the model by {diff:.6f}")
    # a few rows for the browser engine's self-check (tools/calc_cli.mjs --check): features and the model's P
    chk = smp.head(20)
    out["check"] = [{"x": [float(v) for v in row], "p": float(p)} for row, p in
                    zip(W.features(chk).to_numpy(float), m.predict_proba(W.features(chk))[:, 1])]
    cp.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"[calc] trained on {len(r):,} plays ({out['seasons'][0]}-{out['seasons'][1]}); export check max diff {diff:.2e}", flush=True)
  dst = site / "data" / "calc"
  dst.mkdir(parents=True, exist_ok=True)
  (dst / "model.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
  print(f"[calc] wrote data/calc/model.json ({(dst / 'model.json').stat().st_size / 1024:.0f} KB)", flush=True)


if __name__ == "__main__":
  main()
