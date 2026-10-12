"""The Model tab: MODEL.md rendered with live values, plus the staleness check that keeps it honest.

MODEL.md carries `documented_code_hash` in its front matter: a fingerprint of the model code (nfledge/*.py except
presentation modules) and config.toml. When the fingerprint no longer matches, the doc is stale:
- git pre-commit hook (.githooks/pre-commit) blocks the commit,
- the GitHub build emits a warning,
- the Model tab shows an "out of date" banner.
After reviewing / updating MODEL.md, run `python tools/model_doc.py --stamp`.
"""
from __future__ import annotations

import hashlib
import re

import markdown
import numpy as np
import pandas as pd
from jinja2 import Environment, StrictUndefined

from .config import ROOT

DOC = ROOT / "MODEL.md"
PRESENTATION = {"report.py", "docs.py"}  # changes here never change model outputs


def code_fingerprint() -> str:
  parts = [p.read_text(encoding="utf-8") for p in sorted((ROOT / "nfledge").glob("*.py")) if p.name not in PRESENTATION]
  parts.append((ROOT / "config.toml").read_text(encoding="utf-8"))
  return hashlib.sha1("\n".join(parts).replace("\r\n", "\n").encode()).hexdigest()[:16]


def _split() -> tuple[dict, str]:
  text = DOC.read_text(encoding="utf-8")
  m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
  meta = dict(re.findall(r"^(\w+):\s*(.*)$", m.group(1), re.M)) if m else {}
  return meta, text[m.end():] if m else text


def is_stale() -> bool:
  return _split()[0].get("documented_code_hash") != code_fingerprint()


def stamp():
  text = DOC.read_text(encoding="utf-8")
  new = re.sub(r"documented_code_hash:.*", f"documented_code_hash: {code_fingerprint()}", text, count=1)
  DOC.write_text(new, encoding="utf-8")


# ----------------------------------------------------------------------------------------------------------------
# Live values
# ----------------------------------------------------------------------------------------------------------------

def _p100(x) -> str:
  return f"{100 * float(x):+.1f}"


