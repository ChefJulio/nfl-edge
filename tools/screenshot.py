"""Screenshot the built report for visual QA, in the iPhone engine (WebKit) or desktop Chromium.

Usage: python tools/screenshot.py TAB [options]
  TAB              a route: players | players/stats | teams/power | games | model | player/<gsis> ...
  --device=D       iphone (WebKit, iPhone 13 profile; default) | desktop (Chromium, 1440 wide)
  --pos=P          Rankings position tab: QB | RB | WR | TE
  --page-y=N       scroll the page down N px first
  --el=CSS         scroll the first element matching CSS to the top first (e.g. "article:has(.wp.toss)")
  --table-x=N      scroll the visible table sideways N px (pinned-column / compact checks)
  --table-y=N      scroll the visible table down N px (sticky-header checks)
  --out=PATH       output PNG (default scratch/shot_<tab>_<device>.png)
  --url=URL        page to open (default: the dev server, http://127.0.0.1:8765/index.html#TAB; start it with
                   `python tools/dev.py`). Pages fetch their week JSON, so they need http://, not file://.
  --wait=MS        extra wait after load (live data, ESPN fetches)
  --click=CSS      click the first matching element before the shot (player card, buttons)
  --full=1         full-page screenshot

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
  out = Path(opt.get("out", ROOT / "scratch" / f"shot_{tab.replace('/', '_')}_{device}.png"))
  out.parent.mkdir(exist_ok=True)
  with sync_playwright() as pw:
    if device == "iphone":
      browser = pw.webkit.launch()
      ctx = browser.new_context(**pw.devices["iPhone 13"], color_scheme="dark")
    else:
      browser = pw.chromium.launch()
      ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
    page = ctx.new_page()
    page.goto(opt.get("url", f"http://127.0.0.1:8765/index.html#{tab}"))
    page.wait_for_load_state("networkidle")
    if "#" in page.url:  # a week page: wait for the tab to render from its JSON
      page.wait_for_selector("section.on .scroll tbody tr, section.on a.mt, section.on .doc h2, section.on .pc", timeout=15000)
    if "wait" in opt:
      page.wait_for_timeout(int(opt["wait"]))
    if "click" in opt:  # e.g. open a player card: --click="tr.main[data-pos=WR]"
      page.locator(opt["click"]).first.click()
      page.wait_for_timeout(600)
    if "pos" in opt:
      page.click(f"section.on .seg button[data-pos={opt['pos']}], .posbar button[data-pos={opt['pos']}]")
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
    page.screenshot(path=str(out), full_page=opt.get("full") == "1")
    browser.close()
  print(out)


if __name__ == "__main__":
  main()
