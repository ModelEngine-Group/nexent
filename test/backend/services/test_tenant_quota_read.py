# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-QUOTA-READ-01 prove tenant allocation metadata through real SI."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from management.services.knowledge_base.quota_read import TenantQuotaReader
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import StorageScope

from infrastructure import tenant_quota_read as module
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.cleanse_resources import bind_cleanse_resources
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context


@pytest.fixture
def quota(resources, mocker):  # noqa: F811
    _, update, engine, tables = resources
    engine.update_execution_options(schema_translate_map={"nexent": None})
    module.config_table.create(engine)
    mocker.patch.object(module, "knowledge_table", tables["cleanse_knowledge"])
    actor = ServicePrincipal("user-a", "tenant-a")
    opened, closed = [], []

    @contextmanager
    def ports(principal, *, context):
        assert principal == actor
        identity = bind_cleanse_resources(
            StorageScope(
                "management",
                actor.tenant_id,
                actor.user_id,
                {
                    "cleanse_memberships",
                    "cleanse_accounts",
                },
            ),
            engine,
        )
        handles = [identity]

        def records(tenant):
            opened.append((principal, tenant))
            port = module.bind_tenant_quota_records(principal, tenant, engine)
            handles.append(port)
            return port

        try:
            yield identity, records
        finally:
            for port in handles:
                port.close()
            closed.append(True)

    with engine.begin() as conn:
        conn.execute(tables["cleanse_knowledge"].update().values(quota_limit_bytes=3))
        conn.execute(
            tables["cleanse_knowledge"].insert(),
            [
                {
                    "knowledge_id": i,
                    "tenant_id": tenant,
                    "index_name": "kb-" + str(i),
                    "created_by": "other",
                    "ingroup_permission": "PRIVATE",
                    "knowledge_sources": "datamate" if i == 3 else "elasticsearch",
                    "quota_limit_bytes": amount,
                    "delete_flag": flag,
                }
                for i, tenant, amount, flag in [
                    (2, "tenant-a", 7, "N"),
                    (3, "tenant-a", 0, "N"),
                    (4, "tenant-a", 99, "Y"),
                    (5, "tenant-b", 50, "N"),
                ]
            ],
        )
        conn.execute(
            module.config_table.insert(),
            [
                {
                    "tenant_config_id": i,
                    "tenant_id": tenant,
                    "config_key": key,
                    "config_value": value,
                    "delete_flag": flag,
                }
                for i, tenant, key, value, flag in [
                    (1, "tenant-a", "KB_QUOTA_TENANT_HARD_LIMIT_BYTES", "20", "N"),
                    (2, "tenant-a", "KB_QUOTA_HARD_LIMIT_EDITABLE", "false", "N"),
                    (3, "tenant-a", "KB_QUOTA_WARNING_ENABLED", "FALSE", "N"),
                    (4, "tenant-a", "KB_QUOTA_WARNING_THRESHOLD_PCT", "broken", "N"),
                    (5, "tenant-a", "KB_QUOTA_CRITICAL_THRESHOLD_PCT", "0", "N"),
                ]
            ],
        )
    service = TenantQuotaReader(ports=ports)
    return SimpleNamespace(**locals())


def test_read_includes_private_other_users_and_datamate_without_body_dac(quota):
    s = quota
    result = s.service.read("tenant-a", s.actor, context=context())
    assert result["hard_limit_bytes"] == 20 and result["hard_limit_editable"] is False
    assert (
        result["warning_enabled"] is False
        and result["warning_threshold_pct"] == 80
        and result["critical_threshold_pct"] == 0
    )
    assert (
        result["summary"]["soft_allocated_total_bytes"] == 10
        and result["summary"]["kb_count"] == 3
    )
    assert (
        result["summary"]["kbs_with_quota"] == 3
        and result["summary"]["oversubscription_ratio"] == 0.5
    )
    assert result["summary"]["total_bytes"] is None
    assert s.opened == [(s.actor, "tenant-a")] and s.closed == [True]


def test_foreign_user_cannot_open_resource_namespace(quota):
    s = quota
    with pytest.raises(ScopeDenied):
        s.service.read("tenant-b", s.actor, context=context())
    assert not s.opened and s.closed == [True]


def test_own_user_is_allowed_but_foreign_admin_is_not(quota):
    s = quota
    s.update("cleanse_accounts", user_roles=["USER"])
    assert (
        s.service.read("tenant-a", s.actor, context=context())["summary"]["kb_count"]
        == 3
    )
    s.update("cleanse_accounts", user_roles=["ADMIN"])
    with pytest.raises(ScopeDenied):
        s.service.read("tenant-b", s.actor, context=context())
    assert s.opened == [(s.actor, "tenant-a")]


def test_authorization_revoked_before_response_refuses_cross_tenant(quota, mocker):
    s = quota
    s.update("cleanse_accounts", user_roles=["SU"])
    original = s.service._authorize
    count = []

    def authorize(*args):
        count.append(True)
        if len(count) == 2:
            s.update("cleanse_accounts", user_roles=["DEV"])
        return original(*args)

    mocker.patch.object(s.service, "_authorize", side_effect=authorize)
    with pytest.raises(ScopeDenied):
        s.service.read("tenant-b", s.actor, context=context())
    assert len(count) == 2 and s.opened == [(s.actor, "tenant-b")]


def test_metadata_port_cannot_write_quota_records(quota):
    from nexent.storage.models import FieldPatch

    s = quota
    records = module.bind_tenant_quota_records(s.actor, "tenant-a", s.engine)
    try:
        with pytest.raises(ScopeDenied):
            records.patch(
                module.CATALOG,
                1,
                FieldPatch(set_values={"quota_limit_bytes": 999}),
                expected=None,
                context=context(),
            )
    finally:
        records.close()


@pytest.mark.parametrize("role", ["SU", "ASSET_OWNER"])
def test_foreign_privileged_read_retains_actual_actor(quota, role):
    s = quota
    s.update("cleanse_accounts", user_roles=[role])
    result = s.service.read("tenant-b", s.actor, context=context())
    assert (
        result["hard_limit_bytes"] is None
        and result["summary"]["soft_allocated_total_bytes"] == 50
    )
    assert result["summary"]["kb_count"] == 1 and s.opened == [(s.actor, "tenant-b")]


@pytest.mark.parametrize("dataset", ["cleanse_memberships", "cleanse_accounts"])
def test_disabled_identity_never_reads_quota_records(quota, dataset):
    s = quota
    s.update(dataset, delete_flag="Y")
    with pytest.raises(ScopeDenied):
        s.service.read("tenant-a", s.actor, context=context())
    assert not s.opened


def test_duplicate_config_keeps_first_and_deleted_config_does_not_override(quota):
    s = quota
    with s.engine.begin() as conn:
        conn.execute(
            module.config_table.insert(),
            [
                {
                    "tenant_config_id": i,
                    "tenant_id": "tenant-a",
                    "config_key": "KB_QUOTA_TENANT_HARD_LIMIT_BYTES",
                    "config_value": value,
                    "delete_flag": flag,
                }
                for i, value, flag in [(6, "99", "N"), (7, "100", "Y")]
            ],
        )
    assert (
        s.service.read("tenant-a", s.actor, context=context())["hard_limit_bytes"] == 20
    )
