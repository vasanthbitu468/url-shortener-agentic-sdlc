"""Write the API contract to service/openapi.json.

Run after any API change:  python scripts/export_openapi.py
CI fails if the committed file is out of date (tests/integration/test_contract.py).
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("APP_DATABASE_URL", "sqlite://")

from service.main import create_app  # noqa: E402

OUT = ROOT / "service" / "openapi.json"


def render() -> str:
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    # newline="\n": identical bytes on Windows and Linux, so the contract never shows a
    # spurious line-ending-only change
    OUT.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
