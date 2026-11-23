# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Register a reviewed service implementation and freeze business contracts from affected callers."""

from contracts.agentos import MCPExecutionBinding
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.evolution import DevelopmentExperimentRequest, ToolUseRule
from contracts.evolution_sources import example_source_keys
from infrastructure.mcp_execution import (
    build_mcp_tool,
    mcp_binding_identity,
    mcp_execution_revision,
    select_mcp_server,
)
from infrastructure.rdb.mcp_execution_records import read_bound_mcp_tools, read_mcp_execution_servers
from management.db.evaluation import experiments as jobs
from management.db.evaluation import tool_builds as db
from management.services.evaluation.evolution_access import require_business_agent_edit
from management.services.evaluation.experiments import _io, _snapshot, snapshot_digest
from management.services.evaluation.feedback_handoff import completed_baseline, require_development_sources
from management.services.evaluation.replay_cases import get_development_case
from management.services.evaluation.tool_repairs import (
    maintainer_brief,
    require_tool_maintenance,
    verified_example,
)
from management.services.evaluation.tool_set_candidates import invalid
from nexent.core.agents.resources.replay_tools import argument_digest


def _record(tenant, bid):
    item = db.build_record(tenant, bid)
    if not item:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
    if argument_digest(item["manifest"]) != item["digest"]:
        invalid("The reviewed tool build manifest has changed")
    return item


def register_build(tenant, user, fid, request):
    feedback = maintainer_brief(tenant, user, fid)
    handoff = jobs.read_handoff(tenant, fid)
    manifest = {
        **request.model_dump(),
        "feedback_id": fid,
        "server_id": handoff["server_id"],
        "binding_revision": feedback["binding_revision"],
        "suite_digest": argument_digest(feedback["test_suite"]),
    }
    digest = argument_digest(manifest)
    bid = db.store_build(tenant, user, fid, digest, manifest)
    return {"build_id": bid, "digest": digest}


def _key(agent, version, name):
    return (agent, version, agent, version, name)


def _binding_names(scope):
    return {(i["agent_id"], i["version_no"], i["owner_agent"], i["owner_version"], i["name"]) for i in scope}


def _check(label, rule, observation):
    # Hash the exact observed original behavior. A different failure cannot verify the reviewed build.
    return {
        "label": label,
        "rule": rule,
        "original": {
            k: observation[k] for k in ("remote", "kind", "inputs", "content", "before", "after", "error")
        },
    }


def freeze_guard(tenant, user, build, request, spec):
    agent, version = spec.resource.agent_id, spec.resource.version_no
    require_business_agent_edit(agent, tenant, user)
    server_id = build["manifest"]["server_id"]
    scope = db.published_callers(tenant, server_id)
    if _key(agent, version, request.tool_name) not in _binding_names(scope):
        invalid("Choose a currently published caller of this service")
    matches = [
        MCPExecutionBinding.model_validate(t.parameters)
        for t in spec.resource.tools
        if t.tool_id == "mcp" and t.version == "1" and t.parameters.get("tool_name") == request.tool_name
    ]
    if len(matches) != 1 or matches[0].server_id != server_id:
        invalid("This experiment cannot establish the physical service for the selected root tool")
    baseline = snapshot_digest(spec)
    plan, trials = completed_baseline(tenant, request.experiment_id, agent, version, baseline)
    require_development_sources(tenant, agent, [request.case_id], plan)
    case = get_development_case(tenant, user, agent, version, request.case_id)
    if plan["cases"].get(str(request.case_id)) != case["digest"]:
        invalid("The caller regression task changed after the baseline")
    original = jobs.read_handoff(tenant, build["feedback_id"])
    if example_source_keys(case["task"]).intersection(original["source_keys"]):
        invalid("Use different materials for the caller regression task")
    example = verified_example(case, trials.get(request.case_id, {}), "pass", baseline, request.tool_name)
    observed = example["observation"]
    rule = ToolUseRule(
        name=observed["remote"],
        min_calls=1,
        max_calls=1,
        arguments=example["arguments"],
        expected_mcp_reply=example["expected"],
    )
    data = {
        "rule": rule.model_dump(mode="json"),
        "observation": observed,
        "receipt_id": example["receipt_id"],
        "baseline": baseline,
        "case_digest": case["digest"],
        "binding_revision": matches[0].revision,
    }
    require_business_agent_edit(agent, tenant, user)
    db.store_guard(tenant, build["build_id"], user, request, agent, version, data)
    return {"build_id": build["build_id"], "case_id": request.case_id}


