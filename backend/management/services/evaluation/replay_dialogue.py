# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execute the frozen user turns with the history produced by one trial arm."""

import json
from collections import Counter
from hashlib import sha256

from contracts.agentos import RunHistoryMessage
from contracts.errors.exceptions import RuntimeUpstreamError
from management.db.evaluation.replay_cases import task_digest
from nexent.core.agents.resources.replay_files import files_digest


def validate_turn(spec, receipt, attempt, expected_names):
    if not receipt or receipt.trial_id != attempt:
        return {"error": "missing_or_unsuccessful_runtime_receipt"}
    if receipt.outcome != "completed":
        return {"error": "unsuccessful_runtime", "runtime_outcome": receipt.outcome}
    skills = [receipt.skill] if receipt.skill else (receipt.skills or [])
    targets = {ref.package_candidate_id: ref for ref in spec.resource.skill_refs if ref.package_candidate_id}
    if (len(skills) != len(targets) or {s.candidate_id for s in skills} != set(targets)
            or receipt.skill and receipt.skills):
        return {"error": "skill_observation_mismatch"}
    for skill in skills:
        target = targets[skill.candidate_id]
        omitted = spec.omit_root_skill_candidate_id == skill.candidate_id
        if (skill.instance_id != target.instance_id or skill.variant != ("no_skill" if omitted else target.package_variant)
                or skill.mounted_revision != (None if omitted else target.revision) or omitted and (skill.listed or skill.guide_reads)):
            return {"error": "skill_observation_mismatch"}
    if spec.observe_root_skill_choices and expected_names is not None:
        reads = receipt.root_guide_reads
        listed = {item["content"]["name"] for item in (spec.resource.evaluation_options.context_items or [])
                  if item.get("type") == "skill"}
        if reads is None or not listed.issuperset(set(reads).union(expected_names)):
            return {"error": "invalid_skill_choice_receipt"}
    if spec.tool_set_check:
        catalog = receipt.tool_catalog
        if catalog is None or not catalog.model_inputs:
            return {"error": "missing_tool_catalog"}
        removed = set(spec.tool_set_check.removed)
        actual = set(catalog.executable)
        if spec.tool_set_check.arm == "result":
            if removed.intersection(actual.union(catalog.schema_tools, catalog.prompt_tools,
                                                 catalog.instruction_mentions, catalog.native_definitions)):
                return {"error": "excluded_tool_remains_visible_or_callable", "tool_catalog": catalog.model_dump()}
        elif not removed.issubset(actual.intersection(catalog.schema_tools, catalog.prompt_tools)):
            return {"error": "tool_missing_from_baseline", "tool_catalog": catalog.model_dump()}
    return None


async def run_turns(client, spec, task, load_input, job, user, tenant):
    history, observations, records = [], [], []
    followups = task.get("followups", [])
    watch = task.get("tool_use")
    files = task["file_state"]["initial"] if task.get("file_state") else None
    for index in range(len(followups) + 1):
        current = await load_input(index)
        root = job["receipt_id"]
        attempt = root if index == len(followups) else sha256(f"{root}/{index}".encode()).hexdigest()[:32]
        current = current.model_copy(update={"history": list(history)})
        updates = {"input": current, "conversation_id": -job["trial_id"], "replay_trial_id": attempt}
        if watch:
            updates["watch_tool_arguments"] = {r["name"]: sorted(r["arguments"]) for r in watch["rules"]}
        if files is not None:
            updates["replay_files"] = files
        try:
            observed = await client.run_prepared_evaluation(spec.model_copy(update=updates), user, tenant)
        except RuntimeUpstreamError as exc:
            if files is None or exc.status_code != 422:
                raise
            try:
                body = json.loads(exc.content)
            except (ValueError, UnicodeError):
                body = {}
            detail = body.get("detail") if isinstance(body, dict) else None
            code = detail.get("code") if isinstance(detail, dict) else None
            if code not in ("AGENTOS_FILE_STATE_UNSUPPORTED_BINDINGS", "AGENTOS_FILE_STATE_UNREADABLE"):
                raise
            return [], records, {"error": code.lower(), "turn": index + 1}
        receipt = observed.replay_receipt
        error = validate_turn(spec, receipt, attempt, task.get("expected_skill_names"))
        if files is not None and not error:
            state = receipt.file_state
            if state is None or not state.complete or state.initial_digest != files_digest(files):
                error = {"error": "unverified_file_state"}
            else:
                files = state.files
        if followups and not error and not any(e.get("type") == "final_answer" for e in observed.events):
            error = {"error": "missing_final_answer_event"}
        if followups:
            records.append({"turn": index + 1, "query": current.query, "receipt_id": attempt,
                            "input_digest": task_digest(current.model_dump(mode="json")),
                            "events_digest": task_digest(observed.events),
                            "answer": None if error else observed.answer, "outcome": error["error"] if error else receipt.outcome,
                            "attachments": [ref.name for ref in current.attachment_refs]})
            if not error:
                turn_skills, turn_reads = skill_evidence([receipt])
                records[-1].update(skills=turn_skills, guide_reads=turn_reads)
                if receipt.tool_observation:
                    records[-1]["tool_observation"] = receipt.tool_observation.model_dump()
                if files is not None:
                    records[-1]["file_state_digest"] = files_digest(files)
        if error:
            return [], records, error
        observations.append(observed)
        history.extend([RunHistoryMessage(role="user", content=current.query, attachment_refs=current.attachment_refs),
                        RunHistoryMessage(role="assistant", content=observed.answer)])
    return observations, records, None


def judge_file_state(rule, receipts):
    states = [r.file_state for r in receipts]
    actual, expected = states[-1].files, rule["expected"]
    written = {name.casefold() for state in states for name in state.writes}
    writers = {}
    for state in states:
        for tool, names in state.writes_by_tool.items():
            writers.setdefault(tool, set()).update(names)
    protected = [n for n in rule["protected"] if n.casefold() in written]
    missing = sorted(expected.keys() - actual.keys())
    extra = sorted(actual.keys() - expected.keys())
    wrong = sorted(n for n in expected.keys() & actual.keys() if actual[n] != expected[n])
    return {"adapter": rule["adapter"], "status": "fail" if any((missing, extra, wrong, protected)) else "pass",
            "initial_digest": states[0].initial_digest, "final_digest": files_digest(actual),
            "expected_digest": files_digest(expected), "missing": missing, "extra": extra,
            "wrong_content": wrong, "protected_writes": protected,
            "writes_by_tool": {tool: sorted(names) for tool, names in writers.items()}}


def skill_evidence(receipts):
    reads = Counter()
    skills = {}
    for receipt in receipts:
        reads.update(receipt.root_guide_reads or {})
        for skill in ([receipt.skill] if receipt.skill else receipt.skills or []):
            row = skills.setdefault(skill.candidate_id, {**skill.model_dump(), "guide_reads": 0})
            row["guide_reads"] += skill.guide_reads
            row["listed"] = row["listed"] and skill.listed
    return list(skills.values()), dict(reads) if all(r.root_guide_reads is not None for r in receipts) else None
