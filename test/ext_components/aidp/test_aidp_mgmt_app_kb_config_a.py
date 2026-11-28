# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""AIDP management route tests (split by feature from the original suite)."""

from test.ext_components.aidp.test_aidp_mgmt_app import *  # noqa: F401,F403
from test.ext_components.aidp.test_aidp_mgmt_app import (  # noqa: F401
    _bearer,
    _build_app,
    _client,
    _isolated_imports,
    configure_aidp_constants,
)

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException

import pytest

pytestmark = pytest.mark.usefixtures("configure_aidp_constants")


class TestListModels:
    def test_list_models_returns_aidp_response(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(aidp_mgmt_app, "list_aidp_models_impl",
                          return_value={"models": []}) as mock_models:
            response = client.get("/aidp-mgmt/models", headers=_bearer())
        assert response.status_code == HTTPStatus.OK
        mock_models.assert_called_once()


# ---------------------------------------------------------------------------
# _auth edge cases (lines 128-129, 131)
# ---------------------------------------------------------------------------


class TestAuthEdgeCases:
    def test_unauthorized_error_from_get_current_user_id_returns_401(self, monkeypatch):
        """get_current_user_id raises UnauthorizedError -> _auth catches and returns 401."""
        from ext_components.aidp.apps import aidp_mgmt_app
        from contracts.errors.exceptions import UnauthorizedError

        monkeypatch.setattr(
            aidp_mgmt_common.auth_utils_module, "get_current_user_id",
            lambda *_a, **_kw: (_ for _ in ()).throw(
                UnauthorizedError("invalid token")
            ),
        )
        client = _client()
        response = client.get("/aidp-mgmt/knowledge-bases", headers=_bearer())
        assert response.status_code == HTTPStatus.UNAUTHORIZED

    def test_empty_tenant_id_returns_401(self, monkeypatch):
        """get_current_user_id returns empty tenant -> _auth returns 401."""
        from ext_components.aidp.apps import aidp_mgmt_app

        monkeypatch.setattr(
            aidp_mgmt_common.auth_utils_module, "get_current_user_id",
            lambda *_a, **_kw: ("user-1", ""),
        )
        client = _client()
        response = client.get("/aidp-mgmt/knowledge-bases", headers=_bearer())
        assert response.status_code == HTTPStatus.UNAUTHORIZED


# ---------------------------------------------------------------------------
# _infer_is_multimodal and _raise_aidp_conflict helpers
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    def test_infer_is_multimodal_with_non_dict(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        assert aidp_mgmt_app._infer_is_multimodal("not a dict") is False
        assert aidp_mgmt_app._infer_is_multimodal(None) is False
        assert aidp_mgmt_app._infer_is_multimodal(42) is False

    def test_infer_is_multimodal_caption_enable_variants(self):
        from ext_components.aidp.apps import aidp_mgmt_app

        assert aidp_mgmt_app._infer_is_multimodal({"caption_enable": 1}) is True
        assert aidp_mgmt_app._infer_is_multimodal({"caption_enable": "1"}) is True
        assert aidp_mgmt_app._infer_is_multimodal({"caption_enable": True}) is True
        assert aidp_mgmt_app._infer_is_multimodal({"caption_enable": 0}) is False
        assert aidp_mgmt_app._infer_is_multimodal({}) is False

    def test_raise_aidp_conflict_translates_to_http_409(self):
        from ext_components.aidp.apps import aidp_mgmt_app
        from fastapi import HTTPException
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(HTTPException) as exc_info:
            aidp_mgmt_app._raise_aidp_conflict(
                IntegrityError("INSERT", {}, Exception("dup"))
            )
        assert exc_info.value.status_code == HTTPStatus.CONFLICT



# ---------------------------------------------------------------------------
# Count endpoint (lines 279-281)
# ---------------------------------------------------------------------------


class TestCountEndpoint:
    def test_count_knowledge_bases_returns_total(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(aidp_mgmt_app, "_current_accessible_rows", return_value=[{}] * 5):
            response = client.get("/aidp-mgmt/knowledge-bases/count", headers=_bearer())
        assert response.status_code == HTTPStatus.OK
        assert response.json()["total_count"] == 5


# ---------------------------------------------------------------------------
# List KB - detail fetch success with ACTIVE status (line 230)
# ---------------------------------------------------------------------------


class TestListKbsActiveStatus:
    def test_list_marks_kb_active_when_detail_fetch_succeeds(self):
        client = _client()
        from ext_components.aidp.apps import aidp_mgmt_app

        with patch.object(aidp_mgmt_app, "_current_accessible_rows", return_value=[
                 {
                     "kb_id": "kb-1", "owner_user_id": USER_ID, "tenant_id": TENANT_ID,
                     "ingroup_permission": "EDIT", "group_ids": [],
                     "resource_status": "ACTIVE", "permission": "EDIT",
                 }
             ]), \
             patch.object(aidp_mgmt_app, "get_aidp_kb_impl",
                          return_value={"kds_name": "name", "description": "desc", "document_count": 3,
                                        "chunk_count": 10, "embedding_model": "model"}):
            response = client.get("/aidp-mgmt/knowledge-bases", headers=_bearer())
        assert response.status_code == HTTPStatus.OK
        body = response.json()
        assert body["value"][0]["resource_status"] == "ACTIVE"
        assert body["value"][0]["kds_name"] == "name"


# ---------------------------------------------------------------------------
# Create KB - edge cases (lines 294, 307-313, 322-326, 333, 363, 368-373)
# ---------------------------------------------------------------------------


