# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from contracts.agentos import ToolBinding
from infrastructure.agentos_identity import ServicePrincipal
from management.services.agent.preparation import evaluation_snapshot
from nexent.core.agents.agent_model import ToolConfig
from nexent.core.agents.nexent_agent import NexentAgent

from test.backend.app.test_agentos_prepared_evaluation import model_record


@pytest.mark.parametrize(("name", "class_name", "modality", "slot"), [
    ("analyze_text_file", "AnalyzeTextFileTool", "llm_long_context", "llm"),
    ("analyze_image", "AnalyzeImageTool", "vlm", "vlm"),
    ("analyze_audio", "AnalyzeAudioTool", "vlm", "vlm4"),
    ("analyze_video", "AnalyzeVideoTool", "vlm", "vlm3"),
])
@pytest.mark.asyncio
async def test_media_analysis_compiler_uses_model_reference_and_runtime_storage(mocker, name, class_name, modality, slot):
    from contracts.constants import environment
    from infrastructure.object_storage import client as storage
    from management.services.agent.preparation import tools
    from management.services.model import adapter
    from runtime.agentos import prepared_analysis

    model = model_record(model_id=9, model_type=slot, api_key="private-analysis-key")
    raw = {"name": name, "class_name": class_name, "source": "local", "params": [
        {"name": "selected_model_id", "default": "9"},
    ]}
    mocker.patch.object(tools, "discover_langchain_tools", return_value=[])
    mocker.patch.object(tools, "_resolve_runtime_tool_records", return_value=[raw])
    mocker.patch.object(tools, "search_agent_info_by_agent_id", return_value={"name": "agent"})
    lookup = mocker.patch.object(adapter, "get_model_by_model_id", return_value=model)
    legacy_text = mocker.patch.object(tools, "get_llm_adapter")
    legacy_media = mocker.patch.object(tools, "get_vlm_adapter")
    tool, = await tools.create_tool_config_list(7, "tenant-a", "user-a", portable_evaluation=True)
    lookup.assert_called_once_with(9, "tenant-a")
    legacy_text.assert_not_called()
    legacy_media.assert_not_called()
    reference = evaluation_snapshot._export_analysis_binding(tool)
    encoded = reference.model_dump_json()
    assert "private-analysis-key" not in encoded
    assert "runtime-processing" not in encoded

    runtime_model = mocker.patch.object(prepared_analysis, "get_model_by_model_id", return_value=model)
    create_adapter = mocker.patch.object(prepared_analysis, "get_adapter_from_config")
    mocker.patch.object(environment, "DATA_PROCESS_SERVICE", "http://runtime-processing")
    rebound = prepared_analysis.materialize_analysis_tools(
        [ToolBinding.model_validate_json(encoded)], ServicePrincipal("user-a", "tenant-a"),
    )[name]
    runtime_model.assert_called_once_with(9, "tenant-a")
    assert create_adapter.call_args.args == (model, modality, slot, "tenant-a")
    assert rebound.metadata["storage_client"] is storage.minio_client
    tool_instance = NexentAgent.create_local_tool(SimpleNamespace(observer=None), rebound)
    assert tool_instance.selected_model_id == 9
    assert (tool_instance.llm_model if slot == "llm" else tool_instance.vlm_model) is create_adapter.return_value
    if slot == "llm":
        assert tool_instance.data_process_service_url == "http://runtime-processing"
    validate = rebound.metadata["validate_url_access"]
    validate(["/bucket/attachments/user-a/file.txt", "https://example.invalid/image.png"])
    for alias in ("s3://", "s3:/", "/", "//", " s3://"):
        with pytest.raises(PermissionError):
            validate([f"{alias}bucket/attachments/user-b/file.txt"])


@pytest.mark.parametrize(("change", "status"), [
    ("gone", 404), ("other_tenant", 404), ("revision", 409), ("type", 409),
])
def test_media_analysis_refuses_invalid_model_before_adapter_creation(mocker, change, status):
    from management.services.agent.preparation import analysis
    from management.services.model import adapter
    from runtime.agentos import prepared_analysis

    record = model_record(model_id=9, model_type="vlm")
    defaults = mocker.patch.object(adapter.tenant_config_manager, "get_model_config", return_value=record)
    tool = ToolConfig(name="analyze_image", class_name="AnalyzeImageTool", source="local", params={})
    assert analysis.prepare_analysis_tool(tool, "tenant-a")
    defaults.assert_called_once()
    assert defaults.call_args.kwargs["tenant_id"] == "tenant-a"
    reference = evaluation_snapshot._export_analysis_binding(tool)
    result = {
        "gone": None, "other_tenant": record | {"tenant_id": "tenant-b"},
        "revision": record | {"update_time": "changed"}, "type": record | {"model_type": "llm"},
    }[change]
    mocker.patch.object(prepared_analysis, "get_model_by_model_id", return_value=result)
    create_adapter = mocker.patch.object(prepared_analysis, "get_adapter_from_config")
    with pytest.raises(HTTPException) as error:
        prepared_analysis.materialize_analysis_tools([reference], ServicePrincipal("user-a", "tenant-a"))
    assert error.value.status_code == status
    create_adapter.assert_not_called()


def test_media_analysis_keeps_missing_default_model(mocker):
    from management.services.agent.preparation import analysis
    from management.services.model import adapter
    from runtime.agentos import prepared_analysis

    mocker.patch.object(adapter.tenant_config_manager, "get_model_config", return_value={})
    tool = ToolConfig(name="analyze_video", class_name="AnalyzeVideoTool", source="local", params={})
    assert analysis.prepare_analysis_tool(tool, "tenant-a")
    reference = evaluation_snapshot._export_analysis_binding(tool)
    lookup = mocker.patch.object(prepared_analysis, "get_model_by_model_id")
    rebound = prepared_analysis.materialize_analysis_tools([reference], ServicePrincipal("user-a", "tenant-a"))[tool.name]
    assert rebound.metadata["vlm_model"] is None
    lookup.assert_not_called()
