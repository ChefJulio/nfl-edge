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
         "its remaining games, an injured starting QB counted by his chance to be back each week. This week = the same "
         "rating with this week's starter. Offense + Defense + ST = Net. Rank range = 10th-90th percentile rank over "
         f"4,000 simulations. Method: {base}model/games.md", "",
         "| Rank | Team | Record | Net | This week (rank) | Offense | Defense | ST | Rank range | QB note |", "|---|---|---|---|---|---|---|---|---|---|"]
  for r in rows:
    out.append(f"| {r['rank']} | {r['team']} {r.get('nick', '')} | {r.get('record', '')} | {sg(r.get('net'))} | "
               f"{sg(r.get('net_now'))} ({r.get('rank_now', '')}) | {sg(r.get('off'))} | {sg(r.get('def'))} | {sg(r.get('st'))} | "
               f"{r.get('range', '')} | {r.get('qb_note', '')} |")
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


def llms_txt(base: str, season: int, week: int, generated: str, area_files: list[tuple[str, str, int]],
             sizes: dict[str, int]) -> str:
  ar = "\n".join(f"  - [{t}]({base}model/{s}.md) ({_kb(n)})" for t, s, n in area_files)
  return f"""# NFL Edge

> Free NFL fantasy football analytics, rebuilt from public data every day: weekly player projections with ranges and
> touchdown odds, each player's chance to play (injury risk from the injury report and practice, and healthy-scratch
> risk, shown separately), game win chances and lines, team power ratings, playoff odds and rooting guides, player
> grades and durability, kicker and defense projections, live gamecasts, and fantasy league tools (Sleeper, ESPN).
> Stats and game logs cover offensive players, kickers, team defenses and individual defenders.
> Every model change is tested on past seasons (each season predicted only from earlier ones) against a pass bar
> written down before the results; failures are kept and published.

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
- [Lab notebook (Markdown)]({base}notebook.md) ({_kb(sizes.get('notebook.md', 0))}, too big for some fetchers in one
  go; the per-area model files above summarize each test): every test as it happened, with its pass bar written before
  the result (also on GitHub: https://github.com/ChefJulio/nfl-edge/blob/main/docs/INSIGHTS.md)
- [Source code](https://github.com/ChefJulio/nfl-edge)

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
