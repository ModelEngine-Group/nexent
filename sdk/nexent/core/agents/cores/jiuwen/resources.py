# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Expose authorized Jiuwen abilities to the existing controlled Python executor."""

import asyncio
from concurrent.futures import CancelledError
from copy import deepcopy
from uuid import uuid4

from jsonschema import validate

from nexent.core.concurrency.cancellation import RunTerminated


class JiuwenResourceBridge:
    """Share native execution entries without creating a second resource dispatcher.

    Python executes in the managed sandbox lane. Resource coroutines return to
    their owning run loop and retain the existing model-tool-io/MCP ownership.
    No resource worker waits for another worker in its own bounded lane.
    """

    def __init__(self, agent, loop, scope, visible_names, session_id=None):
        self.agent, self.loop, self.scope = agent, loop, scope
        self.visible_names = frozenset(visible_names)
        self.session_id = session_id

    def bindings(self):
        from openjiuwen.core.runner import Runner
        from openjiuwen.core.single_agent import AgentCard

        result = {}
        for card in self.agent.ability_manager.list():
            if card.name not in self.visible_names:
                continue
            if isinstance(card, AgentCard):
                invoke = self._agent_invocation(card.id)
            else:
                tool = Runner.resource_mgr.get_tool(card.id)
                if tool is None:
                    raise RuntimeError("Authorized resource is unavailable")
                invoke = tool.invoke
            result[card.name] = self._binding(invoke, deepcopy(card.input_params))
        return result

    def _agent_invocation(self, card_id):
        from openjiuwen.core.runner import Runner

        from nexent.core.agents.cores.jiuwen.collaboration import collaboration_dispatch

        async def invoke(arguments):
            child_session = f"{self.session_id}:{uuid4().hex}"
            try:
                # This call comes from an authorized Python binding, outside a model tool batch.
                with collaboration_dispatch(child_session, None):
                    return await Runner.run_agent(card_id, arguments, session=child_session)
            finally:
                await Runner.release(child_session)

        return invoke

    def _binding(self, target, schema):
        names = list(schema.get("properties", {}))

        def call(*args, **arguments):
            if self.scope.cancelled:
                raise RunTerminated()
            if len(args) > len(names) or any(key in arguments for key in names[:len(args)]):
                raise ValueError("Invalid positional resource arguments")
            arguments = {**dict(zip(names, args)), **arguments}
            validate(arguments, schema)
            # Identity and other undeclared host arguments cannot enter through code kwargs.
            if set(arguments) - set(names) and schema.get("additionalProperties") is not True:
                raise ValueError("Undeclared resource arguments")

            async def invoke():
                if self.scope.cancelled:
                    raise asyncio.CancelledError()
                return await target(arguments)

            coroutine = invoke()
            try:
                future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
            except BaseException:
                coroutine.close()
                raise
            token = self.scope.register_closer(future.cancel)
            try:
                return future.result()
            except CancelledError:
                raise RunTerminated() from None
            finally:
                self.scope.unregister_closer(token)

        call._nexent_execute_on_host = True
        return call
