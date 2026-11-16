# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Knowledge uploads use file-version ownership without inventing an Agent run."""

import json
from unittest.mock import Mock
from uuid import NAMESPACE_URL, uuid5

import pytest
from contracts.agentos_knowledge import FileCleanseRequest
from contracts.knowledge_cleanse import (
    KnowledgeCleanseLookup,
    KnowledgeCleanseRequest,
    parse_cleanse_request,
)
from management.services.file.cleanse_worker import HANDLER, CleanseHandler
from nexent.storage.errors import Conflict, NotFound
from nexent.storage.models import TaskEnvelope
from pydantic import ValidationError

from test.backend.services.test_cleanse_jobs import artifact, context, request
from test.backend.services.test_cleanse_jobs import (
    setup as setup,  # noqa: PLC0414 - Re-export pytest fixture.
)


def knowledge_request(**changes):
    payload = request().model_dump(exclude={"run_id"})
    payload.update(knowledge_id=1, file_id="b" * 32, file_version=0)
    return KnowledgeCleanseRequest.model_validate({**payload, **changes})


def lookup(state, **changes):
    return KnowledgeCleanseLookup.model_validate(
        {
            **state.model_dump(
                include={"knowledge_id", "file_id", "file_version", "job_id"}
            ),
            **changes,
        }
    )


def test_file_version_scopes_idempotent_admission(setup):
    make, _ = setup
    jobs = make()
    first = jobs.submit(knowledge_request(), context=context())
    assert "run_id" not in first.model_dump()
    assert make().submit(knowledge_request(), context=context()) == first
    next_version = jobs.submit(knowledge_request(file_version=1), context=context())
    assert next_version.job_id != first.job_id
    with pytest.raises(Conflict):
        jobs.submit(knowledge_request(filename="changed.txt"), context=context())


@pytest.mark.parametrize(
    "user,tenant,changes",
    [
        ("user-b", "tenant-a", {}),
        ("user-a", "tenant-b", {}),
        ("user-a", "tenant-a", {"knowledge_id": 2}),
        ("user-a", "tenant-a", {"file_id": "c" * 32}),
        ("user-a", "tenant-a", {"file_version": 1}),
    ],
)
def test_foreign_scope_cannot_inspect_or_cancel(setup, user, tenant, changes):
    make, _ = setup
    jobs = make()
    state = jobs.submit(knowledge_request(), context=context())
    foreign = make(user, tenant)
    for method in (foreign.inspect, foreign.cancel):
        with pytest.raises(NotFound):
            method(lookup(state, **changes), context=context())
    assert jobs.inspect(lookup(state), context=context()).status == "queued"


def test_run_identity_unchanged_and_disjoint_from_knowledge(setup):
    make, _ = setup
    jobs = make()
    run = jobs.submit(request(), context=context())
    seed = json.dumps(
        ["tenant-a", "user-a", request().run_id, request().idempotency_key],
        separators=(",", ":"),
    )
    assert run.job_id == uuid5(NAMESPACE_URL, seed).hex
    kb = jobs.submit(knowledge_request(), context=context())
    assert run.job_id != kb.job_id


def test_worker_decodes_and_reauthorizes_knowledge_snapshot(setup):
    make, _ = setup
    jobs = make()
    state = jobs.submit(knowledge_request(), context=context())
    auth = Mock()
    execute = Mock(return_value=artifact())
    handler = CleanseHandler(
        make("worker"),
        owner_id="worker",
        lease_seconds=60,
        authorize_execution=auth,
        execute=execute,
    )
    handler(
        TaskEnvelope(state.job_id, HANDLER, {"job_id": state.job_id}), context=context()
    )
    row, decoded = auth.call_args.args
    assert row["user_id"] == "user-a" and row["run_id"] is None
    assert decoded == knowledge_request()
    assert execute.call_args.args[1] == decoded
    assert jobs.inspect(lookup(state), context=context()).artifact == artifact()


def test_scope_contracts_reject_mixed_identity():
    with pytest.raises(ValidationError):
        knowledge_request(run_id="a" * 32)
    with pytest.raises(ValidationError):
        FileCleanseRequest.model_validate({**request().model_dump(), "knowledge_id": 1})
    with pytest.raises(ValueError, match="Unsupported"):
        parse_cleanse_request({"scope_kind": "unknown"})


@pytest.mark.parametrize(
    "field,value",
    [
        ("knowledge_id", 0),
        ("knowledge_id", 2**31),
        ("file_version", -1),
        ("file_version", 2**31),
    ],
)
def test_scope_integer_bounds_match_int4_columns(field, value):
    with pytest.raises(ValidationError):
        knowledge_request(**{field: value})
    with pytest.raises(ValidationError):
        KnowledgeCleanseLookup.model_validate(
            {
                "knowledge_id": 1,
                "file_id": "b" * 32,
                "file_version": 0,
                "job_id": "d" * 32,
                field: value,
            }
        )


@pytest.mark.parametrize(
    "field,value", [("knowledge_id", 2), ("file_id", "c" * 32), ("file_version", 1)]
)
def test_worker_rejects_snapshot_context_mismatch(field, value):
    payload = knowledge_request().model_dump()
    row = {
        **payload,
        "scope_kind": "knowledge",
        "request_payload": payload,
        field: value,
    }
    with pytest.raises(ValueError, match="authorization scope"):
        parse_cleanse_request(row)
