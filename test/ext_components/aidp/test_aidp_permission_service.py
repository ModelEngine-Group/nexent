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
from unittest.mock import MagicMock, patch

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
sys.modules.pop("ext_components.aidp.services.aidp_permission_service", None)
sys.modules.pop("ext_components.aidp.database.aidp_permission_db", None)

from ext_components.aidp.services import aidp_permission_service as svc  # noqa: E402
from ext_components.aidp.consts.aidp_exceptions import (  # noqa: E402
    AidpKbNotFoundError,
    AidpKbPermissionDeniedError,
    AidpGroupValidationError,
)
from consts.const import CAN_EDIT_ALL_USER_ROLES  # noqa: E402


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
    @pytest.mark.parametrize("role", sorted(CAN_EDIT_ALL_USER_ROLES))
    def test_management_roles_cannot_access_other_users_private_kb(self, patched, role):
        patched["get_role"].return_value = role
        decision = svc._resolve_permission(_record(ingroup_permission="PRIVATE"), "u", "t")
        assert decision.permission is None
        assert decision.is_management_role is False

    def test_su_role_is_management(self, patched):
        patched["get_role"].return_value = "SU"
        decision = svc._resolve_permission(_record(), "u", "t")
        assert decision.permission == "EDIT"
        assert decision.is_management_role is True

    def test_asset_owner_cannot_access_other_users_private_kb(self, patched):
        patched["get_role"].return_value = "ASSET_OWNER"
        decision = svc._resolve_permission(_record(ingroup_permission="PRIVATE"), "u", "t")
        assert decision.permission is None
        assert decision.is_management_role is False

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

    def test_dev_group_intersection_grants_read_only(self, patched):
        patched["get_role"].return_value = "DEV"
        decision = svc._resolve_permission(
            _record(ingroup_permission="READ_ONLY", group_ids=[1, 2, 3]),
            "u", "t",
            user_groups=[2],
        )
        assert decision.permission == "READ_ONLY"
        assert decision.matched_group_ids == (2,)

    def test_dev_group_intersection_grants_edit(self, patched):
        patched["get_role"].return_value = "DEV"
        decision = svc._resolve_permission(
            _record(ingroup_permission="EDIT", group_ids=[1, 2]),
            "u", "t",
            user_groups=[1, 2],
        )
        assert decision.permission == "EDIT"
        assert sorted(decision.matched_group_ids) == [1, 2]

    def test_no_intersection_blocks_user(self, patched):
        patched["get_role"].return_value = "DEV"
        decision = svc._resolve_permission(
            _record(group_ids=[1, 2]),
            "u", "t",
            user_groups=[5],
        )
        assert decision.permission is None
        assert decision.matched_group_ids == ()

    def test_user_cannot_access_shared_kb_even_with_group_intersection(self, patched):
        decision = svc._resolve_permission(
            _record(ingroup_permission="READ_ONLY", group_ids=[1]),
            "u", "t",
            user_groups=[1],
        )
        assert decision.permission is None

    @pytest.mark.parametrize("role", sorted(CAN_EDIT_ALL_USER_ROLES))
    def test_management_roles_can_edit_shared_kb_without_group_access(self, patched, role):
        patched["get_role"].return_value = role

        decision = svc._resolve_permission(
            _record(
                owner_user_id="another-user",
                ingroup_permission="READ_ONLY",
                group_ids=[8],
            ),
            user_id="management-user",
            tenant_id="t",
            user_groups=[7],
        )

        assert decision.permission == "EDIT"
        assert decision.is_management_role is True
        assert decision.matched_group_ids == ()

    def test_unknown_role_cannot_access_shared_kb_even_with_group_intersection(self, patched):
        patched["get_role"].return_value = "UNKNOWN"

        decision = svc._resolve_permission(
            _record(
                owner_user_id="another-user",
                ingroup_permission="READ_ONLY",
                group_ids=[1],
            ),
            user_id="u",
            tenant_id="t",
            user_groups=[1],
        )

        assert decision.permission is None
        assert decision.matched_group_ids == ()

    def test_missing_record_raises_not_found(self, patched):
        with pytest.raises(AidpKbNotFoundError):
            svc._resolve_permission(record={}, user_id="u", tenant_id="t")


