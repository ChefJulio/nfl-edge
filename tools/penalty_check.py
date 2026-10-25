"""(PB) the penalty rules table against real plays (pre-registered 2026-10-25, docs/INSIGHTS.md).

(A) the penalty branch (nfledge/penalties.penalty_branch) on ACCEPTED fouls; (B) the play branch (play_branch) on
DECLINED fouls; the truth is the next snap (same team with the ball, same down, yards to the end zone and to go within
1). Rules are built on 2022-23 (the default run); the gate reads 2024-25 (--gate), untouched until the rules are frozen.

  python tools/penalty_check.py [--misses=N]        development: 2022-23, per unit, sample misses
  python tools/penalty_check.py --gate               the pre-registered gate on 2024-25

GATE: (A) units (foul x side x play kind) with 20+ accepted fouls that match 95%+ are in scope; PASS if they cover 70%+
of the declined fouls in scope; (B) 95%+ of the declined fouls match.

Rule changes after a first look at 2022-23 (logged as the procedure requires; first look: (A) 0.915 match, units
in scope cover 0.546 of declines; (B) 0.996):
  1. Delay of Game / Defensive Delay of Game after a play: dead-ball fouls after it, from where it ended (14-4-9).
  2. Unnecessary Roughness: mostly late hits, a dead-ball foul from where the play ended, which stands (14-2-4).
  3. An offense's dead-ball foul after earning a first down: 1st & 10 from the new spot (14-4-9), not 1st & 25.
  4. Illegal Contact on a run (a scramble): the run's basic spot (14-3-6), not the previous spot.
  5. Illegal Touch Pass: loss of down, no yards (8-1-8).
  6. Spot rounding (penalties.near_line): a defensive foul without an automatic first down whose yards are within 1
     of the yards to go is rebuilt both ways (first down / short of it); a match if either is the next snap.
  7. Kicking plays left out of parse() (the first run had read punt returns as runs).
  8. The offense's holding / blocking / personal fouls on a completion that gained: unknown spot (the foul may come
     after the catch, in the run that follows: three-and-one, 14-3-6); seen as 86% on completions vs 100% elsewhere.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

from nfledge import penalties as P  # noqa: E402

COLS = ["game_id", "play_id", "season", "season_type", "qtr", "posteam", "defteam", "down", "ydstogo", "yardline_100",
        "desc", "timeout", "play_type"]
EVENT = r"INTERCEPTED|FUMBLES|TOUCHDOWN|SAFETY|BLOCKED|recovered"


def rows(seasons) -> pd.DataFrame:
  """Single fouls during scrimmage plays, with the state at the snap and the next snap."""
  d = pd.concat([pd.read_parquet(ROOT / "cache" / f"pbp_calc_{s}.parquet", columns=COLS) for s in seasons], ignore_index=True)
  d = d[d.season_type == "REG"].sort_values(["game_id", "play_id"]).reset_index(drop=True)
  snap = d[d.down.notna() & d.posteam.notna() & (d.timeout != 1)].copy()
  nxt = snap.groupby("game_id")[["posteam", "down", "ydstogo", "yardline_100", "qtr"]].shift(-1)
  snap = snap.join(nxt.add_prefix("n_"))
  x = snap[snap.desc.str.contains(r"(?i)penalty on", na=False) & ~snap.desc.str.contains(EVENT, na=False)
           & (snap.qtr <= 4) & snap.n_down.notna()]
  # not at a half's end (the next snap is a new half: the state resets)
  x = x[~((x.n_qtr != x.qtr) & x.qtr.isin([2, 4]))]
  out = []
  for r in x.itertuples():
    p = P.parse(r.desc)
    if not p or p["kind"] is None or p["foul"] not in P.FOULS:
      continue
    side = "offense" if p["team"] == r.posteam else "defense" if p["team"] == r.defteam else None
    if side is None:
      continue
    out.append({"season": r.season, "desc": r.desc, "foul": p["foul"], "side": side, "kind": p["kind"], "gain": p["gain"],
                "declined": p["declined"], "down": int(r.down), "togo": float(r.ydstogo), "yl": float(r.yardline_100),
                "same": r.n_posteam == r.posteam, "n_down": int(r.n_down), "n_togo": float(r.n_ydstogo),
                "n_yl": float(r.n_yardline_100)})
  return pd.DataFrame(out)


def match(bs: list, r) -> bool | None:
  """Any of the rebuilt branches (two when the spot rounding is ambiguous: penalties.near_line) is the next snap."""
  if not bs:
    return None
  return any((b["ball"] == "same") == r.same and b["down"] == r.n_down and abs(b["yl"] - r.n_yl) <= 1
             and abs(b["togo"] - r.n_togo) <= 1 for b in bs)


def check(t: pd.DataFrame) -> pd.DataFrame:
  res = []
  for r in t.itertuples():
    st, play = {"down": r.down, "togo": r.togo, "yl": r.yl}, {"kind": r.kind, "gain": r.gain}
    bs = [P.play_branch(st, play)] if r.declined else P.penalty_branches(st, r.foul, r.side, play)
    res.append({"unit": P.unit(r.foul, r.side, play), "punit": P.path_unit(st, r.foul, r.side, play),
                "ok": match(bs, r), "pred": bs})
  return t.join(pd.DataFrame(res, index=t.index))


def main():
  opt = dict((a[2:].split("=", 1) + [""])[:2] for a in sys.argv[1:] if a.startswith("--"))
  gate = "gate" in opt
  seasons = [2024, 2025] if gate else [2022, 2023]
  t = check(rows(seasons))
  acc, dec = t[~t.declined], t[t.declined]
  print(f"[pb] {'GATE' if gate else 'development'} {seasons[0]}-{seasons[-1]}: {len(acc):,} accepted, {len(dec):,} declined single fouls in scope")
  # (A) the penalty branch, by unit: the amended units decide (foul x side x how enforced); the pre-registered
  # ones (foul x side x play kind) are reported alongside
  a = acc[acc.ok.notna()]
  out_of_table = acc.ok.isna().sum()
  print(f"\n(A) penalty branch on accepted fouls: {a.ok.mean():.3f} match over {len(a):,} ({out_of_table:,} with no spot in the text: out of scope)")
  res = {}
  for col, lab in [("unit", "pre-registered units (foul x side x play kind)"), ("punit", "amended units (foul x side x how enforced)")]:
    u = a.groupby(col).ok.agg(n="size", rate="mean")
    u["scope"] = (u.n >= 20) & (u.rate >= 0.95)
    inn = set(u[u.scope].index)
    covered = dec[col].isin(inn).mean()
    res[col] = covered >= 0.70
    print(f"\n(A) {lab}: {len(inn)} in scope; they cover {covered:.3f} of the declined fouls -> {res[col]}")
    print(u[u.n >= 10].sort_values("n", ascending=False).round(3).to_string())
    print("  declined fouls by unit (top 12):")
    print(dec[col].value_counts().head(12).to_string())
  ga = res["punit"]
  # (B) the play branch
  gb_rate = dec.ok.mean()
  gb = gb_rate >= 0.95
  print(f"\n(B) play branch on declined fouls: {gb_rate:.3f} match over {len(dec):,} -> {gb}")
  if not gate:
    n = int(opt.get("misses") or 4)
    for lab, g in [("A", a[a.ok == False]), ("B", dec[dec.ok == False])]:  # noqa: E712
      print(f"\n-- ({lab}) misses by unit (sample)")
      for un, gg in list(g.groupby("unit"))[:40]:
        for r in gg.head(n).itertuples():
          print(f"  [{un}] {r.down}&{r.togo:g} at {r.yl:g} -> next {r.n_down}&{r.n_togo:g} at {r.n_yl:g} ({'same' if r.same else 'other'}) "
                f"pred {r.pred}\n     {r.desc[:170]}")
  else:
    print(f"\n[pb] GATE (amended units): (A) {ga}  (B) {gb}  -> {'PASS' if ga and gb else 'FAIL'}"
          f"   (pre-registered units: (A) {res['unit']} -> {'PASS' if res['unit'] and gb else 'FAIL'})")


if __name__ == "__main__":
  main()
