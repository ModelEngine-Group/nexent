"""Resolve registered D4 model metadata without printing credential values."""
from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.config import model_by_type  # noqa: E402


def model_metadata(capability: str) -> dict:
    model = model_by_type(capability)
    # Project only registered configuration fields. In particular, a literal
    # api_key in malformed local input must not cross the stdout bridge.
    return {key: model.get(key) for key in (
        'provider', 'base_url', 'model', 'preferred_model',
        'dimension', 'max_tokens', 'secret_env_key',
    )}


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Exactly one model capability is required')
    print(json.dumps(model_metadata(sys.argv[1])))
