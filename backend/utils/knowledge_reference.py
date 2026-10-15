# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Managed knowledge parameter names, selection parsing, and lock keys."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, List


PROVIDER_LOCAL = "local"
PROVIDER_AIDP = "aidp"
SUPPORTED_PROVIDERS = (PROVIDER_LOCAL, PROVIDER_AIDP)

# The conversation scope service uses the same param names for its own ranges.
LOCAL_RANGE_PARAM = "index_names"
AIDP_RANGE_PARAM = "kds_list"

# Managed retrieval tools that persist knowledge references in tool params.
# The independent connector ``ind_aidp_search`` is deliberately excluded: its
# scope is owned by the external connector, not by the managed AIDP tenant.
KNOWLEDGE_RANGE_PARAM_BY_TOOL_NAME = {
    "knowledge_base_search": LOCAL_RANGE_PARAM,
    "aidp_search": AIDP_RANGE_PARAM,
}
RANGE_PARAM_BY_PROVIDER = {
    PROVIDER_LOCAL: LOCAL_RANGE_PARAM,
    PROVIDER_AIDP: AIDP_RANGE_PARAM,
}
PROVIDER_BY_RANGE_PARAM = {
    LOCAL_RANGE_PARAM: PROVIDER_LOCAL,
    AIDP_RANGE_PARAM: PROVIDER_AIDP,
}

REFERENCE_ORIGIN_TOOL = "tool"
REFERENCE_ORIGIN_SKILL = "skill"

MAX_STATUS_ITEMS = 100


def normalize_resource_id(value: Any) -> str:
    """Trim string IDs and stringify integer IDs; ignore other value types."""
    return str(value).strip() if type(value) in (str, int) else ""


def parse_knowledge_id_list(value: Any) -> List[str]:
    """Read lists or JSON arrays, as produced by the knowledge selectors."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return dedupe_ids(value)


def dedupe_ids(values: Iterable[Any]) -> List[str]:
    """Return input-order unique ids, dropping empty entries."""
    return list(dict.fromkeys(item for item in (normalize_resource_id(v) for v in values) if item))


def iter_reference_params(params: Any) -> List[tuple[str, str, str]]:
    """Return ``(provider, param_name, resource_id)`` triples found in one params dict."""
    found: List[tuple[str, str, str]] = []
    if not isinstance(params, dict):
        return found
    for param_name, provider in PROVIDER_BY_RANGE_PARAM.items():
        for resource_id in parse_knowledge_id_list(params.get(param_name)):
            found.append((provider, param_name, resource_id))
    return found


def resource_lock_key(provider: str, resource_id: str, namespace: str = "") -> int:
    """Derive the stable advisory-lock key for one knowledge resource.

    The key contains no credentials or user identity, so every writer of the
    same physical resource computes the same key. ``namespace`` separates
    deployments (for example the AIDP server URL) while local indices are
    globally unique inside one deployment.
    """
    payload = f"nexent-kb-resource:{namespace}:{provider}:{resource_id}"
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def optional_resources_from_params(params: Any) -> List[tuple[str, str]]:
    """Return unique (provider, resource_id) pairs from knowledge parameters."""
    return [(provider, resource_id) for provider, _, resource_id in iter_reference_params(params)]
