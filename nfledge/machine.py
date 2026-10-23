"""Machine-readable copies of the site (owner 2026-10-16: "can we serve the model page, or the entire site, in a way
that's scrapeable?"). The app renders everything in the browser behind #hash routes, so a crawler or an LLM that
fetches a URL sees an empty frame. Each current-week build also writes, at the site root:

  llms.txt          what the site is + links to everything below and to the raw JSON files (llmstxt.org format)
  model.md          the Model tab as Markdown: MODEL.md with this build's live values, each track record in its area
  model/<area>.md   the same, one file per area (model.md is too big for some fetchers in one go)
  model/index.html  the same as a static page (no JavaScript), for ordinary crawlers
  rankings.md       this week's projections, one Markdown table per position; kickers and team defenses are added
                    by tools/kdst_build.py (add_kdst), which runs after the week build
  power.md          power rankings; games.md: this week's games; notebook.md: the lab notebook (docs/INSIGHTS.md)

No robots.txt: the site is served under /nfl-edge/ and crawlers read robots.txt only at the domain root.

Everything comes from the same sources as the app (MODEL.md, the week's JSON, the committed track records), so the
copies can't disagree with it.
"""
from __future__ import annotations

import html
import json
import math
import re
import urllib.parse
from pathlib import Path

import markdown

POS = ("QB", "RB", "WR", "TE")
DEPTH = {"QB": 40, "RB": 80, "WR": 100, "TE": 40}


def _avail_md(a: dict | None) -> str:
  if not a:
    return ""
  now = a.get("now") or {}
  nowc = {c["band"]: c for c in now.get("calib") or []}
  out = ["### How accurate is our chance to play? (track record)", "",
         f"Each season ({a['seasons']}) predicted by models trained only on earlier seasons; QB / RB / WR / TE; players "
         "ruled Out left out (0% by rule). Error = Brier score (average squared miss; lower is better; 0 = never wrong).", "",
         "| Final injury report, read as | Error |", "|---|---|"]
  out += [f"| {v['label']}{' **(this site)**' if v.get('ours') else ''} | {v['brier']:.3f} |" for v in a["versus"]]
  out += ["", "| When | Error | Wrong call (did the opposite of our lean) |", "|---|---|---|"]
  out += [f"| {s['label']} | {s['brier']:.3f} | {s['wrong']}% |" for s in a["stages"]]
  out += ["", "Calibration: when we gave a chance in this band, how often those players played"
          + (f" (last column: {now['season']} so far, weeks {now['weeks']}, models trained only on earlier seasons)." if now else "."), "",
          f"| We said | Players | Our average | Played | {now.get('season', '')} |", "|---|---|---|---|---|"]
  out += [f"| {c['band']} | {c['n']:,} | {c['predicted']}% | {c['played']}% | "
          + (f"{nowc[c['band']]['played']}% of {nowc[c['band']]['n']}" if c["band"] in nowc else "-") + " |" for c in a["calib"]]
  out += ["", "| When | Situation | Players | Played | We said |", "|---|---|---|---|---|"]
  out += [f"| {s['when']} | {s['label']} | {s['n']:,} | {s['played']}% | {s['predicted']}% |" for s in a["spots"]]
  return "\n".join(out) + "\n"


def _fav_md(t: dict | None) -> str:
  if not t:
    return ""
  out = ["### How often favorites win (track record)", "",
         f"Market chances, {t['since']}-{t['season']}; each season scored with chances fit only on the seasons before it.", "",
         f"| Favorite's chance | Games | Expected | Won | {t['season']} |", "|---|---|---|---|---|"]
  for r in t["rows"]:
    now = f"{round(r['actual_now'])}% of {r['n_now']}" if r.get("n_now") else "-"
    out.append(f"| {r['label']} | {r['n']} | {round(r['expected'])}% | {round(r['actual'])}% | {now} |")
  return "\n".join(out) + "\n"


def slug(title: str) -> str:
  return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def areas(md: str) -> tuple[str, list[tuple[str, str]]]:
  """(what comes before the first area, [(area title, its Markdown from its '## ' heading on)]). Each '## ' heading of
  MODEL.md is an area, as on the Model tab (nfledge/static/model.js)."""
  parts = re.split(r"(?m)^(?=## )", md)
  return parts[0], [(p.splitlines()[0][3:].strip(), p.rstrip() + "\n") for p in parts[1:]]


def model_md(body_md: str, avail: dict | None, track: dict | None, base: str, generated: str) -> str:
  head = (f"<!-- NFL Edge model description, generated {generated}. App: {base} ; this file: {base}model.md ; "
          f"one file per area: {base}llms.txt -->\n\n")
  intro, ar = areas(body_md.strip() + "\n")
  # each track record goes inside its area (model.js `place`), else at the end
  for rx, extra in ((r"chance to play|inactive|availability", _avail_md(avail)), (r"^games|game lines", _fav_md(track))):
    if not extra:
      continue
    i = next((i for i, (t, _) in enumerate(ar) if re.search(rx, t, re.I)), len(ar) - 1)
    ar[i] = (ar[i][0], ar[i][1] + "\n" + extra)
  return head + intro + "\n".join(text for _, text in ar)


