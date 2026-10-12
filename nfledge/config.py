"""Config + scoring loading."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCORING_KEYS = ("pass_yd", "pass_td", "interception", "rush_yd", "rush_td", "reception", "rec_yd", "rec_td",
                "fumble_lost")


@dataclass
class Scoring:
  weights: dict[str, float]
  te_reception_bonus: float = 0.0
  name: str = "half"

  def points(self, comps: dict, position=None):
    """Fantasy points from a dict/DataFrame of component columns (works on scalars or Series)."""
    total = 0.0
    for k in SCORING_KEYS:
      if k in comps:
        total = total + comps[k] * self.weights.get(k, 0.0)
    if self.te_reception_bonus and position is not None and "reception" in comps:
      total = total + comps["reception"] * self.te_reception_bonus * (position == "TE")
    return total


def load_config(path: Path | None = None) -> dict:
  with open(path or ROOT / "config.toml", "rb") as f:
    return tomllib.load(f)


def load_scoring(path: Path | None = None) -> Scoring:
  with open(path or ROOT / "scoring.toml", "rb") as f:
    raw = tomllib.load(f)
  preset = raw.get("preset", "half")
  block = raw["custom"] if preset == "custom" else raw["presets"][preset]
  weights = {k: float(block.get(k, 0.0)) for k in SCORING_KEYS}
  return Scoring(weights=weights, te_reception_bonus=float(block.get("te_reception_bonus", 0.0)), name=preset)
