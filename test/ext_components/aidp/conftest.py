"""Restore aidp_permission_service.require_permission after each test.

A handful of legacy mgmt_app tests assign directly to the module attribute.
When this fixture is active, any such assignment is reverted at teardown
so that subsequent test modules (notably test_aidp_permission_service) can
exercise the real ``require_permission`` implementation.
"""
from __future__ import annotations

import pytest

from backend.ext_components.aidp.services import aidp_permission_service


_REQUIRE_ATTRS = (
    "require_permission",
    "_get_user_role",
    "_get_user_groups",
)


@pytest.fixture(autouse=True)
def _preserve_aidp_permission_service(monkeypatch):
    """Snapshot selected attributes and restore them after each test."""
    originals = {attr: getattr(aidp_permission_service, attr) for attr in _REQUIRE_ATTRS}
    yield
    for attr, value in originals.items():
        setattr(aidp_permission_service, attr, value)