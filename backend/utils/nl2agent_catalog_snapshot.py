"""Content addressing for immutable NL2AGENT catalog snapshots."""

import hashlib
import json
from typing import Any, Dict


def catalog_snapshot_id(catalogs: Dict[str, Any]) -> str:
    """Return a deterministic identifier for one canonical JSON payload."""
    canonical = json.dumps(
        catalogs,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def mcp_recommendation_id(source: str, item: Dict[str, Any]) -> str:
    """Build the stable recommendation identifier used by search and install."""
    if source == "registry":
        server = item.get("server") if isinstance(item.get("server"), dict) else item
        identity = server.get("name") or server.get("id")
    else:
        identity = (
            item.get("communityId")
            or item.get("community_id")
            or item.get("name")
        )
    return f"{source}:{identity}"
