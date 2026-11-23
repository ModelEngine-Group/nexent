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
from infrastructure.rdb.client import get_db_session
from management.db.evaluation.trace_cases import trace_case_draft, verified_baseline, verified_repair
from management.db.evaluation.replay_cases import read_replay_case, regression_members, save_replay_case, set_regression_membership
from management.db.evaluation.evaluator import get_evaluator
from infrastructure.rdb.skill_execution_records import read_bound_skills
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


def preview_trace_case(tenant, user, agent, version, turn, use_previous_task=False):
    require_business_agent_edit(agent, tenant, user)
    with get_db_session() as session:
        return trace_case_draft(session, tenant, user, agent, version, turn, use_previous_task)


def _approve_trace(request, draft):
    trace = request.trace
    if trace.draft_digest != draft["draft_digest"]:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Review the updated source before confirming")
    count = draft["attachment_count"]
    if (count is None or any(slot > count for slot in trace.unused_attachment_slots)
            or count - len(trace.unused_attachment_slots) > len(request.attachments)):
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Provide the approved replay attachments")
    if draft["tool_count"] and not trace.tools_require_no_reset:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Replay needs a verified tool starting state")
    return {"turn_id": trace.turn_id, "task_turn_id": draft["task_turn_id"], "purpose": trace.purpose,
            "trajectory_id": draft["trajectory_id"], "correction_trajectory_id": draft["correction_trajectory_id"],
            "source_group": draft["source_group"], "draft_digest": draft["draft_digest"],
            "unused_attachment_slots": sorted(trace.unused_attachment_slots)}


def require_trace_baseline(tenant, agent, version, case, rule, language, judge, snapshot=None):
    with get_db_session() as session:
        passed = verified_baseline(session, tenant, agent, version, case["case_id"], case["digest"],
                                   case["task"]["trace_source"]["purpose"], rule, language, judge, snapshot)
    if not passed:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Run the released baseline with the same scoring rule first")


def freeze_development_case(request: ReplayCaseRequest, user_id: str, tenant_id: str):
    require_business_agent_edit(request.agent_id, tenant_id, user_id)
    published_business_agent(tenant_id, request.agent_id, request.version_no)
    if request.trace:
        _approve_trace(request, preview_trace_case(tenant_id, user_id, request.agent_id, request.version_no,
                                                  request.trace.turn_id, request.trace.use_previous_task))
    if request.expected_skill_names:
        names = {row["name"] for row in read_bound_skills(request.agent_id, request.version_no, tenant_id)}
        if not set(request.expected_skill_names) <= names:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Expected Skill must be enabled on this Agent version")
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
    if request.expected_skill_names is not None:
        task["expected_skill_names"] = sorted(request.expected_skill_names)
    if request.tool_use is not None:
        task["tool_use"] = request.tool_use.model_dump(mode="json")
    if request.source_group is not None:
        if not request.source_group.strip():
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Provide a non-empty source group")
        task["source_group"] = request.source_group.strip()
    require_business_agent_edit(request.agent_id, tenant_id, user_id)
    if request.trace:
        with get_db_session() as session:
            draft = trace_case_draft(session, tenant_id, user_id, request.agent_id, request.version_no,
                                     request.trace.turn_id, request.trace.use_previous_task)
            task["trace_source"] = _approve_trace(request, draft)
            return save_replay_case(tenant_id, request.agent_id, request.version_no, user_id, task, transaction=session)
    return save_replay_case(tenant_id, request.agent_id, request.version_no, user_id, task)


def get_development_case(tenant_id, user_id, agent_id, version_no, case_id):
    require_business_agent_edit(agent_id, tenant_id, user_id)
    row = read_replay_case(tenant_id, agent_id, version_no, case_id)
    if not row:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Replay case is outside this Agent version")
    return row


def update_regression_case(tenant, user, agent, version, case_id, enabled, evaluator_id=None, judge_model_id=None, language="zh"):
    case = get_development_case(tenant, user, agent, version, case_id)
    published_business_agent(tenant, agent, version)
    scoring = None
    if enabled:
        rule = get_evaluator(evaluator_id, tenant) if evaluator_id is not None else None
        if not rule or rule["status"] != "PUBLISHED":
            raise AppException(ErrorCode.AGENT_EVALUATION_EVALUATOR_NOT_PUBLISHED)
        if rule["evaluator_type"] != "code" and judge_model_id is None:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Select a judge model for this fixed regression task")
        scoring = {"evaluator": rule, "judge_model_id": judge_model_id if rule["evaluator_type"] != "code" else None,
                   "language": language}
        if case["task"].get("trace_source"):
            require_trace_baseline(tenant, agent, version, case, rule, language, scoring["judge_model_id"])
            if case["task"]["trace_source"]["purpose"] == "reproduce":
                with get_db_session() as session:
                    repaired = verified_repair(session, tenant, agent, version, case_id, case["digest"], scoring)
                if not repaired:
                    raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Verify that a candidate fixes this task before adding it to regression")
    set_regression_membership(tenant, agent, version, case_id, user, enabled, scoring)
    return {"case_id": case_id, "enabled": enabled}


def freeze_regression_members(tenant, user, agent, version):
    require_business_agent_edit(agent, tenant, user)
    published_business_agent(tenant, agent, version)
    frozen = {}
    for member in regression_members(tenant, agent):
        case_id = member["source_case_id"]
        if member["source_version"] != version:
            source = get_development_case(tenant, user, agent, member["source_version"], case_id)
            copy = save_replay_case(tenant, agent, version, user, source["task"])
            if copy["digest"] != member["digest"]:
                raise ValueError("Fixed regression task changed while copying the release manifest")
            case_id = copy["case_id"]
        if not member["scoring"]:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Choose a published rubric for each fixed regression task")
        frozen[str(case_id)] = {"source_case_id": member["source_case_id"], "digest": member["digest"], "scoring": member["scoring"]}
    return frozen


def approved_example_input(tenant, agent_id, task, selection):
    if selection.attachment_name is None:
        content = task["query"]
    else:
        file = next((f for f in task["attachments"] if f["name"] == selection.attachment_name), None)
        if file is None:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Unknown example attachment")
        raw = _read_bounded(_archive_key(tenant, agent_id, file["sha256"]), file["size"])
        if sha256(raw).hexdigest() != file["sha256"]:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Example attachment changed")
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Select an excerpt from a UTF-8 text attachment") from exc
    if selection.input_excerpt not in content:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Example input must appear in the selected source")
    return selection.input_excerpt


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
