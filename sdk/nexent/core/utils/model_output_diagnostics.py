"""Privacy-gated, bounded previews for rejected model output diagnostics."""

from __future__ import annotations

import json
import os
from typing import Any


_PREVIEW_LIMIT = 256
_PREVIEW_ENV = "NEXENT_PROTOCOL_DIAGNOSTIC_CONTENT"


def rejected_output_preview_enabled() -> bool:
    """Raw output is never logged unless an operator explicitly opts in."""

    return os.environ.get(_PREVIEW_ENV) == "1"


def bounded_rejected_output_preview(value: Any) -> str:
    """Escape controls/newlines and cap a single model-output field."""

    content = "" if value is None else str(value)
    return json.dumps(content[:_PREVIEW_LIMIT], ensure_ascii=False)
