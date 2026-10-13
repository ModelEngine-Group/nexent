"""SAI-D1 contracts for isolated invocation factories and ownership."""
import asyncio
from types import SimpleNamespace

import pytest
from nexent.core.agents import nexent_agent as factory_module
from nexent.core.agents.agent_model import AgentConfig
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.concurrency import LanePolicy, ThreadManager
from nexent.core.concurrency.cancellation import RunCancellationScope
from nexent.core.concurrency.context import (
    _reset_current_thread_manager,
    _set_current_thread_manager,
)
from nexent.core.utils.observer import MessageObserver

ORIGINAL_SANDBOX_CLEANUP = NexentAgent._cleanup_sandbox
ORIGINAL_WORKSPACE_INITIALIZE = NexentAgent._initialize_sandbox_workspaces


@pytest.fixture
def setup_factory(monkeypatch):
    instances, cleaned, initialized = [], [], []

    class FakeCore:
        def __init__(self, **kwargs):
            self.name = kwargs['name']
            self.model = kwargs['model']
            self.state = {}
            self.tools = {}
            self.managed_agents = {a.name: a for a in kwargs['managed_agents']}
            self.enable_planning = False
            self.python_executor = object()
            instances.append(self)

        def __call__(self, task, **kwargs):
            if getattr(self.model, 'barrier', None):
                self.model.barrier.wait(timeout=5)
            if task == 'FAIL':
                raise ValueError('controlled task failure')
            if task == 'WAIT':
                self.model.started.set()
                assert self.stop_event.wait(5)
            return {'task': task, 'agent': self, 'model': self.model, 'metadata': self.state.get('metadata')}

    monkeypatch.setattr(factory_module, 'CoreAgent', FakeCore)
    monkeypatch.setattr(NexentAgent, 'create_model', lambda self, name: SimpleNamespace())
    monkeypatch.setattr(NexentAgent, '_cleanup_sandbox', lambda self: cleaned.append(self))
    monkeypatch.setattr(NexentAgent, '_initialize_sandbox_workspaces', lambda self: initialized.append(self))
    monkeypatch.setattr(NexentAgent, '_pull_file_workspace_from_sandbox', lambda self: None)
    scope = RunCancellationScope()
    factory = NexentAgent(MessageObserver(), [], scope.stop_event, cancellation_scope=scope)
    config = AgentConfig(name='parent', description='Parent', model_name='test', tools=[], worker_agents=[
        AgentConfig(name='child', description='Child', model_name='test', tools=[], worker_agents=[
            AgentConfig(name='grandchild', description='Grandchild', model_name='test', tools=[]),
        ]),
    ])
    root = factory.create_single_agent(config)
    factory.set_agent(root)
    return factory, root.managed_agents['child'], instances, cleaned, initialized


@pytest.fixture
def manager():
    value = ThreadManager('sai-d1', {'model-tool-io': LanePolicy('model-tool-io', 2, 4)})
    value.start()
    token = _set_current_thread_manager(value)
    yield value
    _reset_current_thread_manager(token)
    asyncio.run(value.shutdown(timeout=5))
