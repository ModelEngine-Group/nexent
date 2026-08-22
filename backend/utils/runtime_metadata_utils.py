"""Validation and canonical serialization helpers for runtime metadata."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Dict, Mapping

from consts.exceptions import RuntimeMetadataValidationError


MAX_RUNTIME_METADATA_BYTES = 64 * 1024
MAX_RUNTIME_METADATA_DEPTH = 10
MAX_RUNTIME_METADATA_KEYS = 200
MAX_RUNTIME_METADATA_ARRAY_ITEMS = 1000
MAX_RUNTIME_METADATA_KEY_LENGTH = 256




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
            "INVALID_METADATA_TYPE",
            "Runtime metadata must be a JSON object",
        )

    key_count = 0
    array_item_count = 0

    def visit(node: Any, depth: int) -> None:
        nonlocal key_count, array_item_count

        if depth > MAX_RUNTIME_METADATA_DEPTH:
            raise RuntimeMetadataValidationError(
                "METADATA_TOO_DEEP",
                f"Runtime metadata depth exceeds {MAX_RUNTIME_METADATA_DEPTH}",
            )

        if isinstance(node, dict):
            for key, child in node.items():
                if not isinstance(key, str):
                    raise RuntimeMetadataValidationError(
                        "INVALID_METADATA_TYPE",
                        "Runtime metadata keys must be strings",
                    )
                if len(key) > MAX_RUNTIME_METADATA_KEY_LENGTH:
                    raise RuntimeMetadataValidationError(
                        "METADATA_TOO_MANY_ITEMS",
                        f"Runtime metadata key length exceeds {MAX_RUNTIME_METADATA_KEY_LENGTH}",
                    )
                key_count += 1
                if key_count > MAX_RUNTIME_METADATA_KEYS:
                    raise RuntimeMetadataValidationError(
                        "METADATA_TOO_MANY_ITEMS",
                        f"Runtime metadata contains more than {MAX_RUNTIME_METADATA_KEYS} keys",
                    )
                visit(child, depth + 1)
            return

        if isinstance(node, list):
            array_item_count += len(node)
            if array_item_count > MAX_RUNTIME_METADATA_ARRAY_ITEMS:
                raise RuntimeMetadataValidationError(
                    "METADATA_TOO_MANY_ITEMS",
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
            "INVALID_METADATA_TYPE",
            "Runtime metadata contains a non-JSON value",
        )

    visit(value, 1)

    try:
        size_bytes = runtime_metadata_size_bytes(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RuntimeMetadataValidationError(
            "INVALID_METADATA_TYPE",
            "Runtime metadata contains a non-JSON value",
        ) from exc

    if size_bytes > MAX_RUNTIME_METADATA_BYTES:
        raise RuntimeMetadataValidationError(
            "METADATA_TOO_LARGE",
            f"Runtime metadata exceeds {MAX_RUNTIME_METADATA_BYTES} bytes",
        )

    return value

