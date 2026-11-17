# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management-local KB cleansing context, separate from Runtime run callbacks."""

import json
import re
from uuid import NAMESPACE_URL, uuid5

from contracts.agentos_knowledge import (
    CleanseResult,
    FileCleanseLookup,
    FileCleanseRequest,
    FileCleanseState,
    KnowledgeCleanseLookup,
    KnowledgeFileReference,
    ObjectReference,
)
from pydantic import Field

CLEANSE_QUEUE_NAMESPACE = "management-file-cleanse"
CLEANSE_DISPATCH_DATASET = "knowledge_cleanse_dispatch"
CLEANSE_HANDLER = "file.cleanse"


class KnowledgeCleanseRequest(KnowledgeFileReference):
    knowledge_id: int = Field(gt=0, le=2**31 - 1)
    file_version: int = Field(ge=0, le=2**31 - 1)
    source: ObjectReference
    filename: str = Field(min_length=1, max_length=1024)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class KnowledgeCleanseState(KnowledgeCleanseLookup, CleanseResult):
    pass


def cleanse_lookup(row, request):
    """Derive an output owner only from the matching admitted request and row."""
    try:
        if parse_cleanse_request(row) != request:
            raise ValueError('Cleansing request does not match its admission snapshot')
    except (KeyError, TypeError) as error:
        raise ValueError('Invalid cleansing admission snapshot') from error
    if isinstance(request, FileCleanseRequest):
        fields = ('run_id',)
        schema = FileCleanseLookup
    elif isinstance(request, KnowledgeCleanseRequest):
        fields = ('knowledge_id', 'file_id', 'file_version')
        schema = KnowledgeCleanseLookup
    else:
        raise TypeError('Expected a typed cleansing request')
    if any(row[name] != getattr(request, name) for name in fields):
        raise ValueError('Cleansing output owner does not match the admitted request')
    return schema.model_validate({name: row[name] for name in (*fields, 'job_id')})


def knowledge_artifact_prefix(reference, artifact, *, job_id=None):
    """Resolve the authorized layout; shared historical references remain read-only."""
    if not isinstance(reference, KnowledgeFileReference) or not isinstance(artifact, ObjectReference):
        raise TypeError('Expected a knowledge reference and pinned artifact')
    if artifact.key.startswith('artifacts/'):
        return ''
    start = f'knowledge-cleanse/{reference.knowledge_id}/{reference.file_id}/{reference.file_version}/'
    match = re.fullmatch(re.escape(start) + r'([0-9a-f]{32})/artifacts/[0-9a-f]{64}/' + re.escape(artifact.sha256) + r'\.json', artifact.key)
    if match is None:
        raise ValueError('Artifact directory does not match its knowledge owner')
    if job_id is not None and match[1] != job_id:
        raise ValueError('Artifact directory does not match its admitted job')
    return start + match[1] + '/'


def cleanse_job_id(request, tenant_id, user_id):
    """Preserve run and KB job identities while making lost responses queryable."""
    if not isinstance(request, (FileCleanseRequest, KnowledgeCleanseRequest)):
        raise TypeError("Expected a cleansing request")
    if any(not isinstance(value, str) or not value for value in (tenant_id, user_id)):
        raise ValueError("Expected trusted tenant and actor identities")
    scope = request.run_id if isinstance(request, FileCleanseRequest) else [
        "knowledge", request.knowledge_id, request.file_id, request.file_version,
    ]
    return uuid5(NAMESPACE_URL, json.dumps([
        tenant_id, user_id, scope, request.idempotency_key,
    ], separators=(",", ":"))).hex


def parse_cleanse_request(row):
    if row["scope_kind"] == "run":
        request = FileCleanseRequest.model_validate(row["request_payload"])
        fields = ("run_id",)
    elif row["scope_kind"] == "knowledge":
        request = KnowledgeCleanseRequest.model_validate(row["request_payload"])
        fields = ("knowledge_id", "file_id", "file_version")
    else:
        raise ValueError("Unsupported cleansing scope")
    if any(getattr(request, name) != row[name] for name in fields):
        raise ValueError("Cleansing snapshot does not match its authorization scope")
    return request


def cleanse_state(row):
    result = {
        "job_id": row["job_id"],
        "status": row["status"],
        "artifact": ObjectReference.model_validate(row["artifact"])
        if row["artifact"]
        else None,
        "error_code": row["error_code"],
    }
    if row["scope_kind"] == "run":
        return FileCleanseState(run_id=row["run_id"], **result)
    if row["scope_kind"] == "knowledge":
        return KnowledgeCleanseState(
            knowledge_id=row["knowledge_id"],
            file_id=row["file_id"],
            file_version=row["file_version"],
            **result,
        )
    raise ValueError("Unsupported cleansing scope")
