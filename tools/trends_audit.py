"""Audit Players > Trends against nflverse's official season totals (owner 2026-10-22: "assuming any potential audit
passes, pretty nice free tool").

Drives the real page (Playwright, WebKit) for every season: one leaderboard per family (rushing, receiving, passing),
regular season, every player, no minimum, read through the page's own "Download CSV" (matched on its Player ID
column). Compares with nflverse player stats (summary_level="reg"), after the documented definition differences:
  - QB kneels (play type qb_kneel) are carries in the official stats; Trends leaves them out: carries / rushing yards
    are compared net of each player's kneels.
  - Spikes (qb_spike) are pass attempts in the official stats; Trends leaves them out: attempts net of spikes.
  - nflverse's season table has impossible target counts in older seasons (Wes Welker 2008: 0 targets in games with
    6-12 catches; its play-by-play has 113): a target count below the catch count is skipped and counted, not compared.
Everything else should match exactly; any difference is listed.

  python tools/trends_audit.py [--url=http://127.0.0.1:8765/] [--seasons=1999-2025] [--out=scratch/trends_audit.md]
"""
import csv
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import nflreadpy as nfl  # noqa: E402
import pandas as pd  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

FAMS = {  # family: (metric to query, {official column: Trends CSV column})
  "rush": ("yds", {"carries": "Rushes", "rushing_yards": "Yards", "rushing_tds": "TDs"}),
  "rec": ("yds", {"targets": "Targets", "receptions": "Catches", "receiving_yards": "Yards", "receiving_tds": "TDs"}),
  "pass": ("att", {"attempts": "Attempts", "passing_yards": "Yards", "passing_tds": "TDs", "passing_interceptions": "INTs"}),
}
PBP_COLS = ["season_type", "play_type", "rusher_player_id", "passer_player_id", "yards_gained"]


def trends_csv(pg, url: str, fam: str, met: str, season: int) -> pd.DataFrame:
  q = {"fam": fam, "met": met, "who": "L", "wn": "", "by": "player", "by2": "", "st": "reg", "from": season, "to": season,
       "f": {}, "fn": {}, "min": 0, "gt": None, "gn": 4}
  pg.goto(url)
  pg.evaluate(f"localStorage.setItem('nfledge-trends', {json.dumps(json.dumps(q))})")
  pg.goto(url + "#players/trends")
  pg.reload()
  pg.wait_for_function("() => { const b = document.querySelector('.tr-base'); return b && /^(League|No )/.test(b.textContent) && document.querySelector('table.dt'); }",
                       timeout=120000)
  with pg.expect_download() as d:
    pg.click("[data-csv]")
  text = Path(d.value.path()).read_text(encoding="utf-8-sig")
  rows = list(csv.reader(io.StringIO(text)))[1:]  # line 1 is the question
  return pd.DataFrame(rows[1:], columns=rows[0])


def adjustments(season: int) -> tuple[pd.Series, pd.Series, pd.Series]:
  """Per player: kneel carries, kneel yards, spikes (regular season)."""
  f = ROOT / "cache" / f"pbp_{season}.parquet"
  try:
    p = pd.read_parquet(f, columns=PBP_COLS) if f.exists() else None
  except Exception:
    p = None
  if p is None:
    p = nfl.load_pbp([season]).select(PBP_COLS).to_pandas()
  p = p[p.season_type == "REG"]
  k = p[p.play_type == "qb_kneel"].groupby("rusher_player_id")
  return k.size(), k.yards_gained.sum(), p[p.play_type == "qb_spike"].groupby("passer_player_id").size()


