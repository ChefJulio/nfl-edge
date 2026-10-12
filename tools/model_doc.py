"""Keep MODEL.md in sync with the model.

  python tools/model_doc.py --check   exit 1 if model code / config changed since MODEL.md was last stamped
  python tools/model_doc.py --stamp   record the current fingerprint after reviewing / updating MODEL.md
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfledge import docs  # noqa: E402

if __name__ == "__main__":
  if "--stamp" in sys.argv:
    docs.stamp()
    print(f"MODEL.md stamped ({docs.code_fingerprint()})")
  elif docs.is_stale():
    print("MODEL.md is out of date: model code or config.toml changed since it was last reviewed.\n"
          "Update MODEL.md to describe the change, then run: python tools/model_doc.py --stamp")
    sys.exit(1)
  else:
    print("MODEL.md is current.")
