"""Which NFL.com headshots are real photos (owner 2026-10-21: LaDainian Tomlinson's card showed him as a Jet; "can we
get LTs picture to be from his best season?").

No free source has a photo per season. NFL.com keeps a retired player's signature-team photo (Tomlinson a Charger,
Favre a Packer, Moss a Viking), while ESPN's headshot is his last team's. But for many older players NFL.com's
"headshot" is a blank gray helmet render (owner 2026-10-18, Marion Barber), which is why past players' cards lead
with ESPN's. This tells them apart: the render is pure grayscale, so a 48 px thumbnail's opaque pixels have no color
spread (|R-G| + |G-B| = 0.0 on every render checked, 16-85 on real photos). Results are cached by image id
(<cache>/photo_check.json): an image id never changes its picture, so each is fetched once.
"""
import io
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

COLOR_MIN = 6.0  # mean |R-G| + |G-B| over opaque pixels: renders 0.0, real photos 16+
THUMB = "c_thumb,g_face,z_0.75,w_48,h_48,f_png"


def image_id(url: str) -> str | None:
  m = re.search(r"/league/([a-z0-9]+)\s*$", str(url or ""))
  return m.group(1) if m else None


def _colorful(iid: str) -> bool | None:
  url = f"https://static.www.nfl.com/image/private/{THUMB}/league/{iid}"
  try:
    raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "nfl-edge/1.0"}), timeout=20).read()
    a = np.asarray(Image.open(io.BytesIO(raw)).convert("RGBA").resize((48, 48))).astype(float)
  except Exception:
    return None  # unknown: asked again next run
  px = a[..., :3][a[..., 3] > 128]
  if not len(px):
    return False
  return bool((np.abs(px[:, 0] - px[:, 1]) + np.abs(px[:, 1] - px[:, 2])).mean() >= COLOR_MIN)


def real_photos(urls: dict, cache_dir: Path, workers: int = 16) -> set:
  """{key: NFL headshot URL} -> the keys whose image is a real photo."""
  path = Path(cache_dir) / "photo_check.json"
  seen = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
  ids = {k: image_id(u) for k, u in urls.items()}
  todo = sorted({i for i in ids.values() if i and i not in seen})
  if todo:
    with ThreadPoolExecutor(workers) as ex:
      for i, ok in zip(todo, ex.map(_colorful, todo)):
        if ok is not None:
          seen[i] = ok
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seen, separators=(",", ":")), encoding="utf-8")
    print(f"[photos] checked {len(todo)} NFL headshots ({sum(seen.get(i, False) for i in todo)} real photos)", flush=True)
  return {k for k, i in ids.items() if i and seen.get(i)}
