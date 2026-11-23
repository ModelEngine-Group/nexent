# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Derive one schema-preserving MCP argument mapping from a verified failure and protection task."""
import json

from contracts.agentos import MCPExecutionBinding
from infrastructure.mcp_execution import registered_argument_format
from infrastructure.rdb.mcp_execution_records import read_bound_mcp_tools
from management.db.evaluation import experiments as jobs
from management.db.evaluation.candidates import get_prompt_candidate, store_prompt_candidates, text_digest
from management.services.evaluation.evolution_access import require_business_agent_edit
from management.services.evaluation.replay_cases import get_development_case
from management.services.evaluation.tool_set_candidates import encode, invalid
from nexent.core.agents.resources.argument_formats import formatted_value
from nexent.core.agents.resources.replay_tools import argument_digest


FIELD = "agent.tool_format"


def _binding(spec, tenant, name, field):
    resource = spec.resource
    matches = [tool for tool in resource.tools if tool.tool_id == "mcp" and tool.version == "1"
               and tool.parameters.get("tool_name") == name]
    rows = read_bound_mcp_tools(resource.agent_id, resource.version_no, tenant, [name])
    if len(matches) != 1 or len(rows) != 1:
        invalid("Select one directly bound MCP tool on the business Agent")
    tool = matches[0]
    ref = MCPExecutionBinding.model_validate(tool.parameters)
    if ref.instance_id != rows[0]["tool_instance_id"] or field in (ref.argument_overrides or {}):
        invalid("The mapping must target a public argument of the selected instance")
    try:
        rule = registered_argument_format(rows[0], field)
    except (ValueError, TypeError, SyntaxError) as exc:
        invalid(str(exc))
    current = ref.argument_formats or {}
    if field in current or current != (rows[0].get("released_argument_formats") or {}):
        invalid("This field is already mapped or changed since compilation")
    return tool, ref, rule


def generate_mapping(tenant, editor, eid, proposal, plan, spec):
    from management.services.evaluation.feedback_handoff import require_development_sources
    from management.services.evaluation.experiments import snapshot_digest

    resource = spec.resource
    agent, version = resource.agent_id, resource.version_no
    require_business_agent_edit(agent, tenant, editor)
    ids = [proposal.failure_case_id, proposal.protection_case_id]
    require_development_sources(tenant, agent, ids, plan)
    baseline = snapshot_digest(spec)
    if plan["request"]["candidate_type"] != "baseline" or baseline != plan["snapshots"]["base"]:
        invalid("Regenerate the evidence with the current released baseline")
    name, field = proposal.tool_name, proposal.field
    _, ref, rule = _binding(spec, tenant, name, field)
    trials = jobs.trials(tenant, eid)
    if any(row["status"] in {"pending", "running", "cancelled"} for row in trials):
        invalid("Complete the source experiment first")
    from management.services.evaluation.example_candidates import example_source_keys
    source_keys = set()
    rows = {row["case_id"]: row for row in trials if row["variant"] == "base"}
    for cid, expected_status in zip(ids, ("fail", "pass"), strict=True):
        task = get_development_case(tenant, editor, agent, version, cid)
        source_keys.update(example_source_keys(task["task"]))
        trial = rows.get(cid) or {}
        result = trial.get("result") or {}
        grade = result.get("tool_use") or {}
        if (not trial.get("receipt_id") or trial.get("status") != expected_status or grade.get("status") != expected_status
                or result.get("case_digest") != task["digest"] or plan["cases"].get(str(cid)) != task["digest"]
                or result.get("snapshot_digest") != baseline):
            invalid("Select a verified tool failure and a passing protection task from this baseline")
        rules = (task["task"].get("tool_use") or {}).get("rules", [])
        values = [r["arguments"][field] for r in rules if r["name"] == name and field in r["arguments"]]
        observations = [e for e in grade.get("argument_evidence", []) if (e["tool"], e["field"]) == (name, field)]
        if len(values) != 1 or len(observations) != 1:
            invalid("Each example must identify a single observed call and approved argument")
        expected, observation = values[0], observations[0]
        supplied = proposal.supplied_value if cid == ids[0] else expected
        try:
            mapped = formatted_value(rule, supplied)
        except ValueError as exc:
            invalid(str(exc))
        if (not isinstance(expected, str) or mapped != expected or (cid == ids[0] and expected == supplied)
                or observation["requested"] != argument_digest(supplied)
                or observation["effective"] != argument_digest(supplied)
                or observation["expected"] != argument_digest(expected)):
            invalid("The approved representation does not explain both the supplied and effective values")
    source = {"baseline": snapshot_digest(spec.model_copy(update={"observe_root_skill_choices": None})), "tool": name, "instance_id": ref.instance_id, "revision": ref.revision,
              "formats": ref.argument_formats or {}}
    proposed = {"field": field, "rule": rule}
    require_business_agent_edit(agent, tenant, editor)
    cid, = store_prompt_candidates(tenant, agent, version, editor, encode(source), [(encode(proposed),
        {"method":"T2_MAPPING", "experiment_id":eid, "source_case_ids":list(ids), "source_keys":sorted(source_keys)})], field=FIELD)
    return {"candidate_id": cid, "tool": name, **proposed}


def pin_mapping(spec, tenant, cid, baseline, arm):
    resource = spec.resource
    saved = get_prompt_candidate(tenant, resource.agent_id, resource.version_no, cid, field=FIELD)
    if not saved or any(text_digest(saved[key+"_text"]) != saved[digest] for key,digest in
                        (("source","base_digest"),("result","result_digest"))):
        invalid("The reviewed argument mapping is unavailable")
    source, proposed = (json.loads(saved[key+"_text"]) for key in ("source","result"))
    tool, ref, rule = _binding(spec, tenant, source["tool"], proposed["field"])
    if (source != {"baseline": baseline, "tool": ref.tool_name, "instance_id": ref.instance_id,
                   "revision": ref.revision, "formats": ref.argument_formats or {}} or rule != proposed["rule"]):
        invalid("The MCP instance or its argument schema changed since the mapping was proposed")
    if arm == "result":
        tool.parameters = {**tool.parameters, "argument_formats": {**source["formats"], proposed["field"]: rule}}
    return spec

def mapping_difference(base, result):
    def references(resource):
        return {tool.parameters["instance_id"]: MCPExecutionBinding.model_validate(tool.parameters)
                for tool in resource.tools if tool.tool_id == "mcp" and tool.version == "1"}
    before, after = references(base), references(result)
    changed = [key for key in before if before[key] != after.get(key)]
    if before.keys() != after.keys() or len(changed) != 1:
        invalid("Expected a single confirmed MCP binding change")
    key, = changed
    old, new = before[key], after[key]
    previous, proposed = old.argument_formats or {}, new.argument_formats or {}
    added = set(proposed).difference(previous)
    if (len(added) != 1 or old.model_copy(update={"argument_formats":new.argument_formats}) != new
            or any(proposed.get(k) != v for k,v in previous.items())):
        invalid("The confirmed mapping differs outside its approved field")
    return {"instance_id":key, "tool":new.tool_name, "field":added.pop(), "previous":previous, "proposed":proposed}
