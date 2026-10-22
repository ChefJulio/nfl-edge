"""Plain-text pages for assistants and crawlers (owner 2026-10-22: "make the entire site more autonomously usable by
visiting llms"): players.md, players/<gsis_id>.md, teams/<TEAM>.md, injuries.md at the site root, from the built
site's own files (index.json, data/players, data/teams, data/depth, data/espn_injuries). Listed in llms.txt.

Usage: python tools/machine_pages.py --site=site [--base=https://chefjulio.github.io/nfl-edge/]
CI runs it after the game logs, depth charts and injuries are built.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nfledge import machine  # noqa: E402


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  machine.write_pages(Path(opt.get("site", "site")), opt.get("base", "https://chefjulio.github.io/nfl-edge/"))


if __name__ == "__main__":
  main()
