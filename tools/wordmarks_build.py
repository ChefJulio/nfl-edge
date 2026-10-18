"""Team wordmarks for the site (owner 2026-10-17): nflverse's official wordmark per team (load_teams().team_wordmark),
stored with the site's assets as nfledge/static/wordmarks/<TEAM>.png. Run by hand when a team rebrands; the files are
committed (no per-visit fetch from GitHub).

Usage: python tools/wordmarks_build.py [--meta]   (--meta: print the size table for shell.js WM)
Each mark is: white (its own shape, recolored, so every team reads on the dark tiles), the location line dropped (owner:
"dolphins is the only one including the team location": MIAMI over Dolphins, BALTIMORE over Ravens), cropped tight.
Location line = a band of lettering ABOVE the main (tallest) band and under 45% of its height; bands below the main one
(the Giants' underline) stay.
"""
import io
import sys
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "nfledge" / "static" / "wordmarks"


def bands(alpha: np.ndarray) -> list[tuple[int, int]]:
  """Row ranges [start, end) that hold lettering, split at rows with no solid pixels (faint anti-aliasing between
  two lines doesn't join them)."""
  rows = (alpha > 80).any(axis=1)
  out, start = [], None
  for y, on in enumerate(rows):
    if on and start is None:
      start = y
    elif not on and start is not None:
      out.append((start, y)); start = None
  if start is not None:
    out.append((start, len(rows)))
  return out


def is_bar(alpha: np.ndarray, b: tuple[int, int], main_h: int) -> bool:
  """A plain horizontal rule (the Giants' underline): thin, one unbroken run across most of the width."""
  cols = (alpha[b[0]:b[1]] > 80).any(axis=0)
  xs = np.flatnonzero(cols)
  if not len(xs) or (b[1] - b[0]) > 0.3 * main_h:
    return False
  span = xs[-1] - xs[0] + 1
  return span >= 0.5 * alpha.shape[1] * 0.6 and cols[xs[0]:xs[-1] + 1].mean() > 0.95


def drop_upper_line(a: np.ndarray) -> bool:
  """A location line joined to the nickname with no empty row between (TAMPA BAY over BUCCANEERS, whose tall letters
  reach up beside it): find a low-coverage valley near the top; if the lettering above it is a smaller line, drop
  the separate shapes that sit entirely above the valley (the tall letters continue down, so they stay)."""
  from scipy import ndimage
  cov = (a > 80).sum(axis=1).astype(float)
  rows = np.flatnonzero(cov)
  if not len(rows):
    return False
  top, bot = rows[0], rows[-1] + 1
  peak = cov[top:bot].max()
  low = np.flatnonzero(cov[top:bot] < 0.3 * peak) + top
  low = low[(low > top) & (low < top + 0.45 * (bot - top))]
  if not len(low):
    return False
  cut = low.max() + 1
  if cov[top:low.min()].max() >= 0.6 * peak:  # the part above is as big as the name: not a location line
    return False
  lab, n = ndimage.label(a > 24)
  sl = ndimage.find_objects(lab)
  hit = False
  for i, s_ in enumerate(sl, 1):
    if s_ is not None and s_[0].stop <= cut:
      a[lab == i] = 0
      hit = True
  return hit


def process(im: Image.Image) -> tuple[Image.Image, bool]:
  """Nickname only: the bottom-most large line of lettering (>= 60% of the tallest) is the nickname (CAROLINA over
  PANTHERS, LOS ANGELES over CHARGERS, MIAMI over Dolphins); every other line goes (locations above, DENVER below),
  except a plain bar under the nickname."""
  im = im.convert("RGBA")
  a = np.array(im.split()[3])
  bs = bands(a)
  dropped = False
  if len(bs) > 1:
    tallest = max(b[1] - b[0] for b in bs)
    main = [b for b in bs if b[1] - b[0] >= 0.6 * tallest][-1]
    h = main[1] - main[0]
    for b in bs:
      if b == main or (b[0] >= main[1] and is_bar(a, b, h)):
        continue
      a[b[0]:b[1], :] = 0
      dropped = True
    # blank everything outside the kept lines (faint anti-aliased specks of a dropped line: the Jaguars)
    keep = np.zeros(a.shape[0], bool)
    keep[main[0]:main[1]] = True
    for bb in bs:
      if bb[0] >= main[1] and is_bar(a, bb, h):
        keep[bb[0]:bb[1]] = True
    a[~keep, :] = 0
  dropped |= drop_upper_line(a)
  white = Image.new("RGBA", im.size, (255, 255, 255, 255))
  white.putalpha(Image.fromarray(a))
  box = white.getbbox()
  return (white.crop(box) if box else white), dropped


def meta() -> dict:
  """team -> [width / height, ink share] of each stored mark (shell.js WM: matchup tiles size every mark to about the
  same amount of ink, owner 2026-10-17: "boldness and width and sizing are very inconsistent")."""
  out = {}
  for f in sorted(OUT.glob("*.png")):
    im = Image.open(f)
    out[f.stem] = [round(im.width / im.height, 2), round(float((np.array(im.split()[3]) > 80).mean()), 2)]
  return out


def main():
  if "--meta" in sys.argv:  # print the WM table for nfledge/static/shell.js
    import json
    print(json.dumps(meta(), separators=(",", ":")))
    return
  import nflreadpy as nfl
  t = nfl.load_teams().to_pandas()
  # current franchises only (the site's codes; nflverse also lists OAK, SD, STL, LAR)
  t = t[t.team_wordmark.notna() & ~t.team_abbr.isin(["OAK", "SD", "STL", "LAR"])].drop_duplicates("team_abbr")
  OUT.mkdir(parents=True, exist_ok=True)
  n = 0
  for r in t.itertuples():
    try:
      raw = urllib.request.urlopen(r.team_wordmark, timeout=30).read()
    except Exception as e:  # keep going; a missing mark falls back to the typed name on the page
      print(f"[wordmarks] {r.team_abbr}: {e}", file=sys.stderr)
      continue
    im, dropped = process(Image.open(io.BytesIO(raw)))
    im.save(OUT / f"{r.team_abbr}.png", optimize=True)
    n += 1
    print(f"[wordmarks] {r.team_abbr} {im.size[0]}x{im.size[1]}{' (location line dropped)' if dropped else ''}")
  print(f"[wordmarks] wrote {n} to {OUT}")


if __name__ == "__main__":
  main()
