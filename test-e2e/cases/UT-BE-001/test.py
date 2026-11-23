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
@pytest.mark.case_id("UT-BE-001")
def test_permission_core_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    from permissions import depends, rbac
    from permissions.models import CurrentUser
    from permissions.tenant_scope import resolve_personal_target_tenant

    monkeypatch.setattr(depends, "IS_SPEED_MODE", False)
    monkeypatch.setattr(depends, "get_current_user_context", lambda token: ("u1", "t1", "ADMIN"))
    user = depends.authenticate("Bearer verified", None)
    assert user == CurrentUser("u1", "t1", "ADMIN")

    monkeypatch.setattr(rbac, "_INITIALIZED", True)
    monkeypatch.setattr(rbac, "_ROLE_PERMISSIONS", {"ADMIN": {"agent:read"}})
    monkeypatch.setattr(depends, "has_permission", rbac.has_permission)
    assert depends.require("agent:read")(user) is user
    assert resolve_personal_target_tenant(user, None) == "t1"




def _profile(version: str = "2026-01") -> SimpleNamespace:
    return SimpleNamespace(
        context_window_tokens=128_000,
        max_input_tokens=120_000,
        max_output_tokens=8_000,
        default_output_reserve_tokens=4_000,
        tokenizer_family="openai",
        capability_profile_version=version,
    )




















