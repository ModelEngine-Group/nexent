# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-SUM-META-01 exercise scoped SI summary operations and live DAC."""

from contextlib import contextmanager
from time import monotonic
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from contracts.knowledge_summary import SUMMARY_DATASET, SUMMARY_MODEL_DATASET
from management.services.knowledge_base import summary_metadata as module
from nexent.storage.errors import Conflict, NotFound, OutcomeUnknown, ScopeDenied
from nexent.storage.models import OperationContext, StorageScope, WriteOutcome

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.knowledge_collection_metadata import bind_collection_metadata
from infrastructure.rdb.knowledge_deletion_metadata import knowledge
from infrastructure.rdb.knowledge_summary import bind_summary_records
from infrastructure.rdb.tenant_config_record import TenantConfig


@pytest.fixture
def storage(mocker):
    engine = sa.create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=sa.pool.StaticPool,
        execution_options={"schema_translate_map": {"nexent": None}},
    )
    knowledge.create(engine)
    TenantConfig.__table__.create(engine)
    actor = ServicePrincipal("reader", "tenant-a")
    roles, groups, opened = ["DEV"], [5], []
    identity = mocker.patch.object(
        module,
        "metadata_identity",
        side_effect=lambda *a, **kw: (
            {"tenant_id": actor.tenant_id},
            tuple(roles),
            groups,
        ),
    )

    @contextmanager
    def identities(principal, *, context):
        assert principal == actor
        handles = []

        def resources(*, cross_tenant):
            port = bind_collection_metadata(actor, engine, cross_tenant=cross_tenant)
            handles.append(port)
            return port

        try:
            yield None, None, resources
        finally:
            for port in handles:
                port.close()

    @contextmanager
    def ports(tenant, user, *, context, models=False):
        assert user == actor.user_id
        port = bind_summary_records(
            StorageScope(
                "management",
                tenant,
                user,
                {SUMMARY_DATASET, SUMMARY_MODEL_DATASET}
                if models
                else {SUMMARY_DATASET},
            ),
            engine,
        )
        opened.append(port.scope)
        try:
            yield port, None
        finally:
            port.close()

    with engine.begin() as conn:
        for key, tenant, owner, permission, source in [
            (1, "tenant-a", "reader", "PRIVATE", "elasticsearch"),
            (2, "tenant-a", "other", "PRIVATE", "elasticsearch"),
            (3, "tenant-a", "other", "READ_ONLY", "elasticsearch"),
            (4, "tenant-b", "reader", "PRIVATE", "elasticsearch"),
            (5, ASSET_OWNER_TENANT_ID, "owner", "READ_ONLY", "elasticsearch"),
            (6, "tenant-a", "reader", "EDIT", "datamate"),
        ]:
            conn.execute(
                knowledge.insert(),
                {
                    "knowledge_id": key,
                    "tenant_id": tenant,
                    "index_name": f"kb-{key}",
                    "created_by": owner,
                    "updated_by": owner,
                    "ingroup_permission": permission,
                    "group_ids": "5",
                    "knowledge_sources": source,
                    "knowledge_describe": "Old summary",
                    "delete_flag": "N",
                    "version": 1,
                },
            )
    service = module.SummaryMetadata(ports=ports, identities=identities)
    yield SimpleNamespace(**locals())
    engine.dispose()


def context():
    return OperationContext("summary-metadata-unit", monotonic() + 10)


def test_read_original_response_and_empty_summary(storage):
    s = storage
    assert s.service.read("kb-1", s.actor, context=context()) == {
        "status": "success",
        "message": "Index kb-1 summary retrieved successfully",
        "summary": "Old summary",
    }
    with s.engine.begin() as conn:
        conn.execute(
            knowledge.update()
            .where(knowledge.c.knowledge_id == 1)
            .values(knowledge_describe=None)
        )
    assert s.service.read("kb-1", s.actor, context=context())["summary"] is None


def test_update_is_atomic_audited_and_does_not_enable_schedule(storage):
    s = storage
    assert s.service.update("kb-1", "New summary", s.actor, context=context()) == {
        "status": "success",
        "message": "Index kb-1 summary updated successfully",
        "summary": "New summary",
    }
    with s.engine.connect() as conn:
        row = (
            conn.execute(sa.select(knowledge).where(knowledge.c.knowledge_id == 1))
            .mappings()
            .one()
        )
    assert (
        row["knowledge_describe"] == "New summary"
        and row["last_summary_time"] is not None
    )
    assert (
        row["version"] == 2
        and row["updated_by"] == "reader"
        and row["created_by"] == "reader"
    )
    assert row["summary_schedule"] is None and row["summary_frequency"] is None


