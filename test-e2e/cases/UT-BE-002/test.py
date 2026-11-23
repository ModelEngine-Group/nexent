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




@STAGE
@pytest.mark.case_id("UT-BE-002")
def test_permission_rejects_missing_auth_and_cross_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    from permissions import depends
    from permissions.models import CurrentUser
    from permissions.tenant_scope import resolve_personal_target_tenant

    monkeypatch.setattr(depends, "IS_SPEED_MODE", False)
    with pytest.raises(HTTPException) as unauthenticated:
        depends.authenticate(None, None)
    assert unauthenticated.value.status_code == 401

    monkeypatch.setattr(depends, "has_permission", lambda role, permission: False)
    with pytest.raises(HTTPException) as forbidden:
        depends.require("tenant:update")(CurrentUser("u", "t1", "USER"))
    assert forbidden.value.status_code == 403

    with pytest.raises(HTTPException) as cross_tenant:
        resolve_personal_target_tenant(CurrentUser("u", "t1", "ADMIN"), "t2")
    assert cross_tenant.value.status_code == 403


def _profile(version: str = "2026-01") -> SimpleNamespace:
    return SimpleNamespace(
        context_window_tokens=128_000,
        max_input_tokens=120_000,
        max_output_tokens=8_000,
        default_output_reserve_tokens=4_000,
        tokenizer_family="openai",
        capability_profile_version=version,
    )




















