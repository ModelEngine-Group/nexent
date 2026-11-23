# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Select complementary verified demonstrations from a development experiment."""

import json
import unicodedata
from itertools import combinations

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from management.db.evaluation import experiments as jobs
from management.db.evaluation.candidates import store_prompt_candidates, text_digest
from management.services.evaluation.evolution_access import published_business_agent, require_business_agent_edit
from management.services.evaluation.replay_cases import approved_example_input, get_development_case


def _normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def example_source_keys(task):
    keys = {"file:" + file["sha256"] for file in task["attachments"]}
    if not keys:
        keys.add("query:" + text_digest(_normalized(task["query"])))
    if task.get("source_group"):
        keys.add("group:" + text_digest(_normalized(task["source_group"])))
    return keys


def select_examples(examples, target_behavior):
    target = _normalized(target_behavior)
    ranked = sorted(examples, key=lambda ex: (_normalized(ex["behavior"]) != target, ex["case_id"]))
    # At most 20 approved examples and three slots. A greedy first choice may
    # consume the only source available for another behavior.
    for size in range(min(3, len(ranked)), 0, -1):
        options = []
        for group in combinations(ranked, size):
            behaviors = {_normalized(ex["behavior"]) for ex in group}
            sources = [key for ex in group for key in ex["source_keys"]]
            if target in behaviors and len(behaviors) == size and len(set(sources)) == len(sources):
                options.append(group)
        if options:
            return min(options, key=lambda group: sum(len(ex["input"]) + len(ex["output"]) for ex in group))
    raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Approve an example for the target behavior")


def _confirmed_trial(trials, case, variant, status):
    trial = trials.get((case["case_id"], variant))
    if (not trial or trial["status"] != status or not trial["receipt_id"]
            or (trial["result"] or {}).get("case_digest") != case["digest"]):
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "A matching graded development receipt is required")
    return trial


def generate_example_candidates(tenant, user, eid, request, baseline_prompt, agent, version, language):
    require_business_agent_edit(agent, tenant, user)
    trials = {(row["case_id"], row["variant"]): row for row in jobs.trials(tenant, eid)}
    if any(row["status"] in {"pending", "running", "cancelled"} for row in trials.values()):
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Select a finished development experiment")
    target = get_development_case(tenant, user, agent, version, request.target_case_id)
    failed = _confirmed_trial(trials, target, "base", "fail")
    examples = []
    for item in request.examples:
        case = get_development_case(tenant, user, agent, version, item.case_id)
        trial = _confirmed_trial(trials, case, item.variant, "pass")
        if item.output_excerpt not in (trial["result"].get("answer") or ""):
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Example output must appear in the passing answer")
        examples.append({"case_id": item.case_id, "receipt_id": trial["receipt_id"], "behavior": item.behavior,
                         "input": approved_example_input(tenant, agent, case["task"], item),
                         "output": item.output_excerpt, "source_keys": sorted(example_source_keys(case["task"]))})
    chosen = select_examples(examples, request.target_behavior)
    require_business_agent_edit(agent, tenant, user)
    source = published_business_agent(tenant, agent, version).get("prompt") or ""
    if source != baseline_prompt:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Baseline changed during example selection")
    heading = "参考示例（输入和输出）" if language == "zh" else "Examples (input and output)"
    sources = example_source_keys(target["task"])
    sources.update(key for ex in examples for key in ex["source_keys"])
    variants, artifacts = [], []
    for count in sorted({1, len(chosen)}):
        used = chosen[:count]
        body = [{"input": e["input"], "output": e["output"]} for e in used]
        suffix = "\n\n" + heading + "\n" + json.dumps(body, ensure_ascii=False, indent=2)
        provenance = {"method": "P2", "generator_revision": 1, "experiment_id": eid,
                      "target_receipt": failed["receipt_id"], "target_behavior": request.target_behavior,
                      "examples": used, "source_keys": sorted(sources)}
        artifacts.append((source + suffix, provenance))
        variants.append({"example_count": count, "added_utf8_bytes": len(suffix.encode()),
                         "example_case_ids": [e["case_id"] for e in used]})
    ids = store_prompt_candidates(tenant, agent, version, user, source, artifacts)
    for variant, candidate_id in zip(variants, ids, strict=True):
        variant["candidate_id"] = candidate_id
    variants.insert(0, {"example_count": 0, "candidate_id": None, "added_utf8_bytes": 0})
    return {"method": "P2", "experiment_id": eid, "base_version_no": version, "variants": variants}
