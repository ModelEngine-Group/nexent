"""Current user, tenant, cache, and deployment-mode isolation baseline."""

import inspect
from types import SimpleNamespace

import pytest

from backend.agents.agent_run_manager import AgentRunManager
from backend.database.conversation_db import get_conversation
from backend.database.knowledge_db import get_knowledge_name_map_by_index_names
from backend.utils import auth_utils
from nexent.memory.memory_service import search_memory_in_levels


@pytest.fixture
def run_manager():
    manager = AgentRunManager()
    manager.agent_runs.clear()
    manager._conversation_context_managers.clear()
    manager._conversation_run_counts.clear()
    return manager


def test_speed_mode_uses_the_single_local_identity(monkeypatch):
    monkeypatch.setattr(auth_utils, "IS_SPEED_MODE", True)

    assert auth_utils.get_current_user_id() == (
        auth_utils.DEFAULT_USER_ID,
        auth_utils.DEFAULT_TENANT_ID,
    )


def test_full_mode_resolves_same_tenant_users_and_cross_tenant_users(monkeypatch):
    """Freeze the authenticated identity matrix before changing data-access boundaries."""
    identities = {
        "token-a": ("user-a", "tenant-1"),
        "token-b": ("user-b", "tenant-1"),
        "token-c": ("user-c", "tenant-2"),
    }
    monkeypatch.setattr(auth_utils, "IS_SPEED_MODE", False)
    monkeypatch.setattr(
        auth_utils,
        "_decode_jwt_token",
        lambda token: {"sub": identities[token][0]},
    )
    monkeypatch.setattr(auth_utils, "ensure_cas_session_active_from_authorization", lambda token: None)
    monkeypatch.setattr(
        auth_utils,
        "get_user_tenant_by_user_id",
        lambda user_id: {
            "tenant_id": next(tenant for user, tenant in identities.values() if user == user_id)
        },
    )

    assert auth_utils.get_current_user_id("token-a") == identities["token-a"]
    assert auth_utils.get_current_user_id("token-b") == identities["token-b"]
    assert auth_utils.get_current_user_id("token-c") == identities["token-c"]


def test_user_run_keys_are_isolated_for_same_conversation(run_manager):
    """The current in-process run registry separates users sharing a conversation ID."""
    assert run_manager._get_run_key(42, "user-a") != run_manager._get_run_key(42, "user-b")


def test_conversation_read_supports_user_ownership_filter():
    """Record the ownership dimension available at the current DB boundary."""
    parameters = inspect.signature(get_conversation).parameters
    assert "user_id" in parameters
    assert parameters["user_id"].default is None


def test_conversation_read_has_no_explicit_tenant_filter_yet():
    """Known Phase 0 gap: conversation reads do not accept tenant identity."""
    assert "tenant_id" not in inspect.signature(get_conversation).parameters


def test_memory_search_has_explicit_tenant_and_user_dimensions():
    parameters = inspect.signature(search_memory_in_levels).parameters
    assert "tenant_id" in parameters
    assert "user_id" in parameters
    assert "agent_id" in parameters


def test_knowledge_name_lookup_has_no_explicit_tenant_filter_yet():
    """Known Phase 0 gap for the KB display-name lookup used during assembly."""
    assert "tenant_id" not in inspect.signature(get_knowledge_name_map_by_index_names).parameters


def test_context_manager_cache_is_conversation_only_baseline(run_manager, mocker):
    """Known Phase 0 gap: the first config is reused solely by conversation ID."""
    manager_instance = SimpleNamespace(name="first-manager")
    manager_class = mocker.patch(
        "nexent.core.agents.agent_context.ContextManager",
        return_value=manager_instance,
    )
    first_config = SimpleNamespace(name="tenant-a-user-a")
    second_config = SimpleNamespace(name="tenant-b-user-b")

    first = run_manager.get_or_create_context_manager(42, first_config, 10)
    second = run_manager.get_or_create_context_manager(42, second_config, 20)

    assert first is second
    manager_class.assert_called_once_with(config=first_config, max_steps=10)


def test_different_conversations_do_not_share_context_manager(run_manager, mocker):
    manager_class = mocker.patch(
        "nexent.core.agents.agent_context.ContextManager",
        side_effect=[SimpleNamespace(name="first"), SimpleNamespace(name="second")],
    )

    first = run_manager.get_or_create_context_manager(41, SimpleNamespace(), 10)
    second = run_manager.get_or_create_context_manager(42, SimpleNamespace(), 10)

    assert first is not second
    assert manager_class.call_count == 2