# --- require_permission ---------------------------------------------------


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
            patch.object(svc, "_get_user_role", return_value="DEV"), \
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
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "DEV")

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
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "DEV")

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
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "DEV")

        result = svc.get_allowed_kds_list("u", "t")
        assert "edit-1" in result
        assert "read-1" in result
        assert "priv-1" not in result

    def test_get_allowed_kds_list_management_sees_shared_only(self, monkeypatch):
        rows = [
            _record(kb_id="p", ingroup_permission="PRIVATE"),
            _record(kb_id="e", ingroup_permission="EDIT"),
        ]
        monkeypatch.setattr(svc.aidp_permission_db, "list_permissions_by_tenant",
                            lambda tenant_id, page=1, page_size=200: rows)
        monkeypatch.setattr(svc, "_get_user_groups", lambda u, t: [])
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "ADMIN")

        result = svc.get_allowed_kds_list("u", "t")
        assert result == ["e"]


# --- get_accessible_kbs ---------------------------------------------------


class TestGetAccessibleKbs:
    def test_marks_permission_per_row(self, monkeypatch):
        rows = [
            _record(kb_id="creator-kb", owner_user_id="u", ingroup_permission="PRIVATE"),
            _record(kb_id="group-kb", owner_user_id="other", ingroup_permission="READ_ONLY"),
        ]
        monkeypatch.setattr(svc.aidp_permission_db, "list_all_permissions_by_tenant",
                            lambda tenant_id: rows)
        monkeypatch.setattr(svc, "_get_user_groups", lambda u, t: [1])
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "DEV")

        out = svc.get_accessible_kbs("u", "t")
        # Both rows are accessible to DEV:
        #   - creator-kb: owner_user_id == user_id -> EDIT (PRIVATE ignored for owner)
        #   - group-kb:   ingroup_permission=READ_ONLY + no group intersection (user_groups=[1],
        #                 record group_ids default is [1,2]) -> READ_ONLY since 1 is in [1,2]
        assert len(out) == 2
        assert out[0]["permission"] == "EDIT"        # creator -> EDIT regardless of PRIVATE
        assert out[1]["permission"] == "READ_ONLY"   # group intersection grants READ_ONLY

    def test_user_only_sees_own_private_kb(self, monkeypatch):
        rows = [
            _record(kb_id="own", owner_user_id="u", ingroup_permission="PRIVATE"),
            _record(kb_id="shared", owner_user_id="other", ingroup_permission="READ_ONLY"),
        ]
        monkeypatch.setattr(svc.aidp_permission_db, "list_all_permissions_by_tenant",
                            lambda tenant_id: rows)
        monkeypatch.setattr(svc, "_get_user_groups", lambda u, t: [1])
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "USER")

        out = svc.get_accessible_kbs("u", "t")
        assert [row["kb_id"] for row in out] == ["own"]

    def test_management_role_sees_all_shared_rows_but_not_private(self, monkeypatch):
        # Management roles bypass group membership for shared rows, while
        # PRIVATE rows remain visible only to their creator.
        rows = [
            _record(kb_id="editable",   owner_user_id="other", ingroup_permission="EDIT",      group_ids=[1]),
            _record(kb_id="private-kb", owner_user_id="other", ingroup_permission="PRIVATE",   group_ids=[1]),
            _record(kb_id="no-access",  owner_user_id="other", ingroup_permission="READ_ONLY", group_ids=[99]),
        ]
        monkeypatch.setattr(svc.aidp_permission_db, "list_all_permissions_by_tenant",
                            lambda tenant_id: rows)
        monkeypatch.setattr(svc, "_get_user_groups", lambda u, t: [1])
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "ADMIN")

        out = svc.get_accessible_kbs("u", "t")
        assert [r["kb_id"] for r in out] == ["editable", "no-access"]

    def test_count_matches_visible_rows(self, monkeypatch):
        rows = [
            _record(kb_id="public",  owner_user_id="other", ingroup_permission="READ_ONLY", group_ids=[1]),
            _record(kb_id="private", owner_user_id="other", ingroup_permission="PRIVATE",   group_ids=[1]),
            _record(kb_id="no-access", owner_user_id="other", ingroup_permission="READ_ONLY", group_ids=[99]),
        ]
        monkeypatch.setattr(svc.aidp_permission_db, "list_all_permissions_by_tenant",
                            lambda tenant_id: rows)
        monkeypatch.setattr(svc, "_get_user_groups", lambda u, t: [1])
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "DEV")

        assert svc.count_accessible_kbs("u", "t") == 1


