# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Validation and canonical serialization helpers for runtime metadata."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Dict, Mapping

from contracts.errors.exceptions import RuntimeMetadataValidationError
from contracts.errors.codes import RuntimeMetadataValidationCode


from contracts.constants.constants import MAX_RUNTIME_METADATA_BYTES
from contracts.constants.constants import MAX_RUNTIME_METADATA_DEPTH
from contracts.constants.constants import MAX_RUNTIME_METADATA_KEYS
from contracts.constants.constants import MAX_RUNTIME_METADATA_ARRAY_ITEMS
from contracts.constants.constants import MAX_RUNTIME_METADATA_KEY_LENGTH


# ---------------------------------------------------------------------------
# Phase 1: northbound MCP header passthrough — reserved-field whitelist rules
# ---------------------------------------------------------------------------

# Max size of one MCP header value (4 KB as UTF-8 bytes).
MAX_MCP_HEADER_VALUE_BYTES = 4 * 1024

# Max cumulative size of all injected MCP header values across one run (16 KB).
MAX_MCP_HEADERS_TOTAL_BYTES = 16 * 1024

# Header name whitelist.  Lowercased on input so the comparison is
# case-insensitive and HTTP-correct.
ALLOWED_MCP_HEADER_KEYS = frozenset({
    "authorization",
    "cookie",
    "x-tenant-id",
    "x-user-id",
    "x-request-id",
    "x-trace-id",
})

# Hop-by-hop headers that MUST NEVER be injected through metadata.
# See RFC 7230 §6.1 and RFC 8620 §13.5.1.
FORBIDDEN_HOP_BY_HOP_KEYS = frozenset({
    "host",
    "content-length",
    "connection",
    "keep-alive",
    "transfer-encoding",
    "upgrade",
    "te",
    "trailer",
    "proxy-connection",
    "proxy-authorization",
    "proxy-authenticate",
})


def _is_passthrough_header_allowed(key: str) -> bool:
    """Return True iff ``key`` is a header name we will accept for passthrough.

    - ``key`` is lowercased before every comparison.
    - Hop-by-hop headers are rejected even when they would otherwise match
      a broader pattern (defense-in-depth).
    - Whitelist entries and any ``x-*`` custom header are accepted.
    """
    normalized = key.strip().lower()
    if not normalized:
        return False
    if normalized in FORBIDDEN_HOP_BY_HOP_KEYS:
        return False
    if normalized in ALLOWED_MCP_HEADER_KEYS:
        return True
    return normalized.startswith("x-")


def _validate_single_mcp_header_dict(headers: Any) -> int:
    """Validate one ``Dict[str, str]`` header block.

    Returns the cumulative UTF-8 byte count of all header values.  Raises
    :class:`RuntimeMetadataValidationError` on any structural failure.
    """
    if not isinstance(headers, dict):
        raise RuntimeMetadataValidationError(
            RuntimeMetadataValidationCode.MCP_HEADER_TYPE_INVALID,
            "Reserved _mcp_headers* fields must be objects of string -> string",
        )

    total_bytes = 0
    for raw_key, value in headers.items():
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise RuntimeMetadataValidationError(
                RuntimeMetadataValidationCode.MCP_HEADER_TYPE_INVALID,
                "Header keys must be non-empty strings",
            )
        if not isinstance(value, str):
            raise RuntimeMetadataValidationError(
                RuntimeMetadataValidationCode.MCP_HEADER_TYPE_INVALID,
                f"Header value for '{raw_key}' must be a string",
            )
        if not _is_passthrough_header_allowed(raw_key):
            raise RuntimeMetadataValidationError(
                RuntimeMetadataValidationCode.MCP_HEADER_KEY_FORBIDDEN,
                f"Header key '{raw_key}' is not whitelisted for MCP passthrough",
            )
        byte_len = len(value.encode("utf-8"))
        if byte_len > MAX_MCP_HEADER_VALUE_BYTES:
            raise RuntimeMetadataValidationError(
                RuntimeMetadataValidationCode.MCP_HEADER_VALUE_TOO_LARGE,
                f"Header value for '{raw_key}' exceeds {MAX_MCP_HEADER_VALUE_BYTES} bytes",
            )
        total_bytes += byte_len
    return total_bytes


