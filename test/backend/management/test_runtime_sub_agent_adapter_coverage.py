from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from consts.exceptions import RuntimeSubAgentError
from consts.model import NL2SkillRunRequest
from management.services.agent import runtime_sub_agent_adapter as adapter


def test_validate_run_files_delegates_to_canonical_policy(monkeypatch):
    from agents import create_agent_info

    validate = MagicMock()
    monkeypatch.setattr(create_agent_info, "_validate_run_minio_files", validate)

    adapter._validate_run_minio_files([{"object_name": "a"}], "user-a", "tenant-a")

    validate.assert_called_once_with([{"object_name": "a"}], "user-a", "tenant-a")


@pytest.mark.asyncio
async def test_nl2skill_builder_wrapper_forwards_kwargs(monkeypatch):
    from services import nl2skill_service

    expected = SimpleNamespace()
    builder = AsyncMock(return_value=expected)
    monkeypatch.setattr(nl2skill_service, "build_nl2skill_run_info", builder)

    assert await adapter._build_nl2skill_run_info(value=1) is expected
    builder.assert_awaited_once_with(value=1)


def test_nl2skill_stream_wrapper_forwards_kwargs(monkeypatch):
    from services import nl2skill_service

    stream = SimpleNamespace()
    factory = MagicMock(return_value=stream)
    monkeypatch.setattr(nl2skill_service, "create_nl2skill_stream", factory)

    assert adapter._create_nl2skill_stream(value=1) is stream
    factory.assert_called_once_with(value=1)


@pytest.mark.asyncio
async def test_nl2agent_builder_wrapper_forwards_kwargs(monkeypatch):
    from services import nl2agent_service

    expected = SimpleNamespace()
    builder = AsyncMock(return_value=expected)
    monkeypatch.setattr(nl2agent_service, "build_nl2agent_run_info", builder)

    assert await adapter._build_nl2agent_run_info(value=1) is expected
    builder.assert_awaited_once_with(value=1)


def test_nl2agent_stream_wrapper_forwards_kwargs(monkeypatch):
    from services import nl2agent_service

    stream = SimpleNamespace()
    factory = MagicMock(return_value=stream)
    monkeypatch.setattr(nl2agent_service, "create_nl2agent_stream", factory)

    assert adapter._create_nl2agent_stream(value=1) is stream
    factory.assert_called_once_with(value=1)


@pytest.mark.parametrize(
    ("tenant_id", "user_id"),
    [("", "user-a"), ("tenant-a", "   ")],
)
def test_validate_context_rejects_blank_identity(tenant_id, user_id):
    context = adapter.RuntimeSubAgentContext(
        request=NL2SkillRunRequest(query="Create"),
        tenant_id=tenant_id,
        user_id=user_id,
        user_role="ADMIN",
        language="en",
    )

    with pytest.raises(RuntimeSubAgentError, match="runtime_context_invalid"):
        adapter._validate_context(context, NL2SkillRunRequest)
