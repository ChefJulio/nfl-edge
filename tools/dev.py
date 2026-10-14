"""Dev server: serves a built site folder, with assets/ read straight from nfledge/static/, so edits to the shared
JS / CSS show on a browser refresh with no re-render. Nothing is cached (no-store), so a refresh always gets the
current files.

Usage: python tools/dev.py [--site=scratch/site] [--port=8765]
  then open http://127.0.0.1:8765/index.html (build the folder once with
  `python run.py --out scratch/site/index.html`; re-run only for template / Python / model changes).
"""
import http.server
import sys
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "nfledge" / "static"


class Handler(http.server.SimpleHTTPRequestHandler):
  def translate_path(self, path):
    clean = path.split("?", 1)[0].split("#", 1)[0]
    if clean.startswith("/assets/"):
      live = STATIC / clean[len("/assets/"):]
      if live.is_file():
        return str(live)
    return super().translate_path(path)

  def end_headers(self):
    self.send_header("Cache-Control", "no-store")
    super().end_headers()

  def log_message(self, fmt, *args):  # quiet: only errors
    if args and str(args[1]).startswith(("4", "5")):
      super().log_message(fmt, *args)


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  site = Path(opt.get("site", ROOT / "scratch" / "site")).resolve()
  port = int(opt.get("port", 8765))
  print(f"[dev] {site} on http://127.0.0.1:{port}/index.html (assets/ live from {STATIC})", flush=True)
  http.server.ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(site))).serve_forever()


if __name__ == "__main__":
  main()
