# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise the compatibility request's ownership and metadata preparation policies."""

from types import SimpleNamespace

import pytest

from contracts.agent import AgentRequest, WorkbenchSessionConfig
from contracts.constants.constants import DEFAULT_EN_TITLE, DEFAULT_ZH_TITLE, MAX_RUNTIME_METADATA_BYTES
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException, ConversationNotFoundError, ForbiddenError, RuntimeMetadataVersionConflict
from contracts.knowledge import ResolvedKnowledgeScope
from contracts.tool import ToolParamsRequest
from management.services.agent import conversation_preparation as preparation, workbench
from management.services.knowledge_base import scope as knowledge
from management.services.model import run_controls

WORKBENCH = WorkbenchSessionConfig(mode="generic_chat")


@pytest.fixture
def stores(mocker):
    mocker.patch.object(preparation, "ENABLE_AGENT_WORKBENCH", True)
    mocker.patch.object(run_controls, "validate_agent_model_selection")
    mocker.patch.object(run_controls, "preflight_agent_turn_controls")
    services = {
        name: mocker.patch.object(preparation, name)
        for name in (
            "get_conversation_service", "create_new_conversation", "update_conversation_chat_mode_service",
            "update_conversation_agent_id_service", "update_conversation_knowledge_scope_service",
            "resolve_conversation_runtime_metadata", "update_conversation_workbench_and_metadata_service",
            "update_conversation_workbench_config_service", "apply_workbench_runtime_plan",
            "search_agent_info_by_agent_id",
        )
    }
    services["search_agent_info_by_agent_id"].return_value = {"allow_chat_metadata": True}
    services["create_new_conversation"].return_value = {"conversation_id": 42}

    async def inline(_label, callback, *args, lane, owner, **kwargs):
        assert lane == "control-io"
        return callback(*args, **kwargs)

    mocker.patch.object(preparation, "run_blocking", side_effect=inline)
    return SimpleNamespace(**services)


@pytest.mark.parametrize("language,title", [("en", DEFAULT_EN_TITLE), ("zh", DEFAULT_ZH_TITLE)])
async def test_new_conversation_persists_requested_metadata(stores, language, title):
    request = AgentRequest(query="question", agent_id=7, enable_plan=True, metadata={"purpose": "draft"})
    result = await preparation.prepare_conversation_request(request, "actor", "tenant", language, "UTC")
    assert (result.created, result.workbench, result.knowledge) == (True, None, None)
    assert request.conversation_id == 42
    assert request._runtime_metadata_snapshot == {"purpose": "draft"}
    assert request._runtime_metadata_version == 1
    stores.create_new_conversation.assert_called_once_with(
        title=title, user_id="actor", agent_id=7, chat_mode="planning", runtime_metadata={"purpose": "draft"},
    )
    stores.update_conversation_chat_mode_service.assert_not_called()


async def test_debug_metadata_stays_request_owned(stores):
    request = AgentRequest(query="question", agent_id=7, is_debug=True, metadata={"purpose": "debug"})
    result = await preparation.prepare_conversation_request(request, "actor", "tenant", "en", None)
    assert result.created is False
    assert request._debug_run_id.startswith("debug-")
    assert request._runtime_metadata_snapshot == {"purpose": "debug"}
    assert request._runtime_metadata_version is None
    stores.create_new_conversation.assert_not_called()
    stores.resolve_conversation_runtime_metadata.assert_not_called()


@pytest.mark.parametrize("state,entrypoint,disabled,error", [
    (None, None, False, ForbiddenError),
    ({"workbench_config": {"mode": "generic_chat"}}, None, False, ForbiddenError),
    ({"workbench_config": {"mode": "generic_chat"}}, None, True, preparation.WorkbenchError),
    ({}, "workbench", True, preparation.WorkbenchError),
])
async def test_foreign_or_unavailable_conversations_never_write(stores, monkeypatch, state, entrypoint, disabled, error):
    monkeypatch.setattr(preparation, "ENABLE_AGENT_WORKBENCH", not disabled)
    stores.get_conversation_service.return_value = state
    request = AgentRequest(query="question", agent_id=7, conversation_id=42, entrypoint=entrypoint)
    with pytest.raises(error):
        await preparation.prepare_conversation_request(request, "actor", "tenant", "en", None)
    stores.update_conversation_chat_mode_service.assert_not_called()
    stores.resolve_conversation_runtime_metadata.assert_not_called()


@pytest.mark.parametrize("metadata,code", [
    ({"blob": "x" * MAX_RUNTIME_METADATA_BYTES}, ErrorCode.CHAT_METADATA_TOO_LARGE),
    ({"score": float("inf")}, ErrorCode.CHAT_METADATA_INVALID),
    ({"purpose": "draft"}, ErrorCode.CHAT_METADATA_NOT_ALLOWED),
])
async def test_rejected_metadata_never_reaches_conversation_store(stores, metadata, code):
    stores.search_agent_info_by_agent_id.return_value = {}
    request = AgentRequest(query="question", agent_id=7, metadata=metadata)
    with pytest.raises(AppException) as exc:
        await preparation.prepare_conversation_request(request, "actor", "tenant", "en", None)
    assert exc.value.error_code == code
    stores.create_new_conversation.assert_not_called()


