# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""KB dimensions come from the revision-bound authoritative Runtime model record."""

from unittest.mock import Mock

import pytest
from contracts.agentos_knowledge import ModelVersion
from runtime.model.service import ModelAccessError, ModelService

from infrastructure.agentos_identity import ServicePrincipal


@pytest.mark.parametrize("dimensions", [2, 1536])
async def test_dimensions_do_not_probe_a_provider(dimensions, mocker):
    async def direct(_name, fn, *args, **kwargs):
        return fn(*args)

    mocker.patch("runtime.model.service.run_blocking", side_effect=direct)
    build = Mock()
    service = ModelService(
        Mock(
            return_value={
                "tenant_id": "tenant",
                "delete_flag": "N",
                "model_type": "embedding",
                "max_tokens": dimensions,
                "update_time": "v1",
            }
        ),
        build,
    )
    assert (
        await service.embedding_dimensions(
            ModelVersion(model_id=2, revision="v1"), ServicePrincipal("user", "tenant")
        )
        == dimensions
    )
    build.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"max_tokens": None},
        {"max_tokens": 0},
        {"max_tokens": True},
        {"update_time": "changed"},
        {"model_type": "llm"},
    ],
)
async def test_invalid_dimension_or_revision_is_not_guessed(change, mocker):
    async def direct(_name, fn, *args, **kwargs):
        return fn(*args)

    mocker.patch("runtime.model.service.run_blocking", side_effect=direct)
    build = Mock()
    record = {
        "tenant_id": "tenant",
        "delete_flag": "N",
        "model_type": "embedding",
        "max_tokens": 2,
        "update_time": "v1",
        **change,
    }
    with pytest.raises(ModelAccessError):
        await ModelService(Mock(return_value=record), build).embedding_dimensions(
            ModelVersion(model_id=2, revision="v1"), ServicePrincipal("user", "tenant")
        )
    build.assert_not_called()
