"""Direct unit tests for backend/apps/permission_utils.py.

This module is the FastAPI adapter layer that translates domain exceptions raised
by ``ElasticSearchService.require_knowledge_base_{edit,read}_permission`` into the
correct ``HTTPException`` status codes required by the web framework:

    ``ValueError``       -> ``404 NOT_FOUND``  (KB record does not exist in DB)
    ``PermissionError``  -> ``403 FORBIDDEN``  (user lacks the required permission)
    no exception         -> normal return      (permission check passed)

The tests below exercise ALL three code paths for BOTH public functions in the module.
"""

import sys
from http import HTTPStatus
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Module-level stubbing (mirrors the pattern used across the test suite so
# that backend packages import successfully without a live venv/runtime):
# - backend/ and backend/apps/ are added to sys.path
# - services.vectordatabase_service is stubbed (no DB / ES dependency)
# The real ``apps.permission_utils`` module is then imported and tested
# against the stubbed ``ElasticSearchService``.
# ---------------------------------------------------------------------------

_BACKEND_DIR = "D:/work/public/nexent/backend"
_APPS_DIR = f"{_BACKEND_DIR}/apps"
for _path in (_BACKEND_DIR, _APPS_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

sys.modules.setdefault("services.vectordatabase_service", MagicMock())  # noqa: SIM117

with MagicMock() as _stub_es:
    # Expose the two static methods we patch in individual tests.
    _stub_es.require_knowledge_base_edit_permission = MagicMock(return_value="EDIT")
    _stub_es.require_knowledge_base_read_permission = MagicMock(return_value="READ_ONLY")
    sys.modules["services.vectordatabase_service"].ElasticSearchService = _stub_es

from apps import permission_utils  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_es_mocks():
    """Reset ElasticSearchService stubs between tests to avoid cross-test leakage."""
    yield
    permission_utils.ElasticSearchService.require_knowledge_base_edit_permission = MagicMock(
        return_value="EDIT"
    )
    permission_utils.ElasticSearchService.require_knowledge_base_read_permission = MagicMock(
        return_value="READ_ONLY"
    )


# ===========================================================================
# require_knowledge_base_edit_permission
# ===========================================================================


class TestRequireKnowledgeBaseEditPermission:
    """Tests for the edit-permission FastAPI adapter."""

    def test_edit_happy_path_passes_arguments_through(self):
        """When ES layer returns successfully, the adapter returns None and forwards args."""
        mock = permission_utils.ElasticSearchService.require_knowledge_base_edit_permission
        mock.return_value = "EDIT"

        result = permission_utils.require_knowledge_base_edit_permission(
            index_name="kb-1", user_id="user-1", tenant_id="tenant-1"
        )

        assert result is None
        mock.assert_called_once_with(
            index_name="kb-1", user_id="user-1", tenant_id="tenant-1"
        )

    def test_edit_value_error_maps_to_404(self, monkeypatch):
        """KB missing in DB -> ValueError from ES layer -> 404 NOT_FOUND."""

        def raise_missing(**_kwargs):
            raise ValueError("Knowledge base 'missing-kb' not found")

        monkeypatch.setattr(
            permission_utils.ElasticSearchService,
            "require_knowledge_base_edit_permission",
            raise_missing,
        )

        with pytest.raises(HTTPException) as exc_info:
            permission_utils.require_knowledge_base_edit_permission(
                "missing-kb", "user-1", "tenant-1"
            )

        assert exc_info.value.status_code == HTTPStatus.NOT_FOUND
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Knowledge base 'missing-kb' not found"

    def test_edit_permission_error_maps_to_403(self, monkeypatch):
        """User lacks edit permission -> PermissionError -> 403 FORBIDDEN."""

        def raise_forbidden(**_kwargs):
            raise PermissionError("No permission to modify this knowledge base")

        monkeypatch.setattr(
            permission_utils.ElasticSearchService,
            "require_knowledge_base_edit_permission",
            raise_forbidden,
        )

        with pytest.raises(HTTPException) as exc_info:
            permission_utils.require_knowledge_base_edit_permission(
                "kb-1", "user-1", "tenant-1"
            )

        assert exc_info.value.status_code == HTTPStatus.FORBIDDEN
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "No permission to modify this knowledge base"


# ===========================================================================
# require_knowledge_base_read_permission
# ===========================================================================


class TestRequireKnowledgeBaseReadPermission:
    """Tests for the read-permission FastAPI adapter (Issue #3339)."""

    def test_read_happy_path_passes_arguments_through(self):
        """When ES layer returns successfully with a read-level permission, adapter returns None."""
        mock = permission_utils.ElasticSearchService.require_knowledge_base_read_permission
        mock.return_value = "READ_ONLY"

        result = permission_utils.require_knowledge_base_read_permission(
            index_name="kb-readonly", user_id="user-2", tenant_id="tenant-2"
        )

        assert result is None
        mock.assert_called_once_with(
            index_name="kb-readonly", user_id="user-2", tenant_id="tenant-2"
        )

    def test_read_value_error_maps_to_404(self, monkeypatch):
        """KB missing in DB -> ValueError -> 404 NOT_FOUND."""

        def raise_missing(**_kwargs):
            raise ValueError("Knowledge base 'ghost' not found")

        monkeypatch.setattr(
            permission_utils.ElasticSearchService,
            "require_knowledge_base_read_permission",
            raise_missing,
        )

        with pytest.raises(HTTPException) as exc_info:
            permission_utils.require_knowledge_base_read_permission(
                "ghost", "user-2", "tenant-2"
            )

        assert exc_info.value.status_code == HTTPStatus.NOT_FOUND
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Knowledge base 'ghost' not found"

    def test_read_permission_error_maps_to_403(self, monkeypatch):
        """User lacks any read permission -> PermissionError -> 403 FORBIDDEN."""

        def raise_forbidden(**_kwargs):
            raise PermissionError("No permission to access this knowledge base")

        monkeypatch.setattr(
            permission_utils.ElasticSearchService,
            "require_knowledge_base_read_permission",
            raise_forbidden,
        )

        with pytest.raises(HTTPException) as exc_info:
            permission_utils.require_knowledge_base_read_permission(
                "kb-1", "user-2", "tenant-2"
            )

        assert exc_info.value.status_code == HTTPStatus.FORBIDDEN
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "No permission to access this knowledge base"

    def test_read_detail_preserves_exception_message(self, monkeypatch):
        """HTTPException.detail preserves the full message from the underlying exception."""
        custom_message = "Custom read-permission denial with unicode: 没有读取权限"

        def raise_detailed(**_kwargs):
            raise PermissionError(custom_message)

        monkeypatch.setattr(
            permission_utils.ElasticSearchService,
            "require_knowledge_base_read_permission",
            raise_detailed,
        )

        with pytest.raises(HTTPException) as exc_info:
            permission_utils.require_knowledge_base_read_permission(
                "kb-x", "user-9", "tenant-9"
            )

        # The message must be preserved byte-for-byte in the detail field.
        assert exc_info.value.detail == custom_message
        assert "没有读取权限" in exc_info.value.detail