@pytest.mark.parametrize(
    "key,edit,allowed",
    [
        (1, False, True),
        (2, False, False),
        (3, False, True),
        (3, True, False),
        (5, False, True),
        (5, True, False),
        (6, False, True),
        (6, True, False),
        (4, False, False),
    ],
)
def test_read_write_dac_including_shared_and_datamate(storage, key, edit, allowed):
    s = storage

    def operation():
        return (
            s.service.update(f"kb-{key}", "New", s.actor, context=context())
            if edit
            else s.service.read(f"kb-{key}", s.actor, context=context())
        )

    if allowed:
        assert operation()["status"] == "success"
    else:
        with pytest.raises((ScopeDenied, NotFound)):
            operation()


def test_su_cross_tenant_keeps_actual_actor_and_target_restriction(storage):
    s = storage
    s.roles[:] = ["SU"]
    assert (
        s.service.read("kb-4", s.actor, target_tenant="tenant-b", context=context())[
            "summary"
        ]
        == "Old summary"
    )
    assert s.opened[-1].tenant_id == "tenant-b" and s.opened[-1].actor_id == "reader"
    with pytest.raises(NotFound):
        s.service.read("kb-4", s.actor, target_tenant="tenant-a", context=context())


def test_ambiguous_missing_and_deleting_catalog_are_rejected(storage):
    s = storage
    with pytest.raises(NotFound):
        s.service.read("missing", s.actor, context=context())
    with s.engine.begin() as conn:
        conn.execute(
            knowledge.update()
            .where(knowledge.c.knowledge_id == 5)
            .values(index_name="kb-1")
        )
    with pytest.raises(ScopeDenied):
        s.service.read("kb-1", s.actor, context=context())
    with s.engine.begin() as conn:
        conn.execute(
            knowledge.update()
            .where(knowledge.c.knowledge_id == 1)
            .values(deletion_request={"request_id": "deleting"})
        )
    with pytest.raises(ScopeDenied):
        s.service.read("kb-1", s.actor, target_tenant="tenant-a", context=context())


def test_identity_failure_before_data_and_revocation_before_commit(storage):
    s = storage
    s.identity.side_effect = ScopeDenied()
    with pytest.raises(ScopeDenied):
        s.service.read("kb-1", s.actor, context=context())
    assert not s.opened
    s.identity.side_effect = [({"tenant_id": "tenant-a"}, ("DEV",), [5]), ScopeDenied()]
    with pytest.raises(ScopeDenied):
        s.service.update("kb-1", "Rejected", s.actor, context=context())
    with s.engine.connect() as conn:
        assert (
            conn.execute(
                sa.select(knowledge.c.knowledge_describe).where(
                    knowledge.c.knowledge_id == 1
                )
            ).scalar_one()
            == "Old summary"
        )


def test_deadline_before_any_io(storage):
    with pytest.raises(Exception) as error:
        storage.service.read(
            "kb-1", storage.actor, context=OperationContext("expired", monotonic() - 1)
        )
    assert type(error.value).__name__ == "DeadlineExceeded"
    assert not storage.opened


@pytest.mark.parametrize(
    "outcome,matched,error",
    [
        (WriteOutcome.UNKNOWN, False, OutcomeUnknown),
        (WriteOutcome.CONFIRMED, False, Conflict),
    ],
)
def test_unconfirmed_write_has_no_retry_or_success(
    storage, mocker, outcome, matched, error
):
    s = storage
    patch = mocker.patch(
        "infrastructure.rdb.record_store.SQLRecordStore.patch",
        return_value=SimpleNamespace(outcome=outcome, matched=matched),
    )
    with pytest.raises(error):
        s.service.update("kb-1", "New", s.actor, context=context())
    assert patch.call_count == 1
    with s.engine.connect() as conn:
        assert (
            conn.execute(
                sa.select(knowledge.c.knowledge_describe).where(
                    knowledge.c.knowledge_id == 1
                )
            ).scalar_one()
            == "Old summary"
        )
