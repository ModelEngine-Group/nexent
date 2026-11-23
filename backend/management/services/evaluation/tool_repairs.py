# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Turn reproduced remote-tool failures into a maintainer's runnable business contract."""

from contracts.agentos import MCPExecutionBinding
from contracts.constants.constants import CAN_EDIT_ALL_USER_ROLES, PERMISSION_EDIT
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.evolution import DevelopmentExperimentRequest
from contracts.evolution_sources import example_source_keys
from contracts.roles import has_any_role
from contracts.tool_repair import ToolReproductionSuite
from management.db.evaluation import experiments as jobs
from management.db.identity.group import query_group_ids_by_user_in_tenant
from management.db.identity.user_tenant import get_user_role_by_tenant
from management.db.mcp.remote import get_mcp_record_by_id_and_tenant
from management.services.evaluation.evolution_access import require_business_agent_edit
from management.services.evaluation.experiments import _io, _snapshot, snapshot_digest
from management.services.evaluation.feedback_handoff import completed_baseline, require_development_sources
from management.services.evaluation.replay_cases import get_development_case
from management.services.evaluation.tool_set_candidates import invalid
from management.services.mcp.permissions import catalog_permission


def verified_example(case, trial, status, digest, tool):
    result = trial.get("result") or {}
    graded = result.get("tool_use") or {}
    rules = [r for r in (case["task"].get("tool_use") or {}).get("rules", ()) if r["name"] == tool]
    rows = [r for r in graded.get("mcp_evidence", ()) if r["tool"] == tool]
    if (
        len(rules) != 1
        or len(rows) != 1
        or not trial.get("receipt_id")
        or trial.get("status") != status
        or graded.get("status") != status
        or result.get("case_digest") != case["digest"]
        or result.get("snapshot_digest") != digest
    ):
        invalid("Choose graded tasks with one observed remote call and an independent business state check")
    rule, observed = rules[0], rows[0]
    expected = rule.get("expected_mcp_reply") or {}
    if (
        not expected.get("fixture")
        or not observed["input_matches"]
        or not observed.get("before")
        or not observed.get("after")
        or observed["state_matches"] is None
        or (observed["reply_matches"] and observed["state_matches"]) != (status == "pass")
    ):
        invalid("The evidence must locate the difference after the correct request reached the remote service")
    allowed = {"wrong_mcp_reply", "wrong_mcp_state", "mcp_remote_error"}
    if observed["error"]:
        allowed.add("raised")
    if any(i.get("reason") not in allowed or i.get("tool") != tool for i in graded["issues"]):
        invalid("Resolve other tool or argument failures before proposing an implementation change")
    return {
        "arguments": rule["arguments"],
        "expected": expected,
        "observation": observed,
        "receipt_id": trial["receipt_id"],
    }