def main():
  opt = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
  url = opt.get("url", "http://127.0.0.1:8765/")
  a, _, b = opt.get("seasons", "1999-2025").partition("-")
  seasons = list(range(int(a), int(b or a) + 1))
  out = Path(opt.get("out", ROOT / "scratch" / "trends_audit.md"))
  off = nfl.load_player_stats(seasons, summary_level="reg").to_pandas()
  names = dict(zip(off.player_id, off.player_display_name))
  results, worst, missing, skipped = {}, [], [], {}
  with sync_playwright() as pw:
    br = pw.webkit.launch()
    pg = br.new_context(accept_downloads=True).new_page()
    for s in seasons:
      kn_n, kn_y, spk = adjustments(s)
      o = off[off.season == s].set_index("player_id")
      for fam, (met, cols) in FAMS.items():
        t = trends_csv(pg, url, fam, met, s).set_index("Player ID")
        first = next(iter(cols))
        adj = o.copy()  # official totals net of kneels / spikes; a player whose only carries were kneels drops out
        adj["carries"] = adj.carries.fillna(0) - kn_n.reindex(adj.index).fillna(0)
        adj["rushing_yards"] = adj.rushing_yards.fillna(0) - kn_y.reindex(adj.index).fillna(0)
        adj["attempts"] = adj.attempts.fillna(0) - spk.reindex(adj.index).fillna(0)
        want = adj[adj[first].fillna(0) > 0]
        tc0 = cols[first]
        active = t[pd.to_numeric(t[tc0].astype(str).str.replace(",", ""), errors="coerce").fillna(0) > 0]  # e.g. a dropback, no attempt
        for pid in set(want.index) ^ set(active.index):
          side = "official only" if pid in want.index else "Trends only"
          missing.append((s, fam, pid, names.get(pid, t.Player.get(pid, pid) if pid in t.index else pid), side))
        both = want.index.intersection(t.index)
        for oc, tc in cols.items():
          ok = both
          if oc == "targets":  # the official count is impossible: below the catches
            bad = want.loc[both, "targets"].fillna(0) < want.loc[both, "receptions"].fillna(0)
            skipped[s] = skipped.get(s, 0) + int(bad.sum())
            ok = both[~bad.to_numpy()]
          exp = want.loc[ok, oc].fillna(0).astype(float)
          got = pd.to_numeric(t.loc[ok, tc].astype(str).str.replace(",", ""), errors="coerce").fillna(0)
          d = got - exp
          r = results.setdefault((fam, tc), {"n": 0, "exact": 0, "within1": 0, "sum_off": 0.0, "sum_trends": 0.0})
          r["n"] += len(d); r["exact"] += int((d == 0).sum()); r["within1"] += int((d.abs() <= 1).sum())
          r["sum_off"] += float(exp.sum()); r["sum_trends"] += float(got.sum())
          worst += [(abs(v), s, fam, tc, pid, names.get(pid, pid), float(got[pid]), float(exp[pid])) for pid, v in d.items() if v != 0]
        print(f"[audit] {s} {fam}: {len(both)} players matched", flush=True)
    br.close()
  worst.sort(reverse=True)
  lines = ["# Trends audit vs nflverse official season totals", "",
           f"Seasons {seasons[0]}-{seasons[-1]}, regular season. Kneels / spikes netted out of carries / attempts (see tools/trends_audit.py).", "",
           "| Family | Stat | Player-seasons | Exact | Within 1 | Official total | Trends total |", "|---|---|---|---|---|---|---|"]
  for (fam, tc), r in results.items():
    lines.append(f"| {fam} | {tc} | {r['n']:,} | {100 * r['exact'] / max(1, r['n']):.2f}% | {100 * r['within1'] / max(1, r['n']):.2f}% | {r['sum_off']:,.0f} | {r['sum_trends']:,.0f} |")
  if skipped:
    lines += ["", f"Targets not compared where nflverse's season table has fewer targets than catches: {sum(skipped.values()):,} player-seasons "
              f"({', '.join(f'{k}: {v}' for k, v in sorted(skipped.items()) if v)})."]
  lines += ["", f"## Largest differences ({len(worst)} player-season-stats differ)", "",
            "| Season | Family | Stat | Player | Trends | Official (adj.) |", "|---|---|---|---|---|---|"]
  lines += [f"| {s} | {fam} | {tc} | {nm} ({pid}) | {g:,.0f} | {e:,.0f} |" for _, s, fam, tc, pid, nm, g, e in worst[:40]]
  lines += ["", f"## In one list only ({len(missing)})", ""]
  by = pd.DataFrame(missing, columns=["season", "fam", "pid", "name", "side"]) if missing else None
  if by is not None:
    lines.append(by.groupby(["fam", "side"]).size().to_string())
    lines += ["", "| Season | Family | Player | Side |", "|---|---|---|---|"]
    lines += [f"| {r.season} | {r.fam} | {r.name} ({r.pid}) | {r.side} |" for r in by.head(40).itertuples()]
  out.write_text("\n".join(lines) + "\n", encoding="utf-8")
  print("\n".join(lines[:4 + len(results) + 2]))
  print(f"[audit] report: {out}")


if __name__ == "__main__":
  main()
