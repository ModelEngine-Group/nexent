# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Queue composition owns every adapter and grants only Management dispatch."""

from types import SimpleNamespace

import pytest
from nexent.storage.errors import OutcomeUnknown

from infrastructure import knowledge_cleanse as composition
from test.backend.services.test_cleanse_jobs import context


@pytest.mark.parametrize("failure", [None, "bind", "body", "close"])
def test_queue_factory_owns_tenant_queue_and_kv(mocker, failure):
    mocker.patch.object(
        composition,
        "queue_environment",
        return_value=SimpleNamespace(
            REDIS_URL="redis://localhost:6379/0",
            REDIS_BACKEND_URL="redis://localhost:6379/1",
        ),
    )
    kv = mocker.patch.object(composition, "RedisKeyValueStore")
    queue = mocker.patch.object(composition, "KombuWorkQueue")
    if failure == "bind":
        queue.side_effect = ValueError("controlled construction failure")
    if failure == "close":
        queue.return_value.close.side_effect = RuntimeError("private detail")

    def exercise():
        with composition.knowledge_cleanse_queue(
            "tenant-a", "worker", context=context()
        ) as handle:
            assert handle is queue.return_value
            if failure == "body":
                raise ValueError("controlled body failure")

    if failure:
        with pytest.raises(OutcomeUnknown if failure == "close" else ValueError):
            exercise()
    else:
        exercise()
    kv.return_value.close.assert_called_once()
    if failure != "bind":
        queue.return_value.close.assert_called_once()
    scope, binding = queue.call_args.args[:2]
    assert scope.tenant_id == "tenant-a" and scope.service_role == "management"
    assert not scope.system and binding.namespace == "management-file-cleanse"
    assert binding.handlers == {"file.cleanse"}
    assert kv.call_args.args[1] == scope
