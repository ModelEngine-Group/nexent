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
@pytest.mark.case_id("UT-BE-007")
def test_rbac_matrix_and_tenant_scope_are_case_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    from permissions import rbac
    from permissions.models import CurrentUser
    from permissions.tenant_scope import resolve_personal_target_tenant

    monkeypatch.setattr(rbac, "_INITIALIZED", True)
    monkeypatch.setattr(rbac, "_ROLE_PERMISSIONS", {"ADMIN": {"knowledge:read", "knowledge:edit"}})
    assert rbac.has_permission("admin", "KNOWLEDGE:READ")
    assert rbac.get_role_permissions("admin") == {"knowledge:read", "knowledge:edit"}
    copied = rbac.get_role_permissions("ADMIN")
    copied.clear()
    assert rbac.has_permission("ADMIN", "knowledge:read")
    assert resolve_personal_target_tenant(CurrentUser("su", "root", "SU"), "tenant-b") == "tenant-b"










