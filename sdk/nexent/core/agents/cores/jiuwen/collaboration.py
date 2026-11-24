# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Bind Nexent-owned collaborators to Jiuwen's AgentCard dispatch."""

from jsonschema import validate
from openjiuwen.core.foundation.tool import ToolCard
from openjiuwen.core.runner import Runner
from openjiuwen.core.single_agent import AgentCard, BaseAgent
from openjiuwen.core.single_agent.ability_manager import AbilityManager
from openjiuwen.harness.deep_agent import DeepAgent
from openjiuwen.harness.factory import apply_deep_agent_parts, resolve_deep_agent_parts


class _CollaborationAbilityManager(AbilityManager):
    def __init__(self, owner_id):
        super().__init__(owner_id=owner_id)
        self.collaborators = {}

    def add_collaborator(self, agent, *, parallel_safe):
        card = agent.card
        if self.get(card.name) is not None:
            raise ValueError(f"Duplicate Jiuwen ability name: {card.name}")
        registered = Runner.resource_mgr.add_agent(card, lambda: agent)
        if registered.is_err():
            raise registered.msg()
        self.collaborators[card.name] = ToolCard(name=card.name, parallel_safe=parallel_safe)
        self.add(card)

    async def _execute_parallel_tool_tasks(self, tool_calls, tasks, tool_cards=None, *, on_task_started=None):
        # Jiuwen 0.1.19 reads concurrency policy from ToolCards only. Supply
        # the AgentCards' policy here while leaving dispatch and barriers native.
        return await super()._execute_parallel_tool_tasks(
            tool_calls, tasks, {**(tool_cards or {}), **self.collaborators}, on_task_started=on_task_started,
        )

    async def _execute_single_tool_call(self, tool_call, session, tag=None, callback_context=None):
        if tool_call.name not in self.collaborators:
            return await super()._execute_single_tool_call(tool_call, session, tag, callback_context)
        # The native agent-as-tool branch assigns this scoped session before
        # Runner.invoke. Release it after Runner has finished its post-run work.
        session_id = f"{session.get_session_id()}:{tool_call.id}"
        try:
            return await super()._execute_single_tool_call(tool_call, session, tag, callback_context)
        finally:
            await Runner.release(session_id)


class CollaborationAgent(BaseAgent):
    """A native delegate whose body stays under Nexent's execution policy."""

    def __init__(self, card, parent_session, execute):
        super().__init__(card)
        self.parent_session = parent_session
        self.execute = execute

    def configure(self, config):
        self._config = config
        return self

    async def invoke(self, inputs, session=None):
        if session is None or not session.get_session_id().startswith(f"{self.parent_session}:"):
            raise PermissionError("Jiuwen collaborator is not owned by this session")
        arguments = {key: value for key, value in inputs.items() if key != "conversation_id"}
        validate(arguments, self.card.input_params)
        return await self.execute(**arguments)

    async def stream(self, inputs, session=None, stream_modes=None):
        yield await self.invoke(inputs, session=session)


def create_collaboration_host(model, **settings):
    parts = resolve_deep_agent_parts(model, **settings)
    agent = DeepAgent(parts.config.card)
    agent.ability_manager = _CollaborationAbilityManager(parts.config.card.id)
    apply_deep_agent_parts(agent, parts)
    return agent


def remove_run_abilities(agent):
    for card in agent.ability_manager.list():
        if isinstance(card, AgentCard):
            Runner.resource_mgr.remove_agent(card.id)
        elif isinstance(card, ToolCard):
            Runner.resource_mgr.remove_tool(card.id)
        else:
            continue
        agent.ability_manager.remove(card.name)
