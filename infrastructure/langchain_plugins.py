# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Pinned LangChain plugins installed by the deployment."""

import hmac
import json
import logging
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from contracts.constants import environment
from infrastructure.local_tool_execution import catalog_tool_parameters
from infrastructure.rdb.local_tool_records import read_bound_catalog_tools
from infrastructure.rdb.mcp_execution_records import read_skill_derived_tools
from nexent.core.agents.agent_model import ToolConfig

LANGCHAIN_PLUGIN_DIRECTORY = Path(__file__).resolve().parents[1] / "backend/tool_collection/langchain"

logger = logging.getLogger(__name__)


def read_bound_langchain_tools(agent_id, version_no, tenant_id, names):
    return read_bound_catalog_tools(agent_id, version_no, tenant_id, names, source="langchain")


def read_skill_derived_langchain_tools(agent_id, version_no, tenant_id, names):
    return [
        {**row, "source": "langchain"}
        for row in read_skill_derived_tools(agent_id, version_no, tenant_id, names, source="langchain")
    ]


def build_langchain_tool(row: dict) -> ToolConfig:
    if row["source"] != "langchain" or row["name"] != row["class_name"]:
        raise ValueError("Invalid LangChain catalog tool")
    return ToolConfig(
        name=row["name"], class_name=row["class_name"], source="langchain", description=row["description"],
        inputs=row["inputs"], output_type=row["output_type"], usage=row["usage"], params=catalog_tool_parameters(row),
    )


def langchain_binding_revision(scope, row, tool, module_file, module_revision) -> str:
    if not environment.JWT_SECRET:
        raise ValueError("AgentOS signing is not configured")
    identity = (
        ["skill", *sorted(row["skill_instance_ids"])] if "skill_instance_ids" in row
        else ["explicit", row["tool_instance_id"]]
    )
    payload = json.dumps(
        [scope, row["tool_id"], identity, tool.model_dump(mode="json"), module_file, module_revision],
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    key = hmac.digest(environment.JWT_SECRET.encode(), b"nexent/agentos/langchain-tool/v1", "sha256")
    return hmac.digest(key, payload, "sha256").hex()


def _read_plugin(filename: str) -> tuple[Path, bytes]:
    if not filename.endswith(".py") or filename.startswith("__") or any(char in filename for char in "/\\:"):
        raise ValueError("Invalid LangChain plugin file")
    root = LANGCHAIN_PLUGIN_DIRECTORY.resolve()
    path = (root / filename).resolve()
    if path.parent != root:
        raise ValueError("Invalid LangChain plugin file")
    return path, path.read_bytes()


def _load_tools(path: Path, code: bytes):
    from langchain_core.tools import BaseTool

    spec = spec_from_file_location(f"langchain_tool_{path.stem}", path)
    if spec is None:
        raise ValueError("Cannot load LangChain plugin")
    module = module_from_spec(spec)
    exec(compile(code, str(path), "exec", dont_inherit=True), vars(module))
    return {id(obj): obj for obj in vars(module).values() if isinstance(obj, BaseTool)}.values()


def discover_langchain_plugin_refs(names: set[str]) -> dict[str, tuple[str, str]]:
    matches: dict[str, list[tuple[str, str]]] = {}
    for entry in sorted(LANGCHAIN_PLUGIN_DIRECTORY.glob("*.py")):
        if entry.name.startswith("__"):
            continue
        try:
            path, code = _read_plugin(entry.name)
            revision = sha256(code).hexdigest()
            for tool in _load_tools(path, code):
                if tool.name in names:
                    matches.setdefault(tool.name, []).append((entry.name, revision))
        except Exception as exc:
            logger.warning("Unable to discover LangChain plugin %s (%s)", entry.name, type(exc).__name__)
    return {name: refs[0] for name, refs in matches.items() if len(refs) == 1}


def load_langchain_plugin(filename: str, revision: str) -> dict:
    path, code = _read_plugin(filename)
    if not hmac.compare_digest(sha256(code).hexdigest(), revision):
        raise ValueError("LangChain plugin revision changed")
    matches = {}
    try:
        for tool in _load_tools(path, code):
            matches.setdefault(tool.name, []).append(tool)
    except Exception as exc:
        raise ValueError("LangChain plugin cannot be loaded") from exc
    return {name: tools[0] for name, tools in matches.items() if len(tools) == 1}
