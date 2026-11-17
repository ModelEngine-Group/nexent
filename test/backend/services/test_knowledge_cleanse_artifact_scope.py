# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""KB-ARTIFACT-01/02: durable KB output ownership precedes parsing and storage."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.agentos_knowledge import CleanseArtifact, cleanse_output_prefix
from contracts.knowledge_cleanse import cleanse_lookup
from management.services.file.cleanse_executor import CleanseExecutor
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import ObjectRef

from infrastructure.file_processing.objects import CleanseObjects
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_file_cleanse_objects import Store, source
from test.backend.services.test_knowledge_cleanse_jobs import knowledge_request


def admitted(request, job='c' * 32):
    return {'scope_kind': 'knowledge', 'parser_version': 'v1', 'job_id': job,
            'request_payload': request.model_dump(mode='json'),
            **request.model_dump(include={'knowledge_id', 'file_id', 'file_version'})}


def test_same_source_outputs_are_owned_by_kb_file_version_and_job():
    store = Store()
    parser = SimpleNamespace(ensure_initialized=Mock(), file_structure=Mock(return_value=(
        [{'content': 'unchanged'}], [{'image_bytes': b'png-content', 'image_format': 'png'}],
    )))
    executor = CleanseExecutor(runtime=parser, objects=store, parser_version='v1')
    request = knowledge_request(source=source())
    scopes = [(request, 'c' * 32), (knowledge_request(source=source(), knowledge_id=2), 'c' * 32),
              (knowledge_request(source=source(), file_id='d' * 32), 'c' * 32),
              (knowledge_request(source=source(), file_version=1), 'c' * 32), (request, 'd' * 32)]
    results = []
    for request, job in scopes:
        lookup = cleanse_lookup(admitted(request, job), request)
        prefix = cleanse_output_prefix(lookup)
        result = executor(admitted(request, job), request, context=context())
        assert result.key.startswith(prefix + 'artifacts/')
        manifest = CleanseArtifact.model_validate_json(store.data[result.key])
        assert manifest.blocks[0].content == 'unchanged'
        assert manifest.blocks[1].object_ref.key.startswith(prefix + 'images/')
        assert manifest.source == source()
        results.append(result.key)
    assert len(set(results)) == len(scopes)
    assert executor(admitted(request, job), request, context=context()).key == results[-1]


@pytest.mark.parametrize('changed', [{'knowledge_id': 2}, {'file_id': 'e' * 32}, {'file_version': 1}, {'job_id': '../job'}])
def test_invalid_admission_never_warms_parser_or_reads_source(changed):
    request, parser, objects = knowledge_request(), Mock(), Mock()
    executor = CleanseExecutor(runtime=parser, objects=objects, parser_version='v1')
    with pytest.raises(ValueError):
        executor({**admitted(request), **changed}, request, context=context())
    parser.ensure_initialized.assert_not_called()
    objects.stat.assert_not_called()


def test_scoped_output_port_cannot_write_the_shared_or_another_jobs_directory():
    request = knowledge_request(source=source())
    lookup = cleanse_lookup(admitted(request), request)
    inputs, outputs = Mock(), Mock()
    port = CleanseObjects(source(), inputs, outputs, context=context(), run=lookup)
    try:
        for prefix in ('', cleanse_output_prefix(lookup.model_copy(update={'job_id': 'd' * 32})),
                       cleanse_output_prefix(lookup.model_copy(update={'file_version': 1}))):
            with pytest.raises(ScopeDenied):
                port.put(ObjectRef('files', prefix + 'artifacts/' + source().sha256 + '/' + 'a' * 64 + '.json'),
                         Mock(), content_type='application/json', size=1, context=context())
        outputs.put.assert_not_called()
    finally:
        port.close()
    inputs.close.assert_called_once()
    outputs.close.assert_called_once()


@pytest.mark.parametrize('changed', [
    {'source': {**source().model_dump(), 'version': 'etag:other'}},
    {'filename': 'other.txt'}, {'idempotency_key': 'other-admission'},
])
def test_complete_request_snapshot_is_checked_before_any_parser_work(changed):
    request = knowledge_request(source=source())
    row = admitted(request)
    row['request_payload'] = {**row['request_payload'], **changed}
    parser, objects = Mock(), Mock()
    with pytest.raises(ValueError):
        CleanseExecutor(runtime=parser, objects=objects, parser_version='v1')(row, request, context=context())
    parser.ensure_initialized.assert_not_called()
    objects.stat.assert_not_called()
