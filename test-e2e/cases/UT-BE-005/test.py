"""D1 backend unit contracts derived from the functional baseline.

These tests import production modules directly and never import Nexent's old
``test`` package. External services and databases are replaced at the module
boundary; assertions describe user-visible policy, not implementation calls.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException


STAGE = pytest.mark.stage("D1")






def _profile(version: str = "2026-01") -> SimpleNamespace:
    return SimpleNamespace(
        context_window_tokens=128_000,
        max_input_tokens=120_000,
        max_output_tokens=8_000,
        default_output_reserve_tokens=4_000,
        tokenizer_family="openai",
        capability_profile_version=version,
    )






@STAGE
@pytest.mark.case_id("UT-BE-005")
def test_monitoring_status_normalizes_runtime_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps import monitoring_app

    monkeypatch.setattr(monitoring_app, "ENABLE_TELEMETRY", True)
    monkeypatch.setattr(monitoring_app, "MONITORING_PROVIDER", "  OTLP ")
    monkeypatch.setattr(monitoring_app, "MONITORING_DASHBOARD_URL", " https://monitor.example ")
    monkeypatch.setattr(
        monitoring_app,
        "MONITORING_DASHBOARD_ALLOWED_ROLES",
        " su, speed, SU, tenant_admin ",
    )
    status = monitoring_app.get_monitoring_status()
    assert status == {
        "telemetry_enabled": True,
        "provider": "otlp",
        "dashboard_url": "https://monitor.example",
        "dashboard_allowed_roles": ["SU", "SPEED", "TENANT_ADMIN"],
        "dashboard_port": None,
        "dashboard_path": None,
    }














