# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Project confirmed lifecycle snapshots into the existing public file response."""

import time
from datetime import datetime


def public_file_state(row):
    status = row.get("status") or "UPLOADING"
    deletion = row.get('deletion_request')
    if status != 'DELETED' and isinstance(deletion, dict) and deletion.get('scope') == 'full':
        return 'DELETE_REQUESTED'
    if status in {"UPLOADING", "UPLOADED"}:
        return "WAIT_FOR_PROCESSING"
    if status == "PROCESSING" and row.get("cleanse_status") == "queued":
        return "WAIT_FOR_PROCESSING"
    if status == "FORWARDING" and row.get("runtime_status") == "queued":
        return "WAIT_FOR_FORWARDING"
    if status == "FAILED":
        stage = str(row.get("error_stage") or row.get("stage") or "").upper()
        return "FORWARD_FAILED" if stage in {"FORWARD", "FORWARDING"} else "PROCESS_FAILED"
    return status


def merge_lifecycle_files(files_map, lifecycle_rows):
    hidden_paths = {
        path
        for row in lifecycle_rows
        if public_file_state(row) in {"DELETE_REQUESTED", "DELETED"}
        for path in (row.get("object_name"), row.get("local_source_path"))
        if path
    }
    for hidden_path in hidden_paths:
        files_map.pop(hidden_path, None)

    for row in sorted(lifecycle_rows, key=lambda row: str(row.get("update_time") or "")):
        if public_file_state(row) in {"DELETE_REQUESTED", "DELETED"}:
            for path in (row.get("object_name"), row.get("local_source_path")):
                if path:
                    files_map.pop(path, None)
            continue
        path_or_url = row.get("object_name")
        row_key = path_or_url or f"lifecycle:{row.get('file_id')}"
        existing = files_map.get(path_or_url) if path_or_url else None
        timestamp_value = row.get("uploaded_at") or row.get("create_time")
        try:
            timestamp = datetime.fromisoformat(
                str(timestamp_value)
            ).timestamp()
        except (TypeError, ValueError, OverflowError):
            timestamp = time.time()
        lifecycle_status = public_file_state(row)
        # ES retains the effective conflict-resolved display name for historical rows.
        lifecycle_filename = row.get("original_filename") or ""
        legacy_filename = (existing or {}).get("file") or ""
        display_filename = legacy_filename or lifecycle_filename
        file_data = existing or {
            "path_or_url": path_or_url,
            "file": display_filename,
            "file_size": row.get("file_size") or 0,
            "create_time": int(timestamp * 1000),
            "chunk_count": 0,
            "error_reason": None,
            "has_error_info": False,
        }
        file_data.update(
            {
                "path_or_url": path_or_url,
                "file": display_filename or file_data.get("file", ""),
                "file_size": row.get("file_size")
                if row.get("file_size") is not None
                else file_data.get("file_size", 0),
                "create_time": int(timestamp * 1000),
                "status": lifecycle_status,
                "latest_task_id": row.get("forward_task_id")
                or row.get("process_task_id")
                or "",
                "processed_chunk_num": row.get("processed_chunks"),
                "total_chunk_num": row.get("total_chunks"),
                "file_id": row.get("file_id"),
                "error_reason": row.get("error_message")
                or row.get("error_code"),
                "error_code": row.get("error_code"),
                "error_stage": row.get("error_stage") or row.get("stage"),
                "failed_at": row.get("failed_at"),
                "has_error_info": bool(
                    row.get("error_message") or row.get("error_code")
                ),
            }
        )
        files_map[row_key] = file_data
