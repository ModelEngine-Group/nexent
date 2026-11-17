# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-FILE-LIST-02: preserve public fields from durable observations."""

import pytest
from management.services.knowledge_base.file_projection import (
    merge_lifecycle_files,
    public_file_state,
)


@pytest.mark.parametrize("row,expected", [
    ({"status": "UPLOADING"}, "WAIT_FOR_PROCESSING"),
    ({"status": "UPLOADED"}, "WAIT_FOR_PROCESSING"),
    ({"status": "PROCESSING", "cleanse_status": "queued"}, "WAIT_FOR_PROCESSING"),
    ({"status": "PROCESSING", "cleanse_status": "running"}, "PROCESSING"),
    ({"status": "FORWARDING", "runtime_status": "queued"}, "WAIT_FOR_FORWARDING"),
    ({"status": "FORWARDING", "runtime_status": "running"}, "FORWARDING"),
    ({"status": "FAILED", "error_stage": "PROCESS"}, "PROCESS_FAILED"),
    ({"status": "FAILED", "error_stage": "FORWARD"}, "FORWARD_FAILED"),
    ({"status": "COMPLETED"}, "COMPLETED"),
])
def test_public_state_names_remain_stable(row, expected):
    assert public_file_state(row) == expected


def test_projection_preserves_name_and_archived_error_with_confirmed_progress():
    files = {"a.txt": {"file": "a_1.txt", "chunk_count": 8}}
    merge_lifecycle_files(files, [{
        "file_id": "f", "object_name": "a.txt", "original_filename": "a.txt",
        "status": "FAILED", "error_stage": "FORWARD", "error_code": "VECTOR_FAILED",
        "error_message": "original error", "processed_chunks": 3, "total_chunks": 8,
        "forward_task_id": "job", "uploaded_at": "2026-11-17T00:00:00Z", "file_size": 2,
    }])
    result = files["a.txt"]
    assert result["file"] == "a_1.txt" and result["chunk_count"] == 8
    assert (result["processed_chunk_num"], result["total_chunk_num"]) == (3, 8)
    assert result["status"] == "FORWARD_FAILED" and result["has_error_info"]
    assert result["error_reason"] == "original error" and result["latest_task_id"] == "job"


def test_tombstone_hides_both_canonical_and_local_aliases():
    files = {"object": {"file": "a.txt"}, "/local/a.txt": {"file": "a.txt"}}
    merge_lifecycle_files(files, [{"status": "DELETED", "object_name": "object", "local_source_path": "/local/a.txt"}])
    assert files == {}


def test_latest_active_row_wins_independently_of_file_id_page_order():
    files = {}
    rows = [{"file_id": name, "object_name": "a", "status": "COMPLETED", "original_filename": name,
             "update_time": date} for name, date in [("new", "2026-11-17"), ("old", "2026-11-16")]]
    merge_lifecycle_files(files, rows)
    assert files["a"]["file_id"] == "new"


@pytest.mark.parametrize("deletion_is_newer", [True, False])
def test_old_activity_cannot_resurrect_newer_tombstone_and_new_upload_can_replace_old_tombstone(deletion_is_newer):
    files = {"a": {"file": "a.txt"}}
    rows = [
        {"file_id": "deleted", "object_name": "a", "status": "DELETED",
         "update_time": "2026-11-17" if deletion_is_newer else "2026-11-16"},
        {"file_id": "active", "object_name": "a", "status": "COMPLETED",
         "update_time": "2026-11-16" if deletion_is_newer else "2026-11-17"},
    ]
    merge_lifecycle_files(files, rows)
    assert (files == {}) if deletion_is_newer else (files["a"]["file_id"] == "active")


def test_full_request_hides_waiting_publication_and_local_aliases_without_changing_public_fields():
    files = {'object': {'file': 'source.txt'}, '/local/source.txt': {'file': 'source.txt'}}
    row = {'status': 'UPLOADING', 'stage': 'SOURCE_UPLOAD', 'object_name': 'object',
           'local_source_path': '/local/source.txt', 'deletion_request': {'scope': 'full'}}
    assert public_file_state(row) == 'DELETE_REQUESTED'
    merge_lifecycle_files(files, [row])
    assert files == {}


def test_source_only_request_keeps_completed_file_visible_without_exposing_internal_intent():
    files = {}
    merge_lifecycle_files(files, [{'status': 'COMPLETED', 'object_name': 'object', 'original_filename': 'source.txt',
                                  'deletion_request': {'scope': 'source_only', 'user_id': 'editor-b'}}])
    assert files['object']['status'] == 'COMPLETED' and 'deletion_request' not in files['object']