async def approve_guard(tenant, user, bid, request):
    scope = await _io("find-tool-caller", jobs.scope, tenant, request.experiment_id)
    if not scope:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
    await _io("authorize-caller-regression", require_business_agent_edit, scope["agent_id"], tenant, user)
    build = await _io("read-tool-build", _record, tenant, bid)
    plan = await _io("read-caller-baseline", jobs.read_plan, tenant, request.experiment_id, True)
    if not plan or plan["request"]["candidate_type"] != "baseline":
        invalid("Select a completed baseline")
    spec = await _snapshot(DevelopmentExperimentRequest.model_validate(plan["request"]), tenant, user, "base")
    return await _io("approve-caller-regression", freeze_guard, tenant, user, build, request, spec)


def _current_revision(tenant, key, server_id, servers):
    agent, version, _, _, name = key
    rows = read_bound_mcp_tools(agent, version, tenant, [name])
    if len(rows) != 1:
        return None
    row = rows[0]
    try:
        tool = build_mcp_tool(row)
        sid, host = select_mcp_server(servers, tool.usage, tenant)
        if sid != server_id:
            return None
        return mcp_execution_revision(
            tenant,
            agent,
            version,
            mcp_binding_identity(row),
            tool,
            row["origin_name"] or tool.class_name,
            sid,
            host,
        )
    except (LookupError, ValueError):
        return None


def verification_plan(tenant, bid):
    build = _record(tenant, bid)
    manifest = build["manifest"]
    source = maintainer_brief(tenant, build["created_by"], build["feedback_id"])
    handoff = jobs.read_handoff(tenant, build["feedback_id"])
    if manifest["suite_digest"] != argument_digest(source["test_suite"]):
        invalid("The source tests no longer match the reviewed build")
    # Cancelled source experiments cannot authorize further use of their test material.
    approval = db.source_approval(tenant, build["feedback_id"])
    require_business_agent_edit(handoff["agent_id"], tenant, approval["created_by"])
    for eid in [handoff["repeat_experiment_id"], approval["experiment_id"]]:
        if not jobs.read_plan(tenant, eid, True):
            invalid("The source reproduction is no longer available")
    inventory = db.published_callers(tenant, manifest["server_id"])
    available = _binding_names(inventory)
    origin = _key(handoff["agent_id"], handoff["version_no"], handoff["tool_name"])
    if origin not in available:
        invalid("The original caller is no longer current")
    servers = read_mcp_execution_servers(tenant)
    if _current_revision(tenant, origin, manifest["server_id"], servers) != manifest["binding_revision"]:
        invalid("The original tool binding has changed. Reproduce the issue using the current binding")
    covered = {origin}
    accepted_cases = set()
    checks = [
        _check(label, source["test_suite"][label], source[label]["observation"])
        for label in ("failure", "protection")
    ]
    for guard in db.guard_records(tenant, bid):
        key = _key(guard["agent_id"], guard["version_no"], guard["tool_name"])
        if key not in available:
            continue
        plan = jobs.read_plan(tenant, guard["experiment_id"], True)
        if not plan or plan["snapshots"]["base"] != guard["data"]["baseline"]:
            continue
        try:
            require_business_agent_edit(key[0], tenant, guard["approved_by"])
            require_development_sources(tenant, key[0], [guard["case_id"]], plan)
        except AppException as exc:
            if exc.error_code not in {
                ErrorCode.COMMON_FORBIDDEN,
                ErrorCode.COMMON_VALIDATION_ERROR,
                ErrorCode.AGENTSPACE_AGENT_NOT_FOUND,
            }:
                raise
            continue
        label = f"caller/{guard['experiment_id']}/{guard['case_id']}/{guard['tool_name']}"
        identity = (key, guard["data"]["case_digest"])
        if (
            identity in accepted_cases
            or _current_revision(tenant, key, manifest["server_id"], servers)
            != guard["data"]["binding_revision"]
        ):
            continue
        accepted_cases.add(identity)
        if any(check["label"] == label for check in checks):
            continue
        checks.append(_check(label, guard["data"]["rule"], guard["data"]["observation"]))
        covered.add(key)
    plan = {
        "build_digest": build["digest"],
        "callers": inventory,
        "checks": checks,
        "uncovered": [list(key) for key in sorted(available - covered)],
    }
    return manifest, plan, argument_digest(plan)


def build_status(tenant, user, bid):
    build = _record(tenant, bid)
    require_tool_maintenance(tenant, user, build["manifest"]["server_id"])
    manifest, plan, digest = verification_plan(tenant, bid)
    return {
        "build_id": bid,
        "manifest": manifest,
        "plan_digest": digest,
        "caller_count": len(plan["callers"]),
        "missing_caller_count": len(plan["uncovered"]),
        "case_count": len(plan["checks"]),
        "verification": db.latest_run(tenant, bid, digest),
    }


def list_builds(tenant, user, fid):
    maintainer_brief(tenant, user, fid)
    return db.build_ids(tenant, fid)