def live_values(eng, cfg: dict, season: int, week: int, bt_res: pd.DataFrame | None, ev: pd.DataFrame | None) -> dict:
  tmc, pmc = cfg["team_model"], cfg["player_model"]
  r = eng.tm.fit(season, week)
  names = eng.data.rosters.drop_duplicates("gsis_id").set_index("gsis_id").full_name
  top = ""
  if r.qb is not None and r.qb_prior is not None:
    q = r.qb[r.qb.index.isin(r.qb_prior.index)].sort_values(ascending=False).head(5)
    top = ", ".join(f"{names.get(k, k)} ({_p100(v)})" for k, v in q.items())
  k = eng.pm.prior.k
  pts = eng.gm.points.coef
  blend = "; ".join(f"{pos} {m.coef[1]:.2f} × model + {m.coef[2]:.2f} × experts" for pos, m in sorted(eng.blend.items()))
  cov = "n/a"
  if bt_res is not None and "p10" in bt_res:
    d = bt_res[bt_res.played & bt_res.p10.notna() & (bt_res.proj >= 3)]
    if len(d):
      cov = f"{100 * d.actual.between(d.p10, d.p90).mean():.0f}%"
  return {
    "seasons": f"{min(eng.data.seasons)}-{max(eng.data.seasons)}",
    "wp_min": f"{tmc['wp_min']:.0%}", "wp_max": f"{tmc['wp_max']:.0%}",
    "alpha_pass": f"{eng.tm.alphas['pass']:g}", "alpha_rush": f"{eng.tm.alphas['rush']:g}",
    "alpha_st": f"{eng.tm.alphas['st']:g}", "alpha_qb": f"{eng.tm.alpha_qb:g}",
    "hl_team": f"{tmc['half_life_weeks']:g}", "hl_share": f"{pmc['share_half_life_weeks']:g}",
    "prior_weight": f"{tmc['prior_weight']:g}", "prior_decay": f"{tmc['prior_decay_week']}",
    "qb_cut": f"{tmc.get('qb_inexp_dropbacks', 150):g}", "qb_inexp": _p100(r.qb_inexp), "top_qbs": top or "n/a",
    "home_pass": _p100(r.home["pass"]), "home_rush": _p100(r.home["rush"]),
    "bootstrap": f"{tmc['bootstrap_samples']}",
    "points_model": f"points ≈ {pts[0]:.1f} + {pts[1]:.2f} × offensive EPA per game + {pts[2]:.2f} × special-teams edge",
    "margin_disagree": f"{cfg['report']['margin_disagree']:g}", "total_disagree": f"{cfg['report']['total_disagree']:g}",
    "k_wr_catch": f"{k.get(('tgt', 'WR', 'reception'), float('nan')):.0f}",
    "k_wr_ypt": f"{k.get(('tgt', 'WR', 'rec_yd'), float('nan')):.0f}",
    "k_rb_ypc": f"{k.get(('rush', 'RB', 'rush_yd'), float('nan')):.0f}",
    "td_k": f"{pmc['td_blend_k']}", "n_eff_models": f"{len(eng.pm.eff_models)}",
    "wind_thr": f"{pmc['wind_threshold_mph']}", "wind_pen": f"{pmc['wind_penalty_per_mph']:.0%}",
    "wind_cap": f"{pmc['wind_penalty_cap']:.0%}", "blend": blend or "n/a", "coverage": cov,
    "redist_scale": f"{cfg.get('injuries', {}).get('redistribution_scale', 1.0):g}",
    "tiers_qb": " / ".join(map(str, cfg["tiers"]["QB"])),
    "snap_jump": f"{pmc['role_change_snap_jump']:.0%}", "opp_jump": f"{pmc['role_change_opp_jump']:.0%}",
    "bt_table": _bt_table(ev),
    "formulas": formulas(eng, season, week),
  }


def _bt_table(ev: pd.DataFrame | None) -> str:
  if ev is None or ev.empty:
    return "_Backtest not run for this build._"
  ev = ev[ev.subset == "relevant"]
  rows = ["| Position | Avg miss: model | experts | Vegas-scaled | raw | Rank corr.: model | experts |",
          "|---|---|---|---|---|---|---|"]
  for _, x in ev.iterrows():
    rows.append(f"| {x.pos} | **{x.mae_model:.2f}** | {x.get('mae_ecr', np.nan):.2f} | {x.mae_vegas:.2f} | "
                f"{x.mae_raw:.2f} | **{x.rank_model:.3f}** | {x.get('rank_ecr', np.nan):.3f} |")
  return "\n".join(rows)


RAW = {"bt_table", "formulas"}  # generated markdown blocks, inserted as-is


def render(live: dict) -> dict:
  """MODEL.md -> HTML with live values (StrictUndefined: a missing value fails the build, never shows blank)."""
  _, body = _split()
  env = Environment(undefined=StrictUndefined, autoescape=False)
  filled = env.from_string(body).render(L={k: f"<span class=\"live\">{v}</span>" if k not in RAW else v
                                          for k, v in live.items()})
  html = markdown.markdown(filled, extensions=["tables", "sane_lists"])
  toc, n = [], 0

  def anchor(m):
    nonlocal n
    n += 1
    title = re.sub(r"<[^>]+>", "", m.group(1))
    toc.append({"id": f"m{n}", "title": title})
    return f'<h2 id="m{n}">{m.group(1)}</h2>'

  html = re.sub(r"<h2>(.*?)</h2>", anchor, html)
  return {"html": html, "toc": toc, "stale": is_stale()}


# ----------------------------------------------------------------------------------------------------------------
# Formulas and fitted weights (generated from the trained model on every build)
# ----------------------------------------------------------------------------------------------------------------