def _validate_mcp_headers_reserved_fields(metadata: Dict[str, Any]) -> None:
    """Validate the ``_mcp_headers`` / ``_mcp_headers_by_server`` reserved fields.

    Raises :class:`RuntimeMetadataValidationError` for any structural, size,
    or whitelist failure.  When both reserved forms are present the
    ``_mcp_headers_by_server`` shape wins (``_mcp_headers`` is ignored, but
    its structural validity is still checked so the caller is not
    surprised by a half-valid payload).
    """
    total_bytes = 0
    seen = False

    if "_mcp_headers" in metadata and metadata["_mcp_headers"] is not None:
        seen = True
        total_bytes += _validate_single_mcp_header_dict(metadata["_mcp_headers"])

    if "_mcp_headers_by_server" in metadata and metadata["_mcp_headers_by_server"] is not None:
        if not isinstance(metadata["_mcp_headers_by_server"], dict):
            raise RuntimeMetadataValidationError(
                RuntimeMetadataValidationCode.MCP_HEADER_TYPE_INVALID,
                "_mcp_headers_by_server must be an object of server URL -> headers",
            )
        seen = True
        for url, block in metadata["_mcp_headers_by_server"].items():
            if not isinstance(url, str) or not url.strip():
                raise RuntimeMetadataValidationError(
                    RuntimeMetadataValidationCode.MCP_HEADER_TYPE_INVALID,
                    "_mcp_headers_by_server keys must be non-empty MCP server URLs",
                )
            total_bytes += _validate_single_mcp_header_dict(block)

    if seen and total_bytes > MAX_MCP_HEADERS_TOTAL_BYTES:
        raise RuntimeMetadataValidationError(
            RuntimeMetadataValidationCode.MCP_HEADER_VALUE_TOO_LARGE,
            f"Total size of injected MCP headers exceeds {MAX_MCP_HEADERS_TOTAL_BYTES} bytes",
        )


def canonical_runtime_metadata_json(metadata: Mapping[str, Any]) -> str:
    """Serialize runtime metadata deterministically for sizing and hashing."""

    return json.dumps(
        metadata,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def runtime_metadata_hash(metadata: Mapping[str, Any]) -> str:
    """Return the SHA-256 digest of canonical runtime metadata."""

    payload = canonical_runtime_metadata_json(metadata).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def runtime_metadata_size_bytes(metadata: Mapping[str, Any]) -> int:
    """Return the canonical UTF-8 size of runtime metadata."""

    return len(canonical_runtime_metadata_json(metadata).encode("utf-8"))


def validate_runtime_metadata(value: Any) -> Dict[str, Any]:
    """Validate and return a JSON-compatible runtime metadata object."""

    if not isinstance(value, dict):
        raise RuntimeMetadataValidationError(
            RuntimeMetadataValidationCode.INVALID_METADATA_TYPE,
            "Runtime metadata must be a JSON object",
        )

    key_count = 0
    array_item_count = 0

    def visit(node: Any, depth: int) -> None:
        nonlocal key_count, array_item_count

        if depth > MAX_RUNTIME_METADATA_DEPTH:
            raise RuntimeMetadataValidationError(
                RuntimeMetadataValidationCode.METADATA_TOO_DEEP,
                f"Runtime metadata depth exceeds {MAX_RUNTIME_METADATA_DEPTH}",
            )

        if isinstance(node, dict):
            for key, child in node.items():
                if not isinstance(key, str):
                    raise RuntimeMetadataValidationError(
                        RuntimeMetadataValidationCode.INVALID_METADATA_TYPE,
                        "Runtime metadata keys must be strings",
                    )
                if len(key) > MAX_RUNTIME_METADATA_KEY_LENGTH:
                    raise RuntimeMetadataValidationError(
                        RuntimeMetadataValidationCode.METADATA_TOO_MANY_ITEMS,
                        f"Runtime metadata key length exceeds {MAX_RUNTIME_METADATA_KEY_LENGTH}",
                    )
                key_count += 1
                if key_count > MAX_RUNTIME_METADATA_KEYS:
                    raise RuntimeMetadataValidationError(
                        RuntimeMetadataValidationCode.METADATA_TOO_MANY_ITEMS,
                        f"Runtime metadata contains more than {MAX_RUNTIME_METADATA_KEYS} keys",
                    )
                visit(child, depth + 1)
            return

        if isinstance(node, list):
            array_item_count += len(node)
            if array_item_count > MAX_RUNTIME_METADATA_ARRAY_ITEMS:
                raise RuntimeMetadataValidationError(
                    RuntimeMetadataValidationCode.METADATA_TOO_MANY_ITEMS,
                    "Runtime metadata contains too many array items",
                )
            for child in node:
                visit(child, depth + 1)
            return

        if node is None or isinstance(node, (str, bool, int)):
            return
        if isinstance(node, float) and math.isfinite(node):
            return

        raise RuntimeMetadataValidationError(
            RuntimeMetadataValidationCode.INVALID_METADATA_TYPE,
            "Runtime metadata contains a non-JSON value",
        )

    visit(value, 1)

    try:
        size_bytes = runtime_metadata_size_bytes(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RuntimeMetadataValidationError(
            RuntimeMetadataValidationCode.INVALID_METADATA_TYPE,
            "Runtime metadata contains a non-JSON value",
        ) from exc

    if size_bytes > MAX_RUNTIME_METADATA_BYTES:
        raise RuntimeMetadataValidationError(
            RuntimeMetadataValidationCode.METADATA_TOO_LARGE,
            f"Runtime metadata exceeds {MAX_RUNTIME_METADATA_BYTES} bytes",
        )

    # Phase 1: northbound MCP header passthrough reserved-field validation.
    # Runs AFTER the generic structural checks so callers get a single,
    # layered stack of errors rather than two competing reasons.
    _validate_mcp_headers_reserved_fields(value)

    return value
