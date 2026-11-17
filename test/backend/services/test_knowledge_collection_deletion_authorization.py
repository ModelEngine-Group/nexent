# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""KB-COLLECTION-02: live DAC and exact durable file terminals authorize cleanup."""

import pytest
import sqlalchemy as sa
from contracts.knowledge_base_deletion import KnowledgeBaseDeleteAuthorization
from contracts.knowledge_deletion import KnowledgeDeletionIntent
from management.services.knowledge_base.base_deletion import (
    request_knowledge_base_deletion,
)
from management.services.knowledge_base.base_deletion_authorization import (
    authorize_base_deletion,
)
from nexent.storage.errors import Conflict, ScopeDenied
from nexent.storage.models import FieldPatch

from infrastructure.rdb.knowledge_admission import bind_admission_records
from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_upload_admission import (
    admission,  # noqa: F401
)


def authorize(s):
    return authorize_base_deletion(s.records, s.authorized, KnowledgeBaseDeleteAuthorization(knowledge_id=1),
                                   s.actor, context=context())


def fence(s):
    return request_knowledge_base_deletion(s.records, s.authorized, 'kb-one', s.actor, context=context())


def test_unfenced_kb_cannot_grant_collection_authority(admission):  # noqa: F811
    with pytest.raises(ScopeDenied):
        authorize(admission)


def test_empty_fenced_kb_returns_only_logical_collection(admission):  # noqa: F811
    fence(admission)
    assert authorize(admission).model_dump() == {'knowledge_id': 1, 'collection': 'kb-one'}


@pytest.mark.parametrize('changed', [{'user_id': 'other'}, {'knowledge_id': 2}, {'index_name': 'other'}])
def test_original_deletion_identity_is_immutable(admission, changed):  # noqa: F811
    s = admission
    row = fence(s)
    with s.engine.begin() as connection:
        connection.execute(s.knowledge.update().values(deletion_request={**row['deletion_request'], **changed}))
    with pytest.raises(ScopeDenied):
        authorize(s)


def test_membership_revocation_denies_even_previously_fenced_kb(admission):  # noqa: F811
    fence(admission)
    admission.update('cleanse_memberships', delete_flag='Y')
    with pytest.raises(ScopeDenied):
        authorize(admission)


def terminal_file(s):
    row = s.service.admit([s.spec()], context=context())[0]
    deletion = KnowledgeDeletionIntent(knowledge_id=1, file_id=row['file_id'], file_version=0, user_id='previous-editor',
                                      scope='full', index_name='kb-one', filename=row['original_filename'],
                                      object_name=row['object_name'])
    with s.engine.begin() as connection:
        connection.execute(s.files.update().values(status='DELETED', stage='DELETE_DONE', deleted_vector_count=0,
                                                   deletion_request=deletion.model_dump(mode='json')))
    fence(s)
    return deletion


def test_confirmed_full_file_cleanup_by_another_editor_is_allowed(admission):  # noqa: F811
    terminal_file(admission)
    assert authorize(admission).collection == 'kb-one'


@pytest.mark.parametrize('changed', [
    {'stage': 'DELETE_SOURCE_PENDING'}, {'status': 'COMPLETED'}, {'deleted_vector_count': None},
    {'source_generation': 1}, {'original_filename': 'other.txt'}, {'object_name': 'foreign'},
    {'source_space': 'files'}, {'deletion_request': None},
])
def test_incomplete_or_mismatched_file_prevents_collection_grant(admission, changed):  # noqa: F811
    s = admission
    terminal_file(s)
    with s.engine.begin() as connection:
        connection.execute(s.files.update().values(**changed))
    with pytest.raises(Conflict):
        authorize(s)


def test_terminal_check_does_not_stop_at_first_page(admission):  # noqa: F811
    s = admission
    deletion = terminal_file(s)
    with s.engine.begin() as connection:
        row = dict(connection.execute(sa.select(s.files)).mappings().one())
        connection.execute(s.files.insert(), [{**row, 'file_id': f'{number:032x}',
            'deletion_request': deletion.model_copy(update={'file_id': f'{number:032x}'}).model_dump(mode='json')}
            for number in range(200)])
        connection.execute(s.files.update().where(s.files.c.file_id == 'a' * 32).values(deleted_vector_count=None))
    with pytest.raises(Conflict):
        authorize(s)


def test_authorization_port_has_no_record_write_authority(admission):  # noqa: F811
    s = admission
    fence(s)
    records = bind_admission_records(s.records.scope, s.engine, readonly=True)
    try:
        grant = authorize_base_deletion(records, s.authorized, KnowledgeBaseDeleteAuthorization(knowledge_id=1),
                                        s.actor, context=context())
        assert grant.collection == 'kb-one'
        with pytest.raises(ScopeDenied):
            records.patch('management_knowledge_admission', 1, FieldPatch(set_values={'deletion_request': None}),
                          context=context())
    finally:
        records.close()
