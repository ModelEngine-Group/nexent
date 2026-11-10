# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Build and pin local SDK tool parameters from persisted Agent bindings."""

import hmac
import json

from contracts.constants import environment
from nexent.core.agents.agent_model import ToolConfig

LOCAL_SDK_TOOL_CLASSES = {
    "dify_search": "DifySearchTool",
    "datamate_search": "DataMateSearchTool",
    "ragflow_search": "RAGFlowSearchTool",
    "haotian_search": "HaotianSearchTool",
    "idata_search": "IdataSearchTool",
    "deepseek_search": "DeepSeekSearchTool",
    "exa_search": "ExaSearchTool",
    "linkup_search": "LinkupSearchTool",
    "tavily_search": "TavilySearchTool",
    "get_email": "GetEmailTool",
    "send_email": "SendEmailTool",
    "postgres_database": "PostgreSqlTool",
    "mysql_database": "MySqlTool",
    "mssql_database": "MsSqlTool",
}
LOCAL_RERANK_TOOL_CLASSES = frozenset({"DifySearchTool", "DataMateSearchTool", "RAGFlowSearchTool"})


def build_local_tool(row: dict, language: str, description_zh: str | None, inputs: str | None) -> ToolConfig:
    name = row["name"]
    if row["source"] != "local" or LOCAL_SDK_TOOL_CLASSES.get(name) != row["class_name"]:
        raise ValueError("Unsupported local SDK tool")
    overrides = row["instance_params"] or {}
    params = {
        item["name"]: overrides[item["name"]] if overrides.get(item["name"]) is not None else item.get("default")
        for item in (row["params"] or [])
    }
    if name == "deepseek_search":
        params.pop("localization", None)
        params.pop("max_content_chars", None)
        params["language"] = language
    return ToolConfig(
        name=name, class_name=row["class_name"], source="local", description=row["description"],
        description_zh=description_zh, inputs=inputs, output_type=row["output_type"], usage=row["usage"], params=params,
    )


def local_tool_rerank_name(tool: ToolConfig) -> str | None:
    if tool.class_name in LOCAL_RERANK_TOOL_CLASSES and tool.params.get("rerank"):
        return tool.params.get("rerank_model_name") or None
    return None


def local_tool_revision(tenant_id: str, agent_id: int, version_no: int, row: dict, tool: ToolConfig) -> str:
    if not environment.JWT_SECRET:
        raise ValueError("AgentOS signing is not configured")
    key = hmac.digest(environment.JWT_SECRET.encode(), b"nexent/agentos/local-sdk-tool/v1", "sha256")
    payload = json.dumps(
        [tenant_id, agent_id, version_no, row["tool_instance_id"], row["tool_id"], row["inputs"], tool.model_dump(mode="json")],
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hmac.digest(key, payload, "sha256").hex()
