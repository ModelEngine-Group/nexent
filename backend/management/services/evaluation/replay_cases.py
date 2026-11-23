# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Freeze approved business inputs and allocate independently verified attachment copies."""

import io
import re
from contextlib import closing, contextmanager
from hashlib import sha256
from uuid import uuid4

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.evolution import ReplayCaseRequest
from infrastructure.object_storage.client import minio_client
from management.db.evaluation.replay_cases import read_replay_case, save_replay_case
from management.services.agent.preparation.evaluation_snapshot import build_evaluation_input
from management.services.evaluation.evolution_access import published_business_agent, require_business_agent_edit


MAX_CASE_BYTES = 64 * 1024 * 1024


def _archive_key(tenant_id, agent_id, digest):
    return f"evolution/task-inputs/{sha256(tenant_id.encode()).hexdigest()}/{agent_id}/{digest}"


def _read_bounded(key, limit):
    ok, stream = minio_client.get_file_stream(key)
    if not ok:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Replay input is unavailable")
    with closing(stream):
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Replay input exceeds the case byte limit")
    return data


def _write(key, data):
    ok, _ = minio_client.upload_fileobj(io.BytesIO(data), key)
    if not ok:
        raise OSError("Could not store replay input")


def freeze_development_case(request: ReplayCaseRequest, user_id: str, tenant_id: str):
    require_business_agent_edit(request.agent_id, tenant_id, user_id)
    published_business_agent(tenant_id, request.agent_id, request.version_no)
    for file in request.attachments:
        if not file.object_name.startswith(f"attachments/{user_id}/"):
            raise AppException(ErrorCode.COMMON_FORBIDDEN, "Submit an approved copy of your own attachment")
    remaining = MAX_CASE_BYTES
    manifest = []
    for file in request.attachments:
        data = _read_bounded(file.object_name, remaining)
        remaining -= len(data)
        digest = sha256(data).hexdigest()
        _write(_archive_key(tenant_id, request.agent_id, digest), data)
        manifest.append({"name": file.name, "sha256": digest, "size": len(data)})
    task = {"family": request.family, "query": request.query, "expected": request.expected, "attachments": manifest}
    require_business_agent_edit(request.agent_id, tenant_id, user_id)
    return save_replay_case(tenant_id, request.agent_id, request.version_no, user_id, task)


def get_development_case(tenant_id, user_id, agent_id, version_no, case_id):
    require_business_agent_edit(agent_id, tenant_id, user_id)
    row = read_replay_case(tenant_id, agent_id, version_no, case_id)
    if not row:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Replay case is outside this Agent version")
    return row


def temporary_input_prefix(user_id, attempt):
    if not re.fullmatch(r"[a-f0-9]{32}", attempt):
        raise ValueError("Invalid replay attempt")
    return f"attachments/{user_id}/evolution-replay/{attempt}"


def remove_trial_inputs(user_id, attempt, files):
    prefix = temporary_input_prefix(user_id, attempt)
    errors = [file for file in files if not minio_client.delete_file(f"{prefix}/{file['name']}")[0]]
    if errors:
        raise OSError("Could not remove staged replay attachments")


@contextmanager
def stage_case_input(tenant_id, user_id, agent_id, version_no, case_id, attempt=None):
    row = get_development_case(tenant_id, user_id, agent_id, version_no, case_id)
    task = row["task"]
    attempt = attempt or uuid4().hex
    prefix = temporary_input_prefix(user_id, attempt)
    copies = []
    files = []
    try:
        for file in task["attachments"]:
            source = _archive_key(tenant_id, agent_id, file["sha256"])
            data = _read_bounded(source, file["size"])
            if len(data) != file["size"] or sha256(data).hexdigest() != file["sha256"]:
                raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Archived replay attachment changed")
            key = f"{prefix}/{file['name']}"
            copies.append(file)
            _write(key, data)
            if sha256(_read_bounded(key, len(data))).hexdigest() != file["sha256"]:
                raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Staged replay attachment changed")
            files.append({"name": file["name"], "object_name": key})
        yield build_evaluation_input(task["query"], files, [], user_id, tenant_id)
    finally:
        remove_trial_inputs(user_id, attempt, copies)
