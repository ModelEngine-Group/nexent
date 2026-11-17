# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""KB-ARTIFACT-03: only the completed job's private artifact may authorize execution."""

import pytest
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import FieldPatch, PageRequest, RecordQuery, Revision

from test.backend.services.test_cleanse_authorization import resources  # noqa: F401
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_authorization import setup  # noqa: F401


@pytest.mark.parametrize('foreign', [None, 'file', 'version', 'job'])
def test_private_artifact_owner_must_match_the_authorized_completed_job(setup, foreign):  # noqa: F811
    policy, payload, _update, _resource_policy, jobs = setup
    row, = jobs.query('file_cleanse_jobs', RecordQuery(), PageRequest(limit=1), context=context()).items
    prefix = f'knowledge-cleanse/{payload.knowledge_id}/{payload.file_id}/{payload.file_version}/{row["job_id"]}/'
    if foreign:
        parts = prefix.split('/')
        position = {'file': 2, 'version': 3, 'job': 4}[foreign]
        parts[position] = 'e' * 32 if foreign != 'version' else '1'
        prefix = '/'.join(parts)
    reference = payload.artifact.model_copy(update={'key': prefix + 'artifacts/' + 'a' * 64 + '/' + payload.artifact.sha256 + '.json'})
    jobs.patch('file_cleanse_jobs', row['id'], FieldPatch(set_values={'artifact': reference.model_dump(mode='json')}),
               expected=Revision(str(row['revision'])), context=context())
    request = payload.model_copy(update={'artifact': reference})
    if foreign:
        with pytest.raises(ScopeDenied):
            policy.authorize(request, context=context())
    else:
        assert policy.authorize(request, context=context()).artifact == reference