class TestIntersectAccessibleKbs:
    def test_intersects_remote_catalog_and_preserves_remote_order(self, monkeypatch):
        rows = [
            _record(kb_id="kb-1", owner_user_id="u"),
            _record(kb_id="kb-2", owner_user_id="u"),
            _record(kb_id="local-only", owner_user_id="u"),
        ]
        monkeypatch.setattr(
            svc.aidp_permission_db,
            "list_all_permissions_by_tenant",
            lambda tenant_id: rows,
        )
        monkeypatch.setattr(svc, "_get_user_groups", lambda u, t: [])
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "USER")

        result = svc.intersect_accessible_kbs(
            [
                {"kds_id": "kb-2", "kds_name": "Remote two"},
                {"kds_id": "remote-only", "kds_name": "Remote only"},
                {"kds_id": "kb-1", "kds_name": "Remote one"},
            ],
            user_id="u",
            tenant_id="t",
        )

        assert [item["kb_id"] for item in result] == ["kb-2", "kb-1"]
        assert [item["kds_name"] for item in result] == ["Remote two", "Remote one"]
        assert all(item["permission"] == "EDIT" for item in result)

    def test_drops_remote_resource_when_user_has_no_local_access(self, monkeypatch):
        rows = [
            _record(
                kb_id="kb-private",
                owner_user_id="another-user",
                ingroup_permission="PRIVATE",
            ),
        ]
        monkeypatch.setattr(
            svc.aidp_permission_db,
            "list_all_permissions_by_tenant",
            lambda tenant_id: rows,
        )
        monkeypatch.setattr(svc, "_get_user_groups", lambda u, t: [])
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "USER")

        result = svc.intersect_accessible_kbs(
            [{"kds_id": "kb-private"}],
            user_id="u",
            tenant_id="t",
        )

        assert result == []

    def test_deduplicates_remote_ids_and_protects_local_permission(self, monkeypatch):
        rows = [_record(kb_id="kb-1", owner_user_id="u")]
        monkeypatch.setattr(
            svc.aidp_permission_db,
            "list_all_permissions_by_tenant",
            lambda tenant_id: rows,
        )
        monkeypatch.setattr(svc, "_get_user_groups", lambda u, t: [])
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "USER")

        result = svc.intersect_accessible_kbs(
            [
                {"kds_id": "kb-1", "permission": "REMOTE", "kds_name": "First"},
                {"kds_id": "kb-1", "kds_name": "Duplicate"},
            ],
            user_id="u",
            tenant_id="t",
        )

        assert len(result) == 1
        assert result[0]["permission"] == "EDIT"
        assert result[0]["kds_name"] == "First"


# ---------------------------------------------------------------------------
# _parse_group_ids gap coverage (lines 100-108)
# ---------------------------------------------------------------------------


class TestParseGroupIds:
    def test_none_returns_empty(self):
        assert svc._parse_group_ids(None) == []

    def test_empty_string_returns_empty(self):
        assert svc._parse_group_ids("") == []

    def test_comma_separated_string(self):
        assert svc._parse_group_ids("1, 2, 3") == [1, 2, 3]

    def test_list_of_ints(self):
        assert svc._parse_group_ids([10, 20]) == [10, 20]

    def test_generator_yields_list(self):
        gen = (x for x in [5, 6])
        assert svc._parse_group_ids(gen) == [5, 6]

    def test_unsupported_type_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported group_ids payload"):
            svc._parse_group_ids(12345)


# ---------------------------------------------------------------------------
# Direct DB passthrough helpers (lines 241-254)
# ---------------------------------------------------------------------------


class TestDbPassthroughHelpers:
    def test_create_permission_delegates_to_db(self, monkeypatch):
        mock_create = MagicMock(return_value=42)
        monkeypatch.setattr(svc.aidp_permission_db, "create_permission", mock_create)
        result = svc.create_permission(kb_id="kb-1", owner_user_id="u", tenant_id="t")
        assert result == 42
        mock_create.assert_called_once()

    def test_update_permission_delegates_to_db(self, monkeypatch):
        mock_update = MagicMock(return_value=True)
        monkeypatch.setattr(svc.aidp_permission_db, "update_permission", mock_update)
        result = svc.update_permission(kb_id="kb-1", tenant_id="t", ingroup_permission="EDIT")
        assert result is True
        mock_update.assert_called_once()

    def test_soft_delete_permission_delegates_to_db(self, monkeypatch):
        mock_delete = MagicMock(return_value=True)
        monkeypatch.setattr(svc.aidp_permission_db, "soft_delete_permission", mock_delete)
        result = svc.soft_delete_permission(kb_id="kb-1", tenant_id="t")
        assert result is True
        mock_delete.assert_called_once()

    def test_update_resource_status_delegates_to_db(self, monkeypatch):
        mock_status = MagicMock(return_value=True)
        monkeypatch.setattr(svc.aidp_permission_db, "update_resource_status", mock_status)
        result = svc.update_resource_status(kb_id="kb-1", tenant_id="t", status="ACTIVE")
        assert result is True
        mock_status.assert_called_once()


