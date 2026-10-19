# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""CAS creator regressions reusing the existing isolated AIDP HTTP fixtures."""

from unittest.mock import MagicMock

import pytest

from test.ext_components.aidp.test_aidp_mgmt_app import (
    _bearer,
    _client,
    configure_aidp_constants,  # noqa: F401 - shared autouse fixture
)


@pytest.mark.parametrize("lookup_failed", [False, True])
def test_detail_optional_cas_creator_preserves_local_owner_contract(monkeypatch, lookup_failed):
    from ext_components.aidp.apps import aidp_mgmt_app as module
    from management.services.permission.identity import display as user_identity_service

    monkeypatch.setattr(module.perms, "require_permission", lambda *a, **kw: MagicMock(permission="EDIT"))
    monkeypatch.setattr(module, "get_aidp_kb_impl", lambda *a: {"kds_name": "Knowledge", "user_name": "remote"})
    monkeypatch.setattr(module, "count_aidp_docs_impl", lambda *a: 7)
    monkeypatch.setattr(module.aidp_permission_db, "get_permission_by_kb_id",
                        lambda *a: {"owner_user_id": "local-owner", "group_ids": [], "creator_name": "owner@test"})
    lookup = MagicMock(return_value={"local-owner": {"cas_username": "创建人", "email": "owner@test"}})
    if lookup_failed:
        lookup.side_effect = RuntimeError("controlled lookup failure")
    monkeypatch.setattr(user_identity_service, "get_cas_identities", lookup)
    response = _client().get("/aidp-mgmt/knowledge-bases/kb-1", headers=_bearer())
    assert response.status_code == 200
    result = response.json()
    assert result["created_by"] == "local-owner"
    assert result["creator_name"] == "owner@test"
    assert result["document_count"] == 7
    if lookup_failed:
        assert "creator_cas_username" not in result
    else:
        assert result["creator_cas_username"] == "创建人"
    lookup.assert_called_once_with({"local-owner"})
