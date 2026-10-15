# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared knowledge-reference identity, parsing, and lock-key helpers.

A knowledge reference is one knowledge base attached to an agent: a local
Elasticsearch index (``index_names`` param) or a hosted AIDP knowledge base
(``kds_list`` param). References are persisted in ``ag_tool_instance_t.params``
and, for skill-driven retrieval tools, in ``ag_skill_instance_t.config_values``.
Deletion guards and the batch status API both key on the same identity so the
two features cannot drift apart.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
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
LOCAL_KNOWLEDGE_TOOL_NAMES = frozenset({"knowledge_base_search"})
AIDP_KNOWLEDGE_TOOL_NAMES = frozenset({"aidp_search"})

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

# Ids removed from the dialog may still be stored as a comma separated legacy
# string, so every parse accepts list, JSON-encoded list, and comma string.
MAX_STATUS_ITEMS = 100


@dataclass(frozen=True)
class KnowledgeResourceRef:
    """Stable identity of one knowledge resource, independent of display names."""

    provider: str
    resource_id: str

    def __post_init__(self) -> None:
        if self.provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported knowledge provider: {self.provider}")
        object.__setattr__(self, "resource_id", normalize_resource_id(self.resource_id))
        if not self.resource_id:
            raise ValueError("Knowledge resource id must not be empty")

    @property
    def range_param(self) -> str:
        return RANGE_PARAM_BY_PROVIDER[self.provider]

    def as_dict(self) -> dict:
        return {"provider": self.provider, "resource_id": self.resource_id}


def normalize_resource_id(value: Any) -> str:
    """Return the canonical string form of a knowledge resource id."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_knowledge_id_list(value: Any) -> List[str]:
    """Normalize persisted or submitted id collections into ordered unique ids.

    Accepts lists, JSON-encoded strings, and comma separated legacy strings.
    Unparseable values degrade to their plain string form so an exact-match
    check can still succeed instead of silently missing a reference.
    """
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            decoded = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            decoded = text
        if isinstance(decoded, list):
            value = decoded
        elif isinstance(decoded, str):
            parts = decoded.split(",")
            return list(dict.fromkeys(part.strip() for part in parts if part.strip()))
        else:
            value = [decoded]
    if isinstance(value, (list, tuple, set)):
        normalized = [normalize_resource_id(item) for item in value]
        return list(dict.fromkeys(item for item in normalized if item))
    if value is None:
        return []
    normalized = normalize_resource_id(value)
    return [normalized] if normalized else []


def dedupe_ids(values: Iterable[Any]) -> List[str]:
    """Return input-order unique ids, dropping empty entries."""
    return list(dict.fromkeys(item for item in (normalize_resource_id(v) for v in values) if item))


def iter_reference_params(params: Any) -> List[tuple[str, str, str]]:
    """Return ``(provider, param_name, resource_id)`` triples found in one params dict."""
    found: List[tuple[str, str, str]] = []
    if not isinstance(params, dict):
        return found
    for param_name, provider in PROVIDER_BY_RANGE_PARAM.items():
        if param_name not in params:
            continue
        for resource_id in parse_knowledge_id_list(params.get(param_name)):
            found.append((provider, param_name, resource_id))
    return found


def resource_lock_key(ref: KnowledgeResourceRef, namespace: str = "") -> int:
    """Derive the stable advisory-lock key for one knowledge resource.

    The key contains no credentials or user identity, so every writer of the
    same physical resource computes the same key. ``namespace`` separates
    deployments (for example the AIDP server URL) while local indices are
    globally unique inside one deployment.
    """
    payload = f"nexent-kb-resource:{namespace}:{ref.provider}:{ref.resource_id}"
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], "big", signed=False)
    if value >= 2 ** 63:
        value -= 2 ** 64
    return value


def optional_resources_from_params(params: Any) -> List[KnowledgeResourceRef]:
    """Return deduplicated resource refs for any knowledge ids present in params."""
    refs: List[KnowledgeResourceRef] = []
    seen: set[tuple[str, str]] = set()
    for provider, _param_name, resource_id in iter_reference_params(params):
        key = (provider, resource_id)
        if key in seen:
            continue
        seen.add(key)
        refs.append(KnowledgeResourceRef(provider=provider, resource_id=resource_id))
    return refs