# ---------------------------------------------------------------------------
# _get_user_role / _get_user_groups direct calls (lines 129, 133)
# ---------------------------------------------------------------------------


class TestUserLookupHelpers:
    def test_get_user_role_calls_db(self, monkeypatch):
        mock_role = MagicMock(return_value="ADMIN")
        monkeypatch.setattr(svc.user_tenant_db_module, "get_user_role_by_tenant", mock_role)
        result = svc._get_user_role("user-1", "tenant-a")
        assert result == "ADMIN"
        mock_role.assert_called_once_with("user-1", "tenant-a")

    def test_get_user_groups_calls_db(self, monkeypatch):
        mock_groups = MagicMock(return_value=[1, 2, 3])
        monkeypatch.setattr(svc.group_db_module, "query_group_ids_by_user_in_tenant", mock_groups)
        result = svc._get_user_groups("user-1", "tenant-a")
        assert result == [1, 2, 3]
        mock_groups.assert_called_once_with("user-1", "tenant-a")


# ---------------------------------------------------------------------------
# _decision_meets ValueError (line 233)
# ---------------------------------------------------------------------------


class TestDecisionMeets:
    def test_unsupported_required_raises_value_error(self):
        decision = svc.AidpPermissionDecision(
            kb_id="kb-1", tenant_id="t", user_id="u",
            permission="EDIT", is_management_role=False, matched_group_ids=(),
        )
        with pytest.raises(ValueError, match="Unsupported required permission"):
            svc._decision_meets(decision, required="INVALID")

    def test_read_requires_read_only_or_higher(self):
        decision_ro = svc.AidpPermissionDecision(
            kb_id="kb-1", tenant_id="t", user_id="u",
            permission="READ_ONLY", is_management_role=False, matched_group_ids=(),
        )
        decision_none = svc.AidpPermissionDecision(
            kb_id="kb-1", tenant_id="t", user_id="u",
            permission=None, is_management_role=False, matched_group_ids=(),
        )
        assert svc._decision_meets(decision_ro, "READ") is True
        assert svc._decision_meets(decision_none, "READ") is False


# ---------------------------------------------------------------------------
# filter_accessible_kds gap coverage (lines 337, 348-349)
# ---------------------------------------------------------------------------


class TestFilterAccessibleKdsGaps:
    def test_empty_kds_ids_returns_empty(self, monkeypatch):
        # Early exit: empty kds_ids
        assert svc.filter_accessible_kds([], "u", "t") == []

    def test_management_role_drops_other_users_private_records(self, monkeypatch):
        record = {"kb_id": "kb-priv", "owner_user_id": "other",
                  "ingroup_permission": "PRIVATE", "group_ids": [99]}
        monkeypatch.setattr(svc.aidp_permission_db, "get_permission_by_kb_id",
                            lambda *, kb_id, tenant_id: record)
        monkeypatch.setattr(svc, "_get_user_groups", lambda u, t: [])
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "ADMIN")
        result = svc.filter_accessible_kds(["kb-priv"], "admin-user", "t")
        assert result == []

    def test_owner_allows_own_record(self, monkeypatch):
        record = {"kb_id": "kb-own", "owner_user_id": "owner-u",
                  "ingroup_permission": "PRIVATE", "group_ids": [99]}
        monkeypatch.setattr(svc.aidp_permission_db, "get_permission_by_kb_id",
                            lambda *, kb_id, tenant_id: record)
        monkeypatch.setattr(svc, "_get_user_groups", lambda u, t: [])
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "USER")
        result = svc.filter_accessible_kds(["kb-own"], "owner-u", "t")
        assert result == ["kb-own"]


