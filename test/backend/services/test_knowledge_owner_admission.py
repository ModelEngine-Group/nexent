# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-OWNER-03: exact owner cleanup is persisted before account revocation."""

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from contracts.knowledge_admission import KNOWLEDGE_ADMISSION_DATASET as KB
from contracts.knowledge_admission import UPLOAD_ADMISSION_DATASET as FILES
from contracts.knowledge_admission import KnowledgeOwnerCleanup
from management.services.knowledge_base import base_deletion as module
from nexent.storage.errors import Conflict, ScopeDenied
from nexent.storage.models import FieldPatch

from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_ingestion_coordinator import (
    sqlite_threads,  # noqa: F401
)
from test.backend.services.test_knowledge_upload_admission import (
    admission,  # noqa: F401
)


@pytest.fixture
def owned(sqlite_threads, admission, monkeypatch):  # noqa: F811
    s = admission
    s.update('cleanse_knowledge', created_by='owner', ingroup_permission='PRIVATE')
    with s.engine.begin() as conn:
        conn.execute(s.knowledge.update().values(created_by='owner', ingroup_permission='PRIVATE', knowledge_sources='elasticsearch'))
    grant = KnowledgeOwnerCleanup(owner_user_id='owner', actor_tenant_id='operator-tenant', purpose='user_deletion')
    authorizer = Mock(return_value=grant)
    monkeypatch.setattr(module, 'authorize_owner_cleanup_admission', authorizer)
    return s, authorizer


def admit(s):
    return module.request_knowledge_base_owner_deletion(s.records, s.authorized, 'kb-one', 'owner', 'user_deletion',
                                                        s.actor, context=context())


def test_dedicated_intent_records_actual_actor_and_exact_owner(owned):
    s, authorizer = owned
    row = admit(s)
    assert row['deletion_request']['user_id'] == 'user-a'
    assert row['deletion_request']['owner_cleanup'] == {
        'purpose': 'user_deletion', 'owner_user_id': 'owner', 'actor_tenant_id': 'operator-tenant',
    }
    assert row['deletion_request']['phase'] == 'files'
    authorizer.assert_called_once()


def test_reentry_uses_existing_exact_intent_after_identity_deletion(owned):
    s, authorizer = owned
    row = admit(s)
    s.update('cleanse_memberships', delete_flag='Y')
    assert admit(s) == row
    authorizer.assert_called_once()
    with pytest.raises(ScopeDenied):
        module.request_knowledge_base_deletion(s.records, s.authorized, 'kb-one', s.actor, context=context())


def test_admission_refusal_does_not_persist_any_grant(owned):
    s, authorizer = owned
    authorizer.side_effect = ScopeDenied()
    with pytest.raises(ScopeDenied):
        admit(s)
    assert s.records.get(KB, 1, context=context())['deletion_request'] is None


def test_actual_parent_owner_changed_during_admission_is_rejected(owned):
    s, _ = owned
    with s.engine.begin() as conn:
        conn.execute(s.knowledge.update().values(created_by='different-owner'))
    with pytest.raises(ScopeDenied):
        admit(s)
    assert s.records.get(KB, 1, context=context())['deletion_request'] is None


def test_other_persisted_issuer_cannot_be_replaced(owned):
    s, _ = owned
    row = admit(s)
    s.records.patch(KB, 1, FieldPatch(set_values={
        'deletion_request': {**row['deletion_request'], 'user_id': 'original-issuer'},
    }), expected=None, context=context())
    with pytest.raises((ScopeDenied, Conflict)):
        admit(s)
    assert s.records.get(KB, 1, context=context())['deletion_request']['user_id'] == 'original-issuer'


def test_deprovision_admits_inflight_files_without_rewriting_their_stage(owned):
    s, _ = owned
    values = {key: value for key, value in s.spec().items() if key != 'created_by'}
    s.records.create(FILES, {**values, 'status': 'PROCESSING', 'stage': 'CLEANSE_PENDING',
                             'source_generation': 0, 'processing_attempt': 0}, context=context())
    row = admit(s)
    assert row['deletion_request']['owner_cleanup']['owner_user_id'] == 'owner'
    file = s.records.get(FILES, 'a' * 32, context=context())
    assert file['status'] == 'PROCESSING' and file['stage'] == 'CLEANSE_PENDING'


def test_same_actual_owner_can_upgrade_own_parent_with_fresh_deprovision_authority(admission, monkeypatch):  # noqa: F811
    s = admission
    s.update('cleanse_knowledge', ingroup_permission='PRIVATE')
    with s.engine.begin() as connection:
        connection.execute(s.knowledge.update().values(ingroup_permission='PRIVATE', knowledge_sources='elasticsearch'))
    original = module.request_knowledge_base_deletion(s.records, s.authorized, 'kb-one', s.actor, context=context())
    grant = KnowledgeOwnerCleanup(owner_user_id='user-a', actor_tenant_id='tenant-a', purpose='user_deletion')
    authorize = Mock(return_value=grant)
    monkeypatch.setattr(module, 'authorize_owner_cleanup_admission', authorize)
    row = module.request_knowledge_base_owner_deletion(s.records, s.authorized, 'kb-one', 'user-a', 'user_deletion',
                                                       s.actor, context=context())
    assert row['deletion_request']['user_id'] == original['deletion_request']['user_id'] == 'user-a'
    assert row['deletion_request']['owner_cleanup'] == grant.model_dump(mode='json')
    assert row['version'] == original['version'] + 1
    authorize.assert_called_once()


def test_prepare_entry_persists_authority_without_any_runtime_submission(owned, monkeypatch):
    from management.services.knowledge_base.base_deletion_coordinator import (
        KnowledgeBaseDeletionCoordinator,
    )

    s, authorizer = owned

    @contextmanager
    def ports(actor, *, context):
        assert actor == s.actor
        yield s.records, s.authorized

    async def blocking(name, fn, *args, **kwargs):
        kwargs.pop('lane')
        kwargs.pop('owner')
        return await asyncio.to_thread(fn, *args, **kwargs)

    monkeypatch.setattr('management.services.knowledge_base.base_deletion_coordinator.run_blocking', blocking)
    client = SimpleNamespace(delete_knowledge_base=AsyncMock(), inspect_knowledge_base_deletion=AsyncMock())
    coordinator = KnowledgeBaseDeletionCoordinator(None, client, ports=ports)
    row = asyncio.run(coordinator.admit_owner_cleanup('kb-one', 'owner', s.actor))
    assert row['deletion_request']['phase'] == 'files'
    assert row['deletion_request']['user_id'] == 'user-a'
    assert s.records.get(KB, 1, context=context()) == row
    authorizer.assert_called_once()
    client.delete_knowledge_base.assert_not_awaited()
    client.inspect_knowledge_base_deletion.assert_not_awaited()