@pytest.mark.parametrize("failure,code", [
    (None, None),
    (ConversationNotFoundError("gone"), ErrorCode.CHAT_CONVERSATION_NOT_FOUND),
    (RuntimeMetadataVersionConflict(5), ErrorCode.CHAT_METADATA_VERSION_CONFLICT),
])
async def test_native_metadata_update_uses_the_owned_conversation_revision(stores, failure, code):
    stores.get_conversation_service.return_value = {"runtime_metadata": {"old": True}, "runtime_metadata_version": 4}
    resolve = stores.resolve_conversation_runtime_metadata
    resolve.return_value = {"runtime_metadata": {}, "runtime_metadata_version": 5}
    resolve.side_effect = failure
    request = AgentRequest(query="question", agent_id=7, conversation_id=42, metadata={}, expected_metadata_version=4)
    if failure is not None:
        with pytest.raises(AppException) as exc:
            await preparation.prepare_conversation_request(request, "actor", "tenant", "en", None)
        assert exc.value.error_code == code
        stores.update_conversation_chat_mode_service.assert_not_called()
    else:
        await preparation.prepare_conversation_request(request, "actor", "tenant", "en", None)
        assert request._runtime_metadata_snapshot == {}
        assert request._runtime_metadata_version == 5
        stores.update_conversation_agent_id_service.assert_called_once_with(
            conversation_id=42, agent_id=7, user_id="actor",
        )
    resolve.assert_called_once_with(
        conversation_id=42, user_id="actor", request_metadata={}, update_requested=True, expected_version=4,
    )


@pytest.mark.parametrize("source", ["request", "stored"])
async def test_native_knowledge_freezes_owned_tree_before_forwarding(stores, mocker, source):
    desired = {"local": {"mode": "disabled"}}
    stores.get_conversation_service.return_value = {
        "runtime_metadata_version": 4, "runtime_metadata": {"existing": True},
        "knowledge_scope": desired if source == "stored" else None,
    }
    version = mocker.patch.object(knowledge, "resolve_root_version", return_value=2)
    tree = [{"agent_id": 7, "version_no": 2, "tools": []}]
    freeze = mocker.patch.object(knowledge, "snapshot_runtime_knowledge_tree", return_value=tree)
    resolved = ResolvedKnowledgeScope(desired_scope=desired, tool_params=ToolParamsRequest(), local_disabled=True)
    resolve = mocker.patch.object(preparation, "resolve_knowledge_scope", return_value=resolved)
    request = AgentRequest(
        query="question", agent_id=7, conversation_id=42, knowledge_scope=desired if source == "request" else None,
    )

    result = await preparation.prepare_conversation_request(request, "actor", "tenant", "en", None, export_resources=True)

    version.assert_called_once_with(7, "tenant", None, False)
    freeze.assert_called_once_with(7, "tenant", 2)
    assert resolve.call_args.kwargs["runtime_agent_tree"] == tree
    assert resolve.call_args.kwargs["scope"].local.mode == "disabled"
    assert (result.knowledge, result.knowledge_tree) == (resolved, tuple(tree))
    assert request._runtime_metadata_snapshot == {"existing": True}
    assert request._runtime_metadata_version == 4
    if source == "request":
        stores.update_conversation_knowledge_scope_service.assert_called_once_with(
            conversation_id=42, knowledge_scope=desired, user_id="actor", tenant_id="tenant",
        )
    else:
        stores.update_conversation_knowledge_scope_service.assert_not_called()


@pytest.mark.parametrize("mode", ["new", "configuration", "metadata", "stale", "race"])
async def test_workbench_metadata_and_configuration_use_one_version_boundary(stores, mocker, mode):
    stores.get_conversation_service.return_value = {
        "workbench_config": WORKBENCH.model_dump(mode="json"), "workbench_config_version": 3,
        "runtime_metadata": {"existing": True}, "runtime_metadata_version": 4,
    }
    resolver = mocker.patch.object(workbench, "resolve_workbench_config", return_value=(WORKBENCH, object()))
    joint = stores.update_conversation_workbench_and_metadata_service
    joint.return_value = {"workbench_config_version": 4, "runtime_metadata": {}, "runtime_metadata_version": 5}
    configuration = stores.update_conversation_workbench_config_service
    configuration.return_value = {"workbench_config_version": 4}
    if mode == "race":
        joint.side_effect = RuntimeMetadataVersionConflict(5)
    request = AgentRequest(
        query="question", agent_id=7, entrypoint="workbench", workbench=WORKBENCH if mode == "new" else None,
        conversation_id=None if mode == "new" else 42, expected_workbench_config_version=3,
        metadata={} if mode in {"metadata", "stale", "race"} else None,
        expected_metadata_version=3 if mode == "stale" else 4,
    )
    if mode in {"stale", "race"}:
        with pytest.raises(AppException) as exc:
            await preparation.prepare_conversation_request(request, "actor", "tenant", "en", None)
        assert exc.value.error_code == ErrorCode.CHAT_METADATA_VERSION_CONFLICT
        assert resolver.call_count == (mode == "race")
        assert joint.call_count == (mode == "race")
        configuration.assert_not_called()
        return

    result = await preparation.prepare_conversation_request(request, "actor", "tenant", "en", None)
    assert result.created == (mode == "new")
    assert result.workbench == WORKBENCH
    resolver.assert_called_once_with(WORKBENCH, tenant_id="tenant", is_debug=False, user_id="actor")
    stores.update_conversation_agent_id_service.assert_not_called()
    if mode == "metadata":
        joint.assert_called_once_with(
            conversation_id=42, user_id="actor", config=WORKBENCH.model_dump(mode="json"),
            expected_config_version=3, metadata={}, expected_metadata_version=4,
        )
        assert request._runtime_metadata_version == 5
        configuration.assert_not_called()
    elif mode == "configuration":
        configuration.assert_called_once_with(
            conversation_id=42, user_id="actor", config=WORKBENCH.model_dump(mode="json"),
            expected_version=3, only_if_changed=True,
        )
        joint.assert_not_called()
    else:
        assert stores.create_new_conversation.call_args.kwargs["workbench_config"] == WORKBENCH.model_dump(mode="json")