# ---------------------------------------------------------------------------
# require_permission ValueError for unsupported required (line 395)
# ---------------------------------------------------------------------------


class TestRequirePermissionInvalidRequired:
    def test_unsupported_required_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported required permission"):
            svc.require_permission("kb-1", "u", "t", required="INVALID")


# ---------------------------------------------------------------------------
# get_kds_name_to_id_map (lines 381-409)
# ---------------------------------------------------------------------------


class TestGetKdsNameToIdMap:
    """Covers get_kds_name_to_id_map: mirrors get_allowed_kds_list but
    returns {kds_name: kb_id} and skips rows with empty kds_name."""

    def test_returns_empty_dict_when_no_rows(self, monkeypatch):
        monkeypatch.setattr(
            svc.aidp_permission_db, "list_permissions_by_tenant",
            lambda tenant_id, page=1, page_size=200: [],
        )
        monkeypatch.setattr(svc, "_get_user_groups", lambda u, t: [])
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "USER")

        result = svc.get_kds_name_to_id_map("u", "t")
        assert result == {}

    def test_skips_rows_with_empty_kds_name(self, monkeypatch):
        rows = [
            _record(kb_id="kb-1", kds_name="", ingroup_permission="EDIT"),
            _record(kb_id="kb-2", kds_name=None, ingroup_permission="EDIT"),
            _record(kb_id="kb-3", ingroup_permission="EDIT"),
        ]
        monkeypatch.setattr(
            svc.aidp_permission_db, "list_permissions_by_tenant",
            lambda tenant_id, page=1, page_size=200: rows,
        )
        monkeypatch.setattr(svc, "_get_user_groups", lambda u, t: [1])
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "USER")

        result = svc.get_kds_name_to_id_map("u", "t")
        assert result == {}

    def test_management_role_includes_shared_rows_with_name(self, monkeypatch):
        rows = [
            _record(kb_id="kb-1", kds_name="KB One", ingroup_permission="PRIVATE"),
            _record(kb_id="kb-2", kds_name="KB Two", ingroup_permission="EDIT"),
            _record(kb_id="kb-3", kds_name="", ingroup_permission="READ_ONLY"),
        ]
        monkeypatch.setattr(
            svc.aidp_permission_db, "list_permissions_by_tenant",
            lambda tenant_id, page=1, page_size=200: rows,
        )
        monkeypatch.setattr(svc, "_get_user_groups", lambda u, t: [])
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "ADMIN")

        result = svc.get_kds_name_to_id_map("u", "t")
        assert result == {"KB Two": "kb-2"}

    def test_creator_own_private_record_appears_in_map(self, monkeypatch):
        rows = [
            _record(kb_id="kb-priv", kds_name="My KB", owner_user_id="creator",
                    ingroup_permission="PRIVATE"),
        ]
        monkeypatch.setattr(
            svc.aidp_permission_db, "list_permissions_by_tenant",
            lambda tenant_id, page=1, page_size=200: rows,
        )
        monkeypatch.setattr(svc, "_get_user_groups", lambda u, t: [])
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "DEV")

        result = svc.get_kds_name_to_id_map("creator", "t")
        assert result == {"My KB": "kb-priv"}

    def test_read_only_row_included_only_when_group_intersects(self, monkeypatch):
        rows = [
            _record(kb_id="kb-ro", kds_name="RO KB", owner_user_id="other",
                    ingroup_permission="READ_ONLY", group_ids=[10, 20]),
        ]
        monkeypatch.setattr(
            svc.aidp_permission_db, "list_permissions_by_tenant",
            lambda tenant_id, page=1, page_size=200: rows,
        )
        monkeypatch.setattr(svc, "_get_user_groups", lambda u, t: [10])
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "DEV")

        result = svc.get_kds_name_to_id_map("u", "t")
        assert result == {"RO KB": "kb-ro"}

        # No group intersection -> excluded
        monkeypatch.setattr(svc, "_get_user_groups", lambda u, t: [99])
        result = svc.get_kds_name_to_id_map("u", "t")
        assert result == {}

    def test_private_record_excluded_for_non_creator(self, monkeypatch):
        rows = [
            _record(kb_id="kb-priv", kds_name="Private KB", owner_user_id="other",
                    ingroup_permission="PRIVATE", group_ids=[1]),
        ]
        monkeypatch.setattr(
            svc.aidp_permission_db, "list_permissions_by_tenant",
            lambda tenant_id, page=1, page_size=200: rows,
        )
        monkeypatch.setattr(svc, "_get_user_groups", lambda u, t: [1])
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "DEV")

        result = svc.get_kds_name_to_id_map("u", "t")
        assert result == {}

    def test_returns_kds_name_to_kb_id_mapping(self, monkeypatch):
        rows = [
            _record(kb_id="kb-100", kds_name="Alpha", ingroup_permission="EDIT"),
            _record(kb_id="kb-200", kds_name="Beta", ingroup_permission="READ_ONLY"),
        ]
        monkeypatch.setattr(
            svc.aidp_permission_db, "list_permissions_by_tenant",
            lambda tenant_id, page=1, page_size=200: rows,
        )
        monkeypatch.setattr(svc, "_get_user_groups", lambda u, t: [1])
        monkeypatch.setattr(svc, "_get_user_role", lambda u, t: "DEV")

        result = svc.get_kds_name_to_id_map("u", "t")
        assert result["Alpha"] == "kb-100"
        assert result["Beta"] == "kb-200"


