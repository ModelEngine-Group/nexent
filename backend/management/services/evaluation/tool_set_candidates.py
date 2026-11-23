# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Generate subtractive root-tool variants from verified development observations."""
import json
from collections import Counter

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from management.db.evaluation import experiments as jobs
from management.db.evaluation.candidates import get_prompt_candidate, selectable_tool_names, store_prompt_candidates, text_digest
from management.services.evaluation.evolution_access import require_business_agent_edit
from management.services.evaluation.replay_cases import get_development_case


def invalid(message):
    raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, message)


def catalog_source(spec, selectable, baseline_digest):
    visible = sorted({item["content"]["name"] for item in spec.resource.evaluation_options.context_items or ()
                      if item["type"] == "tool" and item["content"].get("name") in selectable})
    return {"baseline": baseline_digest, "selectable": visible}


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def generate_tool_sets(tenant, user, eid, request, source, agent, version):
    require_business_agent_edit(agent, tenant, user)
    rows = jobs.trials(tenant, eid)
    if any(r["status"] in {"pending", "running", "cancelled"} for r in rows):
        invalid("Finish the baseline experiment before proposing tool changes")
    trials = {row["case_id"]: row for row in rows if row["variant"] == "base"}
    excess, necessary, evidence = Counter(), set(), []
    for cid in request.failure_case_ids + request.protection_case_ids:
        failure = cid in request.failure_case_ids
        row = trials.get(cid)
        case = get_development_case(tenant, user, agent, version, cid)
        result = (row or {}).get("result") or {}
        grade = result.get("tool_use") or {}
        if (not row or row["status"] != ("fail" if failure else "pass") or not row["receipt_id"]
                or result.get("case_digest") != case["digest"] or grade.get("status") != row["status"]):
            invalid("Select graded baseline calls with matching frozen task evidence")
        rules = case["task"]["tool_use"]["rules"]
        if failure:
            forbidden = {r["name"] for r in rules if r["max_calls"] == 0}
            wrong = forbidden.intersection(p.get("tool") for p in grade["issues"] if p["reason"] == "too_many")
            if not wrong:
                invalid("Each failure must show a call to a tool this task should skip")
            excess.update(wrong)
        necessary.update(r["name"] for r in rules if r["min_calls"] > 0)
        evidence.append({"case_id": cid, "receipt_id": row["receipt_id"], "case_digest": case["digest"]})
    removable = sorted(set(excess).intersection(source["selectable"]).difference(necessary),
                       key=lambda name: (-excess[name], name))
    if not removable:
        invalid("Every observed extra tool is protected or outside this Agent's selectable tools")
    scopes = [[name] for name in removable[:3]]
    if len(removable) > 1:
        scopes.append(removable)
    variants = [(encode({"retained": sorted(set(source["selectable"]).difference(drop))}),
                 {"method": "T3", "experiment_id": eid, "evidence": evidence, "removed": drop}) for drop in scopes]
    require_business_agent_edit(agent, tenant, user)
    ids = store_prompt_candidates(tenant, agent, version, user, encode(source), variants, field="agent.tools")
    return {"variants": [{"candidate_id": None, "removed": [], "retained": source["selectable"]},
                         *[{"candidate_id": cid, "removed": drop, "retained": sorted(set(source["selectable"])-set(drop))}
                           for cid, drop in zip(ids, scopes)]]}


def resolve_tool_set(tenant, agent, version, candidate_id, spec, baseline_digest):
    row = get_prompt_candidate(tenant, agent, version, candidate_id, field="agent.tools")
    if not row:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Tool-set candidate outside the released Agent")
    source = catalog_source(spec, selectable_tool_names(tenant, agent, version), baseline_digest)
    if (row["source_text"] != encode(source) or text_digest(row["source_text"]) != row["base_digest"]
            or text_digest(row["result_text"]) != row["result_digest"]):
        invalid("Tool-set baseline or candidate changed")
    retained = json.loads(row["result_text"])["retained"]
    if not isinstance(retained, list) or not set(retained) < set(source["selectable"]):
        invalid("Tool-set candidate must strictly narrow the released tool selection")
    return sorted(set(source["selectable"]).difference(retained))
