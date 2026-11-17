# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management knowledge trials cross AgentOS and never instantiate execution locally."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from contracts.agentos import AgentToolResult
from contracts.tool import ToolValidateRequest
from management.services.tool import knowledge_validation


@pytest.mark.asyncio
async def test_trial_exports_v2_binding_and_forwards_trusted_identity(mocker):
    async def prepare(config, user_id, tenant_id, paths):
        assert (user_id, tenant_id, paths) == ("user", "tenant", ["report.txt"])
        config.metadata = {"prepared_knowledge_search": {"description": {}, "index_names": [], "allowed": [],
                                                       "display_name_to_index": {}}}
        return True

    mocker.patch.object(knowledge_validation, "prepare_knowledge_search", side_effect=prepare)
    client = SimpleNamespace(invoke_tool=AsyncMock(return_value=AgentToolResult(result="retrieved")))
    mocker.patch.object(knowledge_validation, "AgentOSClient", return_value=client)
    request = ToolValidateRequest(name="knowledge_base_search", source="local", params={"document_paths": ["report.txt"]},
                                  inputs={"query": "question"})
    assert await knowledge_validation.validate_knowledge_tool(request, "tenant", "user") == "retrieved"
    payload, user_id, tenant_id = client.invoke_tool.await_args.args
    assert payload.tool.version == "2" and payload.tool.tool_id == "knowledge_base_search"
    assert (user_id, tenant_id) == ("user", "tenant")
    assert payload.inputs == {"query": "question"}


@pytest.mark.asyncio
async def test_trial_requires_identity_before_resource_assembly(mocker):
    from contracts.errors.exceptions import ToolExecutionException

    prepare = mocker.patch.object(knowledge_validation, "prepare_knowledge_search")
    with pytest.raises(ToolExecutionException):
        await knowledge_validation.validate_knowledge_tool(ToolValidateRequest(name="knowledge_base_search", source="local"),
                                                           "tenant", None)
    prepare.assert_not_called()


@pytest.mark.asyncio
async def test_public_validation_preserves_runtime_timeout_without_error_log(mocker, caplog):
    from contracts.errors.exceptions import RuntimeServiceTimeoutError
    from management.services.tool import validation

    caplog.clear()
    failure = RuntimeServiceTimeoutError("Knowledge resource preparation timed out")
    execute = mocker.patch.object(knowledge_validation, "validate_knowledge_tool", side_effect=failure)
    with pytest.raises(RuntimeServiceTimeoutError) as error:
        await validation.validate_tool_impl(ToolValidateRequest(name="knowledge_base_search", source="local"),
                                            "tenant", "user")
    assert error.value is failure and execute.await_count == 1
    assert not [record for record in caplog.records if record.levelname == "ERROR"]
