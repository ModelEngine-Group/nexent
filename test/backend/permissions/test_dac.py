"""Unit tests for the resource access control decision engine."""

import pytest
from permissions.dac import ResourceAccessControl, _normalize_group_ids
from permissions.models import Resource


def _resource(**overrides):
    defaults = {
        "resource_type": "knowledge_base",
        "resource_id": "kb-1",
        "tenant_id": "tenant-1",
        "created_by": "creator-1",
        "ingroup_permission": "READ_ONLY",
        "group_ids": [10, 20],
    }
    defaults.update(overrides)
    return Resource(**defaults)


def _check(resource, user_id="u-1", role="USER", groups=None, user_tenant_id="tenant-1"):
    return ResourceAccessControl.check(
        resource=resource,
        user_id=user_id,
        role=role,
        user_groups=groups or [],
        user_tenant_id=user_tenant_id,
    )


class TestCreatorFirst:
    @pytest.mark.parametrize("role", ["USER", "DEV", "ADMIN", "SU", "SPEED"])
    def test_creator_always_gets_full_access(self, role):
        access = _check(
            _resource(ingroup_permission="PRIVATE", group_ids=None),
            user_id="creator-1",
            role=role,
            groups=[10],
        )
        assert access.permission_label == "CREATOR"
        assert access.can_read
        assert access.can_edit
        assert access.is_creator

    def test_creator_group_matching_is_recorded(self):
        access = _check(
            _resource(group_ids=[10, 20]),
            user_id="creator-1",
            groups=[20, 30],
        )
        assert access.permission_label == "CREATOR"
        assert access.matched_groups == ["20"]


class TestManagementRoles:
    @pytest.mark.parametrize("role", ["ADMIN", "SU", "SPEED", "ASSET_OWNER"])
    def test_management_roles_can_edit_shared_kb(self, role):
        access = _check(_resource(ingroup_permission="EDIT", group_ids=[10]), role=role)
        assert access.permission_label == "EDIT"
        assert access.can_read
        assert access.can_edit

    @pytest.mark.parametrize("role", ["ADMIN", "SU", "SPEED", "ASSET_OWNER"])
    def test_management_roles_denied_on_private_kb(self, role):
        access = _check(
            _resource(ingroup_permission="PRIVATE", group_ids=None),
            user_id="other-user",
            role=role,
        )
        assert access.permission_label is None
        assert not access.can_read
        assert not access.can_edit

    def test_asset_owner_record_read_only_for_admin_dev_speed(self):
        resource = _resource(tenant_id="asset_owner_tenant_id")
        for role in ["ADMIN", "SU", "SPEED", "DEV"]:
            access = _check(resource, role=role)
            assert access.permission_label == "READ_ONLY"

    def test_asset_owner_record_edit_for_asset_owner(self):
        access = _check(
            _resource(tenant_id="asset_owner_tenant_id"),
            role="ASSET_OWNER",
        )
        assert access.permission_label == "EDIT"

    def test_asset_owner_record_denied_for_user(self):
        access = _check(
            _resource(tenant_id="asset_owner_tenant_id"),
            role="USER",
        )
        assert access.permission_label is None


class TestGroupAndTenantRules:
    def test_cross_tenant_denied(self):
        access = _check(
            _resource(tenant_id="tenant-a"),
            user_tenant_id="tenant-b",
        )
        assert access.permission_label is None

    def test_no_user_tenant_denied(self):
        access = _check(
            _resource(),
            user_tenant_id="",
        )
        assert access.permission_label is None

    def test_datamate_creator_is_read_only(self):
        access = _check(
            _resource(knowledge_sources="datamate", ingroup_permission="PRIVATE"),
            user_id="creator-1",
            role="USER",
        )
        assert access.permission_label == "READ_ONLY"

    def test_datamate_same_tenant_user_non_owner_denied(self):
        access = _check(
            _resource(knowledge_sources="datamate", ingroup_permission="READ_ONLY"),
            user_id="other-user",
            role="USER",
        )
        assert access.permission_label is None

    @pytest.mark.parametrize("role", ["DEV", "ADMIN", "SU"])
    def test_datamate_same_tenant_non_user_is_read_only(self, role):
        access = _check(
            _resource(knowledge_sources="datamate", ingroup_permission="PRIVATE"),
            user_id="other-user",
            role=role,
        )
        assert access.permission_label == "READ_ONLY"

    @pytest.mark.parametrize("role", ["USER", "DEV", "ADMIN", "SU"])
    def test_datamate_cross_tenant_denied(self, role):
        access = _check(
            _resource(tenant_id="tenant-a", knowledge_sources="datamate"),
            user_id="creator-1",
            role=role,
            user_tenant_id="tenant-b",
        )
        assert access.permission_label is None

    def test_private_denied_for_non_member_user(self):
        access = _check(
            _resource(ingroup_permission="PRIVATE", group_ids=[10]),
            user_id="other-user",
            groups=[99],
        )
        assert access.permission_label is None

    @pytest.mark.parametrize(
        "permission,expected",
        [("EDIT", "EDIT"), ("READ_ONLY", "READ_ONLY"), ("read_only", "READ_ONLY")],
    )
    def test_group_intersection_grants_permission(self, permission, expected):
        access = _check(
            _resource(ingroup_permission=permission, group_ids=[10, 20]),
            user_id="member-user",
            role="DEV",
            groups=[20, 30],
        )
        assert access.permission_label == expected

    def test_no_group_intersection_denied(self):
        access = _check(
            _resource(ingroup_permission="EDIT", group_ids=[10]),
            user_id="member-user",
            role="DEV",
            groups=[99],
        )
        assert access.permission_label is None

    def test_empty_groups_legacy_intersection(self):
        access = _check(
            _resource(ingroup_permission="READ_ONLY", group_ids=None),
            user_id="legacy-user",
            role="DEV",
            groups=[],
        )
        assert access.permission_label == "READ_ONLY"

    def test_empty_permission_defaults_to_read_only(self):
        access = _check(
            _resource(ingroup_permission=None, group_ids=None),
            user_id="legacy-user",
            role="DEV",
            groups=[],
        )
        assert access.permission_label == "READ_ONLY"

    def test_unknown_role_denied(self):
        access = _check(
            _resource(ingroup_permission="EDIT", group_ids=[10]),
            user_id="other-user",
            role="GUEST",
            groups=[10],
        )
        assert access.permission_label is None


class TestNormalizeGroupIds:
    def test_none(self):
        assert _normalize_group_ids(None) == []

    def test_empty_string(self):
        assert _normalize_group_ids("") == []

    def test_int_list_string(self):
        assert _normalize_group_ids("[1, 2, 3]") == [1, 2, 3]

    def test_csv_string(self):
        assert _normalize_group_ids("1,2") == [1, 2]

    def test_non_numeric_string_kept_as_text(self):
        assert _normalize_group_ids("g-a,g-b") == ["g-a", "g-b"]

    def test_list_with_none_filtered(self):
        assert _normalize_group_ids([1, None, 2]) == [1, 2]
