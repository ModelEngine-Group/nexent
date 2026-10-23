"""Tests for specialized Workbench runtime adapters."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from consts.model import NL2AgentRunRequest, NL2SkillRunRequest
from consts.model import HistoryItem
from management.services.agent.runtime_sub_agent_adapter import (
    NL2AGENT_ADAPTER_KEY,
    NL2SKILL_ADAPTER_KEY,
    RuntimeSubAgentContext,
    RuntimeSubAgentError,
    get_runtime_sub_agent_adapter,
    list_runtime_sub_agent_adapters,
)


def test_adapter_registry_has_stable_builtin_keys():
    """UT-BE-NCR-003: registry exposes only stable specialized keys."""
    assert list_runtime_sub_agent_adapters() == [
        NL2AGENT_ADAPTER_KEY,
        NL2SKILL_ADAPTER_KEY,
    ]
    with pytest.raises(ValueError, match="Unknown runtime sub-Agent"):
        get_runtime_sub_agent_adapter("builtin:missing")


@pytest.mark.asyncio
async def test_nl2skill_adapter_preserves_specialized_builder(mocker):
    """UT-BE-NCR-001: Skill mode deterministically uses the NL2Skill builder."""
    expected = SimpleNamespace()
    builder = mocker.patch(
        "management.services.agent.runtime_sub_agent_adapter._build_nl2skill_run_info",
        new_callable=AsyncMock,
        return_value=expected,
    )
    context = RuntimeSubAgentContext(
        request=NL2SkillRunRequest(query="Create a skill"),
        tenant_id="tenant-a",
        user_id="user-a",
        user_role="ADMIN",
        language="en",
    )
    mocker.patch(
        "management.services.agent.runtime_sub_agent_adapter.has_permission",
        return_value=True,
    )
    validate_files = mocker.patch(
        "management.services.agent.runtime_sub_agent_adapter._validate_run_minio_files"
    )

    result = await get_runtime_sub_agent_adapter(NL2SKILL_ADAPTER_KEY).build_run_info(
        context
    )

    assert result is expected
    builder.assert_awaited_once_with(
        request=context.request,
        tenant_id="tenant-a",
        language="en",
    )
    validate_files.assert_called_once_with(None, "user-a", "tenant-a")


@pytest.mark.asyncio
async def test_nl2agent_adapter_forwards_authorization(mocker):
    """UT-BE-NCR-002: Agent mode forwards verified context to NL2Agent."""
    expected = SimpleNamespace()
    builder = mocker.patch(
        "management.services.agent.runtime_sub_agent_adapter._build_nl2agent_run_info",
        new_callable=AsyncMock,
        return_value=expected,
    )
    context = RuntimeSubAgentContext(
        request=NL2AgentRunRequest(query="Create", agent_id=9),
        tenant_id="tenant-a",
        user_id="user-a",
        user_role="DEV",
        language="zh",
        authorization="Bearer token",
    )
    mocker.patch(
        "management.services.agent.runtime_sub_agent_adapter.has_permission",
        return_value=True,
    )
    validate_files = mocker.patch(
        "management.services.agent.runtime_sub_agent_adapter._validate_run_minio_files"
    )
    require_draft = mocker.patch(
        "management.services.agent.runtime_sub_agent_adapter.require_agent_draft_edit"
    )

    result = await get_runtime_sub_agent_adapter(NL2AGENT_ADAPTER_KEY).build_run_info(
        context
    )

    assert result is expected
    builder.assert_awaited_once_with(
        request=context.request,
        tenant_id="tenant-a",
        language="zh",
        authorization="Bearer token",
    )
    validate_files.assert_called_once_with(None, "user-a", "tenant-a")
    require_draft.assert_called_once_with(
        agent_id=9,
        tenant_id="tenant-a",
        user_id="user-a",
    )


@pytest.mark.asyncio
async def test_adapter_rejects_wrong_request_type(mocker):
    """UT-BE-NCR-004: request/adapter mismatch fails before construction."""
    context = RuntimeSubAgentContext(
        request=NL2AgentRunRequest(query="Create", agent_id=9),
        tenant_id="tenant-a",
        user_id="user-a",
        user_role="ADMIN",
        language="en",
    )
    builder = mocker.patch(
        "management.services.agent.runtime_sub_agent_adapter._build_nl2skill_run_info",
        new_callable=AsyncMock,
    )

    with pytest.raises(RuntimeSubAgentError) as exc_info:
        await get_runtime_sub_agent_adapter(NL2SKILL_ADAPTER_KEY).authorize(context)

    assert exc_info.value.code == "runtime_adapter_request_mismatch"
    builder.assert_not_awaited()


@pytest.mark.asyncio
async def test_ncr_007_agent_draft_denial_stops_before_builder(mocker):
    """UT-BE-NCR-007: inaccessible drafts are rejected without disclosure."""
    context = RuntimeSubAgentContext(
        request=NL2AgentRunRequest(query="Create", agent_id=9),
        tenant_id="tenant-a",
        user_id="user-a",
        user_role="DEV",
        language="en",
    )
    mocker.patch(
        "management.services.agent.runtime_sub_agent_adapter.has_permission",
        return_value=True,
    )
    mocker.patch("management.services.agent.runtime_sub_agent_adapter._validate_run_minio_files")
    mocker.patch(
        "management.services.agent.runtime_sub_agent_adapter.require_agent_draft_edit",
        side_effect=PermissionError("tenant-b secret draft"),
    )
    builder = mocker.patch(
        "management.services.agent.runtime_sub_agent_adapter._build_nl2agent_run_info",
        new_callable=AsyncMock,
    )

    with pytest.raises(RuntimeSubAgentError) as exc_info:
        await get_runtime_sub_agent_adapter(NL2AGENT_ADAPTER_KEY).build_run_info(
            context
        )

    assert exc_info.value.code == "draft_forbidden"
    assert "tenant-b" not in str(exc_info.value)
    builder.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("adapter_key", "run_request", "service_target"),
    [
        (
            NL2SKILL_ADAPTER_KEY,
            NL2SkillRunRequest(query="Create a skill"),
            "management.services.agent.runtime_sub_agent_adapter._create_nl2skill_stream",
        ),
        (
            NL2AGENT_ADAPTER_KEY,
            NL2AgentRunRequest(query="Create an Agent", agent_id=9),
            "management.services.agent.runtime_sub_agent_adapter._create_nl2agent_stream",
        ),
    ],
)
async def test_ncr_008_012_adapter_returns_legacy_async_stream(
    mocker,
    adapter_key,
    run_request,
    service_target,
):
    """UT-BE-NCR-008 and UT-BE-NCR-012: preserve legacy event streams."""
    async def legacy_stream():
        yield "data: done\n\n"

    expected_stream = legacy_stream()
    stream_factory = MagicMock(return_value=expected_stream)
    mocker.patch(service_target, new=stream_factory)
    context = RuntimeSubAgentContext(
        request=run_request,
        tenant_id="tenant-a",
        user_id="user-a",
        user_role="ADMIN",
        language="en",
        authorization="Bearer token",
    )
    mocker.patch(
        "management.services.agent.runtime_sub_agent_adapter.has_permission",
        return_value=True,
    )
    mocker.patch("management.services.agent.runtime_sub_agent_adapter._validate_run_minio_files")
    mocker.patch("management.services.agent.runtime_sub_agent_adapter.require_agent_draft_edit")

    result = await get_runtime_sub_agent_adapter(adapter_key).stream(context)

    assert result is expected_stream
    stream_factory.assert_called_once()
    await expected_stream.aclose()


@pytest.mark.asyncio
async def test_ncr_005_adapter_rejects_missing_create_permission(mocker):
    """UT-BE-NCR-005."""
    context = RuntimeSubAgentContext(
        request=NL2SkillRunRequest(query="Create a skill"),
        tenant_id="tenant-a",
        user_id="user-a",
        user_role="USER",
        language="en",
    )
    mocker.patch(
        "management.services.agent.runtime_sub_agent_adapter.has_permission",
        return_value=False,
    )
    validate_files = mocker.patch(
        "management.services.agent.runtime_sub_agent_adapter._validate_run_minio_files"
    )
    builder = mocker.patch(
        "management.services.agent.runtime_sub_agent_adapter._build_nl2skill_run_info",
        new_callable=AsyncMock,
    )

    with pytest.raises(RuntimeSubAgentError) as exc_info:
        await get_runtime_sub_agent_adapter(NL2SKILL_ADAPTER_KEY).build_run_info(
            context
        )

    assert exc_info.value.code == "creation_forbidden"
    validate_files.assert_not_called()
    builder.assert_not_awaited()


@pytest.mark.asyncio
async def test_ncr_006_adapter_rejects_missing_tenant_before_resources(mocker):
    """UT-BE-NCR-006."""
    context = RuntimeSubAgentContext(
        request=NL2SkillRunRequest(query="Create a skill"),
        tenant_id="",
        user_id="user-a",
        user_role="ADMIN",
        language="en",
    )
    permission = mocker.patch(
        "management.services.agent.runtime_sub_agent_adapter.has_permission"
    )
    validate_files = mocker.patch(
        "management.services.agent.runtime_sub_agent_adapter._validate_run_minio_files"
    )

    with pytest.raises(RuntimeSubAgentError) as exc_info:
        await get_runtime_sub_agent_adapter(NL2SKILL_ADAPTER_KEY).authorize(context)

    assert exc_info.value.code == "runtime_context_invalid"
    permission.assert_not_called()
    validate_files.assert_not_called()


@pytest.mark.asyncio
async def test_ncr_011_attachment_denial_stops_before_builder(mocker):
    """UT-BE-NCR-011."""
    request = NL2SkillRunRequest(
        query="Create a skill",
        minio_files=[{"name": "secret.pdf", "url": "s3://other/secret.pdf"}],
    )
    context = RuntimeSubAgentContext(
        request=request,
        tenant_id="tenant-a",
        user_id="user-a",
        user_role="ADMIN",
        language="en",
    )
    mocker.patch(
        "management.services.agent.runtime_sub_agent_adapter.has_permission",
        return_value=True,
    )
    mocker.patch(
        "management.services.agent.runtime_sub_agent_adapter._validate_run_minio_files",
        side_effect=PermissionError("denied"),
    )
    builder = mocker.patch(
        "management.services.agent.runtime_sub_agent_adapter._build_nl2skill_run_info",
        new_callable=AsyncMock,
    )

    with pytest.raises(RuntimeSubAgentError) as exc_info:
        await get_runtime_sub_agent_adapter(NL2SKILL_ADAPTER_KEY).build_run_info(
            context
        )

    assert exc_info.value.code == "attachment_forbidden"
    assert "secret.pdf" not in str(exc_info.value)
    builder.assert_not_awaited()


@pytest.mark.asyncio
async def test_ncr_010_current_and_history_attachments_are_authorized(mocker):
    """UT-BE-NCR-010."""
    current_file = {"name": "current.pdf", "url": "s3://tenant/current.pdf"}
    history_file = {"name": "history.docx", "url": "s3://tenant/history.docx"}
    context = RuntimeSubAgentContext(
        request=NL2SkillRunRequest(
            query="Create a skill",
            minio_files=[current_file],
            history=[
                HistoryItem(
                    role="user",
                    content="Earlier input",
                    minio_files=[history_file],
                )
            ],
        ),
        tenant_id="tenant-a",
        user_id="user-a",
        user_role="ADMIN",
        language="en",
    )
    mocker.patch(
        "management.services.agent.runtime_sub_agent_adapter.has_permission",
        return_value=True,
    )
    validate_files = mocker.patch(
        "management.services.agent.runtime_sub_agent_adapter._validate_run_minio_files"
    )

    await get_runtime_sub_agent_adapter(NL2SKILL_ADAPTER_KEY).authorize(context)

    validate_files.assert_called_once_with(
        [current_file, history_file],
        "user-a",
        "tenant-a",
    )


def test_ncr_003_unknown_adapter_has_stable_error():
    """UT-BE-NCR-003."""
    with pytest.raises(RuntimeSubAgentError) as exc_info:
        get_runtime_sub_agent_adapter("builtin:missing")

    assert exc_info.value.code == "runtime_adapter_not_found"