FEATURE_NAMES = {
  "pace": "team pace (plays/game)", "opp_pace_allowed": "opponent plays allowed/game", "total_line": "Vegas total",
  "spread_team": "Vegas spread (+ = favored)", "proe_team": "team pass rate over expected",
  "pass_rate_team": "team pass rate", "off_epa_game": "expected offensive EPA per game",
  "st_net": "special-teams EPA edge per game", "implied_pts": "Vegas implied team total",
  "home": "home (+1) / away (-1)", "def_pass": "opponent pass-defense rating", "def_rush": "opponent run-defense rating",
  "off_pass": "own pass offense incl. QB", "off_rush": "own run offense", "adot": "average depth of target",
  "snap_pct": "snap share",
}
OPP_LABEL = {"db": "dropback", "rush": "rush attempt", "tgt": "target"}
STAT_LABEL = {"pass_yd": "pass yards", "pass_td": "pass TDs", "interception": "interceptions", "rush_yd": "rush yards",
              "rush_td": "rush TDs", "reception": "catches", "rec_yd": "receiving yards", "rec_td": "receiving TDs"}


def _f(x, d=3) -> str:
  return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:+.{d}f}"


def _eq(lhs: str, lin, names=None, d=3) -> str:
  names = names or {}
  terms = [f"{lin.coef[0]:.{d}f}"] + [f"{b:+.{d}f} × {names.get(c, FEATURE_NAMES.get(c, c))}"
                                      for c, b in zip(lin.cols, lin.coef[1:])]
  return f"`{lhs} = " + " ".join(terms) + "`"


