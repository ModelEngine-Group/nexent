# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Explicit source evidence is pinned atomically with admission and can be restored before execution."""

from types import SimpleNamespace

import pytest
from management.services.knowledge_base.ingestion_journal import IngestionJournal
from nexent.core.concurrency import run_blocking
from nexent.storage.errors import Conflict
from nexent.storage.models import FieldPatch

from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_legacy_ingestion_migration import (
    migration as migration,  # noqa: PLC0414
)
from test.backend.services.test_legacy_ingestion_migration import (
    records as records,  # noqa: PLC0414
)
from test.backend.services.test_legacy_ingestion_migration import (
    resources as resources,  # noqa: PLC0414
)
from test.backend.services.test_legacy_ingestion_migration import (
    setup as setup,  # noqa: PLC0414
)
from test.backend.services.test_legacy_ingestion_migration import (
    sqlite_threads as sqlite_threads,  # noqa: PLC0414
)

FIELDS = ('source_space', 'source_key', 'source_revision', 'source_sha256', 'file_size', 'storage_object_id')
ISSUES = ['SOURCE_SPACE_UNPINNED', 'SOURCE_KEY_UNPINNED', 'SOURCE_REVISION_UNPINNED',
    'SOURCE_HASH_UNPINNED', 'SOURCE_SIZE_UNPINNED', 'LEDGER_LINK_UNBOUND']


@pytest.fixture
async def unpinned(migration):
    m = migration
    s = m.s
    await run_blocking('fixture', s.port.patch, 'knowledge_ingestion_files', s.value.file_id,
        FieldPatch(set_values={name: None for name in FIELDS if name != 'storage_object_id'}), context=context(), lane='control-io')
    s.update('cleanse_files', **{name: None for name in FIELDS[:4]})
    original = m.source.page.side_effect
    def evidence(*args, **kwargs):
        page = original(*args, **kwargs)
        finding = page.files[0].model_dump()
        finding.update(issues=ISSUES.copy(), observed_size=10, candidate_storage_object_id=1)
        page.files[0] = type(page.files[0]).model_validate(finding)
        return page
    m.source.page.side_effect = evidence
    return SimpleNamespace(m=m, s=s)


async def test_default_still_rejects_unpinned_sources(unpinned):
    u = unpinned
    with pytest.raises(Conflict):
        await u.m.service.plan(1, u.s.value.file_id, u.s.actor, legacy_quiesced=True, context=context())
    assert u.s.row()['ingestion_request'] is None


async def test_binding_and_admission_share_one_cas_and_restore_original_fields(unpinned):
    u = unpinned
    before = u.s.row()
    plan = await u.m.service.plan(1, u.s.value.file_id, u.s.actor, legacy_quiesced=True,
        bind_observed_source=True, context=context())
    assert u.s.row() == before
    assert plan.source == u.s.value.source
    assert plan.legacy_snapshot.source_binding.storage_object_id == 1
    row = await u.m.service.admit(plan, u.s.actor, context=context())
    assert row['version'] == before['version']+1 and row['stage'] == 'INGEST_ACCEPTED'
    assert row['source_revision'] == plan.source.version and row['source_sha256'] == plan.source.sha256
    assert row['file_size'] == 10 and row['storage_object_id'] == 1
    assert row['source_generation'] == before['source_generation'] and row['created_by'] == before['created_by']
    # The UT uses separate resource and journal stores; keep its read projection in sync.
    u.s.update('cleanse_files', **{name: row[name] for name in FIELDS[:4]})
    calls = u.m.source.page.call_count
    assert await u.m.service.admit(plan, u.s.actor, context=context()) == row
    assert u.m.source.page.call_count == calls
    restored = await u.m.service.restore(plan, u.s.actor, context=context())
    assert restored['version'] == before['version']+2 and restored['ingestion_request'] is None
    assert {name: restored[name] for name in FIELDS} == {name: before[name] for name in FIELDS}
    u.s.update('cleanse_files', **{name: restored[name] for name in FIELDS[:4]})
    assert await u.m.service.restore(plan, u.s.actor, context=context()) == restored


@pytest.mark.parametrize('change', ['ledger', 'size', 'source', 'finding'])
async def test_admission_rejects_changed_source_evidence_without_binding(unpinned, change):
    u = unpinned
    plan = await u.m.service.plan(1, u.s.value.file_id, u.s.actor, legacy_quiesced=True,
        bind_observed_source=True, context=context())
    original = u.m.source.page.side_effect
    def changed(*args, **kwargs):
        page = original(*args, **kwargs)
        item = page.files[0]
        if change == 'ledger': item.candidate_storage_object_id = 2
        elif change == 'size': item.observed_size = 11
        elif change == 'source': item.candidate_source = item.candidate_source.model_copy(update={'version': 'etag:changed'})
        else: item.issues.append('LEDGER_LINK_MISMATCH')
        return page
    u.m.source.page.side_effect = changed
    with pytest.raises(Conflict): await u.m.service.admit(plan, u.s.actor, context=context())
    assert u.s.row()['ingestion_request'] is None and u.s.row()['source_revision'] is None


async def test_child_reservation_forbids_restoring_unbound_source_fields(unpinned):
    u = unpinned
    plan = await u.m.service.plan(1, u.s.value.file_id, u.s.actor, legacy_quiesced=True,
        bind_observed_source=True, context=context())
    row = await u.m.service.admit(plan, u.s.actor, context=context())
    u.s.update('cleanse_files', **{name: row[name] for name in FIELDS[:4]})
    await run_blocking('fixture', IngestionJournal(u.s.port).begin_cleanse, row, context=context(), lane='control-io')
    with pytest.raises(Conflict): await u.m.service.restore(plan, u.s.actor, context=context())
    assert u.s.row()['source_revision'] == plan.source.version
    assert u.s.row()['stage'] == 'CLEANSE_SUBMITTING'
