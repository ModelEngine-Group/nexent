# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Frozen Management intent and shared child identities survive process boundaries."""

import pytest
from contracts.agentos_knowledge import (
    FileCleanseRequest,
    KnowledgeFileDelete,
    knowledge_job_id,
)
from contracts.knowledge_cleanse import cleanse_job_id
from contracts.knowledge_ingestion import KnowledgeIngestionIntent
from pydantic import ValidationError


def intent(**updates):
    values = {
        "knowledge_id": 1,
        "file_id": "b" * 32,
        "file_version": 0,
        "user_id": "user-a",
        "attempt": 1,
        "source": {
            "space": "files",
            "key": "source.txt",
            "version": "v1",
            "sha256": "a" * 64,
        },
        "filename": "source.txt",
        "parser_version": "parser-v1",
        "embedding_model": {"model_id": 2, "revision": "model-v1"},
        "chunking_strategy": "basic",
    }
    return KnowledgeIngestionIntent.model_validate({**values, **updates})


def test_frozen_intent_builds_consistent_cleanse_and_runtime_requests():
    value = intent()
    restored = KnowledgeIngestionIntent.model_validate_json(value.model_dump_json())
    assert restored == value
    cleanse = value.cleanse_request()
    upload = value.runtime_request(value.source)
    assert cleanse.file_version == upload.file_version == 0
    assert (
        cleanse.idempotency_key
        == upload.idempotency_key
        == "kb-ingest:" + "b" * 32 + ":0:1"
    )
    assert cleanse.source == value.source
    assert upload.embedding_model == value.embedding_model
    assert upload.chunking_strategy == "basic"
    assert upload.parser_version == "parser-v1"
    assert not {"authorization", "tenant_id", "api_key"} & value.model_dump().keys()


def test_existing_child_identity_layout_is_unchanged():
    value = intent()
    cleanse = value.cleanse_request().model_copy(
        update={"idempotency_key": "kb-ingest:b:0:1"}
    )
    upload = value.runtime_request(value.source).model_copy(
        update={"idempotency_key": "kb-ingest:b:0:1"}
    )
    assert (
        cleanse_job_id(cleanse, "tenant-a", "user-a")
        == "b9bd805be3bf57cf9667d7a646f455db"
    )
    assert (
        knowledge_job_id(upload, "tenant-a", "user-a")
        == "036f814a548652fb8bb8db5fefc4ddd0"
    )
    assert knowledge_job_id(
        KnowledgeFileDelete(
            **{
                name: getattr(upload, name)
                for name in (
                    "knowledge_id",
                    "file_id",
                    "file_version",
                    "idempotency_key",
                )
            }
        ),
        "tenant-a",
        "user-a",
    ) != knowledge_job_id(upload, "tenant-a", "user-a")
    run = FileCleanseRequest(
        run_id="c" * 32,
        source=value.source,
        filename="source.txt",
        idempotency_key="run-1",
    )
    assert len(cleanse_job_id(run, "tenant-a", "user-a")) == 32


@pytest.mark.parametrize(
    "tenant,user", [("tenant-b", "user-a"), ("tenant-a", "user-b")]
)
def test_child_identities_are_scoped_by_tenant_and_actor(tenant, user):
    value = intent()
    for request, identify in (
        (value.cleanse_request(), cleanse_job_id),
        (value.runtime_request(value.source), knowledge_job_id),
    ):
        assert identify(request, tenant, user) != identify(
            request, "tenant-a", "user-a"
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"attempt": 0},
        {"attempt": True},
        {"user_id": ""},
        {"file_version": -1},
        {"authorization": "never-persist"},
        {"chunking_strategy": "unknown"},
        {
            "source": {
                "space": "files",
                "key": "https://outside/x",
                "version": "v1",
                "sha256": "a" * 64,
            }
        },
        {
            "source": {
                "space": "secrets",
                "key": "source.txt",
                "version": "v1",
                "sha256": "a" * 64,
            }
        },
    ],
)
def test_invalid_or_credential_bearing_intents_are_rejected(changes):
    with pytest.raises(ValidationError):
        intent(**changes)
