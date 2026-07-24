"""Unit tests for ``aidp_permission_service``.

Exercises the v7.1 permission matrix by stubbing the local DB helpers
(``aidp_permission_db``, ``user_tenant_db``, ``group_db``). This lets us
verify the resolution order without standing up a real database.
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = str(Path(__file__).resolve().parents[3])
BACKEND_ROOT = str(Path(PROJECT_ROOT) / "backend")
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)


# --- Stub nexent SDK and backend.storage.client ----------------------------


if "nexent" not in sys.modules:
    nexent_pkg = types.ModuleType("nexent")
    nexent_pkg.__path__ = []
    sys.modules["nexent"] = nexent_pkg
    nexent_utils_pkg = types.ModuleType("nexent.utils")
    nexent_utils_pkg.__path__ = []
    sys.modules["nexent.utils"] = nexent_utils_pkg
    http_client_mod = types.ModuleType("nexent.utils.http_client_manager")
    http_client_mod.http_client_manager = MagicMock()
    sys.modules["nexent.utils.http_client_manager"] = http_client_mod
    nexent_storage_pkg = types.ModuleType("nexent.storage")
    nexent_storage_pkg.__path__ = []
    sys.modules["nexent.storage"] = nexent_storage_pkg
    storage_factory_mod = types.ModuleType("nexent.storage.storage_client_factory")
    storage_factory_mod.create_storage_client_from_config = MagicMock()

    class _MinIOStorageConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    storage_factory_mod.MinIOStorageConfig = _MinIOStorageConfig
    sys.modules["nexent.storage.storage_client_factory"] = storage_factory_mod

# Force fresh import of the service under test so per-test patching works.
sys.modules.pop("backend.ext_components.aidp.services.aidp_permission_service", None)
sys.modules.pop("backend.ext_components.aidp.database.aidp_permission_db", None)

from backend.ext_components.aidp.services import aidp_permission_service as svc  # noqa: E402
from backend.ext_components.aidp.consts.aidp_exceptions import (  # noqa: E402
    AidpKbNotFoundError,
    AidpKbPermissionDeniedError,
    AidpGroupValidationError,
)
from backend.consts.const import CAN_EDIT_ALL_USER_ROLES  # noqa: E402


# --- Helpers --------------------------------------------------------------


def _record(**overrides) -> dict:
    base = {
        "kb_id": "kb-1",
        "tenant_id": "tenant-a",
        "owner_user_id": "owner",
        "ingroup_permission": "READ_ONLY",
        "group_ids": [1, 2],
        "resource_status": "ACTIVE",
    }
    base.update(overrides)
    return base


@pytest.fixture
def patched(monkeypatch):
    """Patch every external collaborator on the permission service."""
    get_role = MagicMock(return_value="USER")
    get_groups = MagicMock(return_value=[])
    get_perm = MagicMock(return_value=None)

    from unittest.mock import patch

    with patch.object(svc, "_get_user_role", get_role), \
         patch.object(svc, "_get_user_groups", get_groups), \
         patch.object(svc.aidp_permission_db, "get_permission_by_kb_id", get_perm):
        yield {
            "get_role": get_role,
            "get_groups": get_groups,
            "get_perm": get_perm,
        }


# --- _resolve_permission ---------------------------------------------------


class TestResolvePermission:
    def test_management_role_bypasses_group_check(self, patched):
        patched["get_role"].return_value = "ADMIN"
        decision = svc._resolve_permission(_record(ingroup_permission="PRIVATE"), "u", "t")
        assert decision.permission == "EDIT"
        assert decision.is_management_role is True

    def test_su_role_is_management(self, patched):
        patched["get_role"].return_value = "SU"
        decision = svc._resolve_permission(_record(), "u", "t")
        assert decision.permission == "EDIT"
        assert decision.is_management_role is True

    def test_asset_owner_is_management(self, patched):
        patched["get_role"].return_value = "ASSET_OWNER"
        decision = svc._resolve_permission(_record(ingroup_permission="PRIVATE"), "u", "t")
        assert decision.permission == "EDIT"
        assert decision.is_management_role is True

    def test_creator_is_edit(self, patched):
        record = _record(owner_user_id="creator")
        decision = svc._resolve_permission(record, user_id="creator", tenant_id="t")
        assert decision.permission == "EDIT"
        assert decision.is_management_role is False
        patched["get_role"].assert_called_once()

    def test_private_blocks_non_creator(self, patched):
        decision = svc._resolve_permission(_record(ingroup_permission="PRIVATE"), "u", "t")
        assert decision.permission is None

    def test_empty_groups_blocks_user(self, patched):
        decision = svc._resolve_permission(
            _record(ingroup_permission="READ_ONLY", group_ids=[]), "u", "t",
        )
        assert decision.permission is None

    def test_group_intersection_grants_read_only(self, patched):
        decision = svc._resolve_permission(
            _record(ingroup_permission="READ_ONLY", group_ids=[1, 2, 3]),
            "u", "t",
            user_groups=[2],
        )
        assert decision.permission == "READ_ONLY"
        assert decision.matched_group_ids == (2,)

    def test_group_intersection_grants_edit(self, patched):
        decision = svc._resolve_permission(
            _record(ingroup_permission="EDIT", group_ids=[1, 2]),
            "u", "t",
            user_groups=[1, 2],
        )
        assert decision.permission == "EDIT"
        assert sorted(decision.matched_group_ids) == [1, 2]

    def test_no_intersection_blocks_user(self, patched):
        decision = svc._resolve_permission(
            _record(group_ids=[1, 2]),
            "u", "t",
            user_groups=[5],
        )
        assert decision.permission is None
        assert decision.matched_group_ids == ()

    def test_missing_record_raises_not_found(self, patched):
        with pytest.raises(AidpKbNotFoundError):
            svc._resolve_permission(record={}, user_id="u", tenant_id="t")


# --- require_permission ---------------------------------------------------


"""Rewrite TestRequirePermission using per-test patch.object to avoid
cross-file import contamination from the broader AIDP test suite.
"""
from unittest.mock import patch

import pytest

from backend.ext_components.aidp.services import aidp_permission_service as svc
from backend.ext_components.aidp.consts.aidp_exceptions import (
    AidpKbNotFoundError,
    AidpKbPermissionDeniedError,
)


"""Rewrite TestRequirePermission with stable patch target _get_permission_record."""
from unittest.mock import patch

import pytest

from backend.ext_components.aidp.services import aidp_permission_service as svc
from backend.ext_components.aidp.consts.aidp_exceptions import (
    AidpKbNotFoundError,
    AidpKbPermissionDeniedError,
)


class TestRequirePermissionRewritten:
    def test_edit_allowed_for_management_role(self):
        record = {"kb_id": "kb-1", "owner_user_id": "other",
                  "ingroup_permission": "READ_ONLY", "group_ids": [1]}
        with patch.object(svc, "_get_permission_record",
                          return_value=record), \
             patch.object(svc, "_get_user_role", return_value="ADMIN"):
            decision = svc.require_permission("kb-1", "u", "t", required="EDIT")
        assert decision.permission == "EDIT"

    def test_edit_denied_for_read_only_user(self):
        record = {"kb_id": "kb-1", "owner_user_id": "other",
                  "ingroup_permission": "READ_ONLY", "group_ids": [1]}
        with patch.object(svc, "_get_permission_record",
                          return_value=record), \
             patch.object(svc, "_get_user_role", return_value="USER"), \
             patch.object(svc, "_get_user_groups", return_value=[1]):
            with pytest.raises(AidpKbPermissionDeniedError):
                svc.require_permission("kb-1", "u", "t", required="EDIT")

    def test_read_allowed_when_group_intersects(self):
        record = {"kb_id": "kb-1", "owner_user_id": "other",
                  "ingroup_permission": "READ_ONLY", "group_ids": [2]}
        with patch.object(svc, "_get_permission_record",
                          return_value=record), \
             patch.object(svc, "_get_user_role", return_value="USER"), \
             patch.object(svc, "_get_user_groups", return_value=[2]):
            decision = svc.require_permission("kb-1", "u", "t", required="READ")
        assert decision.permission == "READ_ONLY"

    def test_missing_record_raises_not_found(self):
        with patch.object(svc, "_get_permission_record",
                          return_value=None):
            with pytest.raises(AidpKbNotFoundError):
                svc.require_permission("kb-1", "u", "t", required="READ")



# --- _validate_group_ids_strict --------------------------------------------


class TestValidateGroupIdsStrict:
    def test_returns_input_when_all_valid(self, monkeypatch):
        monkeypatch.setattr(
            svc.group_db_module, "filter_tenant_group_ids",
            lambda ids, tenant: list(ids),
        )
        result = svc._validate_group_ids_strict([1, 2], "tenant")
        assert result == [1, 2]

    def test_raises_on_invalid_id(self, monkeypatch):
        monkeypatch.setattr(
            svc.group_db_module, "filter_tenant_group_ids",
            lambda ids, tenant: [g for g in ids if g != 999],
        )
        with pytest.raises(AidpGroupValidationError) as exc:
            svc._validate_group_ids_strict([1, 999], "tenant")
        assert exc.value.invalid_ids == [999]

    def test_empty_returns_empty(self, monkeypatch):
        assert svc._validate_group_ids_strict([], "tenant") == []


# --- Filter / whitelist helpers -------------------------------------------


class TestFilterAndWhitelist:
    def test_filter_accessible_kds_drops_unknown_and_denied(self, monkeypatch):
        rows = {
            "allowed": _record(kb_id="allowed", ingroup_permission="EDIT"),
            "readonly": _record(kb_id="readonly", ingroup_permission="READ_ONLY"),
            "private": _record(kb_id="private", ingroup_permission="PRIVATE"),
        }

        def fake_get(*, kb_id, tenant_id):
            if kb_id == "other-tenant":
                return None
            return rows.get(kb_id)

        monkeypatch.setattr(svc.aidp_permission_db, "get_permission_by_kb_id", fake_get)
        monkeypatch.setattr(svc, "_get_user_groups", lambda u, t: [1])
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "USER")

        result = svc.filter_accessible_kds(
            ["allowed", "readonly", "private", "other-tenant"], "u", "tenant",
        )
        # other-tenant is missing (treated as 404), private has no creator hit.
        assert result == ["allowed", "readonly"]

    def test_filter_accessible_kds_keeps_order(self, monkeypatch):
        def fake_get(*, kb_id, tenant_id):
            return _record(kb_id=kb_id, ingroup_permission="EDIT")

        monkeypatch.setattr(svc.aidp_permission_db, "get_permission_by_kb_id", fake_get)
        monkeypatch.setattr(svc, "_get_user_groups", lambda u, t: [1])
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "USER")

        result = svc.filter_accessible_kds(["z", "a", "m"], "u", "t")
        assert result == ["z", "a", "m"]

    def test_get_allowed_kds_list_returns_readable_kbs(self, monkeypatch):
        rows = [
            _record(kb_id="edit-1", ingroup_permission="EDIT"),
            _record(kb_id="read-1", ingroup_permission="READ_ONLY"),
            _record(kb_id="priv-1", ingroup_permission="PRIVATE"),
        ]
        monkeypatch.setattr(svc.aidp_permission_db, "list_permissions_by_tenant",
                            lambda tenant_id, page=1, page_size=200: rows)
        monkeypatch.setattr(svc, "_get_user_groups", lambda u, t: [1])
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "USER")

        result = svc.get_allowed_kds_list("u", "t")
        assert "edit-1" in result
        assert "read-1" in result
        assert "priv-1" not in result

    def test_get_allowed_kds_list_management_sees_everything(self, monkeypatch):
        rows = [
            _record(kb_id="p", ingroup_permission="PRIVATE"),
            _record(kb_id="e", ingroup_permission="EDIT"),
        ]
        monkeypatch.setattr(svc.aidp_permission_db, "list_permissions_by_tenant",
                            lambda tenant_id, page=1, page_size=200: rows)
        monkeypatch.setattr(svc, "_get_user_groups", lambda u, t: [])
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "ADMIN")

        result = svc.get_allowed_kds_list("u", "t")
        assert sorted(result) == ["e", "p"]


# --- get_accessible_kbs ---------------------------------------------------


class TestGetAccessibleKbs:
    def test_marks_permission_per_row(self, monkeypatch):
        rows = [
            _record(kb_id="creator-kb", owner_user_id="u", ingroup_permission="PRIVATE"),
            _record(kb_id="group-kb", owner_user_id="other", ingroup_permission="READ_ONLY"),
        ]
        monkeypatch.setattr(svc.aidp_permission_db, "list_permissions_by_tenant",
                            lambda tenant_id, page=1, page_size=10: rows)
        monkeypatch.setattr(svc.aidp_permission_db, "count_permissions_by_tenant",
                            lambda tenant_id: len(rows))
        monkeypatch.setattr(svc, "_get_user_groups", lambda u, t: [1])
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "USER")

        out = svc.get_accessible_kbs("u", "t")
        assert out[0]["permission"] == "EDIT"  # creator -> EDIT regardless of PRIVATE
        assert out[1]["permission"] == "READ_ONLY"