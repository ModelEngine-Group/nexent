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
@pytest.mark.case_id("UT-BE-006")
def test_auth_helpers_trust_only_validated_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    from utils import auth_utils

    monkeypatch.setattr(auth_utils, "get_token_by_access_key", lambda key: None)
    assert auth_utils.validate_bearer_token("Bearer unsigned.payload.claims") == (False, None)
    monkeypatch.setattr(
        auth_utils,
        "get_token_by_access_key",
        lambda key: {"user_id": "u1", "delete_flag": "N"} if key == "verified" else None,
    )
    valid, info = auth_utils.validate_bearer_token("Bearer verified")
    assert valid is True and info and info["user_id"] == "u1"
    assert auth_utils.resolve_tenant_id_from_user_tenant_record({"tenant_id": "t1"}) == "t1"












