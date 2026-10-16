"""Keep MODEL.md in sync with the model and with the lab notebook (the pre-commit hook runs --check).

  python tools/model_doc.py --check   exit 1 if (a) model code / config changed since MODEL.md was last stamped, or
                                      (b) the lab notebook and the Model tab's "What we tried" lists disagree
  python tools/model_doc.py --stamp   record the current fingerprint after reviewing / updating MODEL.md

(b) (owner 2026-10-16: "not a claude rule, a hook"): every recorded result in docs/INSIGHTS.md ("- **RESULT {#id} ...")
must have a line in MODEL.md's "What we tried" lists carrying <!-- tried:id -->, and every such marker must point to a
recorded result. A RESULT entry without an {#id} also fails.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nfledge import docs  # noqa: E402

RESULT = re.compile(r"^- \*\*RESULT\b(.*)$", re.M)
ID = re.compile(r"\{#([a-z0-9-]+)\}")
TRIED = re.compile(r"<!--\s*tried:([a-z0-9-]+)\s*-->")


def tried_problems() -> list[str]:
  """Disagreements between the notebook's recorded results and MODEL.md's "What we tried" markers."""
  notes = (ROOT / "docs" / "INSIGHTS.md").read_text(encoding="utf-8")
  model = (ROOT / "MODEL.md").read_text(encoding="utf-8")
  out, ids = [], []
  for m in RESULT.finditer(notes):
    found = ID.match(m.group(1).lstrip())
    if not found:
      line = notes.count("\n", 0, m.start()) + 1
      out.append(f"docs/INSIGHTS.md:{line}: RESULT entry without an id - write it as '- **RESULT {{#some-id}} ...'")
    else:
      ids.append(found.group(1))
  dup = sorted({i for i in ids if ids.count(i) > 1})
  out += [f"docs/INSIGHTS.md: id {{#{i}}} is used by more than one RESULT entry" for i in dup]
  marks = TRIED.findall(model)
  out += [f"MODEL.md: no 'What we tried' line for result {{#{i}}} (add one with <!-- tried:{i} -->)" for i in ids if i not in marks]
  out += [f"MODEL.md: <!-- tried:{i} --> points to no RESULT {{#{i}}} in docs/INSIGHTS.md" for i in marks if i not in ids]
  out += [f"MODEL.md: <!-- tried:{i} --> appears more than once" for i in sorted({i for i in marks if marks.count(i) > 1})]
  return out


if __name__ == "__main__":
  if "--stamp" in sys.argv:
    docs.stamp()
    print(f"MODEL.md stamped ({docs.code_fingerprint()})")
    sys.exit(0)
  bad = False
  if docs.is_stale():
    print("MODEL.md is out of date: model code or config.toml changed since it was last reviewed.\n"
          "Update MODEL.md to describe the change, then run: python tools/model_doc.py --stamp")
    bad = True
  probs = tried_problems()
  if probs:
    print("The lab notebook and the Model tab's 'What we tried' lists disagree:\n  " + "\n  ".join(probs))
    bad = True
  if bad:
    sys.exit(1)
  print("MODEL.md is current; every recorded result has a 'What we tried' line.")
