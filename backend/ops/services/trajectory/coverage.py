# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Describe independent chat, retained archive and whole-conversation sources."""


def conversation_coverage(
    service,
    meta,
    state,
    *,
    has_more_executions,
    messages_requested,
    has_more_messages,
):
    """Use the whole published manifest rather than the currently returned page."""
    history = service.coverage(meta)
    history_reasons = list(history["reasons"])
    window_reasons = [
        reason
        for reason in history_reasons
        if reason not in {"had_expired_history", "unarchived"}
    ]
    availability = service.conversation_availability(meta, state["publication"])
    if availability != "available":
        history_reasons.append(availability)
        if availability != "expired":
            window_reasons.append(availability)
    retained_count = 0
    for run in (meta or {}).get("runs", []):
        publication = run.get("publication_no")
        if publication is None:
            history_reasons.append("unarchived")
            window_reasons.append("unarchived")
            continue
        if publication > state["publication"]:
            continue
        status = service.archive.available(run)
        if status != "available":
            history_reasons.append(status)
        if status == "expired":
            if run.get("cleanup_reason") == "manual":
                window_reasons.append("had_manual_cleanup")
        else:
            retained_count += 1
            if status != "available":
                window_reasons.append(status)
    history_reasons = list(dict.fromkeys(history_reasons))
    window_reasons = list(dict.fromkeys(window_reasons))
    return {
        **history,
        "complete": not history_reasons,
        "reasons": history_reasons,
        "chat": {
            "complete": True if messages_requested else None,
            "reasons": [] if messages_requested else ["not_requested"],
            "scope": "current_messages",
            "message_id_upper": str(state["message_upper"]),
            "has_more": has_more_messages,
        },
        "retention_window": {
            "complete": not window_reasons,
            "reasons": window_reasons,
            "scope": "registered_retained_executions",
            "execution_count": retained_count,
            "publication_no": str(state["publication"]),
            "basis": "manifest",
        },
        "conversation": {
            "complete": not history_reasons,
            "reasons": history_reasons,
            "scope": "conversation",
            "has_more": has_more_executions,
        },
    }
