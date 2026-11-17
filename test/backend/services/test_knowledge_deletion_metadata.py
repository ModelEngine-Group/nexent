# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DELETE-RESULT-03: KB time, ledger and file finalization share one SI transaction."""

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from contracts.knowledge_deletion import DELETION_KNOWLEDGE_DATASET as KNOWLEDGE
from management.services.knowledge_base.deletion_journal import DeletionJournal
from nexent.storage.errors import Conflict, ScopeDenied
from nexent.storage.models import WriteReceipt

from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_deletion_journal import (
    setup as journal_setup,  # noqa: F401
)
from test.backend.services.test_knowledge_source_deletion import (
    setup as setup,  # noqa: PLC0414
)


def test_full_delete_updates_scoped_knowledge_time_with_ledger_and_file(setup):
    s = setup
    before = s.records.get(KNOWLEDGE, 1, context=context())
    assert s.deletion.advance(s.row(), context=context())['status'] == 'DELETED'
    after = s.records.get(KNOWLEDGE, 1, context=context())
    assert after['last_doc_update_time'] != before['last_doc_update_time']
    assert after['updated_by'] == 'user-a' and after['created_by'] == before['created_by']
    assert after['version'] == before['version'] + 1
    instant = datetime.fromisoformat(after['last_doc_update_time'])
    assert instant.tzinfo == UTC
    with s.s.engine.connect() as connection:
        raw = connection.execute(sa.select(sa.type_coerce(s.knowledge.c.last_doc_update_time, sa.DateTime()))).scalar_one()
    assert raw.replace(tzinfo=None) == instant.astimezone().replace(tzinfo=None)


def test_terminal_failure_rolls_back_knowledge_time_and_ledger(setup, monkeypatch):
    s = setup
    before = s.records.get(KNOWLEDGE, 1, context=context())
    monkeypatch.setattr(DeletionJournal, 'finish_source', Mock(side_effect=Conflict()))
    with pytest.raises(Conflict):
        s.deletion.advance(s.row(), context=context())
    assert s.records.get(KNOWLEDGE, 1, context=context()) == before
    assert s.row()['stage'] == 'DELETE_SOURCE_DELETING'


def test_only_source_preserves_knowledge_time(setup):
    s = setup
    before = s.records.get(KNOWLEDGE, 1, context=context())
    value = s.value.model_copy(update={'scope': 'source_only'})
    with s.s.engine.begin() as connection:
        connection.execute(s.s.table.update().values(status='COMPLETED', stage='DELETE_ACCEPTED',
                                                     deleted_vector_count=None, deletion_request=value.model_dump(mode='json')))
    assert s.deletion.advance(s.row(), context=context())['stage'] == 'SOURCE_DELETED'
    assert s.records.get(KNOWLEDGE, 1, context=context()) == before


@pytest.mark.parametrize('changed', [{'tenant_id': 'other'}, {'index_name': 'other'}, {'delete_flag': 'Y'}])
def test_other_or_deleted_knowledge_cannot_complete_accounting(setup, changed):
    s = setup
    with s.s.engine.begin() as connection:
        connection.execute(s.knowledge.update().values(**changed))
    with pytest.raises((Conflict, ScopeDenied)):
        s.deletion.advance(s.row(), context=context())
    assert s.row()['stage'] == 'DELETE_SOURCE_DELETING'


def test_missing_confirmed_count_cannot_delete_source(setup):
    s = setup
    with s.s.engine.begin() as connection:
        connection.execute(s.s.table.update().values(deleted_vector_count=None))
    with pytest.raises(Conflict):
        s.deletion.advance(s.row(), context=context())
    s.objects.delete.assert_not_called()


def test_metadata_cas_contention_does_not_replay_source_delete(setup, monkeypatch):
    from nexent.storage.errors import NotFound

    s = setup
    patch = type(s.records).patch

    def contend(records, dataset, *args, **kwargs):
        if dataset == KNOWLEDGE:
            assert kwargs['expected'].value == '0'
            return WriteReceipt('contended', False)
        return patch(records, dataset, *args, **kwargs)

    monkeypatch.setattr(type(s.records), 'patch', contend)
    with pytest.raises(Conflict):
        s.deletion.advance(s.row(), context=context())
    assert s.row()['stage'] == 'DELETE_SOURCE_DELETING'
    assert s.records.get(KNOWLEDGE, 1, context=context())['version'] == 0
    monkeypatch.setattr(type(s.records), 'patch', patch)
    s.objects.stat.side_effect = NotFound()
    assert s.deletion.advance(s.row(), context=context())['status'] == 'DELETED'
    s.objects.delete.assert_called_once()


def test_no_object_and_no_vectors_preserves_existing_document_change_time(setup):
    from management.services.knowledge_base.source_deletion import SourceDeletion

    s = setup
    before = s.records.get(KNOWLEDGE, 1, context=context())
    value = s.value.model_copy(update={'source': None, 'object_name': None})
    with s.s.engine.begin() as connection:
        connection.execute(s.s.table.update().values(object_name=None, storage_object_id=None, source_space=None,
                                                     source_key=None, source_revision=None, source_sha256=None,
                                                     deletion_request=value.model_dump(mode='json')))
    assert SourceDeletion(s.records, None).advance(s.row(), context=context())['status'] == 'DELETED'
    assert s.records.get(KNOWLEDGE, 1, context=context()) == before
