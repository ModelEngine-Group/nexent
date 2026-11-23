# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Compare only the business-approved tool checks with a signed execution receipt."""

import shlex
from hashlib import sha256

from nexent.core.agents.resources.replay_tools import argument_digest


def judge_tool_use(expectation, observation, *, absent=frozenset()):
    return judge_dialogue_tools(expectation, [observation], absent=absent)


def judge_dialogue_tools(expectation, observations, *, absent=frozenset()):
    required = {rule["name"] for rule in expectation["rules"]}
    registered = required.difference(absent)
    calls = []
    offset = 0
    for observation in observations:
        if (observation is None or not observation.complete or set(observation.registered) != registered
            or any(call.name not in registered or call.outcome == "pending" or call.end is None or call.end <= call.start
                   for call in observation.calls)):
            return {"status": "missing_evidence", "reason": "incomplete_tool_observation"}
        for call in observation.calls:
            calls.append(call.model_copy(update={"start": call.start + offset, "end": call.end + offset}) if offset else call)
        offset += max((call.end for call in observation.calls), default=0)
    issues = []
    argument_evidence = []
    script_evidence = []
    sequence = [call.name for call in calls]
    for rule in expectation["rules"]:
        name = rule["name"]
        count = sequence.count(name)
        if count < rule["min_calls"]:
            issues.append({"tool": name, "reason": "too_few", "count": count})
        if rule["max_calls"] is not None and count > rule["max_calls"]:
            issues.append({"tool": name, "reason": "too_many", "count": count, "max_calls": rule["max_calls"]})
        for index, call in enumerate(calls, 1):
            if call.name != name:
                continue
            expected_stdout = rule.get("expected_script_stdout")
            if expected_stdout is not None:
                process = call.skill_process
                if process is None:
                    return {"status": "missing_evidence", "reason": "unverified_skill_process", "call": index}
                args = rule["arguments"]
                expected_input = (argument_digest(args["skill_name"]), argument_digest(args["script_path"]),
                                  argument_digest(shlex.split(args.get("params", ""))))
                expected_output = sha256(expected_stdout.encode("utf-8")).hexdigest()
                same_input = (process.skill, process.path, process.argv) == expected_input
                script_evidence.append({**process.model_dump(), "call": index, "input_matches": same_input,
                                        "stdout_matches": process.stdout == expected_output})
                if not same_input or process.exit_code != 0 or process.stdout != expected_output:
                    issues.append({"tool": name, "reason": "wrong_script_result", "call": index})
            if call.requested_arguments is not None:
                for key, expected in rule["arguments"].items():
                    raw = call.requested_arguments.get(key)
                    effective = call.arguments.get(key)
                    argument_evidence.append({"tool": name, "field": key, "call": index, "requested": raw,
                                              "effective": effective, "expected": argument_digest(expected)})
            if call.outcome == "raised":
                issues.append({"tool": name, "reason": "raised", "call": index})
            wrong = [key for key, value in rule["arguments"].items() if call.arguments.get(key) != argument_digest(value)]
            if wrong:
                issues.append({"tool": name, "reason": "wrong_arguments", "call": index, "fields": wrong})
    order = expectation.get("order")
    if order:
        ordered_calls = [call for call in calls if call.name in order]
        if ([call.name for call in ordered_calls] != order
                or any(a.end >= b.start for a, b in zip(ordered_calls, ordered_calls[1:]))):
            issues.append({"reason": "wrong_order"})
    return {"status": "fail" if issues else "pass", "checked": sorted(required), "sequence": sequence, "issues": issues,
            **({"script_evidence": script_evidence} if script_evidence else {}),
            **({"argument_evidence": argument_evidence} if argument_evidence else {})}

def observed_mapping(result, mapping):
    rows = [entry for entry in (result.get("tool_use") or {}).get("argument_evidence", ())
            if entry["tool"] == mapping["tool"] and entry["field"] == mapping["field"]]
    return rows[0] if len(rows) == 1 else None


def mapping_effect(old, new):
    if not old or not new or not old["requested"] or old["requested"] != new["requested"]:
        return None
    if old["effective"] != old["requested"] or old["expected"] != new["expected"] or new["effective"] != new["expected"]:
        return None
    return "protected" if old["effective"] == old["expected"] else "corrected"
