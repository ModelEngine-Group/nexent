# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Unit regressions for Workbench catalog scope and effective IDs."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb import workbench_skill_records as records


ACTOR = ServicePrincipal("member", "tenant")


def skill(skill_id, *, created_by="owner", source="custom", permission="PRIVATE"):
    return SimpleNamespace(
        skill_id=skill_id, skill_name="report", skill_description="", config_schemas=[], config_values={},
        source=source, created_by=created_by, group_ids="", ingroup_permission=permission,
    )


@pytest.fixture
def session(mocker):
    db = mocker.Mock()
    db.scalar.return_value = 1
    db.execute.side_effect = [[(1, {"format": "published"})], [(1, 15), (1, 10)]]
    db.scalars.return_value = [skill(1)]
    mocker.patch.object(records, "get_db_session", return_value=nullcontext(db))
    mocker.patch.object(records, "tenant_membership_matches", return_value=True)
    mocker.patch.object(records, "get_user_role_by_tenant", return_value=("USER",))
    mocker.patch.object(records, "query_group_ids_by_user_in_tenant", return_value=[])
    return db


def test_published_default_uses_platform_scope_and_skips_tenant_acl(session, mocker):
    visibility = mocker.patch.object(records, "can_view_skill")
    rows = records.read_workbench_skill_rows(7, 3, ACTOR, {}, {1})
    assert rows[1]["owner_tenant_id"] == ASSET_OWNER_TENANT_ID
    assert rows[1]["config"] == {"format": "published"}
    assert rows[1]["tool_ids"] == [10, 15]
    assert session.scalar.call_count == 1
    assert session.scalar.call_args.args[1] == {
        "agent_id": 7, "version_no": 3, "owner": ASSET_OWNER_TENANT_ID,
    }
    assert (1, ASSET_OWNER_TENANT_ID) in next(iter(session.scalars.call_args.args[0].compile().params.values()))
    visibility.assert_not_called()


def test_no_published_workbench_identity_stops_before_catalog_read(session):
    session.scalar.return_value = None
    assert records.read_workbench_skill_rows(7, 3, ACTOR, {}, {1}) == {}
    session.execute.assert_not_called()
    session.scalars.assert_not_called()


def test_invalid_membership_stops_before_platform_lookup(session, mocker):
    mocker.patch.object(records, "tenant_membership_matches", return_value=False)
    assert records.read_workbench_skill_rows(7, 3, ACTOR, {}, {1}) == {}
    session.scalar.assert_not_called()


@pytest.mark.parametrize(("explicit_owner", "expected_ids", "result_ids"), [
    ("member", {2}, {2}),
    ("member", {1, 2}, set()),
    ("member", {1}, set()),
    ("other-user", {2}, set()),
])
def test_signed_ids_must_match_the_authorized_winner(session, explicit_owner, expected_ids, result_ids):
    session.execute.side_effect = [[(1, {"format": "published"})], [(2, 20)]]
    session.scalars.return_value = [skill(1), skill(2, created_by=explicit_owner)]
    rows = records.read_workbench_skill_rows(7, 3, ACTOR, {2: {}}, expected_ids)
    assert rows.keys() == result_ids
    if result_ids:
        assert rows[2]["owner_tenant_id"] == ACTOR.tenant_id
        assert rows[2]["config"] == {}
        assert rows[2]["tool_ids"] == [20]
    else:
        assert session.execute.call_count == 1


def test_absent_tenant_mount_cannot_fall_back_to_platform_default(session):
    assert records.read_workbench_skill_rows(7, 3, ACTOR, {2: {}}, {1}) == {}
    assert session.execute.call_count == 1
