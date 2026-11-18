# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""File-scope rules for AIDP retrieval.

AIDP FusionSearch exposes ``metadata_condition`` with the hard-coded field
``original_file_name``. The tool therefore filters selected files by name for
the vector/full-text channels. The graph channel does not consume
``metadata_condition``, so a file-scoped run with graph retrieval enabled must
fail closed instead of issuing an unfiltered graph request.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Sequence, Tuple

FILE_NAME_METADATA_FIELD = "original_file_name"

FILE_SCOPE_UNAVAILABLE_MESSAGE = (
    "File-scoped retrieval is temporarily unavailable. No search was performed. "
    "Remove the selected files or restore all files, then try again."
)

FILE_SCOPE_EMPTY_MESSAGE = (
    "None of the selected files is inside the current knowledge-base range. "
    "No search was performed; adjust the selected files and try again."
)

FILE_SCOPE_GRAPH_UNSUPPORTED_MESSAGE = (
    "File-scoped retrieval is not available with the current retrieval method. "
    "No search was performed. Disable graph retrieval or restore all files, then try again."
)

FILE_SCOPE_VIOLATION_MESSAGE = (
    "The search returned a result outside the selected files. The result was "
    "discarded and no answer was produced from it; please try again."
)


class AidpFileScopeUnavailableError(RuntimeError):
    """Raised when a selected scope cannot be represented as a safe request filter."""


def _file_entry(item: Any) -> Tuple[str, str, str] | None:
    if not isinstance(item, dict):
        return None
    kds_id = str(item.get("kds_id") or "").strip()
    file_uuid = str(item.get("file_uuid") or "").strip()
    file_name = str(item.get("file_name") or "").strip()
    if not kds_id or not file_uuid:
        return None
    return kds_id, file_uuid, file_name


def normalize_file_scope(value: Any) -> Dict[str, Any]:
    """Return a validated ``{mode, files}`` scope or raise ``ValueError``.

    ``selected`` with an empty file list is valid on purpose: the backend can
    reduce a selection to zero readable files, and the tool must then fail
    closed instead of widening to all files.
    """
    if value is None or value == "":
        return {"mode": "all", "files": []}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"file_scope must be valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("file_scope must be an object")

    mode = value.get("mode", "all")
    if mode not in ("all", "selected"):
        raise ValueError("file_scope.mode must be 'all' or 'selected'")

    raw_files = value.get("files", [])
    if raw_files is None:
        raw_files = []
    if not isinstance(raw_files, list):
        raise ValueError("file_scope.files must be a list")
    if mode == "all" and raw_files:
        raise ValueError("file_scope mode 'all' does not accept files")

    files: List[Dict[str, str]] = []
    seen: set[Tuple[str, str]] = set()
    for item in raw_files:
        entry = _file_entry(item)
        if entry is None:
            raise ValueError("file_scope.files entries require kds_id and file_uuid")
        key = (entry[0], entry[1])
        if key in seen:
            continue
        seen.add(key)
        file_entry = {"kds_id": entry[0], "file_uuid": entry[1]}
        if entry[2]:
            file_entry["file_name"] = entry[2]
        files.append(file_entry)
    return {"mode": mode, "files": files}


def active_file_names(file_scope: Dict[str, Any], kds_list: Sequence[str]) -> List[str]:
    """Return unique selected file names whose KB is inside the search range."""
    if not isinstance(file_scope, dict) or file_scope.get("mode") != "selected":
        return []
    allowed_kds = {str(kds_id) for kds_id in kds_list if str(kds_id)}
    names: List[str] = []
    for item in file_scope.get("files") or []:
        entry = _file_entry(item)
        if entry is None or entry[0] not in allowed_kds or not entry[2]:
            continue
        if entry[2] not in names:
            names.append(entry[2])
    return names


def build_file_filter_payload(
    file_scope: Dict[str, Any], kds_list: Sequence[str]
) -> Dict[str, Any]:
    """Build the FusionSearch ``metadata_condition`` for the selected files.

    AIDP only supports ``original_file_name`` among the fields that can
    identify a file, and it applies one condition set to every selected KB.
    Same-name files across KBs therefore share the condition, which is the
    accepted product trade-off for this request.
    """
    names = active_file_names(file_scope, kds_list)
    if not names:
        raise AidpFileScopeUnavailableError("selected files have no usable file names")
    return {
        "metadata_condition": {
            "logical_operator": "or",
            "conditions": [
                {
                    "name": FILE_NAME_METADATA_FIELD,
                    "comparison_operator": "=",
                    "value": name,
                }
                for name in names
            ],
        }
    }


def verify_file_scope_records(
    records: Iterable[Dict[str, Any]],
    file_scope: Dict[str, Any],
    kds_list: Sequence[str],
) -> Tuple[List[Dict[str, Any]], int]:
    """Perform the defensive post-response check for a file-scoped search.

    Returns the accepted records and the number of rejected records. A record
    whose returned name is outside the selected names is a contract violation;
    the caller must fail closed and not use any record.
    """
    allowed = set(active_file_names(file_scope, kds_list))
    accepted: List[Dict[str, Any]] = []
    rejected = 0
    for record in records:
        metadata = record.get("metadata") if isinstance(record, dict) else None
        metadata = metadata if isinstance(metadata, dict) else {}
        returned_name = str(
            metadata.get(FILE_NAME_METADATA_FIELD)
            or metadata.get("file_name")
            or (record.get("title") if isinstance(record, dict) else "")
            or ""
        ).strip()
        if returned_name and returned_name not in allowed:
            rejected += 1
            continue
        accepted.append(record)
    return accepted, rejected
