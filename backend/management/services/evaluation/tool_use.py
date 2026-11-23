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
    mcp_evidence = []
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
            expected_remote_error = False
            expected_reply = rule.get("expected_mcp_reply")
            if expected_reply:
                if call.mcp_fixture_unready:
                    return {"status": "missing_evidence", "reason": "unverified_mcp_fixture", "call": index}
                reply = call.mcp_reply
                if reply is None or reply.kind != expected_reply["kind"] or reply.content is None:
                    return {"status": "missing_evidence", "reason": "unverified_mcp_reply", "call": index}
                fixture = expected_reply.get("fixture")
                if fixture and (reply.before != argument_digest(fixture["initial"]) or reply.after is None):
                    return {"status": "missing_evidence", "reason": "unverified_mcp_fixture", "call": index}
                state_match = reply.after == argument_digest(fixture["final"]) if fixture else None
                inputs_match = reply.exact_fields and reply.inputs == argument_digest(rule["arguments"])
                error_expected = expected_reply.get("error", False)
                content_match = reply.error == error_expected and reply.content == argument_digest(expected_reply["value"])
                expected_remote_error = reply.error and error_expected and content_match
                mcp_evidence.append({**reply.model_dump(), "tool": name, "call": index,
                                     "input_matches": inputs_match, "reply_matches": content_match, "state_matches": state_match})
                if not inputs_match:
                    issues.append({"tool": name, "reason": "wrong_mcp_inputs", "call": index})
                if state_match is False:
                    issues.append({"tool": name, "reason": "wrong_mcp_state", "call": index})
                if not content_match:
                    issues.append({"tool": name, "reason": "mcp_remote_error" if reply.error and not error_expected else "wrong_mcp_reply",
                                   "call": index})
            expected_stdout = rule.get("expected_script_stdout")
            expected_files = rule.get("expected_script_files")
            if expected_stdout is not None or expected_files is not None:
                process = call.skill_process
                if process is None:
                    return {"status": "missing_evidence", "reason": "unverified_skill_process", "call": index}
                args = rule["arguments"]
                expected_input = (argument_digest(args["skill_name"]), argument_digest(args["script_path"]),
                                  argument_digest(shlex.split(args.get("params", ""))))
                if expected_files is not None and process.files is None:
                    return {"status": "missing_evidence", "reason": "unverified_script_files", "call": index}
                expected_changes = {sha256(name.encode()).hexdigest(): sha256(content.encode()).hexdigest()
                                    for name, content in (expected_files or {}).items()}
                files_match = process.files.changes == expected_changes if process.files else None
                stdout_match = (process.stdout == sha256(expected_stdout.encode()).hexdigest()
                                if expected_stdout is not None else None)
                same_input = (process.skill, process.path, process.argv) == expected_input
                script_evidence.append({**process.model_dump(), "call": index, "input_matches": same_input,
                                        "stdout_matches": stdout_match, "files_match": files_match})
                if not same_input or process.exit_code != 0 or stdout_match is False or expected_files is not None and not files_match:
                    issues.append({"tool": name, "reason": "wrong_script_result", "call": index})
            if call.requested_arguments is not None:
                for key, expected in rule["arguments"].items():
                    raw = call.requested_arguments.get(key)
                    effective = call.arguments.get(key)
                    argument_evidence.append({"tool": name, "field": key, "call": index, "requested": raw,
                                              "effective": effective, "expected": argument_digest(expected)})
            if call.outcome == "raised" and not expected_remote_error:
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
            **({"mcp_evidence": mcp_evidence} if mcp_evidence else {}),
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


def observed_script(result, build, arm):
    """Return only the input fingerprint and verdict for one matching sandbox process."""
    processes = (result.get("tool_use") or {}).get("script_evidence", [])
    if len(processes) != 1:
        return None
    process = processes[0]
    if (not process["input_matches"] or process["script"] != build[arm] or process["image"] != build["image"]
            or process["skill"] != argument_digest(build["name"]) or process["path"] != argument_digest(build["path"])):
        return None
    if process.get("files_match") is None or not process.get("files"):
        return None
    return {"argv": process["argv"], "initial": process["files"]["initial"],
            "passed": process["exit_code"] == 0 and process["stdout_matches"] is not False and process["files_match"]}


def script_effect(base, result):
    if (base is None or result is None or base["argv"] != result["argv"] or base["initial"] != result["initial"]
            or not result["passed"]):
        return None
    return "protected" if base["passed"] else "corrected"