def freeze_tool_brief(tenant, user, eid, request, spec):
    resource = spec.resource
    agent, version = resource.agent_id, resource.version_no
    require_business_agent_edit(agent, tenant, user)
    targets = [
        MCPExecutionBinding.model_validate(binding.parameters)
        for binding in resource.tools
        if binding.tool_id == "mcp"
        and binding.version == "1"
        and binding.parameters.get("tool_name") == request.tool_name
    ]
    if len(targets) != 1 or not targets[0].server_id:
        invalid("Choose one directly bound tool from a registered tenant MCP service")
    target = targets[0]
    digest = snapshot_digest(spec)
    if eid == request.repeat_experiment_id:
        invalid("Use a separate baseline execution to reproduce the problem")
    plan, trials = completed_baseline(tenant, eid, agent, version, digest)
    repeat_plan, repeats = completed_baseline(tenant, request.repeat_experiment_id, agent, version, digest)
    ids = [request.failure_case_id, request.protection_case_id]
    require_development_sources(tenant, agent, ids, plan)
    require_development_sources(tenant, agent, ids[:1], repeat_plan)
    cases = [get_development_case(tenant, user, agent, version, cid) for cid in ids]
    if (
        any(plan["cases"].get(str(cid)) != case["digest"] for cid, case in zip(ids, cases))
        or repeat_plan["cases"].get(str(ids[0])) != cases[0]["digest"]
        or repeat_plan["evaluator"] != plan["evaluator"]
    ):
        invalid("Use the same frozen failure task and evaluator for reproduction")
    failure, guard = [
        verified_example(case, trials.get(cid, {}), status, digest, request.tool_name)
        for case, cid, status in zip(cases, ids, ("fail", "pass"))
    ]
    repeat = verified_example(cases[0], repeats.get(ids[0], {}), "fail", digest, request.tool_name)
    original = failure["observation"]
    if (
        failure["receipt_id"] == repeat["receipt_id"]
        or any(
            original[k] != repeat["observation"][k]
            for k in ("remote", "kind", "inputs", "content", "before", "after", "error")
        )
        or guard["observation"]["remote"] != original["remote"]
    ):
        invalid("Repeat the same remote request and result from the same initial state")
    if example_source_keys(cases[0]["task"]).intersection(example_source_keys(cases[1]["task"])):
        invalid("Choose a protection task from separate business material")
    brief = {
        "method": "T4",
        "agent_id": agent,
        "version_no": version,
        "server_id": target.server_id,
        "instance_id": target.instance_id,
        "binding_revision": target.revision,
        "tool_name": request.tool_name,
        "goal": request.goal,
        "baseline_digest": digest,
        "source_case_ids": ids,
        "source_keys": sorted(set.union(*(example_source_keys(c["task"]) for c in cases))),
        "failure": failure,
        "protection": guard,
        "repeat_receipt": repeat["receipt_id"],
        "repeat_experiment_id": request.repeat_experiment_id,
    }
    require_business_agent_edit(agent, tenant, user)
    return jobs.store_handoff(tenant, user, eid, brief)


async def share_tool_brief(tenant, user, eid, request):
    scope = await _io("find-tool-repair-source", jobs.scope, tenant, eid)
    if not scope:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
    await _io("authorize-tool-repair-source", require_business_agent_edit, scope["agent_id"], tenant, user)
    plan = await _io("read-tool-repair-source", jobs.read_plan, tenant, eid, True)
    if not plan or plan["request"]["candidate_type"] != "baseline":
        invalid("Select a completed baseline")
    spec = await _snapshot(DevelopmentExperimentRequest.model_validate(plan["request"]), tenant, user, "base")
    return await _io("freeze-tool-repair-examples", freeze_tool_brief, tenant, user, eid, request, spec)


def require_tool_maintenance(tenant, user, server_id):
    roles = get_user_role_by_tenant(user, tenant)
    service = get_mcp_record_by_id_and_tenant(server_id, tenant)
    if not roles or not service:
        raise AppException(ErrorCode.COMMON_FORBIDDEN)
    all_tools = has_any_role(roles, CAN_EDIT_ALL_USER_ROLES)
    groups = query_group_ids_by_user_in_tenant(user, tenant)
    if catalog_permission(service, user, all_tools, groups) != PERMISSION_EDIT:
        raise AppException(ErrorCode.COMMON_FORBIDDEN)


def maintainer_brief(tenant, user, fid):
    brief = jobs.read_handoff(tenant, fid)
    if not brief or brief.get("method") != "T4":
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
    require_tool_maintenance(tenant, user, brief["server_id"])
    require_development_sources(tenant, brief["agent_id"], brief["source_case_ids"], {})
    remote = brief["failure"]["observation"]["remote"]
    cases = {
        label: {
            "name": remote,
            "min_calls": 1,
            "max_calls": 1,
            "arguments": brief[label]["arguments"],
            "expected_mcp_reply": brief[label]["expected"],
        }
        for label in ("failure", "protection")
    }
    suite = ToolReproductionSuite(format="nexent-mcp-repair-v1", **cases)
    result = {
        key: brief[key]
        for key in (
            "goal",
            "tool_name",
            "binding_revision",
            "instance_id",
            "failure",
            "protection",
            "repeat_receipt",
        )
    }
    return {**result, "test_suite": suite.model_dump(mode="json")}
