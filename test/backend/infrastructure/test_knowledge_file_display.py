# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exact source display bindings keep original stored addresses and real actor."""

from threading import Event
from time import monotonic
from unittest.mock import Mock

import pytest
from nexent.storage.errors import ScopeDenied
from nexent.storage.models import ObjectRef, OperationContext

from infrastructure import knowledge_file_display as module
from infrastructure.agentos_identity import ServicePrincipal


@pytest.mark.parametrize(
    "address,bucket,key",
    [
        ("knowledge_base/a", "default-bucket", "knowledge_base/a"),
        ("s3://historical-bucket/source/a", "historical-bucket", "source/a"),
        ("/historical-bucket/source/a", "historical-bucket", "source/a"),
    ],
)
def test_actual_si_stat_exact_key_scope_and_close(mocker, address, bucket, key):
    context = OperationContext("display-binding", monotonic() + 10, cancelled=Event())
    actor = ServicePrincipal("reader", "tenant-a")
    mocker.patch.object(module.environment, "MINIO_DEFAULT_BUCKET", "default-bucket")
    client = Mock()
    client.head_object.return_value = {"ContentLength": 9, "ETag": "version"}
    factory = mocker.patch.object(module, "_configured_client", return_value=client)
    with module.knowledge_file_display_objects(actor, address, context=context) as (
        objects,
        ref,
    ):
        assert ref == ObjectRef("files", key)
        assert (
            objects.scope.actor_id,
            objects.scope.tenant_id,
            objects.scope.service_role,
            objects.scope.system,
        ) == ("reader", "tenant-a", "management", False)
        assert objects.stat(ref, context=context).size == 9
        with pytest.raises(ScopeDenied):
            objects.stat(ObjectRef("files", "sibling"), context=context)
    client.head_object.assert_called_once_with(Bucket=bucket, Key=key)
    client.close.assert_called_once()
    assert factory.call_count == 1 and 0 < factory.call_args.args[0] <= 10
