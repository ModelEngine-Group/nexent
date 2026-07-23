"""Focused tests for the unified NL2AGENT action dispatcher."""

from copy import deepcopy
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import TypeAdapter, ValidationError

from consts.exceptions import ForbiddenError, Nl2AgentWorkflowConflictError
from consts.model import Nl2AgentActionContext, Nl2AgentActionRequest
from services.nl2agent_action_service import (
    Nl2AgentActionDependencies,
    _fingerprint_action,
    dispatch_nl2agent_action,
    validate_nl2agent_action_context,
)


ACTION_ID = "2f8567b1-7080-4d7e-9f57-fac9db39cd20"
ACTION_ADAPTER = TypeAdapter(Nl2AgentActionRequest)


def _workflow_state():
    return {
        "revision": 18,
        "recommendations": {
            "local-batch": {
                "resource_type": "local",
                "status": "searched",
                "tool_ids": [1],
                "skill_ids": [2],
            },
            "mcp-batch": {
                "resource_type": "mcp",
                "status": "searched",
                "item_keys": ["registry:github"],
            },
            "skill-batch": {
                "resource_type": "skill",
                "status": "searched",
                "item_keys": ["skill:12"],
            },
        },
        "mcp_workflows": {
            "registry:github": {"mcp_id": 5, "status": "connected"},
        },
    }


def _session(*, revision=18, status="active"):
    return {
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "draft_agent_id": 202,
        "conversation_id": 902,
        "status": status,
        "workflow_revision": revision,
        "workflow_state": _workflow_state(),
    }


def _request(action: str, payload: dict, **overrides):
    return ACTION_ADAPTER.validate_python(
        {
            "action_id": ACTION_ID,
            "action": action,
            "expected_revision": 18,
            "display_text": f"Applied {action}",
            "payload": payload,
            **overrides,
        }
    )


def _dependencies(*, allowed_actions=None, existing=None):
    allowed = allowed_actions or [
        "render_requirements_summary",
        "confirm_requirements",
        "select_models",
        "apply_local_resources",
        "skip_local_resources",
        "configure_online_resources",
        "complete_online_configuration",
        "save_identity",
        "publish_agent",
    ]
    get_session = MagicMock(side_effect=[_session(), _session(revision=19)])
    get_action_message = MagicMock(return_value=existing)
    claim_action_message = MagicMock(
        return_value=(
            {
                "message_id": 77,
                "message_metadata": {"action_status": "pending"},
            },
            True,
        )
    )
    async_result = AsyncMock(return_value={"ok": True, "chat_injection_text": "hidden"})
    return Nl2AgentActionDependencies(
        get_session=get_session,
        get_action_message=get_action_message,
        claim_action_message=claim_action_message,
        update_action_message=MagicMock(return_value=True),
        summarize_workflow_state=MagicMock(
            return_value={
                "current_stage": "revision_routing",
                "allowed_actions": allowed,
            }
        ),
        get_session_catalogs=MagicMock(
            return_value={
                "official_skills": [
                    {"skill_id": 12, "skill_name": "code-review"}
                ]
            }
        ),
        confirm_requirements=MagicMock(
            return_value={"status": "confirmed", "fingerprint": "a" * 64}
        ),
        save_model_selection=async_result,
        apply_local_resources=async_result,
        skip_local_resources=async_result,
        install_mcp=async_result,
        bind_mcp_tools=async_result,
        skip_mcp_tools=async_result,
        install_web_skill=async_result,
        complete_online_configuration=async_result,
        save_identity=async_result,
        finalize=async_result,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "payload"),
    [
        (
            "confirm_requirements",
            {
                "summary": {
                    "goal": "Build an agent",
                    "audience_or_scenario": "Operators",
                    "primary_input": "Requests",
                    "expected_output": "Actions",
                    "key_constraints": "Use trusted resources",
                }
            },
        ),
        ("save_model_selection", {"primary_model_id": 7, "fallback_model_ids": [8]}),
        (
            "apply_local_resources",
            {
                "recommendation_batch_id": "local-batch",
                "tool_ids": [1],
                "skill_ids": [2],
                "tool_config_values": {},
            },
        ),
        ("skip_local_resources", {"recommendation_batch_id": "local-batch"}),
        (
            "install_mcp",
            {
                "recommendation_batch_id": "mcp-batch",
                "recommendation_id": "registry:github",
                "option_id": "remote-0",
                "config_values": {},
            },
        ),
        ("bind_mcp_tools", {"recommendation_id": "registry:github", "tool_ids": [11]}),
        ("skip_mcp_tools", {"recommendation_id": "registry:github"}),
        (
            "install_web_skill",
            {
                "recommendation_batch_id": "skill-batch",
                "item_key": "skill:12",
                "config_values": {},
            },
        ),
        ("complete_online_configuration", {}),
        ("save_identity", {"display_name": "Research Agent"}),
        (
            "finalize",
            {
                "business_description": "Build an agent",
                "duty_prompt": "Help the user",
                "greeting_message": "Hello",
            },
        ),
    ],
)
async def test_each_action_dispatches_successfully(action, payload):
    dependencies = _dependencies()

    response = await dispatch_nl2agent_action(
        dependencies,
        draft_agent_id=202,
        request=_request(action, payload),
        tenant_id="tenant-1",
        user_id="user-1",
        locale="en",
    )

    assert response["status"] == "applied"
    assert response["workflow_revision"] == 19
    assert "chat_injection_text" not in response["result"]
    dependencies.claim_action_message.assert_called_once()
    dependencies.update_action_message.assert_called_once()


