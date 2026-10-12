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


def render(live: dict) -> dict:
  """MODEL.md -> HTML with live values (StrictUndefined: a missing value fails the build, never shows blank)."""
  _, body = _split()
  env = Environment(undefined=StrictUndefined, autoescape=False)
  filled = env.from_string(body).render(L={k: f"<span class=\"live\">{v}</span>" if k != "bt_table" else v
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
