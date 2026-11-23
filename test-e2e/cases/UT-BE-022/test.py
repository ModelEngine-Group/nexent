"""D1 backend policy tests for repository, sharing, runtime and memory."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


STAGE = pytest.mark.stage("D1")




















@STAGE
@pytest.mark.case_id("UT-BE-022")
def test_monitoring_provider_and_time_range_normalization() -> None:
    from apps.monitoring_app import _compute_time_range_filter, _normalize_monitoring_provider

    assert _normalize_monitoring_provider(None) == "otlp"
    assert _normalize_monitoring_provider("  LANGFUSE ") == "langfuse"
    assert "24 hours" in _compute_time_range_filter("unknown")
    assert "168 hours" in _compute_time_range_filter("7d")