@pytest.mark.asyncio
async def test_expected_revision_conflict_does_not_claim_action():
    dependencies = _dependencies()
    request = _request("save_identity", {"display_name": "Agent"}, expected_revision=17)

    with pytest.raises(Nl2AgentWorkflowConflictError, match="revision changed"):
        await dispatch_nl2agent_action(
            dependencies,
            draft_agent_id=202,
            request=request,
            tenant_id="tenant-1",
            user_id="user-1",
            locale="en",
        )

    dependencies.claim_action_message.assert_not_called()


@pytest.mark.asyncio
async def test_illegal_stage_does_not_claim_action():
    dependencies = _dependencies(allowed_actions=["clarify_requirements"])

    with pytest.raises(Nl2AgentWorkflowConflictError, match="not allowed"):
        await dispatch_nl2agent_action(
            dependencies,
            draft_agent_id=202,
            request=_request("save_identity", {"display_name": "Agent"}),
            tenant_id="tenant-1",
            user_id="user-1",
            locale="en",
        )

    dependencies.claim_action_message.assert_not_called()


@pytest.mark.asyncio
async def test_same_action_id_and_fingerprint_replays_without_domain_effects():
    request = _request("save_identity", {"display_name": "Agent"})
    dependencies = _dependencies(
        existing={
            "message_metadata": {
                "action_fingerprint": _fingerprint_action(request),
                "action_status": "applied",
                "workflow_revision": 19,
                "action_result": {"display_name": "Agent"},
            }
        }
    )

    response = await dispatch_nl2agent_action(
        dependencies,
        draft_agent_id=202,
        request=request,
        tenant_id="tenant-1",
        user_id="user-1",
        locale="en",
    )

    assert response["status"] == "replayed"
    assert response["result"] == {"display_name": "Agent"}
    dependencies.claim_action_message.assert_not_called()
    dependencies.save_identity.assert_not_awaited()


