"""Ask for a complete build (the slow data rebuilt: game logs, grades, depth charts, rosters ...) durably.

Usage: python tools/request_complete.py      writes .github/complete_request (now, UTC), commits and pushes it

Why not `gh workflow run deploy.yml -f mode=complete`: GitHub keeps one waiting run per concurrency group, so a
dispatched complete build that has to wait behind a running build is replaced by the next push and silently dropped
(owner 2026-10-31: "we need to stop cancelling builds ... make that never happen again"). deploy.yml's plan instead
asks the live site when its last complete build ran (data/complete_build.json) and does one whenever that is older
than the latest 2 a.m. Central or than this request, in whichever run gets to execute. A Claude Code hook
(~/.claude/hooks/no-complete-dispatch.js) blocks the direct dispatch.
"""
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
  f = ROOT / ".github" / "complete_request"
  at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
  f.write_text(at + "\n", encoding="utf-8")
  git = lambda *a: subprocess.run(["git", *a], cwd=ROOT, check=True)  # noqa: E731
  git("add", str(f.relative_to(ROOT)))
  git("commit", "-q", "-m", f"Request a complete build ({at})")
  if "--no-push" not in sys.argv:
    git("push", "-q")
  print(f"[request] complete build requested at {at}: every run builds it until the live site's "
        f"data/complete_build.json is newer")


if __name__ == "__main__":
  main()
