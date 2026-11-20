# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""FILE-BODY-03 seals the exact read port and normalizes transport deadlines."""

from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from botocore.exceptions import ReadTimeoutError
from nexent.storage.errors import DeadlineExceeded, ScopeDenied
from nexent.storage.models import ObjectRef, OperationContext


def test_exact_read_port_and_body_timeout_close_once(mocker):
    from infrastructure import file_reads

    raw = Mock()
    body = Mock()
    raw.get_object.return_value = {'Body': body}
    body.read.side_effect = ReadTimeoutError(endpoint_url='https://private.invalid')
    configured = mocker.patch.object(file_reads, '_configured_client', return_value=raw)
    mocker.patch.object(file_reads, '_configured_environment', return_value=SimpleNamespace(MINIO_DEFAULT_BUCKET='owned'))
    ctx = OperationContext('owned', monotonic()+30)
    with file_reads.file_read_ports('knowledge_base/a:colon', context=ctx) as store:
        assert store.scope.system and store.scope.actor_id == 'management.file.read'
        with pytest.raises(ScopeDenied):
            store.delete(ObjectRef('files', 'knowledge_base/a:colon'), context=ctx)
        with pytest.raises(DeadlineExceeded), store.open_read(ObjectRef('files', 'knowledge_base/a:colon'), context=ctx) as reader:
            reader.read(64*1024)
    assert 0 < configured.call_args.args[0] <= 5
    raw.get_object.assert_called_once_with(Bucket='owned', Key='knowledge_base/a:colon')
    body.close.assert_called_once()
    raw.close.assert_called_once()
