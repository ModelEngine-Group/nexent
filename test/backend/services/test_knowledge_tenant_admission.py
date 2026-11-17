# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Tenant authority fences only the selected shared KB before identity revocation."""

from unittest.mock import Mock

import pytest
from contracts.knowledge_admission import KNOWLEDGE_ADMISSION_DATASET as KB
from contracts.knowledge_admission import UPLOAD_ADMISSION_DATASET as FILES
from contracts.knowledge_admission import KnowledgeTenantCleanup
from management.services.knowledge_base import base_deletion as module
from nexent.storage.errors import ScopeDenied

from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_upload_admission import (
    admission,  # noqa: F401
)


@pytest.fixture
def shared(admission, monkeypatch):  # noqa: F811
    s = admission
    s.update('cleanse_knowledge', created_by='departed', ingroup_permission='READ_ONLY')
    with s.engine.begin() as conn:
        conn.execute(s.knowledge.update().values(created_by='departed', ingroup_permission='READ_ONLY',
                                                knowledge_sources='elasticsearch'))
    authorizer = Mock(return_value=KnowledgeTenantCleanup(actor_tenant_id='operator'))
    monkeypatch.setattr(module, 'authorize_tenant_cleanup_admission', authorizer)
    return s, authorizer


def admit(s):
    return module.request_knowledge_base_tenant_deletion(s.records, s.authorized, 'kb-one', s.actor, context=context())


def test_shared_parent_persists_actual_issuer_and_separate_tenant_scope(shared):
    s, authorizer = shared
    row = admit(s)
    assert row['deletion_request']['tenant_cleanup'] == {'actor_tenant_id': 'operator'}
    assert row['deletion_request']['owner_cleanup'] is None
    assert row['deletion_request']['user_id'] == 'user-a'
    authorizer.assert_called_once()


def test_existing_scope_survives_revocation_but_ordinary_and_private_entry_cannot_adopt_it(shared):
    s, authorizer = shared
    row = admit(s)
    s.update('cleanse_memberships', delete_flag='Y')
    assert admit(s) == row
    authorizer.assert_called_once()
    with pytest.raises(ScopeDenied):
        module.request_knowledge_base_deletion(s.records, s.authorized, 'kb-one', s.actor, context=context())
    with pytest.raises(ScopeDenied):
        module.request_knowledge_base_owner_deletion(s.records, s.authorized, 'kb-one', 'departed', 'tenant_deletion',
                                                    s.actor, context=context())


def test_denied_admission_does_not_mutate_parent(shared):
    s, authorizer = shared
    authorizer.side_effect = ScopeDenied()
    with pytest.raises(ScopeDenied):
        admit(s)
    assert s.records.get(KB, 1, context=context())['deletion_request'] is None


def test_resource_changed_under_admission_does_not_expand_grant(shared):
    s, _ = shared
    with s.engine.begin() as conn:
        conn.execute(s.knowledge.update().values(ingroup_permission='PRIVATE'))
    with pytest.raises(ScopeDenied):
        admit(s)
    assert s.records.get(KB, 1, context=context())['deletion_request'] is None


def test_inflight_file_remains_owned_by_existing_attempt_under_new_parent_fence(shared):
    s, _ = shared
    values = {key: value for key, value in s.spec().items() if key != 'created_by'}
    s.records.create(FILES, {**values, 'status': 'PROCESSING', 'stage': 'CLEANSE_PENDING',
                            'source_generation': 0, 'processing_attempt': 0}, context=context())
    row = admit(s)
    assert row['deletion_request']['phase'] == 'files'
    assert s.records.get(FILES, 'a' * 32, context=context())['stage'] == 'CLEANSE_PENDING'
