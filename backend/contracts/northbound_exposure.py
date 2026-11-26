# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Declarative northbound exposure annotation for service-side gates.

The annotation is inert at service runtime; the only consumer is the
offline generator (``scripts/generate_exposure_registry.py``), which
compiles the declarations into the Gateway exposure snapshot
(``backend/gateway/exposure/registry.json``).

Fields:
    capability_id  Stable ``domain.action`` id; also the emergency-exclusion key.
    audit          Action capability: the signature must carry audit_hook (checked).
    enabled        False = dark launch: no registry row, gateway 404.
    auth           ``key`` (default) or ``public`` (anonymous, e.g. agent-card).
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
    """Attach the declaration to the gate; return the function unchanged.

    Wrapping would break FastAPI's Depends resolution, which inspects the
    endpoint signature. Only the generator reads the metadata.
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
        # No wrapper: FastAPI resolves Depends from the original signature.
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
    """Yield (declaration, route) for every route carrying the annotation."""
    pairs = []
    for route in router.routes:
        endpoint = getattr(route, "endpoint", None)
        meta = getattr(endpoint, "nb_capability", None)
        if meta is not None:
            pairs.append((meta, route))
    return pairs


def gate_has_audit_dependency(func: Callable[..., Any]) -> bool:
    """Whether the signature carries a Depends(audit_hook(...)) parameter."""
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
