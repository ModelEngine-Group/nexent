# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unit coverage for the declarative northbound exposure annotation.

The annotation is inert at runtime; these tests pin the declaration contract
the offline generator relies on: id/auth validation, duplicate-declaration
rejection, signature preservation for FastAPI Depends resolution, route
iteration, and the audit-dependency signature rule.
"""

from fastapi import APIRouter, Depends
import pytest

from contracts.northbound_exposure import (
    NbCapability,
    gate_has_audit_dependency,
    iter_declared_capabilities,
    nb_exposed,
)


def make_gate(capability_id="demo.action", **kwargs):
    @nb_exposed(capability_id, **kwargs)
    async def gate(task_id: int):
        return task_id

    return gate


# ---------------------------------------------------------------------------
# declaration validation
# ---------------------------------------------------------------------------


def test_valid_declaration_attaches_metadata_without_wrapping():
    gate = make_gate("demo.action", audit=True, enabled=False, auth="key")
    meta = gate.nb_capability
    assert isinstance(meta, NbCapability)
    assert (meta.capability_id, meta.audit, meta.enabled, meta.auth) == (
        "demo.action", True, False, "key",
    )
    # No wrapper: the original function object is returned unchanged.
    assert gate.__name__ == "gate"


def test_public_auth_is_accepted():
    gate = make_gate("demo.card", auth="public")
    assert gate.nb_capability.auth == "public"


@pytest.mark.parametrize("capability_id", ["", "no-dot", None])
def test_capability_id_must_be_domain_action(capability_id):
    with pytest.raises(ValueError, match="domain.action"):
        nb_exposed(capability_id)


def test_auth_must_be_known():
    with pytest.raises(ValueError, match="auth must be one of"):
        nb_exposed("demo.action", auth="session")


def test_duplicate_declaration_rejected():
    gate = make_gate("demo.first")
    with pytest.raises(ValueError, match="already declared"):
        nb_exposed("demo.second")(gate)


# ---------------------------------------------------------------------------
# route iteration
# ---------------------------------------------------------------------------


def test_iter_declared_capabilities_pairs_meta_and_route():
    router = APIRouter(prefix="/nb/v1/demo")

    @router.get("/open")
    @nb_exposed("demo.open")
    async def open_gate():
        return {}

    @router.get("/plain")
    async def plain_gate():
        return {}

    pairs = iter_declared_capabilities(router)
    assert len(pairs) == 1
    meta, route = pairs[0]
    assert meta.capability_id == "demo.open"
    assert route.path == "/nb/v1/demo/open"


# ---------------------------------------------------------------------------
# audit-dependency signature rule (shared with the offline generator)
# ---------------------------------------------------------------------------


def audit_hook(capability_id):
    async def recorder():
        return None

    return recorder


def test_audit_dependency_detected_on_signature():
    async def gate(task_id: int, audit=Depends(audit_hook("demo.action"))):
        return task_id

    assert gate_has_audit_dependency(gate) is True


def test_missing_audit_parameter_is_not_audited():
    async def gate(task_id: int):
        return task_id

    assert gate_has_audit_dependency(gate) is False


def test_plain_default_is_not_an_audit_dependency():
    async def gate(task_id: int, audit=None):
        return task_id

    assert gate_has_audit_dependency(gate) is False


def test_non_inspectable_callable_is_not_audited():
    assert gate_has_audit_dependency(object()) is False