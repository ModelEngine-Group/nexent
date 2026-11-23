# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management grants only current authorized resources and completed cleanse outputs."""

import pytest
from contracts.agentos_knowledge import KnowledgeAuthorizationRequest, ObjectReference
from contracts.knowledge_deletion import KnowledgeDeletionIntent
from management.services.file.cleanse_jobs import CleanseJobs
from management.services.knowledge_base.authorization import KnowledgeAuthorization
from nexent.storage.errors import Conflict, ScopeDenied
from nexent.storage.models import (
    Comparison,
    FieldPatch,
    PageRequest,
    RecordQuery,
    Revision,
    StorageScope,
)
from pydantic import ValidationError

from infrastructure.rdb.cleanse_jobs import DATASET, bind_cleanse_jobs, cleanse_jobs
from test.backend.services.test_cleanse_authorization import (
    resources as resources,  # noqa: PLC0414 - Re-export the shared pytest fixture.
)
from test.backend.services.test_cleanse_jobs import context
from test.backend.services.test_knowledge_cleanse_jobs import knowledge_request


@pytest.fixture
def setup(resources):
    authorize, update, engine, _tables = resources
    update("cleanse_knowledge", embedding_model_id=2)
    job_engine = engine.execution_options(schema_translate_map={"nexent": None})
    cleanse_jobs.create(job_engine)
    jobs = bind_cleanse_jobs(
        StorageScope("management", "tenant-a", "user-a", {DATASET}), job_engine
    )
    resource_policy = authorize()
    policy = KnowledgeAuthorization(jobs, resource_policy.records, user_id="user-a")
    request = knowledge_request()
    artifact = ObjectReference(
        space="files",
        key="artifacts/source/artifact.json",
        version="artifact-v1",
        sha256="a" * 64,
    )
    cleanse = CleanseJobs(
        jobs, authorize=resource_policy.authorize, parser_version="v2"
    )
    state = cleanse.submit(request, context=context())
    row = jobs.query(
        DATASET,
        RecordQuery(where=Comparison("job_id", "eq", state.job_id)),
        PageRequest(limit=1),
        context=context(),
    ).items[0]
    # The completed parser publication is the controlled external input of this unit.
    assert jobs.patch(
        DATASET,
        row["id"],
        FieldPatch(
            set_values={
                "status": "completed",
                "artifact": artifact.model_dump(mode="json"),
            }
        ),
        expected=Revision(str(row["revision"])),
        context=context(),
    ).matched
    payload = KnowledgeAuthorizationRequest(
        knowledge_id=1,
        file_id=request.file_id,
        file_version=0,
        action="upload",
        artifact=artifact,
        parser_version="v2",
    )
    yield policy, payload, update, resource_policy, jobs
    jobs.close()
    resource_policy.records.close()


def test_grant_binds_source_model_and_completed_artifact(setup):
    policy, payload, _, _, _ = setup
    grant = policy.authorize(payload, context=context())
    assert grant.source == knowledge_request().source
    assert grant.artifact == payload.artifact and grant.parser_version == "v2"
    assert grant.filename == "source.txt" and grant.collection == "kb-one"
    assert grant.embedding_model_id == 2


@pytest.mark.parametrize(
    "change",
    [
        {"parser_version": "other"},
        {
            "artifact": ObjectReference(
                space="files", key="other", version="v1", sha256="b" * 64
            )
        },
        {"file_version": 1},
    ],
)
def test_artifact_or_source_generation_mismatch_never_grants(setup, change):
    policy, payload, _, _, _ = setup
    with pytest.raises(ScopeDenied):
        policy.authorize(payload.model_copy(update=change), context=context())


def test_read_only_can_inspect_but_cannot_execute_or_delete(setup):
    policy, payload, update, _, _ = setup
    update("cleanse_knowledge", created_by="other", ingroup_permission="READ_ONLY")
    read = KnowledgeAuthorizationRequest(
        knowledge_id=1, file_id=payload.file_id, file_version=0, action="inspect"
    )
    assert policy.authorize(read, context=context()).artifact is None
    for request in (payload, read.model_copy(update={"action": "delete"})):
        with pytest.raises(ScopeDenied):
            policy.authorize(request, context=context())


def test_delete_can_authorize_history_without_reenabling_cleansing(setup):
    policy, payload, update, cleanse, _ = setup
    update("cleanse_files", status="DELETED", delete_flag="Y")
    delete = KnowledgeAuthorizationRequest(
        knowledge_id=1, file_id=payload.file_id, file_version=0, action="delete"
    )
    assert policy.authorize(delete, context=context()).source is None
    with pytest.raises(ScopeDenied):
        cleanse.authorize(knowledge_request(), context=context())


@pytest.mark.parametrize("reused", [False, True])
def test_legacy_delete_requires_unique_source_across_file_history(setup, resources, monkeypatch, reused):
    from contracts.constants import environment

    policy, payload, update, _, _ = setup
    _, _, engine, tables = resources
    monkeypatch.setattr(environment, "KNOWLEDGE_RUNTIME_HYBRID_ENABLED", True)
    source = knowledge_request().source
    intent = KnowledgeDeletionIntent(knowledge_id=1, file_id=payload.file_id, file_version=0, user_id="user-a",
        scope="full", index_name="kb-one", filename="source.txt", object_name=f"/bucket/{source.key}", source=source)
    update("cleanse_files", status="DELETE_REQUESTED", stage="DELETE_RUNTIME_PENDING", bucket_name="bucket",
           object_name=intent.object_name, deletion_request=intent.model_dump(mode="json"))
    request = KnowledgeAuthorizationRequest(knowledge_id=1, file_id=payload.file_id, file_version=0, action="delete")
    if reused:
        with engine.begin() as connection:
            connection.execute(tables["cleanse_files"].insert().values(
                file_id="c" * 32, tenant_id="tenant-a", knowledge_id=1, status="DELETED", delete_flag="Y",
                original_filename="retired.txt", source_generation=0, bucket_name="bucket",
                object_name=f"s3://bucket/{source.key}",
            ))
        with pytest.raises(Conflict):
            policy.authorize(request, context=context())
    else:
        grant = policy.authorize(request, context=context())
        assert grant.source is None
        assert set(grant.legacy_sources) == {source.key, f"/bucket/{source.key}", f"s3://bucket/{source.key}"}


def test_revoked_membership_stops_grant_even_with_completed_artifact(setup):
    policy, payload, update, _, _ = setup
    update("cleanse_memberships", tenant_id="other")
    with pytest.raises(ScopeDenied):
        policy.authorize(payload, context=context())


@pytest.mark.parametrize(
    "action,extra",
    [("upload", {}), ("execute", {}), ("delete", {"parser_version": "v2"})],
)
def test_authorization_contract_has_explicit_action_payload(action, extra):
    with pytest.raises(ValidationError):
        KnowledgeAuthorizationRequest(
            knowledge_id=1, file_id="b" * 32, file_version=0, action=action, **extra
        )