@pytest.mark.asyncio
async def test_applied_action_replays_after_session_completion():
    request = _request(
        "finalize",
        {
            "business_description": "Build an agent",
            "duty_prompt": "Help the user",
            "greeting_message": "Hello",
        },
    )
    dependencies = replace(
        _dependencies(
            existing={
                "message_metadata": {
                    "action_fingerprint": _fingerprint_action(request),
                    "action_status": "applied",
                    "workflow_revision": 19,
                    "action_result": {"agent_id": 202},
                }
            }
        ),
        get_session=MagicMock(return_value=_session(revision=19, status="completed")),
    )

    response = await dispatch_nl2agent_action(
        dependencies,
        draft_agent_id=202,
        request=request,
        tenant_id="tenant-1",
        user_id="user-1",
        locale="en",
    )

    assert response == {
        "action_id": request.action_id,
        "action": "finalize",
        "status": "replayed",
        "workflow_revision": 19,
        "result": {"agent_id": 202},
    }
    dependencies.claim_action_message.assert_not_called()
    dependencies.finalize.assert_not_awaited()


@pytest.mark.asyncio
async def test_same_action_id_with_different_payload_is_rejected():
    original = _request("save_identity", {"display_name": "First"})
    dependencies = _dependencies(
        existing={
            "message_metadata": {
                "action_fingerprint": _fingerprint_action(original),
                "action_status": "applied",
            }
        }
    )

    with pytest.raises(Nl2AgentWorkflowConflictError, match="different"):
        await dispatch_nl2agent_action(
            dependencies,
            draft_agent_id=202,
            request=_request("save_identity", {"display_name": "Second"}),
            tenant_id="tenant-1",
            user_id="user-1",
            locale="en",
        )


@pytest.mark.asyncio
async def test_cross_tenant_or_owner_access_fails_closed():
    dependencies = replace(
        _dependencies(),
        get_session=MagicMock(return_value=None),
    )

    with pytest.raises(ForbiddenError):
        await dispatch_nl2agent_action(
            dependencies,
            draft_agent_id=202,
            request=_request("save_identity", {"display_name": "Agent"}),
            tenant_id="other-tenant",
            user_id="other-user",
            locale="en",
        )


def test_discriminated_payload_rejects_fields_for_another_action():
    with pytest.raises(ValidationError):
        _request("save_identity", {"primary_model_id": 7})


def test_action_context_must_match_applied_message_and_conversation():
    context = Nl2AgentActionContext(
        action_id=ACTION_ID,
        action="save_identity",
        display_text="Agent saved",
        workflow_revision=19,
    )
    get_session = MagicMock(return_value=_session(revision=19))
    get_message = MagicMock(
        return_value={
            "message_content": "Agent saved",
            "message_metadata": {
                "action": "save_identity",
                "action_status": "applied",
                "workflow_revision": 19,
            },
        }
    )

    prompt = validate_nl2agent_action_context(
        get_session=get_session,
        get_action_message=get_message,
        context=context,
        draft_agent_id=202,
        conversation_id=902,
        tenant_id="tenant-1",
        user_id="user-1",
    )

    assert '"type":"nl2agent_action_context"' in prompt
    assert "AUTO_CONTINUE" not in prompt

    bad_message = deepcopy(get_message.return_value)
    bad_message["message_metadata"]["workflow_revision"] = 18
    get_message.return_value = bad_message
    with pytest.raises(Nl2AgentWorkflowConflictError):
        validate_nl2agent_action_context(
            get_session=get_session,
            get_action_message=get_message,
            context=context,
            draft_agent_id=202,
            conversation_id=902,
            tenant_id="tenant-1",
            user_id="user-1",
        )


def test_action_context_rejects_a_different_conversation():
    context = Nl2AgentActionContext(
        action_id=ACTION_ID,
        action="save_identity",
        display_text="Agent saved",
        workflow_revision=19,
    )
    get_action_message = MagicMock()

    with pytest.raises(ForbiddenError, match="not accessible"):
        validate_nl2agent_action_context(
            get_session=MagicMock(
                return_value={**_session(revision=19), "conversation_id": 901}
            ),
            get_action_message=get_action_message,
            context=context,
            draft_agent_id=202,
            conversation_id=902,
            tenant_id="tenant-1",
            user_id="user-1",
        )

    get_action_message.assert_not_called()
