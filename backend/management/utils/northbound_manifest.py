# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Northbound manifest loading, validation and startup reconciliation.

The manifest (``deploy/northbound.yaml``) is the single hand-written source
of truth for the open surface. Both the gateway and the service load the same
file at startup; this module is the service side:

1. parse and validate the manifest (schema, ids, duplicate paths);
2. forward reconciliation — every manifest path must exist as an actual
   FastAPI route (checked at the *declared* ``enabled`` value, so a dark
   capability still requires its gate to exist);
3. reverse reconciliation — every actual ``/nb/`` route must be listed in the
   manifest, so a new gate cannot ship silently unlisted;
4. exclusion spelling check — ``NORTHBOUND_EXPOSED_EXCLUDE`` ids that are not
   in the manifest produce a startup warning with the closest suggestions.

Every structural problem is fail-fast: a drifted manifest refuses startup
instead of silently 404-ing at runtime. A missing file or a disabled
environment switch disables the reconciliation silently, so local
development without the manifest keeps working.
"""

import difflib
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

NORTHBOUND_MANIFEST_PATH_ENV = "NORTHBOUND_MANIFEST_PATH"
DEFAULT_MANIFEST_PATHS = (
    "deploy/northbound.yaml",
    "../deploy/northbound.yaml",
    "/app/deploy/northbound.yaml",
    "/app/northbound.yaml",
)
# Reconciliation is meaningful only when the manifest is expected; tests and
# local development can opt out explicitly.
NORTHBOUND_RECONCILE_ENV = "NORTHBOUND_MANIFEST_RECONCILE"

VALID_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "WS"}
VALID_AUTH = {"key", "public"}


class ManifestError(RuntimeError):
    """Raised when the manifest itself is invalid or drifted."""


@dataclass(frozen=True)
class ManifestEntry:
    """One declared capability."""

    id: str
    upstream: str
    path: str
    methods: Tuple[str, ...]
    auth: str = "key"
    params_lock: Mapping[str, Sequence[str]] = field(default_factory=dict)
    audit: bool = False
    rate_limit: bool = False
    log_usage: bool = True
    enabled: bool = True

    def method_set(self) -> Set[str]:
        return set(self.methods)


def _parse_manifest(raw: object) -> List[ManifestEntry]:
    """Parse and validate one manifest document. Raises ManifestError."""
    try:
        import yaml  # imported lazily: the service image may not need it elsewhere
    except ImportError as exc:  # pragma: no cover - deployment guarantees PyYAML
        raise ManifestError("PyYAML is required to load the northbound manifest") from exc

    if not isinstance(raw, Mapping):
        # ``yaml.safe_load`` was already applied by the caller for dict input.
        if isinstance(raw, str):
            raw = yaml.safe_load(raw)
        else:
            raise ManifestError("Northbound manifest must be a YAML mapping")
    entries = raw.get("northbound") if isinstance(raw, Mapping) else None
    if not isinstance(entries, list):
        raise ManifestError("Northbound manifest must contain a 'northbound' list")

    parsed: List[ManifestEntry] = []
    seen_ids: Set[str] = set()
    seen_paths: Dict[Tuple[str, str], str] = {}
    for index, item in enumerate(entries):
        if not isinstance(item, Mapping):
            raise ManifestError(f"Manifest entry #{index} must be a mapping")
        entry_id = str(item.get("id", "")).strip()
        if not entry_id or "." not in entry_id:
            raise ManifestError(f"Manifest entry #{index} has an invalid id: {item.get('id')!r}")
        if entry_id in seen_ids:
            raise ManifestError(f"Duplicate capability id: {entry_id}")
        seen_ids.add(entry_id)

        path = str(item.get("path", "")).strip()
        if not path.startswith("/"):
            raise ManifestError(f"Capability {entry_id}: path must start with '/'")
        methods_raw = item.get("methods")
        if not isinstance(methods_raw, list) or not methods_raw:
            raise ManifestError(f"Capability {entry_id}: methods must be a non-empty list")
        methods = tuple(str(m).upper() for m in methods_raw)
        invalid = set(methods) - VALID_METHODS
        if invalid:
            raise ManifestError(f"Capability {entry_id}: invalid methods {sorted(invalid)}")

        auth = str(item.get("auth", "key")).lower()
        if auth not in VALID_AUTH:
            raise ManifestError(f"Capability {entry_id}: auth must be one of {sorted(VALID_AUTH)}")

        params_lock_raw = item.get("params_lock") or {}
        if not isinstance(params_lock_raw, Mapping):
            raise ManifestError(f"Capability {entry_id}: params_lock must be a mapping")
        params_lock = {
            str(name): tuple(str(v) for v in values)
            for name, values in params_lock_raw.items()
        }

        entry = ManifestEntry(
            id=entry_id,
            upstream=str(item.get("upstream", "")).strip(),
            path=path,
            methods=methods,
            auth=auth,
            params_lock=params_lock,
            audit=bool(item.get("audit", False)),
            rate_limit=bool(item.get("rate_limit", False)),
            log_usage=bool(item.get("log_usage", True)),
            enabled=bool(item.get("enabled", True)),
        )
        if not entry.upstream:
            raise ManifestError(f"Capability {entry_id}: upstream is required")

        for method in entry.methods:
            key = (path, method)
            if key in seen_paths:
                raise ManifestError(
                    f"Path conflict: {path} [{method}] is declared by both "
                    f"{seen_paths[key]} and {entry_id}"
                )
            seen_paths[key] = entry_id
        parsed.append(entry)
    return parsed


def load_manifest_file(path: str) -> Tuple[List[ManifestEntry], object]:
    """Parse the manifest file. Raises ManifestError with path context."""
    import yaml

    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except OSError as exc:
        raise ManifestError(f"Cannot read northbound manifest at {path}: {exc}") from exc
    entries = _parse_manifest(raw)
    return entries, raw


def find_manifest_file() -> Optional[str]:
    """Locate the manifest: explicit env override first, then known roots."""
    explicit = os.environ.get(NORTHBOUND_MANIFEST_PATH_ENV, "").strip()
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    for candidate in DEFAULT_MANIFEST_PATHS:
        if os.path.isfile(candidate):
            return candidate
    return None


def _route_signature(route) -> Tuple[str, str]:
    """Route path template normalized: no trailing slash, keep {params}."""
    path = getattr(route, "path", "") or ""
    if len(path) > 1:
        path = path.rstrip("/")
    return path, ",".join(sorted(getattr(route, "methods", ()) or ()))


def _path_matches(template: str, manifest_path: str) -> bool:
    """Whether two path templates describe the same route.

    Parameter names may differ between the manifest and the actual route
    (``{task_id}`` vs ``{id}``); segment count and static segments must agree.
    """
    t = [seg for seg in template.strip("/").split("/") if seg]
    m = [seg for seg in manifest_path.strip("/").split("/") if seg]
    if len(t) != len(m):
        return False
    for ts, ms in zip(t, m):
        t_param = ts.startswith("{") and ts.endswith("}")
        m_param = ms.startswith("{") and ms.endswith("}")
        if t_param and m_param:
            continue
        if ts != ms:
            return False
    return True


def _app_nb_routes(app, seen=None) -> List[Tuple[str, Set[str]]]:
    """Collect (path, methods) of every actual /nb route on the app.

    Newer FastAPI versions include routers lazily through ``_IncludedRouter``
    wrappers, so the walk descends into ``original_router`` subtrees too.
    """
    if seen is None:
        seen = set()
    routes = []
    for route in getattr(app, "routes", []) or []:
        marker = id(route)
        if marker in seen:
            continue
        seen.add(marker)
        if getattr(route, "original_router", None) is not None:
            routes.extend(_app_nb_routes(route.original_router, seen))
            continue
        path = getattr(route, "path", "") or ""
        if not (path == "/nb" or path.startswith("/nb/")):
            continue
        methods = set(getattr(route, "methods", ()) or ())
        if methods:
            routes.append((path, methods))
    return routes


def reconcile_northbound_manifest(app, *, strict: Optional[bool] = None) -> List[ManifestEntry]:
    """Validate the manifest against the app's actual routes. Fail-fast.

    Called once at startup after all routers (including the northbound gates)
    are mounted. Returns the parsed entries for logging; raises
    ``ManifestError`` on any structural drift so the process refuses to start.

    Missing manifest or an explicit opt-out disables the check silently —
    local development keeps working without the deployment file.
    """
    if strict is None:
        strict = os.environ.get(NORTHBOUND_RECONCILE_ENV, "true").lower() != "false"

    manifest_path = find_manifest_file()
    if manifest_path is None:
        if strict:
            logger.info("Northbound manifest not found; reconciliation skipped")
        return []
    entries, _ = load_manifest_file(manifest_path)
    if not strict:
        return entries

    actual = _app_nb_routes(app)

    # Forward: every manifest entry (at its declared enabled value) must have
    # a matching actual route with at least the declared methods.
    for entry in entries:
        candidates = [(p, m) for p, m in actual if _path_matches(p, entry.path)]
        if not candidates:
            raise ManifestError(
                f"Manifest capability '{entry.id}' declares path {entry.path} "
                f"[{','.join(entry.methods)}] but no matching route exists on this app"
            )
        missing_methods = set(entry.method_set()) - set().union(*(m for _, m in candidates))
        if missing_methods:
            raise ManifestError(
                f"Manifest capability '{entry.id}' ({entry.path}) declares methods "
                f"{sorted(missing_methods)} that the actual route does not accept"
            )

    # Reverse: every actual /nb route must be listed in the manifest.
    listed_paths = [entry.path for entry in entries]
    for path, methods in actual:
        if not any(_path_matches(path, listed) for listed in listed_paths):
            raise ManifestError(
                f"Northbound route {path} exists on the app but is not listed in "
                f"the manifest ({manifest_path}); add it or remove the route"
            )

    # Exclude spelling check: warn (not fail) with the closest suggestions.
    excluded = _configured_exclusions()
    known = {entry.id for entry in entries}
    for unknown in excluded - known:
        suggestions = difflib.get_close_matches(unknown, known, n=3)
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        logger.warning(
            "NORTHBOUND_EXPOSED_EXCLUDE contains unknown capability id '%s'.%s",
            unknown,
            hint,
        )

    enabled_count = sum(1 for e in entries if e.enabled)
    excluded_here = tuple(sorted(known & excluded))
    logger.info(
        "Northbound manifest: %d entries, %d serving, excluded-by-env=[%s] (%s)",
        len(entries),
        enabled_count - len(excluded_here),
        ", ".join(excluded_here) or "-",
        manifest_path,
    )
    return entries


def _configured_exclusions() -> Set[str]:
    try:
        from contracts.constants import environment

        return set(environment.NORTHBOUND_EXPOSED_EXCLUDE)
    except Exception:  # pragma: no cover - import guard for isolated tests
        raw = os.environ.get("NORTHBOUND_EXPOSED_EXCLUDE", "")
        return {item.strip() for item in raw.split(",") if item.strip()}


def manifest_entries_by_path(entries: Iterable[ManifestEntry]) -> Dict[str, ManifestEntry]:
    """Index parsed entries by path, for gateway-side route building."""
    return {entry.path: entry for entry in entries}
