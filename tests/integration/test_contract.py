"""The committed OpenAPI file is the API contract. Changing the API without regenerating it
(python scripts/export_openapi.py) fails CI, so every API change is visible in review."""

import json
from pathlib import Path

CONTRACT = Path(__file__).resolve().parents[2] / "service" / "openapi.json"


def test_committed_openapi_matches_app(app):
    committed = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert committed == json.loads(json.dumps(app.openapi())), (
        "API changed: run `python scripts/export_openapi.py` and commit service/openapi.json"
    )
