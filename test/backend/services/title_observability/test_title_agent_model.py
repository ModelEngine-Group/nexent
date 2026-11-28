# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Title generation must reuse the conversation agent's bound model.

Regression tests for the issue where web chats with an agent bound to a
non-default model still sent one title request to the tenant default LLM.
"""

import pytest
from contracts.errors.exceptions import AgentNotFoundError
from pytest_mock import MockerFixture

pytestmark = pytest.mark.asyncio


async def test_title_uses_agent_bound_model_when_no_explicit_model(service, mocker: MockerFixture):
    mocker.patch.object(service, "get_conversation", return_value={
        "conversation_title": "New Conversation", "title_version": 0, "agent_id": 7,
    })
    mocker.patch("management.db.agent.version.query_current_version_no", return_value=3)
    agent_lookup = mocker.patch(
        "management.db.agent.repository.search_agent_info_by_agent_id", return_value={"model_ids": [42]})
    mocker.patch("management.services.model.resolver.is_model_available", return_value=True)
    mocker.patch.object(service, "get_model_by_model_id", return_value={"model_id": 1})
    run = mocker.patch.object(service, "call_llm_for_title", new=mocker.AsyncMock(return_value="T"))
    mocker.patch.object(service, "rename_conversation", return_value=True)

    title = await service.generate_conversation_title_service(
        1, "question", "user", tenant_id="tenant")

    assert title == "T"
    agent_lookup.assert_called_once_with(7, "tenant", 3)
    assert run.await_args.args[3] == 42


async def test_title_falls_back_to_draft_version_without_published(service, mocker: MockerFixture):
    mocker.patch.object(service, "get_conversation", return_value={
        "conversation_title": "New Conversation", "title_version": 0, "agent_id": 7,
    })
    mocker.patch("management.db.agent.version.query_current_version_no", return_value=None)
    agent_lookup = mocker.patch(
        "management.db.agent.repository.search_agent_info_by_agent_id", return_value={"model_ids": [5]})
    mocker.patch("management.services.model.resolver.is_model_available", return_value=True)
    mocker.patch.object(service, "get_model_by_model_id", return_value={"model_id": 1})
    run = mocker.patch.object(service, "call_llm_for_title", new=mocker.AsyncMock(return_value="T"))
    mocker.patch.object(service, "rename_conversation", return_value=True)

    await service.generate_conversation_title_service(1, "question", "user", tenant_id="tenant")

    agent_lookup.assert_called_once_with(7, "tenant", 0)
    assert run.await_args.args[3] == 5


async def test_title_falls_back_to_tenant_default_without_agent(service, mocker: MockerFixture):
    mocker.patch.object(service, "get_conversation", return_value={
        "conversation_title": "New Conversation", "title_version": 0,
    })
    agent_lookup = mocker.patch("management.db.agent.repository.search_agent_info_by_agent_id")
    run = mocker.patch.object(service, "call_llm_for_title", new=mocker.AsyncMock(return_value="T"))
    mocker.patch.object(service, "rename_conversation", return_value=True)

    await service.generate_conversation_title_service(1, "question", "user", tenant_id="tenant")

    agent_lookup.assert_not_called()
    assert run.await_args.args[3] is None


async def test_title_falls_back_to_tenant_default_when_agent_lookup_fails(service, mocker: MockerFixture):
    mocker.patch.object(service, "get_conversation", return_value={
        "conversation_title": "New Conversation", "title_version": 0, "agent_id": 9,
    })
    mocker.patch("management.db.agent.version.query_current_version_no", return_value=None)
    mocker.patch(
        "management.db.agent.repository.search_agent_info_by_agent_id", side_effect=AgentNotFoundError("agent not found"))
    run = mocker.patch.object(service, "call_llm_for_title", new=mocker.AsyncMock(return_value="T"))
    mocker.patch.object(service, "rename_conversation", return_value=True)

    await service.generate_conversation_title_service(1, "question", "user", tenant_id="tenant")

    assert run.await_args.args[3] is None


async def test_title_falls_back_to_tenant_default_when_agent_binds_no_model(service, mocker: MockerFixture):
    mocker.patch.object(service, "get_conversation", return_value={
        "conversation_title": "New Conversation", "title_version": 0, "agent_id": 7,
    })
    mocker.patch("management.db.agent.version.query_current_version_no", return_value=None)
    mocker.patch(
        "management.db.agent.repository.search_agent_info_by_agent_id", return_value={"model_ids": []})
    run = mocker.patch.object(service, "call_llm_for_title", new=mocker.AsyncMock(return_value="T"))
    mocker.patch.object(service, "rename_conversation", return_value=True)

    await service.generate_conversation_title_service(1, "question", "user", tenant_id="tenant")

    assert run.await_args.args[3] is None


async def test_explicit_model_id_still_wins(service, mocker: MockerFixture):
    mocker.patch.object(service, "get_conversation", return_value={
        "conversation_title": "New Conversation", "title_version": 0, "agent_id": 7,
    })
    agent_lookup = mocker.patch("management.db.agent.repository.search_agent_info_by_agent_id")
    run = mocker.patch.object(service, "call_llm_for_title", new=mocker.AsyncMock(return_value="T"))
    mocker.patch.object(service, "rename_conversation", return_value=True)

    await service.generate_conversation_title_service(
        1, "question", "user", tenant_id="tenant", model_id=9)

    agent_lookup.assert_not_called()
    assert run.await_args.args[3] == 9
