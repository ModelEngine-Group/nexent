# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Discover original execution references within the loaded checkpoint's authority."""

import json

from infrastructure.rdb.conversation_state import list_checkpoint_execution_results
from nexent.core.agents.context.native_history import decode_history_event


def _source(row):
    if row["record_type"] == "tool_result":
        call = decode_history_event({**row, "record_type": "tool", "content": row.get("call_content")})
        if call is None:
            return None
        names, arguments = [call["name"]], call["arguments"]
    else:
        # Call coverage lives inside legacy result bodies; discovery must not fetch or infer it.
        names, arguments = [], ""
    return {"output_ref": f"message:{row['message_id']}/unit-index:{row['unit_index']}",
            "message_index": row["message_index"], "record_type": row["record_type"],
            "tool_names": names, "arguments_preview": arguments[:512],
            "arguments_truncated": len(arguments) > 512}


def discover_summary_sources(user_id, tenant_id, conversation_id, checkpoint_unit_id,
                             covered_message_id, offset, max_chars):
    """Return navigation metadata, never summary-derived values or original result bodies."""
    rows, more = list_checkpoint_execution_results(
        user_id, tenant_id, conversation_id, checkpoint_unit_id, covered_message_id, offset,
    )
    entries, cursor = [], offset
    for row in rows:
        entry = _source(row)
        if entry is None:
            cursor += 1
            continue
        proposed = {"results": [*entries, entry], "next_offset": cursor + 1, "eof": False}
        if len(json.dumps(proposed, ensure_ascii=False)) > max_chars:
            if not entries:
                raise ValueError("Increase max_chars to fit an execution source reference")
            break
        entries.append(entry)
        cursor += 1
    return {"results": entries, "next_offset": cursor, "eof": cursor == offset + len(rows) and not more}
