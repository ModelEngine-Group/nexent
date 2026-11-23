# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Decide whether a development candidate can be submitted for independent confirmation."""


def _verified(row, case_digest, arm_digest, rubric):
    result = row.get("result") or {}
    judgments = [(result.get(k) or {}).get("status") for k in ("judgment", "tool_use", "file_state")
                 if k == "judgment" or k in result]
    return (row.get("receipt_id") is not None and row.get("status") in {"pass", "fail"}
            and case_digest and result.get("case_digest") == case_digest
            and arm_digest and result.get("snapshot_digest") == arm_digest
            and rubric.get("version_no") is not None and result.get("evaluator_version") == rubric["version_no"]
            and rubric.get("evaluator_id") is not None and result.get("evaluator_id") == rubric["evaluator_id"]
            and all(j in {"pass", "fail"} for j in judgments)
            and row["status"] == ("fail" if "fail" in judgments else "pass"))


def screen_development(plan, pairs, *, cancelled):
    request = plan["request"]
    criteria = request["screening"]
    targets = set(criteria["target_case_ids"])
    regression = plan["regression_cases"]
    gaps, failures = {}, {}
    fixed = base_tokens = candidate_tokens = 0

    for key, digest in plan["cases"].items():
        cid = int(key)
        pair = pairs.get(cid, {})
        rubric = regression[key]["scoring"]["evaluator"] if key in regression else plan["evaluator"]
        verified = {arm for arm, arm_digest in plan["snapshots"].items()
                    if _verified(pair.get(arm, {}), digest, arm_digest, rubric)}
        if len(verified) != len(plan["snapshots"]):
            gaps.setdefault("unverified_trials", []).append(cid)
        if "result" not in verified:
            continue
        result = pair["result"]
        evidence = result["result"]
        if (evidence.get("selection") or {}).get("outcome") in {"wrong", "missed"}:
            failures.setdefault("skill_selection", []).append(cid)
        if (evidence.get("file_state") or {}).get("protected_writes") or any(
                issue.get("reason") == "too_many" and issue.get("max_calls") == 0
                for issue in (evidence.get("tool_use") or {}).get("issues", [])):
            failures.setdefault("forbidden_action", []).append(cid)
        if cid not in targets:
            if result["status"] != "pass":
                failures.setdefault("protection_failed", []).append(cid)
            continue
        if "base" not in verified:
            continue
        base = pair["base"]
        if base["status"] == "pass" and result["status"] == "fail":
            failures.setdefault("quality_regressed", []).append(cid)
        if base["status"] == "fail" and result["status"] == "pass":
            fixed += 1
            if request["candidate_type"] == "skill_step" and any(
                    not (pair[arm]["result"].get("skill") or {}).get("guide_reads") for arm in ("base", "result")):
                gaps.setdefault("skill_not_read", []).append(cid)
        if criteria["metric"] == "input_token_reduction_pct":
            if result["status"] != "pass":
                failures.setdefault("unfinished_token_target", []).append(cid)
            counts = [r["result"].get("reported_step_input_tokens") for r in (base, result)]
            if any(type(n) is not int or n < 0 for n in counts):
                gaps.setdefault("missing_tokens", []).append(cid)
            else:
                base_tokens += counts[0]
                candidate_tokens += counts[1]

    if not regression:
        gaps["no_fixed_regression"] = []
    if cancelled:
        gaps["cancelled"] = []
    gain = None
    if criteria["metric"] == "tasks_fixed":
        gain = fixed
    elif not gaps:
        if base_tokens:
            gain = (base_tokens - candidate_tokens) * 100 / base_tokens
        else:
            gaps["missing_tokens"] = sorted(targets)
    if not gaps and gain < criteria["minimum"]:
        failures["below_target"] = sorted(targets)
    status = "failed" if failures else "incomplete" if gaps else "eligible"
    return {"status": status, "criteria": criteria, "gain": gain if not gaps else None,
            "failures": failures, "missing": gaps}
