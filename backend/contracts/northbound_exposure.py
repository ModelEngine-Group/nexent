# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Declarative northbound exposure annotation for service-side gates.

A northbound gate declares its exposure facts where it lives — on the gate
function itself. The annotation is inert at service runtime: importing the
gate module changes nothing about how the service behaves. The single
consumer is the offline generator
(``scripts/generate_exposure_registry.py``), which scans gate modules,
collects the declared capabilities, and compiles them into the Gateway
exposure snapshot (``backend/gateway/exposure/registry.json``).

Why an annotation instead of a sidecar manifest: path, methods and upstream
are already facts of the gate code (router prefix + decorator + module
location). The annotation only adds what code cannot express — the stable
capability id, whether the action is audited, whether it is serving yet
(dark launch) and the credential policy. Keeping the declaration on the
gate removes the manifest↔code reconciliation surface entirely: a gate
cannot drift from its declaration because they are one artefact.

Fields:
    capability_id  Stable ``domain.action`` id (contract level, never
                    renamed after release). The generator derives the
                    deterministic route_id from it and the emergency
                    exclusion env var addresses capabilities by this id.
    audit          True for action capabilities: the gate signature must
                    carry ``Depends(audit_hook(...))`` and the generator
                    fails when it does not (declared-but-missing audit is
                    a review regression, not a warning).
    enabled        False = declared but not serving (dark launch): the
                    gate code exists, the generator emits no registry row,
                    the Gateway returns 404 indistinguishable from
                    nonexistent.
    auth           ``key`` (default) requires an API-Key credential,
                    ``public`` maps to the anonymous credential policy
                    (protocol endpoints such as agent-card discovery).
"""

from typing import Any, Callable, Optional

VALID_AUTH = ("key", "public")


def nb_exposed(
    capability_id: str,
    *,
    audit: bool = False,
    enabled: bool = True,
    auth: str = "key",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark a northbound gate with its exposure declaration.

    Inert at runtime: only attaches :data:`nb_capability` metadata to the
    decorated function and preserves its signature. The offline generator
    reads the metadata; services never do.
    """
    if not capability_id or "." not in capability_id:
        raise ValueError(
            f"nb_exposed: capability_id must be a stable 'domain.action' id, got {capability_id!r}"
        )
    if auth not in VALID_AUTH:
        raise ValueError(f"nb_exposed: auth must be one of {VALID_AUTH}, got {auth!r}")

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        if getattr(func, "nb_capability", None) is not None:
            raise ValueError(
                f"nb_exposed: {func.__module__}.{func.__qualname__} is already declared "
                f"as {func.nb_capability.capability_id!r}"
            )
        # Attach and return the original function untouched: FastAPI inspects
        # the endpoint signature to resolve Depends(...), so any wrapper would
        # strip the dependency chain. The annotation must stay inert.
        func.nb_capability = NbCapability(  # type: ignore[attr-defined]
            capability_id=capability_id, audit=audit, enabled=enabled, auth=auth
        )
        return func

    return decorate


class NbCapability:
    """Immutable exposure declaration attached to a gate function."""

    __slots__ = ("capability_id", "audit", "enabled", "auth")

    def __init__(self, *, capability_id: str, audit: bool, enabled: bool, auth: str):
        self.capability_id = capability_id
        self.audit = audit
        self.enabled = enabled
        self.auth = auth

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"NbCapability(capability_id={self.capability_id!r}, audit={self.audit!r}, "
            f"enabled={self.enabled!r}, auth={self.auth!r})"
        )


def iter_declared_capabilities(router) -> list:
    """Collect (declaration, route) pairs from a northbound gate router.

    Yields every API route whose endpoint carries ``nb_capability``
    metadata, preserving route order. Used by tests and the offline
    generator's runtime-free verification helpers.
    """
    pairs = []
    for route in router.routes:
        endpoint = getattr(route, "endpoint", None)
        meta = getattr(endpoint, "nb_capability", None)
        if meta is not None:
            pairs.append((meta, route))
    return pairs


def gate_has_audit_dependency(func: Callable[..., Any]) -> bool:
    """Best-effort static check that an audited gate actually audits.

    Checks the decorated function's source signature for an ``audit``
    keyword with a ``Depends(audit_hook(...))`` default — the review the
    generator enforces for ``audit=True`` declarations.
    """
    import inspect

    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):  # pragma: no cover - exotic callables
        return False
    parameter = signature.parameters.get("audit")
    if parameter is None:
        return False
    default = parameter.default
    return hasattr(default, "dependency") and "audit_hook" in repr(default.dependency)