def formulas(eng, season: int, week: int) -> str:
  r = eng.tm.fit(season, week)
  names = eng.data.rosters.drop_duplicates("gsis_id").set_index("gsis_id").full_name
  out = []
  add = out.append

  # --- team model -----------------------------------------------------------------------------------------------
  add("### 10.1 Team ratings (ridge regression on play EPA)")
  add("For each unit u (pass, rush, special teams), with play weights w (recency x prior-season decay):")
  add("`EPA_play = a_u + O[offense] + D[defense] + Q[passer] (pass only) + I x inexperienced QB (pass only) + H_u x home`")
  add("solved by minimizing `sum w (EPA - prediction)^2 + alpha_u (sum O^2 + sum D^2 + H^2) + alpha_QB sum Q^2 + 1.0 x I^2`.")
  add("| Unit | Intercept a (EPA/play) | Home edge H (per 100 plays) | alpha (teams) | alpha (QBs) |")
  add("|---|---|---|---|---|")
  for u in ("pass", "rush", "st"):
    add(f"| {u} | {r.intercept[u]:+.4f} | {100 * r.home[u]:+.2f} | {eng.tm.alphas[u]:g} | "
        f"{eng.tm.alpha_qb:g} |" if u == "pass" else
        f"| {u} | {r.intercept[u]:+.4f} | {100 * r.home[u]:+.2f} | {eng.tm.alphas[u]:g} | - |")
  add(f"Inexperienced-QB effect I = **{100 * r.qb_inexp:+.2f}** per 100 dropbacks (fewer than "
      f"{r.inexp_cut:g} career dropbacks). Net rating = 0.58 x (O_pass - D_pass) + 0.42 x (O_rush - D_rush) "
      f"+ 0.18 x (O_st - D_st). Team values are on the Power tab (x100).")
  if r.qb is not None and r.qb_prior is not None:
    q = r.qb[r.qb.index.isin(r.qb_prior.index[r.qb_prior >= r.inexp_cut])].sort_values(ascending=False)
    add("Quarterback effects Q (per 100 dropbacks, experienced QBs):")
    add("| Top 10 | Q | | Bottom 10 | Q |")
    add("|---|---|---|---|---|")
    top, bot = list(q.head(10).items()), list(q.tail(10).sort_values().items())
    for (k1, v1), (k2, v2) in zip(top, bot):
      add(f"| {names.get(k1, k1)} | {100 * v1:+.2f} | | {names.get(k2, k2)} | {100 * v2:+.2f} |")

  # --- game model -----------------------------------------------------------------------------------------------
  gm = eng.gm
  add("### 10.2 Game volume and points")
  add(_eq("plays (with Vegas)", gm.plays_vegas))
  add("")
  add(_eq("plays (model-only lines)", gm.plays_model))
  add("")
  add(_eq("pass rate", gm.pass_rate))
  add("")
  add(_eq("team points", gm.points))
  add("")
  add("Expected offensive EPA per game = dropbacks x (a_pass + O_pass + Q + D_pass,opp + H_pass x home) "
      "+ rushes x (a_rush + O_rush + D_rush,opp + H_rush x home).")

  # --- shares ---------------------------------------------------------------------------------------------------
  add("### 10.3 Usage shares (calibrated next-game share)")
  add("`share_next = b0 + b1 x recent share (half-life weighted) + b2 x long-run share (season-weighted)`")
  add("| Share | Position | b0 | b1 recent | b2 long-run |")
  add("|---|---|---|---|---|")
  for (share, pos), m in sorted(eng.pm.share_models.items()):
    add(f"| {share.replace('_', ' ')} | {pos} | {m.coef[0]:+.3f} | {m.coef[1]:+.3f} | {m.coef[2]:+.3f} |")
  add("Opportunities = share x team dropbacks (or designed rushes). QB rushes = carry share x team rushes "
      "+ scramble rate x dropbacks.")

  # --- efficiency -----------------------------------------------------------------------------------------------
  add("### 10.4 Efficiency per opportunity")
  add("Each stat per opportunity is a linear regression fit on earlier seasons (weighted by opportunities):")
  add("`rate = b0 + b1 x shrunk rate + b2 x adjusted EPA/opp + b3 x opponent defense + b4 x own offense "
      "+ b5 x home + b6 x Vegas implied total`")
  add("| Stat per opportunity | Group | b0 | b1 shrunk rate | b2 adj. EPA | b3 opp. D | b4 own O | b5 home | b6 implied |")
  add("|---|---|---|---|---|---|---|---|---|")
  for (opp, grp, c), m in eng.pm.eff_models.items():
    co = dict(zip(m.cols, m.coef[1:]))
    get = lambda key: next((v for k, v in co.items() if k.startswith(key) or k == key), np.nan)
    add(f"| {STAT_LABEL.get(c, c)} / {OPP_LABEL[opp]} | {grp} | {m.coef[0]:+.3f} | {_f(co.get(f'{c}_per_{opp}'))} | "
        f"{_f(co.get(f'{opp}_adj_per_{opp}'))} | {_f(get('def_'))} | {_f(get('off_'))} | {_f(co.get('home'))} | "
        f"{_f(co.get('implied_pts'), 4)} |")
  add("Shrunk rate (empirical Bayes): `(sum of player's stat + k x prior mean) / (player's opportunities + k)`, "
      "with season weights 1.0 / 0.6 / 0.3 for this season and the two before. Prior means by draft tier and "
      "prior strengths k:")
  pr = eng.pm.prior
  add("| Stat per opportunity | Group | k | R1 | R2-3 | R4-7 | UDFA |")
  add("|---|---|---|---|---|---|---|")
  for (opp, grp, c), m in eng.pm.eff_models.items():
    mus = [pr.mu.get((opp, grp, t), pr.mu_pos.get((opp, grp), {})).get(c, np.nan) for t in ("R1", "R2-3", "R4-7", "UDFA")]
    d = 2 if "yd" in c else 4
    add(f"| {STAT_LABEL.get(c, c)} / {OPP_LABEL[opp]} | {grp} | {pr.k.get((opp, grp, c), np.nan):.0f} | "
        + " | ".join("n/a" if np.isnan(v) else f"{v:.{d}f}" for v in mus) + " |")
  add("Touchdown feature: `expected TDs + n/(n + k_td) x (actual TDs - expected TDs)`, k_td = "
      f"{eng.cfg['player_model']['td_blend_k']}. Expected-TD rates by distance to the end zone:")
  xt = eng.pm.xtd
  bins = ["1", "2", "3", "4", "5", "6-7", "8-10", "11-15", "16-20", "21-30", "31-50", "51+"]
  add("| Yards to go | " + " | ".join(bins) + " |")
  add("|---|" + "---|" * len(bins))
  add("| Rush | " + " | ".join(f"{xt.rush.get(i, np.nan):.2f}" for i in range(len(bins))) + " |")
  add("| Target, end-zone throw | " + " | ".join(f"{xt.tgt.get((i, 1), np.nan):.2f}" for i in range(len(bins))) + " |")
  add("| Target, short of end zone | " + " | ".join(f"{xt.tgt.get((i, 0), np.nan):.2f}" for i in range(len(bins))) + " |")
  pc = eng.cfg["player_model"]
  add(f"Wind: passing efficiency x (1 - min({pc['wind_penalty_per_mph']} x max(0, wind - "
      f"{pc['wind_threshold_mph']}), {pc['wind_penalty_cap']})). TD odds: P(k TDs) = e^-x x^k / k! with x = "
      "expected TDs.")

  # --- blend / ranges -------------------------------------------------------------------------------------------
  add("### 10.5 Expert blend, uncertainty and ranges")
  for pos in sorted(eng.ecr_map):
    m = eng.ecr_map[pos]
    line = f"**{pos}**: expert points = {m.coef[0]:.2f} {m.coef[1]:+.2f} x ln(expert rank)"
    if pos in eng.blend:
      b = eng.blend[pos]
      line += f"; projection = {b.coef[0]:+.2f} + {b.coef[1]:.2f} x model + {b.coef[2]:.2f} x expert points"
    else:
      line += "; not blended (model only)"
    add(line + "  ")
  add("")
  add("Spread of outcomes: `sd^2 = a + b x projection`, widened x(1 + 0.6/(1 + games)) relative to an established "
      "player, x1.2 for low data, x1.25 for injury-boosted roles.")
  add("| Position | a | b | Floor (10th) / middle (25th-75th) / ceiling (90th) at projection 5, 10, 15, 20 |")
  add("|---|---|---|---|")
  for pos in sorted(eng.sd_model):
    a, b = eng.sd_model[pos]
    cells = []
    if pos in eng.q_model:
      centers, offs = eng.q_model[pos]
      for x in (5, 10, 15, 20):
        q = [max(0.0, x + np.interp(x, centers, offs[:, k])) for k in range(5)]
        cells.append(f"{x}: {q[0]:.0f} / {q[1]:.0f}-{q[3]:.0f} / {q[4]:.0f}")
    add(f"| {pos} | {a:.1f} | {b:.2f} | {'; '.join(cells)} |")

  # --- availability ---------------------------------------------------------------------------------------------
  im = eng.injury_model
  if im is not None:
    add("### 10.6 Availability and redistribution")
    add("Chance to play by final game status x final practice day (fallback when daily practice data is missing):")
    add("| Status | Did not practice | Limited | Full |")
    add("|---|---|---|---|")
    for rep in ("Questionable", "Doubtful", "None"):
      add(f"| {rep if rep != 'None' else 'No game status'} | " + " | ".join(
        f"{im.p_rep_prac[(rep, p)]:.0%}" if (rep, p) in im.p_rep_prac else "-" for p in ("DNP", "LP", "FP")) + " |")
    add("Before the week's report: P(plays) given last week's status = " + ", ".join(
      f"{k} {v:.0%}" for k, v in im.p_next.items() if k in ("Out", "Doubtful", "Questionable")) + ".")
    if im.practice_model is not None:
      from .injuries import practice_features
      seqs = ["DDD", "DDL", "DLL", "LLL", "DLF", "LLF", "LFF", "FFF"]
      rows = pd.DataFrame([{"days": s, "game_status": gs, "position": "WR"} for gs in ("QUESTIONABLE", "DOUBTFUL")
                           for s in seqs])
      pr_ = im.practice_model.predict_proba(practice_features(rows)[im.practice_cols])[:, 1]
      add("The practice model is gradient-boosted trees (no single formula; features: count of DNP / limited / full "
          "days, first and last day, trend, all-DNP flag, game status, skill position). Its outputs for a skill "
          "player (D = did not practice, L = limited, F = full, Wed/Thu/Fri):")
      add("| Status | " + " | ".join(seqs) + " |")
      add("|---|" + "---|" * len(seqs))
      for i, gs in enumerate(("Questionable", "Doubtful")):
        add(f"| {gs} | " + " | ".join(f"{p:.0%}" for p in pr_[i * len(seqs):(i + 1) * len(seqs)]) + " |")
    if getattr(im, "scratch_model", None) is not None:
      prof = pd.DataFrame([
        {"label": "Every-week starter", "n_prev": 5, "act_rate": 0.97, "played_last": 1, "snap_avg": 0.85, "rank": 1, "ahead_out": 0, "rookie": 0},
        {"label": "Rotational WR3", "n_prev": 5, "act_rate": 0.9, "played_last": 1, "snap_avg": 0.45, "rank": 3, "ahead_out": 0, "rookie": 0},
        {"label": "Depth WR5, often inactive", "n_prev": 5, "act_rate": 0.4, "played_last": 0, "snap_avg": 0.1, "rank": 5, "ahead_out": 0, "rookie": 0},
        {"label": "Same, starter ahead is out", "n_prev": 5, "act_rate": 0.4, "played_last": 0, "snap_avg": 0.1, "rank": 5, "ahead_out": 1, "rookie": 0},
        {"label": "Rookie RB3", "n_prev": 5, "act_rate": 0.6, "played_last": 1, "snap_avg": 0.15, "rank": 3, "ahead_out": 0, "rookie": 1},
      ])
      for p_ in ("QB", "RB", "WR", "TE"):
        prof[f"is_{p_}"] = 0
      prof.loc[prof.label.str.contains("RB"), "is_RB"] = 1
      prof.loc[~prof.label.str.contains("RB"), "is_WR"] = 1
      ps = im.scratch_model.predict_proba(prof[im.SCRATCH_COLS])[:, 1]
      add("Healthy-scratch model (gradient-boosted trees on active history, last game, snap share, depth rank, "
          "teammates out ahead, rookie, position). Example outputs:")
      add("| Profile | Inactive% |")
      add("|---|---|")
      for lbl, p_ in zip(prof.label, ps):
        add(f"| {lbl} | {1 - p_:.0%} |")
    if getattr(im, "coef", None):
      from .injuries import MISSING, RANKS, RECV
      add(f"Redistribution: teammate's added share = scale ({im.scale:g}) x vacated share x (1 - share of recent "
          "games already missed) x weight, fit by non-negative least squares on past absences:")
      add("| Vacated | Missing | Receiver | Rank 1 | Rank 2 | Rank 3+ | x his share |")
      add("|---|---|---|---|---|---|---|")
      for share, c in im.coef.items():
        if c is None:
          continue
        i = 0
        for m in MISSING[share]:
          for rcv in RECV:
            w = c[i:i + 4]
            i += 4
            if np.abs(w).sum() < 1e-4:
              continue
            add(f"| {share.replace('_share', '')} | {m} | {rcv} | " + " | ".join(f"{v:.3f}" for v in w) + " |")
  return "\n".join(out)
