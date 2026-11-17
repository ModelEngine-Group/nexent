# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""SOURCE-ONLY-IMAGE-01/02: retained images require an exact, authorized terminal."""

import pytest
from contracts.agentos_knowledge import CleanseBlock, ObjectReference
from contracts.knowledge_deletion import KnowledgeDeletionIntent
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import FieldPatch, PageRequest, RecordQuery

from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_authorization import setup  # noqa: F401
from test.backend.services.test_knowledge_cleanse_jobs import knowledge_request
from test.backend.services.test_knowledge_content_authorization import (
    content,  # noqa: F401
)


@pytest.fixture(params=['shared', 'private'])
def deleted(content, request):  # noqa: F811
    policy, lookup, image, load, update = content
    source = knowledge_request().source
    if request.param == 'private':
        row, = policy.jobs.query('file_cleanse_jobs', RecordQuery(), PageRequest(limit=1), context=context()).items
        prefix = f'knowledge-cleanse/1/{lookup.file_id}/0/{row["job_id"]}/'
        artifact = ObjectReference.model_validate(row['artifact'])
        artifact = artifact.model_copy(update={'key': prefix + 'artifacts/' + source.sha256 + '/' + artifact.sha256 + '.json'})
        policy.jobs.patch('file_cleanse_jobs', row['id'], FieldPatch(set_values={'artifact': artifact.model_dump(mode='json')}), context=context())
        image = image.model_copy(update={'key': prefix + image.key})
        load.return_value = load.return_value.model_copy(update={'blocks': [
            CleanseBlock(ordinal=0, kind='image', sha256=image.sha256, object_ref=image),
        ]})
    intent = KnowledgeDeletionIntent(knowledge_id=1, file_id=lookup.file_id, file_version=0, user_id='original-deleter',
                                      scope='source_only', index_name='kb-one', filename='source.txt',
                                      object_name=source.key, source=source)
    update('cleanse_files', status='COMPLETED', stage='SOURCE_DELETED', object_name=source.key,
           deletion_request=intent.model_dump(mode='json'), source_space=None, source_key=None,
           source_revision=None, source_sha256=None)
    return policy, lookup, image, load, update, intent


def test_current_read_only_member_can_read_retained_image_but_never_deleted_source(deleted):
    policy, request, image, load, update, _intent = deleted
    update('cleanse_knowledge', created_by='other', ingroup_permission='READ_ONLY')
    assert policy.authorize(request.model_copy(update={'image_ref': image}), context=context()).object_ref == image
    load.assert_called_once()
    with pytest.raises(ScopeDenied):
        policy.authorize(request, context=context())


@pytest.mark.parametrize('dataset,changes', [
    ('cleanse_files', {'status': 'DELETE_REQUESTED'}), ('cleanse_files', {'status': 'DELETED'}),
    ('cleanse_files', {'delete_flag': 'Y'}), ('cleanse_files', {'source_generation': 1}),
    ('cleanse_files', {'stage': 'DELETE_SOURCE_DELETING'}), ('cleanse_files', {'source_key': 'incomplete-clear'}),
    ('cleanse_memberships', {'delete_flag': 'Y'}), ('cleanse_memberships', {'tenant_id': 'other'}),
    ('cleanse_knowledge', {'created_by': 'other', 'ingroup_permission': 'NONE'}),
    ('cleanse_knowledge', {'deletion_request': {'schema_version': 1, 'knowledge_id': 1, 'index_name': 'kb-one', 'user_id': 'user-a'}}),
])
def test_terminal_images_remain_subject_to_lifecycle_and_live_dac(deleted, dataset, changes):
    policy, request, image, load, update, _intent = deleted
    update(dataset, **changes)
    with pytest.raises(ScopeDenied):
        policy.authorize(request.model_copy(update={'image_ref': image}), context=context())
    load.assert_not_called()


@pytest.mark.parametrize('changed', [{'scope': 'full'}, {'file_id': 'e' * 32}, {'knowledge_id': 2},
                                     {'file_version': 1}, {'index_name': 'other'}, {'filename': 'other.txt'},
                                     {'object_name': 'other.txt'}, {'source': None}])
def test_frozen_intent_must_match_the_exact_retained_file(deleted, changed):
    policy, request, image, load, update, intent = deleted
    update('cleanse_files', deletion_request={**intent.model_dump(mode='json'), **changed})
    with pytest.raises(ScopeDenied):
        policy.authorize(request.model_copy(update={'image_ref': image}), context=context())
    load.assert_not_called()


def test_uncertain_cleanse_is_not_a_source_only_image_proof(deleted):
    policy, request, image, load, _update, _intent = deleted
    row, = policy.jobs.query('file_cleanse_jobs', RecordQuery(), PageRequest(limit=1), context=context()).items
    policy.jobs.patch('file_cleanse_jobs', row['id'], FieldPatch(set_values={'reconcile_required': True}), context=context())
    with pytest.raises(ScopeDenied):
        policy.authorize(request.model_copy(update={'image_ref': image}), context=context())
    load.assert_not_called()


@pytest.mark.parametrize('field,value', [('version', 'other'), ('sha256', 'd' * 64)])
def test_fixed_deleted_source_must_match_the_completed_cleanse(deleted, field, value):
    policy, request, image, load, update, intent = deleted
    snapshot = intent.model_dump(mode='json')
    snapshot['source'][field] = value
    update('cleanse_files', deletion_request=snapshot)
    with pytest.raises(ScopeDenied):
        policy.authorize(request.model_copy(update={'image_ref': image}), context=context())
    load.assert_not_called()


@pytest.mark.parametrize('field,value', [('version', 'other'), ('key', 'images/other.png'), ('sha256', 'd' * 64)])
def test_retained_image_still_requires_exact_manifest_membership(deleted, field, value):
    policy, request, image, _load, _update, _intent = deleted
    with pytest.raises(ScopeDenied):
        policy.authorize(request.model_copy(update={'image_ref': image.model_copy(update={field: value})}), context=context())
