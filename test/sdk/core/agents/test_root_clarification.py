# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Root-only clarification is shared by factory and legacy Core boundaries."""

import asyncio
import json
from threading import Event
from unittest.mock import MagicMock, patch

import pytest

from nexent.core.agents.contracts.config import AgentConfig
from nexent.core.agents.contracts.identity import root_clarification_allowed, run_identity_scope
from nexent.core.agents.contracts.run import AgentRunInfo
from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter
from nexent.core.agents.orchestration.children import child_run_info
from nexent.core.agents.orchestration.execution import execute_adapter
from nexent.core.agents.prompt.clarification import child_information_policy
from nexent.core.agents.prompt.policies import common_behavior_guidance
from nexent.core.concurrency import RunCancellationScope
from nexent.core.utils.observer import MessageObserver, ProcessType
from test.sdk.core.agents.test_nexent_agent_context_runtime_factory import _factory


@pytest.fixture
def root():
    return AgentRunInfo(
        query="task",
        model_config_list=[],
        observer=MessageObserver(),
        stop_event=Event(),
        agent_config=AgentConfig(name="root", description="Root", model_name="model", tools=[]),
    )


def child_of(parent):
    return child_run_info(parent, parent.agent_config, RunCancellationScope(Event()))


def test_factory_children_have_explicit_non_promotable_identity(root):
    child = child_of(root)
    assert getattr(root, "run_role", None) == "root"
    assert getattr(child, "run_role", None) == "subagent"
    assert child_of(child).run_role == "subagent"
    assert child.observer is root.observer


def test_jiuwen_child_does_not_advertise_clarification(root):
    assert JiuwenAdapter(root).clarification is not None
    assert JiuwenAdapter(child_of(root)).clarification is None


def test_internal_identity_is_not_serialized_and_invalid_role_is_rejected(root):
    assert "run_role" not in root.model_dump()
    with pytest.raises(ValueError):
        with run_identity_scope("model_supplied_role"):
            pass


def test_nested_scope_cannot_promote_child_and_restores_after_error(root):
    with pytest.raises(RuntimeError):
        with run_identity_scope("subagent"):
            with run_identity_scope("root"):
                assert not root_clarification_allowed(root)
                assert JiuwenAdapter(root).clarification is None
                raise RuntimeError("controlled")
    assert root_clarification_allowed(root)


@pytest.mark.parametrize("failure", [False, True])
def test_factory_lifetime_uses_the_child_identity_and_always_restores_it(root, mocker, failure):
    observed = []
    adapter = MagicMock()

    def run():
        observed.append(root_clarification_allowed())
        if failure:
            raise RuntimeError("controlled")
        return "Missing birth date"

    adapter.run.side_effect = run
    adapter.close.side_effect = lambda: observed.append(root_clarification_allowed())
    mocker.patch("nexent.core.agents.factory.AgentCoreFactory.create", return_value=adapter)
    if failure:
        with pytest.raises(RuntimeError):
            execute_adapter(child_of(root))
    else:
        assert execute_adapter(child_of(root)) == "Missing birth date"
    assert observed == [False, False]
    assert root_clarification_allowed()


@pytest.mark.parametrize("child,legacy", [(False, False), (True, False), (False, True)])
def test_smolagents_factory_shares_identity_policy_without_changing_other_context(root, child, legacy):
    from nexent.core.agents.context import ContextItemInput

    factory = _factory()
    factory._core_run_info = child_of(root) if child else root
    config = root.agent_config.model_copy(
        update={
            "context_items": [
                ContextItemInput(id="system:business", type="system", content={"text": "Business policy"})
            ]
        }
    )
    with (
        patch.object(factory, "create_model", return_value=MagicMock()),
        patch("nexent.core.agents.cores.smolagents.agent.CoreAgent") as core,
    ):
        factory.create_single_agent(config, _managed_context=legacy)
    kwargs = core.call_args.kwargs
    assert kwargs["enable_clarification"] is (not child and not legacy)
    instructions = " ".join(item.content.get("text", "") for item in kwargs["context_runtime"].items)
    assert (child_information_policy(factory.observer.lang) in instructions) is (child or legacy)
    assert "Business policy" in instructions


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_child_missing_information_guidance_is_shared_and_root_prompt_stays_unchanged(lang):
    assert child_information_policy(lang) not in common_behavior_guidance(lang)
    with run_identity_scope("subagent"):
        assert child_information_policy(lang) in common_behavior_guidance(lang)


def test_child_discards_stale_platform_clarification_instructions():
    from nexent.core.agents.context import ContextItemInput
    from nexent.core.agents.prompt.policies import with_common_behavior

    saved = [
        ContextItemInput(id="system:clarification_protocol", type="system", content={"text": "Call ask_user directly"})
    ]
    assert any(item.id == saved[0].id for item in with_common_behavior(saved))
    assert all(item.id != saved[0].id for item in with_common_behavior(saved, is_subagent=True))
    assert saved[0].content["text"] == "Call ask_user directly"


def test_legacy_subagent_observer_scope_blocks_forms_but_allows_missing_information(root):
    observer = root.observer
    observer.add_subagent_start(agent_id="child", agent_name="child", task="task", invocation_id="call")
    try:
        observer.add_message("child", ProcessType.HUMAN_INTERACTION, '{"questions":[]}')
        observer.add_message("child", ProcessType.EXECUTION_LOGS, "Missing birth date")
    finally:
        observer.add_subagent_end(agent_id="child", agent_name="child", invocation_id="call")
    observer.add_message("root", ProcessType.HUMAN_INTERACTION, '{"questions":[]}')
    events = [json.loads(event) for event in observer.get_cached_message()]
    cards = [event for event in events if event["type"] == "human_interaction"]
    assert len(cards) == 1 and not cards[0].get("invocation_id")
    assert any(event["content"] == "Missing birth date" for event in events)


@pytest.mark.asyncio
async def test_parallel_root_and_child_permissions_do_not_interfere(root):
    async def emit(role):
        with run_identity_scope(role):
            await asyncio.sleep(0)
            root.observer.add_message(role, ProcessType.HUMAN_INTERACTION, '{"questions":[]}')
            return root_clarification_allowed()

    assert await asyncio.gather(emit("root"), emit("subagent")) == [True, False]
    events = [json.loads(event) for event in root.observer.get_cached_message()]
    assert len(events) == 1 and events[0]["type"] == "human_interaction"
