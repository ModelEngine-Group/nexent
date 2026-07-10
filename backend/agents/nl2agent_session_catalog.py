"""In-memory NL2AGENT session catalog handoff.

The NL2AGENT session endpoint pre-fetches resource catalogs before chat starts.
Later, agent config creation needs the same catalogs to inject them into the
pure SDK search tools. This module keeps that handoff local to the backend
process and avoids any SDK dependency on backend services.
"""

from copy import deepcopy
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple


_CATALOG_KEYS = (
    "tool_catalog",
    "skill_catalog",
    "registry_results",
    "community_results",
    "official_skills",
)

_CATALOG_CACHE: Dict[Tuple[str, int], Dict[str, List[Dict[str, Any]]]] = {}
_CATALOG_LOCK = Lock()


def _empty_catalogs() -> Dict[str, List[Dict[str, Any]]]:
    return {key: [] for key in _CATALOG_KEYS}


def set_nl2agent_session_catalogs(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
    catalogs: Dict[str, List[Dict[str, Any]]],
) -> None:
    """Store catalogs for the draft agent created by an NL2AGENT session."""
    if not tenant_id or not draft_agent_id:
        return

    payload = _empty_catalogs()
    for key in _CATALOG_KEYS:
        payload[key] = deepcopy(catalogs.get(key) or [])

    with _CATALOG_LOCK:
        _CATALOG_CACHE[(tenant_id, int(draft_agent_id))] = payload


def get_nl2agent_session_catalogs(
    tenant_id: Optional[str],
    draft_agent_id: Optional[int],
) -> Dict[str, List[Dict[str, Any]]]:
    """Return cached catalogs for a draft agent, or empty catalogs on miss."""
    if not tenant_id or not draft_agent_id:
        return _empty_catalogs()

    with _CATALOG_LOCK:
        catalogs = _CATALOG_CACHE.get((tenant_id, int(draft_agent_id)))

    if catalogs is None:
        return _empty_catalogs()
    return deepcopy(catalogs)


def clear_nl2agent_session_catalogs() -> None:
    """Clear all cached catalogs. Intended for tests."""
    with _CATALOG_LOCK:
        _CATALOG_CACHE.clear()
