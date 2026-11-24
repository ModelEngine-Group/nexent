# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Recover the accepted root answer from a recorded evaluation stream."""


def has_completed_root_answer(events):
    return any(event.get("type") == "final_answer" and not event.get("invocation_id")
               and not event.get("depth") and event.get("answer_phase") in (None, "complete")
               for event in events)


def completed_root_answer(events):
    """None means no completion. Older producers emit unphased final-answer fragments."""
    attempts = {}
    last_attempt = {}
    legacy = []
    accepted = None
    for event in events:
        if event.get("invocation_id") or event.get("depth", 0):
            continue
        kind = event.get("type")
        step, attempt = event.get("step_id"), event.get("attempt_id")
        if kind == "model_attempt_control":
            if event.get("phase") == "begin":
                last_attempt[step] = attempt
            elif event.get("phase") == "rollback":
                attempts.pop((step, attempt), None)
                if last_attempt.get(step) == attempt:
                    last_attempt.pop(step, None)
            continue
        if kind not in {"model_output_thinking", "model_output_code", "final_answer"}:
            continue
        content = event.get("content")
        if not isinstance(content, str):
            continue
        phase = event.get("answer_phase")
        if kind == "final_answer" and phase is None:
            legacy.append(content)
            continue
        if attempt is not None:
            last_attempt[step] = attempt
        key = (step, attempt if attempt is not None else last_attempt.get(step))
        body, deltas = attempts.setdefault(key, ([], []))
        if kind != "final_answer":
            body.append(content)
        elif phase == "delta":
            deltas.append(content)
        elif phase == "complete":
            accepted = content or "".join(deltas)
            if not accepted and step is not None and event.get("reclassify_step") is True:
                accepted = "".join(body)
    if accepted is not None:
        return accepted.strip()
    return "".join(legacy).strip() if legacy else None
