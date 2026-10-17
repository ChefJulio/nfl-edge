"""UI-only deploy: refresh the browser assets of an already built site (.github/workflows/deploy.yml, fast path).

A push that only changes nfledge/static/ needs none of the data pipeline: take the last deployed site, copy the
current assets and game page over it, and point every page's ?v= at the new asset hash so phones fetch them at once.

  python tools/assets_deploy.py --site=site
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfledge.site_assets import asset_version, restamp_pages, write_site_assets  # noqa: E402


def main() -> None:
  ap = argparse.ArgumentParser()
  ap.add_argument("--site", required=True)
  site = Path(ap.parse_args().site)
  if not (site / "index.html").exists():
    sys.exit(f"[assets] {site}/index.html missing: not a built site")
  write_site_assets(site)
  n = restamp_pages(site)
  print(f"[assets] assets {asset_version()} written; {n} pages restamped")


if __name__ == "__main__":
  main()
