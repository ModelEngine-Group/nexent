# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-DELETE-INTENT-01: immutable scope and standard AgentOS identity."""

import pytest
from contracts.agentos_knowledge import knowledge_job_id
from contracts.knowledge_deletion import KnowledgeDeletionIntent
from pydantic import ValidationError


def intent(**updates):
    return KnowledgeDeletionIntent.model_validate({
        "knowledge_id": 1, "file_id": "b" * 32, "file_version": 0,
        "user_id": "user-a", "scope": "full", "index_name": "kb-one",
        "filename": "source.txt", "object_name": "source.txt",
        "source": {"space": "files", "key": "source.txt", "version": "v1", "sha256": "a" * 64},
        **updates,
    })


def test_roundtrip_and_runtime_identity_use_existing_file_delete_contract():
    value = intent()
    restored = KnowledgeDeletionIntent.model_validate_json(value.model_dump_json())
    request = restored.runtime_request()
    assert restored == value
    assert request.idempotency_key == "kb-delete:" + "b" * 32 + ":0:full"
    assert restored.runtime_lookup("tenant-a").job_id == knowledge_job_id(request, "tenant-a", "user-a")
    assert not {"tenant_id", "api_key", "authorization"} & value.model_dump().keys()


def test_source_only_cannot_build_a_runtime_delete_request():
    value = intent(scope="source_only")
    with pytest.raises(ValueError):
        value.runtime_request()
    with pytest.raises(ValueError):
        value.runtime_lookup("tenant-a")


@pytest.mark.parametrize("updates", [
    {"scope": "all"}, {"file_version": True}, {"file_version": -1},
    {"user_id": ""}, {"api_key": "forbidden"},
    {"scope": "source_only", "source": None}, {"scope": "source_only", "object_name": None},
])
def test_invalid_or_unpinned_intent_is_rejected(updates):
    with pytest.raises(ValidationError):
        intent(**updates)
