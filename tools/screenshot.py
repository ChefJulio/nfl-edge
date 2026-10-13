"""Screenshot the built report for visual QA, in the iPhone engine (WebKit) or desktop Chromium.

Usage: python tools/screenshot.py TAB [options]
  TAB              players | games | power | roles | model
  --device=D       iphone (WebKit, iPhone 13 profile; default) | desktop (Chromium, 1440 wide)
  --pos=P          Rankings position tab: QB | RB | WR | TE
  --page-y=N       scroll the page down N px first
  --el=CSS         scroll the first element matching CSS to the top first (e.g. "article:has(.wp.toss)")
  --table-x=N      scroll the visible table sideways N px (pinned-column / compact checks)
  --table-y=N      scroll the visible table down N px (sticky-header checks)
  --out=PATH       output PNG (default scratch/shot_<tab>_<device>.png)
  --html=PATH      page to open (default: the newest report/nfl_edge_week*.html)

Owner tests on Brave/iPhone. Every iOS browser is WebKit, and headless Chrome cannot reproduce WebKit layout bugs
(it missed a stray-line bug from row overlays), so check mobile layouts here with --device=iphone.
Dev-only: needs `pip install playwright` and `python -m playwright install webkit chromium`; not a site dependency.
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent


def main():
  args = [a for a in sys.argv[1:] if not a.startswith("--")]
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  tab = args[0] if args else "players"
  device = opt.get("device", "iphone")
  page_html = (Path(opt["html"]).resolve() if "html" in opt
               else max((ROOT / "report").glob("nfl_edge_week*.html"), key=lambda p: p.stat().st_mtime))
  out = Path(opt.get("out", ROOT / "scratch" / f"shot_{tab}_{device}.png"))
  out.parent.mkdir(exist_ok=True)
  with sync_playwright() as pw:
    if device == "iphone":
      browser = pw.webkit.launch()
      ctx = browser.new_context(**pw.devices["iPhone 13"], color_scheme="dark")
    else:
      browser = pw.chromium.launch()
      ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
    page = ctx.new_page()
    page.goto(page_html.as_uri() + f"#{tab}")
    page.wait_for_load_state("networkidle")
    if "pos" in opt:
      page.click(f".posbar button[data-pos={opt['pos']}]")
    if "el" in opt:  # scroll the first matching element to the top of the screen
      page.locator(opt["el"]).first.evaluate("e => window.scrollTo(0, e.getBoundingClientRect().top + scrollY - 70)")
    if "page-y" in opt:
      page.evaluate(f"window.scrollTo(0, {int(opt['page-y'])})")
    for axis, prop in (("table-x", "scrollLeft"), ("table-y", "scrollTop")):
      if axis in opt:
        page.evaluate("""([prop, v]) => { const sc = [...document.querySelectorAll('section.on .scroll')]
          .find(s => s.offsetWidth > 0); sc[prop] = v; sc.dispatchEvent(new Event('scroll')); }""",
                      [prop, int(opt[axis])])
    page.wait_for_timeout(400)
    page.screenshot(path=str(out))
    browser.close()
  print(out)


if __name__ == "__main__":
  main()
