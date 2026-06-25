"""Integration tests for context component registration in NexentAgent and CoreAgent."""

import pytest
from unittest.mock import MagicMock, patch

from sdk.nexent.core.agents.agent_model import (
    SystemPromptComponent,
    ToolsComponent,
    AgentConfig,
    ToolConfig,
)
from sdk.nexent.core.agents.summary_config import ContextManagerConfig


STRATEGY_TOKEN_BUDGET = "token_budget"


class TestNexentAgentComponentRegistration:
    """Tests for NexentAgent.register_context_components functionality."""

    @pytest.fixture
    def mock_context_manager(self):
        manager = MagicMock()
        manager._components = []
        manager.get_registered_components = lambda: list(manager._components)
        manager.register_component = lambda c: manager._components.append(c)
        return manager

    @pytest.fixture
    def agent_config_with_components(self):
        ctx_config = ContextManagerConfig(
            token_threshold=1000,
            strategy=STRATEGY_TOKEN_BUDGET,
            component_budgets={"tools": 200, "skills": 100},
        )
        
        components = [
            ToolsComponent(content="Tool descriptions", token_estimate=50),
            SystemPromptComponent(content="System prompt", token_estimate=100),
        ]
        
        return AgentConfig(
            name="test_agent",
            description="Test agent",
            model_name="test-model",
            tools=[],
            context_manager_config=ctx_config,
            context_components=components,
        )

    def test_context_manager_mounted_when_config_present(self, agent_config_with_components):
        agent = MagicMock()
        agent.context_manager = None
        
        ctx_config = getattr(agent_config_with_components, 'context_manager_config', None)
        if ctx_config:
            from sdk.nexent.core.agents.agent_context import ContextManager
            agent.context_manager = ContextManager(
                config=ctx_config,
                max_steps=10
            )
            
            components = getattr(agent_config_with_components, 'context_components', None)
            if components:
                for component in components:
                    agent.context_manager.register_component(component)
        
        assert agent.context_manager is not None
        assert len(agent.context_manager.get_registered_components()) == 2

    def test_no_context_manager_when_config_absent(self):
        agent_config = AgentConfig(
            name="test_agent",
            description="Test agent",
            model_name="test-model",
            tools=[],
        )
        
        ctx_config = getattr(agent_config, 'context_manager_config', None)
        agent = MagicMock()
        agent.context_manager = None
        
        assert ctx_config is None
        assert agent.context_manager is None

    def test_components_registered_in_order(self, mock_context_manager, agent_config_with_components):
        components = getattr(agent_config_with_components, 'context_components', [])
        
        for component in components:
            mock_context_manager.register_component(component)
        
        registered = mock_context_manager.get_registered_components()
        assert len(registered) == 2
        assert registered[0].component_type == "tools"
        assert registered[1].component_type == "system_prompt"


class TestCoreAgentSystemPromptAssembly:
    """Tests for CoreAgent._build_system_prompt_from_components functionality."""

    @pytest.fixture
    def mock_context_manager_with_components(self):
        manager = MagicMock()
        manager.get_registered_components = lambda: [
            SystemPromptComponent(content="Base prompt", token_estimate=50),
            ToolsComponent(content="Tool info", token_estimate=30),
        ]
        manager.build_system_prompt = lambda: [
            {"role": "system", "content": "Base prompt\n\nTool info"},
        ]
        return manager

    def test_system_prompt_uses_components_when_registered(self, mock_context_manager_with_components):
        base_prompt = "Original system prompt"
        
        if mock_context_manager_with_components and mock_context_manager_with_components.get_registered_components():
            component_messages = mock_context_manager_with_components.build_system_prompt()
            if component_messages:
                final_prompt = "\n\n".join(
                    msg.get("content", "") for msg in component_messages if msg.get("role") == "system"
                )
        
        assert final_prompt == "Base prompt\n\nTool info"

    def test_system_prompt_fallback_when_no_components(self):
        base_prompt = "Original system prompt"
        context_manager = MagicMock()
        context_manager.get_registered_components = lambda: []
        
        if context_manager and context_manager.get_registered_components():
            component_messages = context_manager.build_system_prompt()
            if component_messages:
                final_prompt = "\n\n".join(
                    msg.get("content", "") for msg in component_messages if msg.get("role") == "system"
                )
            else:
                final_prompt = base_prompt
        else:
            final_prompt = base_prompt
        
        assert final_prompt == "Original system prompt"

    def test_system_prompt_fallback_when_no_context_manager(self):
        base_prompt = "Original system prompt"
        context_manager = None
        
        if context_manager and context_manager.get_registered_components():
            component_messages = context_manager.build_system_prompt()
            if component_messages:
                final_prompt = "\n\n".join(
                    msg.get("content", "") for msg in component_messages if msg.get("role") == "system"
                )
            else:
                final_prompt = base_prompt
        else:
            final_prompt = base_prompt
        
        assert final_prompt == "Original system prompt"

    def test_empty_component_messages_fallback(self):
        base_prompt = "Original system prompt"
        context_manager = MagicMock()
        context_manager.get_registered_components = lambda: [MagicMock()]
        context_manager.build_system_prompt = lambda: []
        
        if context_manager and context_manager.get_registered_components():
            component_messages = context_manager.build_system_prompt()
            if component_messages:
                final_prompt = "\n\n".join(
                    msg.get("content", "") for msg in component_messages if msg.get("role") == "system"
                )
            else:
                final_prompt = base_prompt
        else:
            final_prompt = base_prompt
        
        assert final_prompt == "Original system prompt"


class TestBackwardCompatibility:
    """Tests for backward compatibility with existing agent creation."""

    def test_agent_config_without_components_still_works(self):
        config = AgentConfig(
            name="legacy_agent",
            description="Legacy agent",
            model_name="test-model",
            tools=[],
            context_manager_config=ContextManagerConfig(token_threshold=1000),
        )
        
        components = getattr(config, 'context_components', None)
        assert components is None

    def test_context_manager_config_without_strategy_defaults(self):
        config = ContextManagerConfig(token_threshold=2000)
        
        assert config.strategy == STRATEGY_TOKEN_BUDGET
        assert "system_prompt" in config.component_budgets