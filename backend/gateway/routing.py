# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Fixed upstream selection and proxy header policy.

Security rules stay hardcoded (prefix admission, internal-segment ban,
untrusted header stripping) while routing data comes from the northbound
manifest (``deploy/northbound.yaml``): the gateway never grows a line of
business logic, opening 100 more capabilities changes only the manifest.

Structure (design §5.6.4):

* ``/nb/`` — exact manifest matching, no fallback. A path that is not in the
  effective route table (not declared, ``enabled: false`` or excluded by
  ``NORTHBOUND_EXPOSED_EXCLUDE``) is routed to ``None`` → 404,
  indistinguishable from a nonexistent endpoint (AC-R4/AC-07).
* ``/api/`` and ``/user/`` — transitional prefix fallback for internal
  traffic (runtime prefixes, then the management default). The end state is
  a derived table for internal routes too; until then the prefix layer stays
  constant in size.

Matching supports one wildcard segment of the form ``{name:path}`` at the
template tail only: it absorbs all remaining segments including slashes
(MinIO object names routinely contain ``/``), and a wildcard in a middle
segment is treated as a declaration error and never matches (fail-safe).
"""
import logging
import os

logger = logging.getLogger(__name__)

_RUNTIME_PATHS = (
    "/agent/run", "/agent/nl2agent/run", "/agent/human-interactions",
    "/skills/nl2skill/run", "/agent/stop", "/agent/automations",
    "/conversation", "/share", "/file/preprocess", "/voice/stt/ws", "/voice/tts/ws",
)
_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
}
_UNTRUSTED_HEADERS = {
    "forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto",
    "x-real-ip", "x-user-id", "x-tenant-id", "x-internal-token",
    "x-authenticated-user", "x-authenticated-tenant",
}

NORTHBOUND_MANIFEST_PATH_ENV = "NORTHBOUND_MANIFEST_PATH"
NORTHBOUND_EXPOSED_EXCLUDE_ENV = "NORTHBOUND_EXPOSED_EXCLUDE"
_DEFAULT_MANIFEST_CANDIDATES = (
    "deploy/northbound.yaml",
    "/app/deploy/northbound.yaml",
    "/app/northbound.yaml",
)


def _admit(path: str) -> bool:
    """Prefix admission (hardcoded, security rule)."""
    return path.startswith("/api/") or path.startswith("/nb/") or path.startswith("/user/")


def _bans_internal(path: str) -> bool:
    """Internal-segment ban (hardcoded, security rule)."""
    return "internal" in path.split("/")


class _RouteEntry:
    """One manifest capability reduced to what routing needs."""

    __slots__ = ("capability_id", "upstream", "path_template", "methods")

    def __init__(self, capability_id, upstream, path_template, methods):
        self.capability_id = capability_id
        self.upstream = upstream
        self.path_template = path_template
        self.methods = frozenset(methods)


def _is_wildcard_segment(segment: str) -> bool:
    return segment.endswith(":path}") and segment.startswith("{")


def _match_entry(entry: _RouteEntry, method: str, path: str) -> bool:
    """Match one entry against method + path (design §3.1.1 algorithm)."""
    if method not in entry.methods:
        return False
    template = entry.path_template.strip("/").split("/") if entry.path_template.strip("/") else []
    actual = path.strip("/").split("/") if path.strip("/") else []
    # A wildcard in a middle segment is a declaration error: fail-safe, never matches.
    if any(_is_wildcard_segment(seg) for seg in template[:-1]):
        return False
    has_wild = bool(template) and _is_wildcard_segment(template[-1])
    if not has_wild and len(template) != len(actual):
        return False  # segment-count pre-check (99% of misses stop here)
    if has_wild and len(actual) < len(template):
        return False  # a wildcard still needs at least one segment to absorb
    for index, (t_seg, a_seg) in enumerate(zip(template, actual)):
        if _is_wildcard_segment(t_seg):
            # Only legal as the tail: absorb every remaining segment.
            return index == len(template) - 1
        if not (t_seg.startswith("{") and t_seg.endswith("}")) and t_seg != a_seg:
            return False  # static segments compare strictly
    return True  # plain parameter segments match any single value


class RouteTable:
    """Immutable effective routing table loaded from the manifest at startup.

    ``select_upstream`` keeps the historical signature so the application
    layer does not change; the table itself is loaded once and rebuilt only
    through an explicit ``reload()`` (file-based hot reload stays a later
    evolution step).
    """

    def __init__(self, entries=()):
        self.entries = tuple(entries)

    def select_upstream(self, method: str, path: str) -> str | None:
        if not _admit(path):
            return None
        if _bans_internal(path):
            return None
        if path.startswith("/nb"):
            for entry in self.entries:
                if _match_entry(entry, method, path):
                    return entry.upstream
            return None  # no fallback in the northbound namespace: 404 (AC-R4)
        # Transitional internal namespace: prefix layer, constant in size.
        normalized = path.removeprefix("/api") if path.startswith("/api/") else path
        if not normalized.startswith("/"):
            return None
        if method == "POST" and normalized.rstrip("/") == "/file/storage":
            return "runtime"
        if any(normalized == prefix or normalized.startswith(prefix + "/") for prefix in _RUNTIME_PATHS):
            return "runtime"
        return "management"

    # ── Loading ────────────────────────────────────────────────────────────

    @classmethod
    def from_manifest(cls, entries, excluded=()) -> "RouteTable":
        """Build the effective table: enabled entries minus the env exclusions."""
        excluded_set = {str(item).strip() for item in (excluded or ()) if str(item).strip()}
        routes = []
        for entry in entries:
            if not entry.get("enabled", True):
                continue
            if entry.get("id") in excluded_set:
                continue
            routes.append(
                _RouteEntry(
                    entry["id"], entry["upstream"], entry["path"], entry["methods"]
                )
            )
        table = cls(routes)
        if excluded_set:
            known = {entry["id"] for entry in entries}
            for unknown in sorted(excluded_set - known):
                logger.warning(
                    "NORTHBOUND_EXPOSED_EXCLUDE lists unknown capability id '%s'", unknown
                )
        return table

    def reload(self, entries, excluded=()) -> None:
        rebuilt = self.from_manifest(entries, excluded)
        self.entries = rebuilt.entries


def _load_manifest_raw(path: str) -> list:
    """Parse the manifest file into plain dicts (fail-fast on any error)."""
    import yaml

    with open(path, "r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    entries = (document or {}).get("northbound")
    if not isinstance(entries, list):
        raise RuntimeError(f"Northbound manifest at {path} must contain a 'northbound' list")
    parsed = []
    seen_paths = {}
    for item in entries:
        if not isinstance(item, dict):
            raise RuntimeError("Northbound manifest entries must be mappings")
        methods = [str(m).upper() for m in (item.get("methods") or [])]
        if not methods:
            raise RuntimeError(f"Manifest entry {item.get('id')!r} declares no methods")
        for method in methods:
            key = (item.get("path"), method)
            if key in seen_paths:
                raise RuntimeError(
                    f"Manifest path conflict: {key[0]} [{method}] declared by both "
                    f"{seen_paths[key]} and {item.get('id')}"
                )
            seen_paths[key] = item.get("id")
        normalized = dict(item)
        normalized["methods"] = methods
        parsed.append(normalized)
    return parsed


def _configured_exclusions() -> tuple:
    raw = os.environ.get(NORTHBOUND_EXPOSED_EXCLUDE_ENV, "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _find_manifest() -> str | None:
    explicit = os.environ.get(NORTHBOUND_MANIFEST_PATH_ENV, "").strip()
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    for candidate in _DEFAULT_MANIFEST_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    return None


def load_route_table() -> RouteTable:
    """Load the effective route table from the manifest.

    Fail-fast: an unreadable, unparsable or structurally invalid manifest
    refuses startup rather than silently routing nothing. A missing manifest
    keeps the northbound namespace empty (every /nb/ path 404s), which is the
    safe state — the deployment contract is "the manifest ships with the
    image" (§5.7).
    """
    path = _find_manifest()
    if path is None:
        logger.warning("Northbound manifest not found; the /nb/ namespace routes to 404")
        return RouteTable()
    entries = _load_manifest_raw(path)
    table = RouteTable.from_manifest(entries, _configured_exclusions())
    logger.info("Gateway route table: %d northbound capabilities from %s", len(table.entries), path)
    return table


# Backwards-compatible module-level entry point. Reconstructed on import so
# the application layer can keep calling ``select_upstream`` directly; tests
# may swap ``ROUTE_TABLE`` (or call ``reload``) to inject a table.
ROUTE_TABLE = load_route_table()


def select_upstream(method: str, path: str) -> str | None:
    """Route public API paths; internal service endpoints are never exposed."""
    return ROUTE_TABLE.select_upstream(method, path)


def filtered_headers(headers, *, request=False):
    """Preserve duplicate headers while removing hop and untrusted identity fields."""
    headers = list(headers)
    blocked = set(_HOP_HEADERS)
    for name, value in headers:
        if name.lower() == "connection":
            blocked.update(item.strip().lower() for item in value.split(","))
    if request:
        blocked.update(_UNTRUSTED_HEADERS)
    return [(name, value) for name, value in headers if name.lower() not in blocked
            and not (request and (name.lower().startswith("x-internal-") or name.lower().startswith("x-nexent-")))]
