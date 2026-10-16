"""Machine-readable copies of the site (owner 2026-10-16: "can we serve the model page, or the entire site, in a way
that's scrapeable?"). The app renders everything in the browser behind #hash routes, so a crawler or an LLM that
fetches a URL sees an empty frame. Each current-week build also writes, at the site root:

  llms.txt          what the site is + links to everything below and to the raw JSON files (llmstxt.org format)
  model.md          the Model tab as Markdown: MODEL.md with this build's live values + both track records
  model/index.html  the same as a static page (no JavaScript), for ordinary crawlers
  rankings.md       this week's projections, one Markdown table per position

Everything comes from the same sources as the app (MODEL.md, the week's JSON, the committed track records), so the
copies can't disagree with it.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

import markdown

POS = ("QB", "RB", "WR", "TE")
DEPTH = {"QB": 40, "RB": 80, "WR": 100, "TE": 40}


def _avail_md(a: dict | None) -> str:
  if not a:
    return ""
  out = ["## How accurate is our inactive %? (track record)", "",
         f"Each season ({a['seasons']}) predicted by models trained only on earlier seasons; QB / RB / WR / TE; players "
         "ruled Out left out (0% by rule). Error = Brier score (average squared miss; lower is better).", "",
         "| Final injury report, read as | Error |", "|---|---|"]
  out += [f"| {v['label']}{' **(this site)**' if v.get('ours') else ''} | {v['brier']:.3f} |" for v in a["versus"]]
  out += ["", "| When | Error | Wrong call (did the opposite of our lean) |", "|---|---|---|"]
  out += [f"| {s['label']} | {s['brier']:.3f} | {s['wrong']}% |" for s in a["stages"]]
  out += ["", "Calibration: when we gave a chance in this band, how often those players played.", "",
          "| We said | Players | Our average | Played |", "|---|---|---|---|"]
  out += [f"| {c['band']} | {c['n']:,} | {c['predicted']}% | {c['played']}% |" for c in a["calib"]]
  out += ["", "| When | Situation | Players | Played | We said |", "|---|---|---|---|---|"]
  out += [f"| {s['when']} | {s['label']} | {s['n']:,} | {s['played']}% | {s['predicted']}% |" for s in a["spots"]]
  return "\n".join(out) + "\n"


def _fav_md(t: dict | None) -> str:
  if not t:
    return ""
  out = ["## How often favorites win (track record)", "",
         f"Market chances, {t['since']}-{t['season']}; each season scored with chances fit only on the seasons before it.", "",
         f"| Favorite's chance | Games | Expected | Won | {t['season']} |", "|---|---|---|---|---|"]
  for r in t["rows"]:
    now = f"{round(r['actual_now'])}% of {r['n_now']}" if r.get("n_now") else "-"
    out.append(f"| {r['label']} | {r['n']} | {round(r['expected'])}% | {round(r['actual'])}% | {now} |")
  return "\n".join(out) + "\n"


def model_md(body_md: str, avail: dict | None, track: dict | None, base: str, generated: str) -> str:
  head = (f"<!-- NFL Edge model description, generated {generated}. App: {base} ; this file: {base}model.md -->\n\n")
  return head + body_md.strip() + "\n\n" + _avail_md(avail) + "\n" + _fav_md(track)


def model_page(md: str, base: str, generated: str) -> str:
  body = markdown.markdown(md, extensions=["tables", "sane_lists"])
  return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>How the NFL Edge model works</title>
<meta name="description" content="How every number on NFL Edge is calculated: projections, inactive chances, game lines, playoff odds, grades, and what was tested and rejected.">
<link rel="alternate" type="text/markdown" href="{base}model.md">
<style>body{{margin:0;background:#0d0f13;color:#e9ecf0;font:16px/1.6 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
main{{max-width:860px;margin:0 auto;padding:24px 16px 64px}}a{{color:#6d9eff}}h1,h2,h3{{line-height:1.25}}
table{{border-collapse:collapse;width:100%;font-size:14px;display:block;overflow-x:auto}}th,td{{border-bottom:1px solid #262b33;padding:6px 8px;text-align:left;vertical-align:top}}
th{{color:#98a0ab;font-size:12px;text-transform:uppercase;letter-spacing:.04em}}code{{background:#1a1e24;padding:1px 4px;border-radius:4px}}</style></head>
<body><main><p><a href="{base}">&larr; NFL Edge (the app)</a> &middot; <a href="{base}model.md">Markdown</a> &middot; <a href="{base}llms.txt">llms.txt</a> &middot; generated {html.escape(generated)}</p>
{body}</main></body></html>
"""


def rankings_md(week: dict, base: str) -> str:
  ps = list(week.get("players", {}).values())
  out = [f"# NFL Edge weekly rankings: {week['season']} week {week['week']}", "",
         f"Generated {week.get('generated', '')}. Projected fantasy points in half-PPR scoring, IF the player plays (the "
         "chance he doesn't is the Inactive column; under 10% to play shows as likely out). Range = 10th-90th percentile "
         f"outcome. Full data: {base}index.json ; method: {base}model.md", ""]
  for pos in POS:
    # as the app ranks them: by projection, near-certain outs (under 10% to play) after everyone else
    rows = sorted((p for p in ps if p.get("pos") == pos and p.get("rank")),
                  key=lambda p: ((p.get("inactive") or 0) >= 0.9, -p["proj"]))[:DEPTH[pos]]
    if not rows:
      continue
    out += [f"## {pos}", "", "| Rank | Player | Team | Opp | Proj | Range | Inactive | Status |", "|---|---|---|---|---|---|---|---|"]
    for i, p in enumerate(rows, 1):
      q = p.get("q") or [None] * 5
      rng = f"{q[0]:.0f}-{q[4]:.0f}" if q[0] is not None and q[4] is not None else ""
      ina = p.get("inactive") or 0.0
      opp = (("" if p.get("home") else "@") + p["opp"]) if p.get("opp") else "bye"
      st = (p.get("status") or "").replace("|", "/").strip()
      out.append(f"| {i} | {p['name']} | {p.get('team', '')} | {opp} | {p['proj']:.1f}{' (likely out)' if ina >= 0.9 else ''} | "
                 f"{rng} | {round(100 * ina)}% | {st} |")
    out.append("")
  return "\n".join(out)


