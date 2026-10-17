"""Shared site files: the page shells (nfledge/pages/) and the browser assets (nfledge/static/ -> assets/).

Standard library only, so the UI-only deploy (tools/assets_deploy.py) can refresh a built site without the model's
dependencies; report.render writes them on every full build."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

PAGES_DIR = Path(__file__).resolve().parent / "pages"  # page shells (plain HTML with %TOKENS%, filled by render)
STATIC_DIR = Path(__file__).resolve().parent / "static"
VERSION_RX = re.compile(r"\?v=[0-9a-f]{10}\b")  # the ?v= every page puts on its asset links


def page_html(name: str, **tokens) -> str:
  """A page shell from nfledge/pages/ with its %TOKENS% filled (plain replacement: the pages hold no logic)."""
  out = (PAGES_DIR / name).read_text(encoding="utf-8")
  for k, v in tokens.items():
    out = out.replace(f"%{k}%", str(v))
  return out


def asset_version() -> str:
  """Short content hash of the shared assets, added to their links (?v=) so a deploy reaches phones at once
  instead of after the browser's cache lifetime (GitHub Pages: 10 minutes)."""
  h = hashlib.sha1()
  for f in sorted(STATIC_DIR.iterdir()):
    if f.is_file():
      h.update(f.read_bytes())
  return h.hexdigest()[:10]


def write_site_assets(root_dir: Path) -> None:
  """Shared files at the site root: the game page and the live / player-card / gamecast script and styles. Every
  week page (current, lookahead and archived) links to these, so improvements reach old pages without rebuilding
  them."""
  (root_dir / "assets").mkdir(parents=True, exist_ok=True)
  for f in STATIC_DIR.iterdir():
    if f.is_file():
      (root_dir / "assets" / f.name).write_bytes(f.read_bytes())
  (root_dir / "game.html").write_text(page_html("game.html", V=asset_version()), encoding="utf-8")


def restamp_pages(root_dir: Path) -> int:
  """Point every page's asset links at the current version (?v=<hash>); returns how many pages changed."""
  v, n = asset_version(), 0
  for p in root_dir.rglob("*.html"):
    s = p.read_text(encoding="utf-8")
    t = VERSION_RX.sub(f"?v={v}", s)
    if t != s:
      p.write_text(t, encoding="utf-8")
      n += 1
  return n
