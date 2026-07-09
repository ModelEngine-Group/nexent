"""
Unit tests for ExternalKnowledgeBaseService
(backend/services/external_kb_service.py).

Covers the dispatcher-layer safeguards:
  - delete_adapter() must reject the built-in local adapter
  - register_adapter() must reject manual registration of platform="local"

Other dispatcher behavior is exercised indirectly by integration tests
of the unified_kb_app and external_kb_app HTTP routers.
"""
import os
import sys
import pytest
from unittest.mock import MagicMock

_test_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
for _p in [os.path.join(_test_root, "backend"), os.path.join(_test_root, "sdk")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from services.external_kb_service import ExternalKnowledgeBaseService


# ---------------------------------------------------------------------------
# delete_adapter — local protection
# ---------------------------------------------------------------------------

def test_delete_adapter_blocks_local_platform(monkeypatch):
    """Built-in local adapter cannot be deleted via the dispatcher."""
    monkeypatch.setattr(
        "database.external_kb_adapter_db.get_adapter_by_id",
        lambda adapter_id, tenant_id: {
            "adapter_id": adapter_id,
            "platform": "local",
            "name": "本地知识库",
        },
    )
    deleted = MagicMock()
    monkeypatch.setattr(
        "database.external_kb_adapter_db.delete_adapter", deleted
    )

    with pytest.raises(ValueError, match="Cannot delete the built-in local adapter"):
        ExternalKnowledgeBaseService.delete_adapter(adapter_id=1, tenant_id="t1")
    deleted.assert_not_called()


def test_delete_adapter_allows_external_platform(monkeypatch):
    """Non-local adapters can still be deleted normally."""
    monkeypatch.setattr(
        "database.external_kb_adapter_db.get_adapter_by_id",
        lambda adapter_id, tenant_id: {
            "adapter_id": adapter_id,
            "platform": "dify",
            "name": "Dify",
        },
    )
    monkeypatch.setattr(
        "database.external_kb_adapter_db.delete_adapter",
        lambda adapter_id, tenant_id: True,
    )
    assert ExternalKnowledgeBaseService.delete_adapter(adapter_id=2, tenant_id="t1") is True


def test_delete_adapter_returns_false_when_not_found(monkeypatch):
    monkeypatch.setattr(
        "database.external_kb_adapter_db.get_adapter_by_id",
        lambda adapter_id, tenant_id: None,
    )
    assert ExternalKnowledgeBaseService.delete_adapter(adapter_id=999, tenant_id="t1") is False


# ---------------------------------------------------------------------------
# register_adapter — local protection
# ---------------------------------------------------------------------------

def test_register_adapter_blocks_local(monkeypatch):
    """Manual registration of platform='local' must be rejected."""
    created = MagicMock()
    monkeypatch.setattr("database.external_kb_adapter_db.create_adapter", created)

    with pytest.raises(ValueError, match="auto-provisioned"):
        ExternalKnowledgeBaseService.register_adapter(
            request_data={"platform": "local", "name": "dup"},
            tenant_id="t1",
        )
    created.assert_not_called()


def test_register_adapter_allows_external(monkeypatch):
    """External platforms can still be registered normally."""
    monkeypatch.setattr(
        "database.external_kb_adapter_db.create_adapter",
        lambda data: {"adapter_id": 7, **data},
    )
    # Pretend there's a registered adapter class for "dify"
    monkeypatch.setattr(
        "nexent.core.knowledge_base.platform_adapters.ExternalKBAdapterRegistry.get",
        lambda platform: MagicMock(),
    )
    result = ExternalKnowledgeBaseService.register_adapter(
        request_data={"platform": "dify", "name": "Dify KB"},
        tenant_id="t1",
    )
    assert result["adapter_id"] == 7
    assert result["platform"] == "dify"


def test_register_adapter_rejects_unknown_platform(monkeypatch):
    """Unregistered platform strings must raise ValueError."""
    monkeypatch.setattr(
        "nexent.core.knowledge_base.platform_adapters.ExternalKBAdapterRegistry.get",
        lambda platform: None,
    )
    monkeypatch.setattr(
        "nexent.core.knowledge_base.platform_adapters.ExternalKBAdapterRegistry.registered_platforms",
        lambda: ["local", "dify"],
    )
    created = MagicMock()
    monkeypatch.setattr("database.external_kb_adapter_db.create_adapter", created)

    with pytest.raises(ValueError, match="No adapter registered for platform"):
        ExternalKnowledgeBaseService.register_adapter(
            request_data={"platform": "nonexistent"},
            tenant_id="t1",
        )
    created.assert_not_called()
