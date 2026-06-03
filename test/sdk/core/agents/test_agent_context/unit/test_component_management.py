"""
Unit tests for ContextManager component management methods.

Tests:
- register_component()
- clear_components()
- get_registered_components()
- build_system_prompt()
- _get_strategy()
- _calculate_component_budget()
"""
import sys
import os
from pathlib import Path

TEST_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = TEST_ROOT.parent

for _path in (str(PROJECT_ROOT), str(TEST_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from loader import ContextManager, ContextManagerConfig
from stubs import _SystemPromptStep


class MockComponent:
    """Mock context component for testing."""
    
    def __init__(self, component_type="test", content="", priority=10, token_estimate=0):
        self.component_type = component_type
        self.priority = priority
        self.token_estimate = token_estimate
        self._content = content
        self.metadata = {}
    
    def to_messages(self):
        if self._content:
            return [{"role": "system", "content": self._content}]
        return []
    
    def estimate_tokens(self, chars_per_token=1.5):
        return int(len(self._content) / chars_per_token)


class TestRegisterComponent:
    """Tests for register_component() method."""
    
    def test_register_single_component(self):
        cm = ContextManager()
        comp = MockComponent(component_type="test", content="test content")
        cm.register_component(comp)
        assert len(cm.get_registered_components()) == 1
    
    def test_register_multiple_components(self):
        cm = ContextManager()
        cm.register_component(MockComponent(content="comp1"))
        cm.register_component(MockComponent(content="comp2"))
        cm.register_component(MockComponent(content="comp3"))
        assert len(cm.get_registered_components()) == 3
    
    def test_register_sets_token_estimate(self):
        cm = ContextManager()
        comp = MockComponent(content="test content here", token_estimate=0)
        cm.register_component(comp)
        registered = cm.get_registered_components()
        assert registered[0].token_estimate > 0
    
    def test_register_preserves_existing_token_estimate(self):
        cm = ContextManager()
        comp = MockComponent(content="test", token_estimate=100)
        cm.register_component(comp)
        registered = cm.get_registered_components()
        assert registered[0].token_estimate == 100


class TestClearComponents:
    """Tests for clear_components() method."""
    
    def test_clear_removes_all_components(self):
        cm = ContextManager()
        cm.register_component(MockComponent(content="comp1"))
        cm.register_component(MockComponent(content="comp2"))
        cm.clear_components()
        assert cm.get_registered_components() == []
    
    def test_clear_on_empty_manager(self):
        cm = ContextManager()
        cm.clear_components()
        assert cm.get_registered_components() == []
    
    def test_clear_allows_new_registration(self):
        cm = ContextManager()
        cm.register_component(MockComponent(content="old"))
        cm.clear_components()
        cm.register_component(MockComponent(content="new"))
        assert len(cm.get_registered_components()) == 1
        assert cm.get_registered_components()[0]._content == "new"


class TestGetRegisteredComponents:
    """Tests for get_registered_components() method."""
    
    def test_returns_copy_not_reference(self):
        cm = ContextManager()
        cm.register_component(MockComponent(content="original"))
        copy1 = cm.get_registered_components()
        copy2 = cm.get_registered_components()
        copy1.clear()
        assert len(copy2) == 1
    
    def test_returns_empty_list_when_no_components(self):
        cm = ContextManager()
        result = cm.get_registered_components()
        assert result == []
    
    def test_preserves_component_order(self):
        cm = ContextManager()
        cm.register_component(MockComponent(content="first", priority=10))
        cm.register_component(MockComponent(content="second", priority=20))
        registered = cm.get_registered_components()
        assert registered[0]._content == "first"
        assert registered[1]._content == "second"


class TestGetStrategy:
    """Tests for _get_strategy() method."""
    
    def test_default_returns_token_budget_strategy(self):
        cm = ContextManager()
        strategy = cm._get_strategy()
        assert strategy.get_strategy_name() == "token_budget"
    
    def test_full_strategy(self):
        config = ContextManagerConfig(strategy="full")
        cm = ContextManager(config)
        strategy = cm._get_strategy()
        assert strategy.get_strategy_name() == "full"
    
    def test_buffered_strategy_with_custom_buffer_size(self):
        config = ContextManagerConfig(strategy="buffered", buffer_size_per_component=5)
        cm = ContextManager(config)
        strategy = cm._get_strategy()
        assert strategy.get_strategy_name() == "buffered"
        assert strategy.buffer_size == 5
    
    def test_priority_strategy(self):
        config = ContextManagerConfig(strategy="priority")
        cm = ContextManager(config)
        strategy = cm._get_strategy()
        assert strategy.get_strategy_name() == "priority"
    
    def test_unknown_strategy_defaults_to_token_budget(self):
        config = ContextManagerConfig(strategy="unknown")
        cm = ContextManager(config)
        strategy = cm._get_strategy()
        assert strategy.get_strategy_name() == "token_budget"


class TestBuildSystemPrompt:
    """Tests for build_system_prompt() method."""
    
    def test_empty_components_returns_empty_messages(self):
        cm = ContextManager()
        messages = cm.build_system_prompt()
        assert messages == []
    
    def test_single_component_returns_messages(self):
        cm = ContextManager()
        cm.register_component(MockComponent(content="test prompt"))
        messages = cm.build_system_prompt()
        assert len(messages) == 1
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "test prompt"
    
    def test_multiple_components_combined(self):
        cm = ContextManager()
        cm.register_component(MockComponent(content="prompt1", priority=20))
        cm.register_component(MockComponent(content="prompt2", priority=10))
        messages = cm.build_system_prompt()
        assert len(messages) == 2
    
    def test_custom_token_budget(self):
        cm = ContextManager()
        cm.register_component(MockComponent(content="short", token_estimate=50))
        cm.register_component(MockComponent(content="very long content here", token_estimate=500))
        messages = cm.build_system_prompt(token_budget=100)
        total_content = sum(len(m["content"]) for m in messages)
        assert total_content < 500
    
    def test_deduplicates_identical_messages(self):
        cm = ContextManager()
        cm.register_component(MockComponent(content="same content"))
        cm.register_component(MockComponent(content="same content"))
        messages = cm.build_system_prompt()
        assert len(messages) == 1


class TestCalculateComponentBudget:
    """Tests for _calculate_component_budget() method."""
    
    def test_excludes_conversation_history(self):
        cm = ContextManager()
        budget = cm._calculate_component_budget()
        budgets = cm.config.component_budgets
        assert "conversation_history" in budgets
        assert budget == sum(v for k, v in budgets.items() if k != "conversation_history")
    
    def test_sum_of_non_excluded_budgets(self):
        cm = ContextManager()
        budget = cm._calculate_component_budget()
        expected = (
            cm.config.component_budgets["system_prompt"] +
            cm.config.component_budgets["tools"] +
            cm.config.component_budgets["skills"] +
            cm.config.component_budgets["memory"] +
            cm.config.component_budgets["knowledge_base"] +
            cm.config.component_budgets["managed_agents"] +
            cm.config.component_budgets["external_a2a_agents"]
        )
        assert budget == expected


class TestMessageAlreadyPresent:
    """Tests for _message_already_present() method."""
    
    def test_identical_message_detected(self):
        cm = ContextManager()
        messages = [{"role": "system", "content": "test"}]
        new_msg = {"role": "system", "content": "test"}
        assert cm._message_already_present(messages, new_msg) is True
    
    def test_different_content_not_detected(self):
        cm = ContextManager()
        messages = [{"role": "system", "content": "test"}]
        new_msg = {"role": "system", "content": "different"}
        assert cm._message_already_present(messages, new_msg) is False
    
    def test_different_role_not_detected(self):
        cm = ContextManager()
        messages = [{"role": "system", "content": "test"}]
        new_msg = {"role": "user", "content": "test"}
        assert cm._message_already_present(messages, new_msg) is False
    
    def test_empty_messages_list(self):
        cm = ContextManager()
        new_msg = {"role": "system", "content": "test"}
        assert cm._message_already_present([], new_msg) is False


class TestComponentManagementWithConfig:
    """Tests for component management with custom ContextManagerConfig."""
    
    def test_strategy_selection_from_config(self):
        config = ContextManagerConfig(strategy="full")
        cm = ContextManager(config)
        strategy = cm._get_strategy()
        assert strategy.get_strategy_name() == "full"
    
    def test_component_budgets_from_config(self):
        custom_budgets = {"system_prompt": 2000, "tools": 1000, "conversation_history": 3000}
        config = ContextManagerConfig(component_budgets=custom_budgets)
        cm = ContextManager(config)
        budget = cm._calculate_component_budget()
        assert budget == 3000
    
    def test_chars_per_token_used_in_estimation(self):
        config = ContextManagerConfig(chars_per_token=2.0)
        cm = ContextManager(config)
        comp = MockComponent(content="test content")
        cm.register_component(comp)
        registered = cm.get_registered_components()
        assert registered[0].token_estimate > 0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__])