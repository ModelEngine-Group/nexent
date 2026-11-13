# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Build and pin local SDK tool parameters from persisted Agent bindings."""

import hmac
import json

from contracts.agentos import LocalSearchOverrides
from contracts.constants import environment
from infrastructure.shared_aidp_tool import shared_aidp_parameters
from nexent.core.agents.agent_model import ToolConfig

LOCAL_SDK_TOOL_CLASSES = {
    "dify_search": "DifySearchTool",
    "datamate_search": "DataMateSearchTool",
    "ragflow_search": "RAGFlowSearchTool",
    "haotian_search": "HaotianSearchTool",
    "idata_search": "IdataSearchTool",
    "ind_aidp_search": "IndependentAidpSearchTool",
    "aidp_search": "AidpSearchTool",
    "deepseek_search": "DeepSeekSearchTool",
    "exa_search": "ExaSearchTool",
    "linkup_search": "LinkupSearchTool",
    "tavily_search": "TavilySearchTool",
    "get_email": "GetEmailTool",
    "send_email": "SendEmailTool",
    "postgres_database": "PostgreSqlTool",
    "mysql_database": "MySqlTool",
    "mssql_database": "MsSqlTool",
    "create_file": "CreateFileTool",
    "read_file": "ReadFileTool",
    "delete_file": "DeleteFileTool",
    "create_directory": "CreateDirectoryTool",
    "delete_directory": "DeleteDirectoryTool",
    "list_directory": "ListDirectoryTool",
    "move_item": "MoveItemTool",
    "terminal": "TerminalTool",
}
LOCAL_SDK_CLASS_NAMES = {
    **{value: key for key, value in LOCAL_SDK_TOOL_CLASSES.items()},
    # Canonical injected tools keep their dedicated bindings; catalog aliases use sdk_local.
    "DownloadFromS3Tool": "download_from_s3",
    "UploadToS3Tool": "upload_to_s3",
    "ParallelExecutorTool": "parallel_executor",
    "StoreMemoryTool": "store_memory",
    "SearchMemoryTool": "search_memory",
}
LOCAL_SDK_BINDING_PREFIX = "sdk_local:"
LOCAL_RERANK_TOOL_CLASSES = frozenset({"DifySearchTool", "DataMateSearchTool", "RAGFlowSearchTool"})
LOCAL_SEARCH_TUNING_METADATA = "agentos_local_search_overrides"
LOCAL_PARAMETER_OVERRIDES_METADATA = "agentos_local_parameter_overrides"
LOCAL_SEARCH_TUNING_FIELDS = {
    "dify_search": {"top_k", "rerank", "rerank_model_name"},
    "datamate_search": {"top_k", "threshold", "rerank", "rerank_model_name"},
    "ragflow_search": {"top_k", "similarity_threshold", "rerank", "rerank_model_name"},
    "haotian_search": {"top_k", "score_threshold"},
    "idata_search": {"top_k", "similarity_threshold"},
    "deepseek_search": {"max_results"},
    "exa_search": {"max_results"},
    "linkup_search": {"max_results"},
    "tavily_search": {"max_results"},
}


def local_tool_binding_id(tool: ToolConfig) -> str:
    if LOCAL_SDK_TOOL_CLASSES.get(tool.name) == tool.class_name:
        return tool.name
    return LOCAL_SDK_BINDING_PREFIX + tool.name


def local_tool_binding_name(binding_id: str) -> str:
    return binding_id.removeprefix(LOCAL_SDK_BINDING_PREFIX)


def is_catalog_local_tool(tool: ToolConfig) -> bool:
    return (
        tool.source == "local" and tool.class_name in LOCAL_SDK_CLASS_NAMES
        and (tool.class_name, tool.name) not in {
            ("ParallelExecutorTool", "parallel_executor"),
            ("StoreMemoryTool", "store_memory"), ("SearchMemoryTool", "search_memory"),
        }
    )


def catalog_tool_parameters(row: dict) -> dict:
    overrides = row["instance_params"] or {}
    return {
        item["name"]: overrides[item["name"]] if overrides.get(item["name"]) is not None else item.get("default")
        for item in (row["params"] or [])
    }


def build_local_tool(row: dict, language: str, description_zh: str | None, inputs: str | None) -> ToolConfig:
    name = row["name"]
    canonical = LOCAL_SDK_CLASS_NAMES.get(row["class_name"])
    if row["source"] != "local" or canonical is None:
        raise ValueError("Unsupported local SDK tool")
    params = catalog_tool_parameters(row)
    if canonical == "deepseek_search":
        params.pop("localization", None)
        params.pop("max_content_chars", None)
        params["language"] = language
    elif canonical == "aidp_search":
        params = shared_aidp_parameters(params)
    return ToolConfig(
        name=name, class_name=row["class_name"], source="local", description=row["description"],
        description_zh=description_zh, inputs=inputs, output_type=row["output_type"], usage=row["usage"], params=params,
    )


def local_tool_rerank_name(tool: ToolConfig) -> str | None:
    if tool.class_name in LOCAL_RERANK_TOOL_CLASSES and tool.params.get("rerank"):
        return tool.params.get("rerank_model_name") or None
    return None


def apply_local_search_overrides(tool: ToolConfig, overrides: LocalSearchOverrides | None) -> ToolConfig:
    if overrides is None:
        return tool
    values = overrides.model_dump(exclude_unset=True)
    canonical = LOCAL_SDK_CLASS_NAMES.get(tool.class_name)
    if values.keys() - LOCAL_SEARCH_TUNING_FIELDS.get(canonical, set()):
        raise ValueError("Unsupported local search override")
    if any(value is None for name, value in values.items() if name != "score_threshold"):
        raise ValueError("Local search override requires a value")
    if canonical == "deepseek_search" and values.get("max_results", 0) > 50:
        raise ValueError("DeepSeek search supports up to 50 results")
    if canonical == "ragflow_search" and values.get("similarity_threshold", 0) < 0:
        raise ValueError("RAGFlow similarity threshold must be nonnegative")
    return tool.model_copy(update={"params": {**tool.params, **values}})


def local_tool_revision(tenant_id: str, agent_id: int, version_no: int, row: dict, tool: ToolConfig) -> str:
    if not environment.JWT_SECRET:
        raise ValueError("AgentOS signing is not configured")
    if "workbench_skill_ids" in row:
        identity = row["workbench_skill_ids"]
        key_scope = b"nexent/agentos/local-sdk-tool/workbench/v1"
    elif "skill_instance_ids" in row:
        identity = sorted(row["skill_instance_ids"])
        key_scope = b"nexent/agentos/local-sdk-tool/v2"
    else:
        identity = row["tool_instance_id"]
        key_scope = b"nexent/agentos/local-sdk-tool/v1"
    key = hmac.digest(environment.JWT_SECRET.encode(), key_scope, "sha256")
    payload = json.dumps(
        [tenant_id, agent_id, version_no, identity, row["tool_id"], row["inputs"], tool.model_dump(mode="json")],
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hmac.digest(key, payload, "sha256").hex()


def apply_local_parameter_overrides(tool: ToolConfig, parameters: dict) -> ToolConfig:
    """Retain the compiler's run-language and shared-AIDP ownership rules."""
    params = {**tool.params, **parameters}
    canonical = LOCAL_SDK_CLASS_NAMES.get(tool.class_name)
    if canonical == "deepseek_search":
        params.pop("localization", None)
        params.pop("max_content_chars", None)
        params["language"] = tool.params["language"]
    elif canonical == "aidp_search":
        params = shared_aidp_parameters(params)
    return tool.model_copy(update={"params": params})
