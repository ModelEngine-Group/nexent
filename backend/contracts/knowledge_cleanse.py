# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management-local KB cleansing context, separate from Runtime run callbacks."""

from contracts.agentos_knowledge import (
    CleanseResult,
    FileCleanseRequest,
    FileCleanseState,
    KnowledgeFileReference,
    ObjectReference,
)
from pydantic import Field


class KnowledgeCleanseRequest(KnowledgeFileReference):
    knowledge_id: int = Field(gt=0, le=2**31 - 1)
    file_version: int = Field(ge=0, le=2**31 - 1)
    source: ObjectReference
    filename: str = Field(min_length=1, max_length=1024)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class KnowledgeCleanseLookup(KnowledgeFileReference):
    knowledge_id: int = Field(gt=0, le=2**31 - 1)
    file_version: int = Field(ge=0, le=2**31 - 1)
    job_id: str = Field(pattern=r"^[0-9a-f]{32}$")


class KnowledgeCleanseState(KnowledgeCleanseLookup, CleanseResult):
    pass


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
