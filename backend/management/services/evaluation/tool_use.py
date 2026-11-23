# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Compare only the business-approved tool checks with a signed execution receipt."""

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
    return {"status": "fail" if issues else "pass", "checked": sorted(required), "sequence": sequence, "issues": issues}