# --- intersect_accessible_kbs -------------------------------------------------


class TestIntersectAccessibleKbs:
    def test_order_follows_remote_and_merges_protected_fields(self, patched):
        local_rows = [
            {
                "kb_id": "k1", "kds_name": "Local KB 1", "tenant_id": "t",
                "owner_user_id": "owner", "ingroup_permission": "READ_ONLY",
                "group_ids": [1], "permission": "READ",
            },
            {
                "kb_id": "k2", "kds_name": "Local KB 2", "tenant_id": "t",
                "owner_user_id": "owner", "ingroup_permission": "PRIVATE",
                "group_ids": [], "permission": "EDIT",
            },
        ]
        with patch.object(svc, "_compute_accessible_rows", return_value=local_rows):
            remote = [
                {"kds_id": "k1", "kds_name": "Remote KB 1"},
                {"kds_id": "k2", "kds_name": "Remote KB 2"},
            ]
            result = svc.intersect_accessible_kbs(remote, "u", "t")

        assert [r["kds_id"] for r in result] == ["k1", "k2"]
        assert result[0]["kds_name"] == "Remote KB 1"
        assert result[0]["tenant_id"] == "t"
        assert result[0]["owner_user_id"] == "owner"
        assert result[0]["kb_id"] == "k1"
        assert result[0]["kds_id"] == "k1"

    def test_skips_missing_ids_and_permissionless(self, patched):
        with patch.object(svc, "_compute_accessible_rows", return_value=[]):
            remote = [
                None,
                {"kds_name": "no id"},
                {"kds_id": "k1"},  # no local permission
            ]
            assert svc.intersect_accessible_kbs(remote, "u", "t") == []

    def test_dedupes_remote_ids(self, patched):
        local_rows = [
            {
                "kb_id": "k1", "kds_name": "Local", "tenant_id": "t",
                "owner_user_id": "o", "ingroup_permission": "PUBLIC",
                "group_ids": [], "permission": "READ",
            }
        ]
        with patch.object(svc, "_compute_accessible_rows", return_value=local_rows):
            remote = [
                {"kds_id": "k1"},
                {"id": "k1"},
            ]
            result = svc.intersect_accessible_kbs(remote, "u", "t")

        assert len(result) == 1
        assert result[0]["kds_id"] == "k1"

    def test_treats_int_id_as_string(self, patched):
        local_rows = [
            {
                "kb_id": "7", "kds_name": "Local", "tenant_id": "t",
                "owner_user_id": "o", "ingroup_permission": "PUBLIC",
                "group_ids": [], "permission": "READ",
            }
        ]
        with patch.object(svc, "_compute_accessible_rows", return_value=local_rows):
            result = svc.intersect_accessible_kbs([{"kds_id": 7}], "u", "t")

        assert result[0]["kds_id"] == "7"

    def test_tolerates_missing_optional_protected_local_fields(self, patched):
        local_rows = [{"kb_id": "k1", "permission": "EDIT"}]
        with patch.object(svc, "_compute_accessible_rows", return_value=local_rows):
            result = svc.intersect_accessible_kbs(
                [{"kds_id": "k1", "kds_name": "Remote KB"}],
                "u",
                "t",
            )

        assert result == [{
            "kb_id": "k1",
            "permission": "EDIT",
            "kds_id": "k1",
            "kds_name": "Remote KB",
        }]