def model_page(md: str, base: str, generated: str) -> str:
  body = markdown.markdown(md, extensions=["tables", "sane_lists"])
  return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>How the NFL Edge model works</title>
<meta name="description" content="How every number on NFL Edge is calculated: projections, chances to play, game lines, playoff odds, grades, and what was tested and rejected.">
<link rel="alternate" type="text/markdown" href="{base}model.md">
<style>body{{margin:0;background:#0d0f13;color:#e9ecf0;font:16px/1.6 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
main{{max-width:860px;margin:0 auto;padding:24px 16px 64px}}a{{color:#6d9eff}}h1,h2,h3{{line-height:1.25}}
table{{border-collapse:collapse;width:100%;font-size:14px;display:block;overflow-x:auto}}th,td{{border-bottom:1px solid #262b33;padding:6px 8px;text-align:left;vertical-align:top}}
th{{color:#98a0ab;font-size:12px;text-transform:uppercase;letter-spacing:.04em}}code{{background:#1a1e24;padding:1px 4px;border-radius:4px}}</style></head>
<body><main><p><a href="{base}">&larr; NFL Edge (the app)</a> &middot; <a href="{base}model.md">Markdown</a> &middot; <a href="{base}llms.txt">llms.txt</a> &middot; generated {html.escape(generated)}</p>
{body}</main></body></html>
"""


def _play(p: dict) -> float:  # chance to take the field (AY3); older weeks: 1 - inactive
  return float(p["play"]) if p.get("play") is not None else 1.0 - float(p.get("inactive") or 0.0)


def _pct(v: float) -> str:
  return "<1%" if 0 < v < 0.005 else f"{round(100 * v)}%"


def rankings_md(week: dict, base: str) -> str:
  ps = list(week.get("players", {}).values())
  out = [f"# NFL Edge weekly rankings: {week['season']} week {week['week']}", "",
         f"Generated {week.get('generated', '')}. Projected fantasy points in half-PPR scoring, IF the player plays. "
         "Play = his chance to take the field; Injury = his chance to sit injured (injury report, practice); Scratch = "
         "his chance to be a healthy scratch (inactive while healthy, e.g. a backup quarterback). Under 10% to play shows "
         "as likely out. Range = 10th-90th percentile outcome. Full data: "
         f"{base}index.json ; method: {base}model/chance-to-play.md", ""]
  for pos in POS:
    # as the app ranks them: by projection, near-certain outs (under 10% to play) after everyone else
    rows = sorted((p for p in ps if p.get("pos") == pos and p.get("rank")),
                  key=lambda p: (_play(p) < 0.1, -p["proj"]))[:DEPTH[pos]]
    if not rows:
      continue
    out += [f"## {pos}", "", "| Rank | Player | Team | Opp | Proj | Range | Play | Injury | Scratch | Status |", "|---|---|---|---|---|---|---|---|---|---|"]
    for i, p in enumerate(rows, 1):
      q = p.get("q") or [None] * 5
      rng = f"{q[0]:.0f}-{q[4]:.0f}" if q[0] is not None and q[4] is not None else ""
      pl = _play(p)
      opp = (("" if p.get("home") else "@") + p["opp"]) if p.get("opp") else "bye"
      st = (p.get("status") or "").replace("|", "/").strip()
      out.append(f"| {i} | {p['name']} | {p.get('team', '')} | {opp} | {p['proj']:.1f}{' (likely out)' if pl < 0.1 else ''} | "
                 f"{rng} | {_pct(pl)} | {_pct(p.get('inactive') or 0.0)} | {_pct(p.get('scratch') or 0.0)} | {st} |")
    out.append("")
  return "\n".join(out)


# Kicker and D/ST scoring: standard ESPN rules, as the Rankings tab scores them (nfledge/static/shell.js NFLE.kdst)
STD_K = {"fgm_0_19": 3, "fgm_20_29": 3, "fgm_30_39": 3, "fgm_40_49": 4, "fgm_50_59": 5, "fgm_60_": 5, "fgmiss_0_19": -1,
         "fgmiss_20_29": -1, "fgmiss_30_39": -1, "fgmiss_40_49": -1, "fgmiss_50_59": -1, "fgmiss_60_": -1, "xpm": 1, "xpmiss": -1}
STD_D = {"sack": 1, "int": 2, "fum_rec": 2, "def_td": 6, "st_td": 6, "safe": 2, "blk": 2}
PA_TIERS = ((0, 0, 5), (1, 6, 4), (7, 13, 3), (14, 17, 1), (18, 27, 0), (28, 34, -1), (35, 45, -3), (46, math.inf, -5))
KD_MARK = "<!-- kickers and defenses: tools/kdst_build.py -->"


def _between(mu: float, sd: float, lo: float, hi: float) -> float:
  """P(lo <= X <= hi) for an integer outcome of normal(mu, sd); below 0 counts as 0 (shell.js pBetween)."""
  phi = lambda z: 0.5 * (1 + math.erf(z / math.sqrt(2)))  # noqa: E731
  return (1.0 if hi == math.inf else phi((hi + 0.5 - mu) / sd)) - (0.0 if lo <= 0 else phi((lo - 0.5 - mu) / sd))


def kdst_md(kd: dict, week: dict) -> str:
  """This week's kickers and team defenses, ranked as the Rankings tab ranks them (data/kdst.json lines)."""
  wk, teams = int(week["week"]), week.get("teams") or {}
  opp = {}
  for g in week.get("games") or []:
    a, h = g["away"]["team"], g["home"]["team"]
    opp[a], opp[h] = "@" + h, "vs " + a
  ks = []
  for team, o in (kd.get("k") or {}).items():
    e = next((x for x in o["w"] if x[0] == wk), None)
    if e:
      ln = dict(zip(kd["k_keys"], e[2]))
      ks.append((sum(v * STD_K.get(k, 0) for k, v in ln.items()), o["name"], team, e[1],
                 sum(v for k, v in ln.items() if k.startswith("fg")), ln.get("xpm", 0)))
  ds = []
  for team, o in (kd.get("dst") or {}).items():
    e = next((x for x in o["w"] if x[0] == wk), None)
    if e:
      ln = dict(zip(kd["d_keys"], e[3]))
      v = sum(ln.get(k, 0) * w for k, w in STD_D.items()) + sum(p * _between(ln["pa_mu"], ln["pa_sd"], lo, hi) for lo, hi, p in PA_TIERS)
      ds.append((v, team, ln["pa_mu"], ln["sack"], ln["int"] + ln["fum_rec"]))
  if not ks and not ds:
    return ""
  out = [KD_MARK, "## K", "", f"Standard scoring (FG 0-39 yds 3, 40-49 4, 50+ 5, miss -1; XP 1, miss -1). Data: data/kdst.json "
         f"(built {kd.get('built', '')}).", "", "| Rank | Kicker | Team | Opp | Proj | Team implied points | FG attempts | XP made |",
         "|---|---|---|---|---|---|---|---|"]
  out += [f"| {i} | {n} | {t} | {opp.get(t, 'bye')} | {v:.1f} | {imp:.1f} | {fga:.1f} | {xpa:.1f} |"
          for i, (v, n, t, imp, fga, xpa) in enumerate(sorted(ks, key=lambda r: -r[0]), 1)]
  out += ["", "## DST", "", "Standard scoring (sack 1, takeaway 2, defensive or return TD 6, safety 2, block 2; points allowed: "
          "0 = 5, 1-6 = 4, 7-13 = 3, 14-17 = 1, 18-27 = 0, 28-34 = -1, 35-45 = -3, 46+ = -5).", "",
          "| Rank | Defense | Opp | Proj | Points allowed | Sacks | Takeaways |", "|---|---|---|---|---|---|---|"]
  out += [f"| {i} | {t} {(teams.get(t) or {}).get('nick', '')} | {opp.get(t, 'bye')} | {v:.1f} | {pa:.1f} | {sk:.1f} | {tk:.1f} |"
          for i, (v, t, pa, sk, tk) in enumerate(sorted(ds, key=lambda r: -r[0]), 1)]
  return "\n".join(out) + "\n"


def add_kdst(root: Path) -> None:
  """Add (or replace) the kicker and D/ST tables at the end of rankings.md, once data/kdst.json is built."""
  rk, kp, wp = root / "rankings.md", root / "data" / "kdst.json", root / "index.json"
  if not (rk.exists() and kp.exists() and wp.exists()):
    return
  s = rk.read_text(encoding="utf-8").split(KD_MARK)[0].rstrip() + "\n\n"
  rk.write_text(s + kdst_md(json.loads(kp.read_text(encoding="utf-8")), json.loads(wp.read_text(encoding="utf-8"))),
                encoding="utf-8")


def power_md(week: dict, base: str) -> str:
  rows = week.get("power") or []
  sg = lambda v: "" if v is None else f"{v:+.1f}"  # noqa: E731
  out = [f"# NFL Edge power rankings: {week['season']} week {week['week']}", "",
         "Rank and Net = how good each team is from here on: opponent-adjusted points per game vs an average team over "
         "its remaining games, an injured starting QB counted by his chance to be back each week. Offense + Defense + "
         f"ST = Net. Rank range = 10th-90th percentile rank over 4,000 simulations. Method: {base}model/games.md", "",
         "| Rank | Team | Record | Net | Offense | Defense | ST | Rank range |", "|---|---|---|---|---|---|---|---|"]
  for r in rows:
    out.append(f"| {r['rank']} | {r['team']} {r.get('nick', '')} | {r.get('record', '')} | {sg(r.get('net'))} | "
               f"{sg(r.get('off'))} | {sg(r.get('def'))} | {sg(r.get('st'))} | {r.get('range', '')} |")
  return "\n".join(out) + "\n"


def games_md(week: dict, base: str) -> str:
  out = [f"# NFL Edge games: {week['season']} week {week['week']}", "",
         "Market chance = from the Vegas spread when posted; our model = this week's rank gap (each team with this week's QB) + Elo + home field "
         f"(method: {base}model/games.md).", "",
         "| Kickoff | Game | QBs | Vegas line | Total | Market favorite | Our model | Final |", "|---|---|---|---|---|---|---|---|"]
  for g in week.get("games") or []:
    a, h, f = g.get("away", {}), g.get("home", {}), g.get("fc", {}) or {}
    fin = g.get("final") or {}
    final = f"{a.get('team')} {fin.get('away')} - {h.get('team')} {fin.get('home')}" if fin.get("home") is not None else ""
    mk = "tossup" if f.get("tossup") else f"{f.get('fav', '')} {f.get('pct', '')}%"
    md = "tossup" if f.get("model_tossup") else f"{f.get('model_fav', '')} {f.get('model_pct', '')}%"
    out.append(f"| {g.get('kickoff', '')} | {a.get('team')} ({a.get('record', '')}) {'vs' if g.get('neutral') else '@'} {h.get('team')} ({h.get('record', '')}) | "
               f"{a.get('qb', '')} / {h.get('qb', '')} | {g.get('vegas_line') or ''} | {g.get('vegas_total') or ''} | {mk} | {md} | {final} |")
  return "\n".join(out) + "\n"


def _kb(n: int) -> str:
  return f"{max(1, round(n / 1024))} KB"


def trends_link(base: str, q: dict) -> str:
  """A Trends query as a link (?q= plain JSON; the page fills defaults and looks up player names)."""
  return f"{base}?q={urllib.parse.quote(json.dumps(q, separators=(',', ':')))}#players/trends"


def trends_md(base: str) -> str:
  """llms.txt section (owner 2026-10-22): how an assistant answers play-by-play questions with a Trends link."""
  ex = [("Aaron Jones's rushing against the Packers while with the Vikings, by season",
         {"fam": "rush", "met": "ypc", "who": "P:Aaron Jones", "f": {"vs": "GB", "tm": "MIN"}, "by": "season", "from": 2024, "to": 2025}),
        ("Receiving yards per route run, tight ends, 2025",
         {"fam": "route", "met": "yprr", "f": {"rpos": "TE"}, "from": 2025, "to": 2025}),
        ("Rushing yards per carry on 3rd and 1-3, every team, last 3 seasons",
         {"fam": "rush", "met": "ypc", "by": "team", "f": {"down": "3", "dist": "R:1~3"}}),
        ("Most 100-yard rushing games in 2025, with the longest streak",
         {"fam": "rush", "met": "yds", "by": "pmark", "gt": 100, "from": 2025, "to": 2025})]
  exs = "\n".join(f"  - {t}: {trends_link(base, q)}" for t, q in ex)
  return f"""## Ask the play-by-play (Trends)

Trends answers questions over every run and pass play since 1999 (charting: personnel, coverage, routes, pressure
2016 on; play action, motion 2022 on): leaderboards against the league in the same situation, splits, 2-D grids,
game logs, streaks and best stretches. Its rushing / receiving / passing totals match nflverse's official season
stats (audit: https://github.com/ChefJulio/nfl-edge/blob/main/docs/trends_audit.md).

To answer a question with it, give the person a link: {base}?q=<URL-encoded JSON query>#players/trends. The page
opens with the answer. The query, and every measure, filter (allowed values, ranges, presets), breakdown and which
seasons have which charting: [{base}data/plays/schema.json]({base}data/plays/schema.json). Unset fields take
defaults (rushing YPC, every player, regular season, last 3 seasons); players can be named ("who": "P:Aaron Jones",
"f": {{"wo": "Justin Jefferson"}}), the page looks them up. Ranges are "R:lo~hi"; several values of one filter are a
list (any of); "fn": {{"<filter>": 1}} excludes. Examples:
{exs}

To compute answers yourself (no browser): the same engine runs from the command line,
`node tools/trends_cli.mjs '<query JSON>' --data={base}` in the source repo (https://github.com/ChefJulio/nfl-edge).
"""


def llms_txt(base: str, season: int, week: int, generated: str, area_files: list[tuple[str, str, int]],
             sizes: dict[str, int]) -> str:
  ar = "\n".join(f"  - [{t}]({base}model/{s}.md) ({_kb(n)})" for t, s, n in area_files)
  return f"""# NFL Edge

> NFL Edge is a free NFL analytics site, rebuilt from public data every day. It covers the whole league: game win
> chances and team power ratings, playoff odds, every team's and player's stats and game logs back to 1999, live
> gamecasts, injury reports with each player's chance to play, and Trends, a play-by-play query tool for almost any
> split since 1999. For fantasy, it adds weekly and rest-of-season projections, rankings re-scored to your league's
> settings, and Sleeper / ESPN league tools. Every prediction model is tested on past seasons before it ships, and the
> misses are published.

Current week: {season} week {week} (generated {generated}). The app ({base}) renders in the browser; the links below
are the same content in plain text and JSON.

## Read these first

- How the model works, one Markdown file per area: what each number means, how it is computed, what was tested and
  rejected, and accuracy track records. "Site guide" explains every tab and card of the app.
{ar}
- [How the model works, all areas in one file]({base}model.md) ({_kb(sizes.get('model.md', 0))})
- [How the model works (static HTML)]({base}model/): the same, as a web page without JavaScript
- [This week's rankings (Markdown)]({base}rankings.md): projections per position with ranges, chance to play, and
  its injury and healthy-scratch parts; kickers and team defenses
- [Power rankings (Markdown)]({base}power.md): every team's rest-of-season and this-week rating, units, rank range
- [This week's games (Markdown)]({base}games.md): kickoff, QBs, Vegas line and total, market and model chances, finals
- [Every player (Markdown)]({base}players.md): name, position, team, and a page per player at
  {base}players/<gsis_id>.md: this week's chance to play and why, injury status, projection with range and expected
  stat line, practice and games this season day by day, recent injuries, durability, game logs (this season and
  last), bio and contract
- [Injuries (Markdown)]({base}injuries.md): every player on an injury report or list, by team, with our chance to play
- Teams, one page each: {base}teams/<TEAM>.md (e.g. {base}teams/BUF.md): record, power rank, results with lines,
  upcoming games with our win chance, this week's injuries, depth chart, players
- [Lab notebook (Markdown)]({base}notebook.md) ({_kb(sizes.get('notebook.md', 0))}, too big for some fetchers in one
  go; the per-area model files above summarize each test): every test as it happened, with its pass bar written before
  the result (also on GitHub: https://github.com/ChefJulio/nfl-edge/blob/main/docs/INSIGHTS.md)
- [Source code](https://github.com/ChefJulio/nfl-edge)

{trends_md(base)}
## Data (JSON)

- [{base}index.json]({base}index.json): this week: players (projection, stat line, range quantiles; `play` = chance
  to take the field and `play_why`, `inactive` = injury part and `inactive_why`, `scratch` = healthy-scratch part;
  matchup, status), games (lines, win chances, battle bars), teams, power ratings, roles
- [{base}weeks.json]({base}weeks.json): every built week (season -> week -> page); each page's data is the same path
  with .json; the current week is also at {season}/week-{week:02d}.json (same file as index.json). index.json
  ({_kb(sizes.get('index.json', 0))}) is too big for some fetchers in one go; the Markdown files above are smaller.
- [{base}data/ros.json]({base}data/ros.json): rest of season, per player and week: expected stat line if active,
  chance to play, opponent
- [{base}data/kdst.json]({base}data/kdst.json): kicker and team-defense expected stat lines this week through week 17
- [{base}data/playoffs/odds.json]({base}data/playoffs/odds.json): playoff, division, bye and title odds per team,
  rooting guide, odds history, track record
- [{base}data/model.json]({base}data/model.json): the Model tab as rendered HTML + track records
- {base}data/players/<gsis_id>.json: one player's career game log, offense or defense (gsis ids are nflverse's,
  e.g. 00-0034857)
- {base}data/teams/<TEAM>.json: one team's game log (team codes as nflverse, e.g. BUF, LA)
"""


def write(root: Path, body_md: str, avail: dict | None, track: dict | None, week_json: str, base: str, generated: str) -> None:
  week = json.loads(week_json)
  md = model_md(body_md, avail, track, base, generated)
  (root / "model.md").write_text(md, encoding="utf-8")
  (root / "model").mkdir(exist_ok=True)
  (root / "model" / "index.html").write_text(model_page(md, base, generated), encoding="utf-8")
  area_files = []
  for f in (root / "model").glob("*.md"):  # an area renamed or removed leaves no orphan
    f.unlink()
  for title, text in areas(md)[1]:
    s = slug(title)
    page = (f"<!-- NFL Edge: how the model works, area \"{title}\", generated {generated}. All areas: {base}llms.txt -->\n\n"
            + text)
    (root / "model" / f"{s}.md").write_text(page, encoding="utf-8")
    area_files.append((title, s, len(page.encode("utf-8"))))
  (root / "rankings.md").write_text(rankings_md(week, base), encoding="utf-8")
  (root / "power.md").write_text(power_md(week, base), encoding="utf-8")
  (root / "games.md").write_text(games_md(week, base), encoding="utf-8")
  nb = Path(__file__).resolve().parent.parent / "docs" / "INSIGHTS.md"  # the lab notebook (github.com blocks fetchers)
  if nb.exists():
    (root / "notebook.md").write_text(nb.read_text(encoding="utf-8"), encoding="utf-8")
  # the current week's data at its archive path too, so {season}/week-NN.json always works
  wk = root / str(week["season"]) / f"week-{int(week['week']):02d}.json"
  wk.parent.mkdir(exist_ok=True)
  wk.write_text(week_json, encoding="utf-8")
  sizes = {n: (root / n).stat().st_size for n in ("model.md", "notebook.md", "index.json") if (root / n).exists()}
  (root / "llms.txt").write_text(llms_txt(base, int(week["season"]), int(week["week"]), generated, area_files, sizes),
                                 encoding="utf-8")


# ---- per-player / per-team pages (owner 2026-10-22: "make the entire site more autonomously usable by visiting llms",
# option 2): what an assistant gets asked ("is X playing Sunday?", "how has he been doing?") answered in one small
# fetch each, from the same files the app reads. Written by tools/machine_pages.py after the game-log and depth steps.
PRAC_WORD = {"F": "full", "L": "limited", "D": "did not practice", "-": "not on the report", "R": "reserve list", "S": "practice squad"}
STAT_COLS = {  # (label, key in the log's "keys", or x index: completions, attempts, carries, targets)
  "QB": [("Cmp", 0), ("Att", 1), ("Pass yd", "pass_yd"), ("Pass TD", "pass_td"), ("INT", "interception"), ("Car", 2), ("Rush yd", "rush_yd"), ("Rush TD", "rush_td")],
  "RB": [("Car", 2), ("Rush yd", "rush_yd"), ("Rush TD", "rush_td"), ("Tgt", 3), ("Rec", "reception"), ("Rec yd", "rec_yd"), ("Rec TD", "rec_td")],
  "WR": [("Tgt", 3), ("Rec", "reception"), ("Rec yd", "rec_yd"), ("Rec TD", "rec_td"), ("Car", 2), ("Rush yd", "rush_yd")],
  "TE": [("Tgt", 3), ("Rec", "reception"), ("Rec yd", "rec_yd"), ("Rec TD", "rec_td")],
}


def _status(p: dict) -> str:
  """The status in words: "Questionable (ESPN) (LF)" stays; on the report with no game status (src "report", the
  status is just his practice letters) it's spelled out."""
  st, d = (p.get("status") or "").replace("|", "/").strip(), p.get("days") or ""
  return f"on the report, practiced: {', '.join(PRAC_WORD.get(c, c) for c in d)}" if p.get("src") == "report" and d and st == f"({d})" else st


def _num(v) -> str:
  return "" if v is None else (f"{v:.0f}" if float(v).is_integer() else f"{v:.1f}")


def _head(title: str, base: str, generated: str, app: str) -> list[str]:
  return [f"# {title}", "", f"<!-- NFL Edge, generated {generated}. In the app: {app} . Everything: {base}llms.txt -->", ""]


def _logline(g: dict, keys: list, cols: list) -> list[str]:
  c, x = dict(zip(keys, g.get("c") or [])), g.get("x") or []
  return [_num(x[k] if k < len(x) else None) if isinstance(k, int) else _num(c.get(k)) for _, k in cols]


def player_md(p: dict, log: dict | None, week: dict, base: str, games: dict) -> str:
  pid, pos = p["pid"], p.get("pos", "")
  title = f"{p['name']} ({pos}, {p.get('team', '')}): {week['season']} week {week['week']}"
  out = _head(title, base, week.get("generated", ""), f"{base}#player/{pid}")
  pl = _play(p)
  opp = f"{'vs' if p.get('home') else '@'} {p['opp']}" if p.get("opp") else "bye week"
  g = games.get(p.get("team"))
  out += ["## This week", "", f"- Game: {g if g and p.get('opp') else opp}"]
  if p.get("opp"):
    why = "; ".join(x for x in (p.get("play_why"), p.get("inactive_why")) if x)
    out.append(f"- Chance to play: {_pct(pl)} (injury: {_pct(p.get('inactive') or 0)} chance to sit injured; healthy scratch: "
               f"{_pct(p.get('scratch') or 0)}){f'. Why: {why}' if why else ''}")
    if _status(p):
      out.append(f"- Injury status: {_status(p)}")
    q = p.get("q") or []
    rng = f", range {q[0]:.1f} to {q[-1]:.1f} (10th-90th percentile)" if len(q) >= 5 and q[0] is not None else ""
    out.append(f"- Projection (half PPR, if he plays): {p['proj']:.1f} points{rng}" + (f"; {p.get('tier')}, rank {p['rank']} at {pos}" if p.get("rank") else ""))
    if p.get("proj_line"):
      out.append("- Expected stat line: " + ", ".join(f"{k.replace('_', ' ')} {v:.1f}" for k, v in p["proj_line"].items() if v))
    for k in ("vol", "td"):
      if (p.get(k) or {}).get("d"):
        out.append(f"- {p[k]['d']}")
  if p.get("fpg") is not None:
    out.append(f"- This season: {p['fpg']:.1f} fantasy points per game" + (f", last 3 games {p['last3']:.1f}" if p.get("last3") is not None else ""))
  out += ["", f"Method: {base}model/chance-to-play.md and {base}model/projections.md", ""]
  if not log:
    return "\n".join(out) + "\n"
  prac = [e for e in (log.get("prac") or []) if e[0] in ("p", "g")][-24:]
  if prac:
    out += ["## Practice and games, this season (latest last)", ""]
    for e in prac:
      if e[0] == "p":
        # e[4] = 1: inferred (on the roster, not on his team's filed report that day: the league's "not listed = full")
        how = "full (not on the report)" if len(e) > 4 and e[4] else PRAC_WORD.get(e[2], e[2])
        out.append(f"- {e[1]}: practice, {how}{f' ({e[3]})' if len(e) > 3 and e[3] else ''}")
      else:
        played = f", {e[4]}% of snaps" if len(e) > 4 and e[4] not in ("", None) else (" (upcoming)" if len(e) > 4 and e[4] == "" else "")
        out.append(f"- {e[1]}: game {e[3]} {e[2]}{played}")
    out.append("")
  inj = [i for i in (log.get("inj") or []) if i.get("s", 0) >= int(week["season"]) - 1][:8]
  if inj:
    out += ["## Recent injuries", ""]
    for i in inj:
      span = f"week {i['w0']}" + (f"-{i['w1']}" if i.get("w1") != i.get("w0") else "")
      out.append(f"- {i['s']} {span}: {i.get('part', 'injury')}" + (f", {i['list']}" if i.get("list") else "")
                 + (f", worst status {i['worst']}" if i.get("worst") else "") + f"; missed {i.get('missed', 0)}, played {i.get('played', 0)}")
    out.append("")
  d = log.get("dur") or {}
  if d.get("games"):
    out += [f"Durability: played {d['games'] - d.get('missed', 0)} of {d['games']} games he could have ({_pct(d.get('avail', 0))})"
            + (f", {d['per1k']:.1f} injuries per 1,000 snaps" if d.get("per1k") is not None else "") + ".", ""]
  cols = STAT_COLS.get(pos, STAT_COLS["WR"])
  keys = log.get("keys") or []
  for sea in sorted((s for s in log.get("seasons") or [] if s.get("s", 0) >= int(week["season"]) - 1), key=lambda s: -s["s"]):
    rows = [(r["w"], r) for r in sea.get("g") or []] + [(r["w"], r) for r in sea.get("m") or []]
    if not rows:
      continue
    out += [f"## Game log {sea['s']} (regular season)", "", "| Week | Opp | " + " | ".join(c for c, _ in cols) + " | Snaps |",
            "|---|---|" + "---|" * len(cols) + "---|"]
    for w, r in sorted(rows, key=lambda t: t[0]):
      if r.get("bye"):
        out.append(f"| {w} | bye |" + " |" * len(cols) + " |")
      elif "miss" in r:
        out.append(f"| {w} | {'vs' if r.get('h') else '@'} {r.get('o', '')} | did not play ({r['miss']}) |" + " |" * len(cols))
      else:
        out.append(f"| {w} | {'vs' if r.get('h') else '@'} {r.get('o', '')} | " + " | ".join(_logline(r, keys, cols)) + f" | {_num(r.get('sn'))}{'%' if r.get('sn') is not None else ''} |")
    out.append("")
  b = log.get("bio") or {}
  if b:
    dr = b.get("draft") or {}
    deal = b.get("deal") or {}
    bits = [f"born {b['born']}" if b.get("born") else "", f"college {b['college']}" if b.get("college") else "",
            f"drafted {dr['y']} round {dr['r']}, pick {dr['o']}" if dr else "undrafted" if b.get("exp") else "",
            f"contract ${deal['apy']:.2f}M a year through {deal.get('fa', '?') - 1 if isinstance(deal.get('fa'), int) else '?'}" if deal.get("apy") else ""]
    out += ["## Bio", "", "; ".join(x for x in bits if x) + ".", ""]
  out.append(f"Splits of any kind (by opponent, down, coverage, with or without a teammate...): {base}llms.txt, section Trends.")
  return "\n".join(out) + "\n"


def team_md(team: str, week: dict, tlog: dict | None, depth: dict | None, base: str, games: dict) -> str:
  t = (week.get("teams") or {}).get(team) or {}
  out = _head(f"{t.get('name', team)} ({team}): {week['season']} week {week['week']}", base, week.get("generated", ""), f"{base}#team/{team}")
  pw = next((r for r in week.get("power") or [] if r.get("team") == team), None)
  if pw:
    out += [f"Record {pw.get('record', '')}, {t.get('division', '')}. Power rank {pw['rank']} (net {pw.get('net', 0):+.1f} points per game vs an "
            f"average team; offense rank {pw.get('off_rk')}, defense rank {pw.get('def_rk')}). This week: {games.get(team, 'bye')}.", ""]
  sea = next((s for s in (tlog or {}).get("seasons") or [] if s.get("s") == int(week["season"])), None)
  if sea:
    out += [f"## {week['season']} results", "", "| Week | Opp | Result | Score | Line | ATS | Total |", "|---|---|---|---|---|---|---|"]
    for g in sea.get("g") or []:
      out.append(f"| {g['w']} | {'vs' if g.get('h') else '@'} {g.get('o', '')} | {g.get('r', '')} | {g.get('ps', '')}-{g.get('pa', '')} | "
                 f"{_num(g.get('ln'))} | {g.get('ats', '')} | {_num(g.get('tot'))} |")
    out.append("")
  up = [u for u in (tlog or {}).get("up") or [] if not u.get("bye")]
  if up:
    out += ["## Coming up", "", "| Week | Opp | Our win chance | Opponent power rank |", "|---|---|---|---|"]
    out += [f"| {u['w']} | {'vs' if u.get('h') else '@'} {u.get('o', '')} | {u.get('mc', '')}% | {u.get('opr', '')} |" for u in up]
    out.append("")
  hurt = sorted((p for p in (week.get("players") or {}).values() if p.get("team") == team and (p.get("status") or _play(p) < 0.95)), key=_play)
  if hurt:
    out += ["## Injuries this week (fantasy-relevant players)", "", "| Player | Pos | Status | Chance to play |", "|---|---|---|---|"]
    out += [f"| [{p['name']}]({base}players/{p['pid']}.md) | {p.get('pos', '')} | {_status(p)} | {_pct(_play(p))} |" for p in hurt]
    out.append("")
  if depth and depth.get("weeks"):
    wk = max(depth["weeks"], key=int)
    names = depth.get("players") or []
    out += [f"## Depth chart (week {wk}, offense)", ""]
    for code, label, slots in depth["weeks"][wk].get("off") or []:
      people = [f"{names[i][0]}{f' ({tag})' if tag else ''}" for i, _, tag in slots if i < len(names)]
      out.append(f"- {label}: {', '.join(people)}")
    out.append("")
  ps = sorted((p for p in (week.get("players") or {}).values() if p.get("team") == team), key=lambda p: (p.get("pos", ""), -(p.get("proj") or 0)))
  if ps:
    out += ["## Players", ""] + [f"- [{p['name']}]({base}players/{p['pid']}.md) ({p.get('pos', '')})" for p in ps] + [""]
  return "\n".join(out) + "\n"


def injuries_md(week: dict, espn: dict | None, base: str) -> str:
  ps = list((week.get("players") or {}).values())
  by_espn = {str(p.get("espn")): p for p in ps if p.get("espn")}
  out = _head(f"NFL Edge injuries: {week['season']} week {week['week']}", base, week.get("generated", ""), f"{base}#players/injuries")
  out += ["Chance to play = ours (injury report, practice, history; method: " f"{base}model/chance-to-play.md); status and details "
          f"from ESPN (fetched {(espn or {}).get('fetched', '')}).", ""]
  rows = [r for r in (espn or {}).get("rows") or [] if r.get("status") and r["status"] != "Active"]
  teams = week.get("teams") or {}
  abbr = {v.get("name"): k for k, v in teams.items()}
  for name in sorted({r.get("team") for r in rows if r.get("team")}):
    tr = sorted((r for r in rows if r.get("team") == name), key=lambda r: r.get("status", ""))
    out += [f"## {name}", "", "| Player | Status | Injury | Return | Our chance to play |", "|---|---|---|---|---|"]
    for r in tr:
      p = by_espn.get(str(r.get("espn_id")))
      who = f"[{r['name']}]({base}players/{p['pid']}.md)" if p else r.get("name", "")
      parts = [x for x in (r.get("side"), r.get("type"), r.get("detail")) if x and x != "Not Specified"]
      inj = " ".join(dict.fromkeys(parts))  # "Concussion Concussion" once
      out.append(f"| {who} | {r['status']} | {inj} | {r.get('return_date') or ''} | {_pct(_play(p)) if p and p.get('opp') else ''} |")
    out.append("")
  if abbr:
    out.append(f"Team pages: {', '.join(f'[{k}]({base}teams/{k}.md)' for k in sorted(teams))}")
  return "\n".join(out) + "\n"


def players_index_md(week: dict, base: str) -> str:
  ps = sorted((week.get("players") or {}).values(), key=lambda p: p["name"])
  out = _head(f"NFL Edge players: {week['season']} week {week['week']}", base, week.get("generated", ""), base)
  out += ["Every player on this week's page, with his own page (chance to play and why, projection, practice, game log, "
          f"bio). Teams: {', '.join(f'[{k}]({base}teams/{k}.md)' for k in sorted(week.get('teams') or {}))}.", "",
          "| Player | Pos | Team | Page |", "|---|---|---|---|"]
  out += [f"| {p['name']} | {p.get('pos', '')} | {p.get('team', '')} | {base}players/{p['pid']}.md |" for p in ps]
  return "\n".join(out) + "\n"


def write_pages(root: Path, base: str) -> None:
  """players.md, players/<gsis>.md, teams/<TEAM>.md, injuries.md from the built site's own files."""
  wp = root / "index.json"
  if not wp.exists():
    return
  week = json.loads(wp.read_text(encoding="utf-8"))
  for pid, p in (week.get("players") or {}).items():
    p.setdefault("pid", pid)
  games = {}
  for g in week.get("games") or []:
    a, h = g["away"]["team"], g["home"]["team"]
    k = g.get("kickoff", "")
    games[a] = f"@ {h}{f', {k}' if k else ''}"
    games[h] = f"vs {a}{f', {k}' if k else ''}"
  load = lambda f: json.loads(f.read_text(encoding="utf-8")) if f.exists() else None  # noqa: E731
  pd_ = root / "players"
  pd_.mkdir(exist_ok=True)
  for f in pd_.glob("*.md"):  # players no longer on the page leave no stale file
    f.unlink()
  for pid, p in week["players"].items():
    (pd_ / f"{pid}.md").write_text(player_md(p, load(root / "data" / "players" / f"{pid}.json"), week, base, games), encoding="utf-8")
  td = root / "teams"
  td.mkdir(exist_ok=True)
  for team in week.get("teams") or {}:
    (td / f"{team}.md").write_text(team_md(team, week, load(root / "data" / "teams" / f"{team}.json"),
                                           load(root / "data" / "depth" / str(week["season"]) / f"{team}.json"), base, games), encoding="utf-8")
  (root / "injuries.md").write_text(injuries_md(week, load(root / "data" / "espn_injuries" / "latest.json"), base), encoding="utf-8")
  (root / "players.md").write_text(players_index_md(week, base), encoding="utf-8")
  print(f"[machine] pages: {len(week['players'])} players, {len(week.get('teams') or {})} teams, injuries.md, players.md", flush=True)