def power_md(week: dict, base: str) -> str:
  rows = week.get("power") or []
  sg = lambda v: "" if v is None else f"{v:+.1f}"  # noqa: E731
  out = [f"# NFL Edge power rankings: {week['season']} week {week['week']}", "",
         "Rank and Net = how good each team is from here on: opponent-adjusted points per game vs an average team over "
         "its remaining games, an injured starting QB counted by his chance to be back each week. This week = the same "
         "rating with this week's starter. Offense + Defense + ST = Net. Rank range = 10th-90th percentile rank over "
         f"4,000 simulations. Method: {base}model.md (Games).", "",
         "| Rank | Team | Record | Net | This week (rank) | Offense | Defense | ST | Rank range | QB note |", "|---|---|---|---|---|---|---|---|---|---|"]
  for r in rows:
    out.append(f"| {r['rank']} | {r['team']} {r.get('nick', '')} | {r.get('record', '')} | {sg(r.get('net'))} | "
               f"{sg(r.get('net_now'))} ({r.get('rank_now', '')}) | {sg(r.get('off'))} | {sg(r.get('def'))} | {sg(r.get('st'))} | "
               f"{r.get('range', '')} | {r.get('qb_note', '')} |")
  return "\n".join(out) + "\n"


def games_md(week: dict, base: str) -> str:
  out = [f"# NFL Edge games: {week['season']} week {week['week']}", "",
         "Market chance = from the Vegas spread when posted; our model = power rank gap + Elo + home field "
         f"(method: {base}model.md, Games).", "",
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


def llms_txt(base: str, season: int, week: int, generated: str) -> str:
  return f"""# NFL Edge

> Free NFL fantasy football analytics, rebuilt from public data every day: weekly player projections with ranges and
> touchdown odds, each player's chance to be inactive (injury report, practice, healthy scratches), game win chances
> and lines, team power ratings, playoff odds and rooting guides, player grades, kicker and defense projections.
> Every model change is tested on past seasons (each season predicted only from earlier ones) against a pass bar
> written down before the results; failures are kept and published.

Current week: {season} week {week} (generated {generated}). The app ({base}) renders in the browser; the links below
are the same content in plain text and JSON.

## Read these first

- [How the model works (Markdown)]({base}model.md): every number on the site, by area (projections, inactive %,
  games, playoffs, grades, kickers and defenses), what was tested and rejected, and accuracy track records
- [How the model works (static HTML)]({base}model/): the same, as a web page without JavaScript
- [This week's rankings (Markdown)]({base}rankings.md): projections per position with ranges and inactive chances
- [Power rankings (Markdown)]({base}power.md): every team's rest-of-season and this-week rating, units, rank range
- [This week's games (Markdown)]({base}games.md): kickoff, QBs, Vegas line and total, market and model chances, finals
- [Lab notebook (Markdown)]({base}notebook.md): every test as it happened, with its pass bar written before the result
  (also on GitHub: https://github.com/ChefJulio/nfl-edge/blob/main/docs/INSIGHTS.md)
- [Source code](https://github.com/ChefJulio/nfl-edge)

## Data (JSON)

- [{base}index.json]({base}index.json): this week: players (projection, stat line, range quantiles, inactive chance
  and why, matchup, status), games (lines, win chances, battle bars), teams, power ratings, roles
- [{base}weeks.json]({base}weeks.json): every built week (season -> week -> page); each page's data is the same path
  with .json; the current week is also at {season}/week-{week:02d}.json (same file as index.json). The Markdown files
  above are small enough for one fetch; index.json (~550 KB) is not, for some fetchers.
- [{base}data/ros.json]({base}data/ros.json): rest of season, per player and week: expected stat line if active,
  chance to play, opponent
- [{base}data/kdst.json]({base}data/kdst.json): kicker and team-defense expected stat lines this week through week 17
- [{base}data/playoffs/odds.json]({base}data/playoffs/odds.json): playoff, division, bye and title odds per team,
  rooting guide, odds history, track record
- [{base}data/model.json]({base}data/model.json): the Model tab as rendered HTML + track records
- {base}data/players/<gsis_id>.json: one player's career game log (gsis ids are nflverse's, e.g. 00-0034857)
- {base}data/teams/<TEAM>.json: one team's game log (team codes as nflverse, e.g. BUF, LA)
"""


def write(root: Path, body_md: str, avail: dict | None, track: dict | None, week_json: str, base: str, generated: str) -> None:
  week = json.loads(week_json)
  md = model_md(body_md, avail, track, base, generated)
  (root / "model.md").write_text(md, encoding="utf-8")
  (root / "model").mkdir(exist_ok=True)
  (root / "model" / "index.html").write_text(model_page(md, base, generated), encoding="utf-8")
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
  (root / "llms.txt").write_text(llms_txt(base, int(week["season"]), int(week["week"]), generated), encoding="utf-8")
