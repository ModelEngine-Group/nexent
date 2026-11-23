# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Reduce private paired measurements to the fields permitted to leave the evaluator."""

from collections import Counter
from math import ceil


def new_skill_use(evidence):
    trial = evidence.get("new_skill_trial")
    if not trial or trial["arm"] != "result":
        return None
    selection = evidence.get("selection") or {}
    if "expected" not in selection or "reads" not in selection:
        return None
    name = trial["name"]
    if selection.get("outcome") in {"missed", "wrong"}:
        return "incorrect"
    if name in selection["expected"]:
        return "used" if selection["reads"].get(name) else "alternative"
    return "skipped" if not selection["reads"].get(name) else "incorrect"


def arm_measurement(status, result, *, task=None, require_selection=False):
    task = task or {}
    file_grade = result.get("file_state") or {}
    tool_grade = result.get("tool_use") or {}
    forbidden = bool(file_grade.get("protected_writes")) or any(
        issue.get("reason") == "too_many" and issue.get("max_calls") == 0
        for issue in tool_grade.get("issues", [])
    )
    checks = [
        result.get("judgment") or {},
        *[result[k] or {} for k in ("tool_use", "file_state") if k in result],
    ]
    selection = result.get("selection") or {}
    control_without_proposal = (result.get("new_skill_trial") or {}).get("arm") == "base"
    if (
        status not in {"pass", "fail"}
        or any(c.get("status") not in {"pass", "fail"} for c in checks)
        or require_selection
        and selection.get("outcome") not in {"missed", "wrong", "hit", "correct_skip"}
    ):
        status = "invalid"
    elif any(c["status"] == "fail" for c in checks) or not control_without_proposal and selection.get("outcome") in {
        "missed",
        "wrong",
    }:
        status = "fail"
    return {
        **({"new_skill_use": new_skill_use(result)} if result.get("new_skill_trial") else {}),
        "status": status,
        "forbidden": forbidden,
        "unverified_protection": (
            bool((task.get("file_state") or {}).get("protected"))
            and file_grade.get("status") not in {"pass", "fail"}
            or any(rule.get("max_calls") == 0 for rule in (task.get("tool_use") or {}).get("rules", []))
            and tool_grade.get("status") not in {"pass", "fail"}
        ),
        "ms": result.get("execution_ms"),
        "tokens": result.get("reported_step_input_tokens"),
        "events_digest": result.get("events_digest"),
        "guide_read": (result.get("skill") or {}).get("guide_reads", 0) > 0,
    }


def comparison_summary(policy, pairs, *, require_guide=False, require_new_skill=False):
    # Private family names and individual task outcomes never appear in the returned object.
    valid, families, timings, token_pairs = [], Counter(), [], []
    failed, missing = [], []
    forbidden = sum(candidate["forbidden"] for _, _, candidate in pairs)
    if forbidden:
        failed.append("forbidden_action")
    if any(candidate.get("unverified_protection") for _, _, candidate in pairs):
        missing.append("unverified_protection")
    for family, base, candidate in pairs:
        if base["status"] not in {"pass", "fail"} or candidate["status"] not in {"pass", "fail"}:
            continue
        if (
            require_guide
            and base["status"] == "fail"
            and candidate["status"] == "pass"
            and not (base["guide_read"] and candidate["guide_read"])
        ):
            continue
        valid.append((base["status"], candidate["status"]))
        families[family] += 1
        if type(candidate["ms"]) is int and candidate["ms"] >= 0:
            timings.append(candidate["ms"])
        if base["status"] == candidate["status"] == "pass":
            token_pairs.append((base["tokens"], candidate["tokens"]))
    if require_new_skill:
        uses = {new.get("new_skill_use") for _, old, new in pairs
                if old["status"] in {"pass", "fail"} and new["status"] in {"pass", "fail"}}
        if not {"used", "skipped"} <= uses:
            missing.append("new_skill_scope_coverage")
        if "incorrect" in uses:
            failed.append("skill_selection")
        if any(old["status"] == "fail" and new["status"] == "pass" and new.get("new_skill_use") != "used"
               for _, old, new in pairs):
            missing.append("new_skill_gain_without_read")
    total, count = len(pairs), len(valid)
    improved, regressed = valid.count(("fail", "pass")), valid.count(("pass", "fail"))
    if count < policy.minimum_valid_pairs or count * 100 < total * policy.minimum_valid_percent:
        missing.append("insufficient_valid_pairs")
    if any(families[name] < minimum for name, minimum in policy.family_minimums.items()):
        missing.append("insufficient_family_coverage")
    if regressed > policy.max_regressed_tasks:
        failed.append("regression_limit")
    quality = (improved - regressed) * 100 / count if count else None
    if not missing and (improved - regressed) * 100 < policy.minimum_quality_gain_pp * count:
        failed.append("quality_target")
    p95 = sorted(timings)[ceil(0.95 * count) - 1] if count and len(timings) == count else None
    if policy.max_candidate_p95_ms is not None:
        if p95 is None:
            missing.append("missing_latency")
        elif not missing and p95 > policy.max_candidate_p95_ms:
            failed.append("latency_limit")
    saving = None
    if policy.minimum_input_saving_percent is not None:
        if (
            len(token_pairs) < policy.minimum_valid_pairs
            or any(type(n) is not int or n < 0 for row in token_pairs for n in row)
            or not sum(a for a, b in token_pairs)
        ):
            missing.append("insufficient_token_pairs")
        else:
            old, new = map(sum, zip(*token_pairs))
            saving = (old - new) * 100 / old
            if not missing and (old - new) * 100 < old * policy.minimum_input_saving_percent:
                failed.append("usage_target")
    return {
        "decision": "failed" if failed else "insufficient" if missing else "passed",
        "total_pairs": total,
        "valid_pairs": count,
        "improved": improved,
        "regressed": regressed,
        "base_passed": sum(a == "pass" for a, b in valid),
        "candidate_passed": sum(b == "pass" for a, b in valid),
        "quality_gain_pp": quality,
        "candidate_p95_ms": p95,
        "input_saving_percent": saving,
        "forbidden_tasks": forbidden,
        "failures": failed,
        "missing": missing,
    }
