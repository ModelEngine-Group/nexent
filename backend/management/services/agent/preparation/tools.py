# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Enrich effective tools with per-run providers and execution metadata."""

import copy
import json
import logging
from typing import Any, Dict, List, Optional

from consts.const import (
    AIDP_API_KEY,
    AIDP_SERVER_URL,
    AIDP_TENANT_ID,
    DATA_PROCESS_SERVICE,
)
from contracts.constants.tool import SYSTEM_MANAGED_TOOL_NAMES
from contracts.errors.exceptions import ValidationError
from contracts.tool import ToolParamsRequest
from management.db.agent.repository import search_agent_info_by_agent_id
from management.db.client import minio_client
from management.db.knowledge_base.repository import (
    get_knowledge_name_map_by_index_names,
)
from management.services.agent.resource_resolver import _resolve_runtime_tool_records
from management.services.file.service import validate_urls_access
from management.services.knowledge_base.providers.aidp import (
    create_ind_aidp_image_url_builder,
)
from management.services.knowledge_base.service import (
    ElasticSearchService,
    get_embedding_model_by_index_name,
    get_vector_db_core,
)
from management.services.model.adapter import get_llm_adapter, get_vlm_adapter
from management.services.model.resolver import get_rerank_model
from nexent.core.agents.agent_model import AgentConfig, ToolConfig
from nexent.core.agents.prompt import get_builtin_tool_descriptions
from nexent.core.concurrency import run_blocking
from nexent.core.tools.parallel_executor import ParallelExecutorTool

logger = logging.getLogger("create_agent_info")
logger.setLevel(logging.INFO)


def _build_parallel_executor_tool_config(default_timeout_seconds: int) -> ToolConfig:
    return ToolConfig(
        class_name=ParallelExecutorTool.__name__,
        name=ParallelExecutorTool.name,
        description=ParallelExecutorTool.description,
        description_zh=ParallelExecutorTool.description_zh,
        inputs=json.dumps(
            ParallelExecutorTool.inputs_for_timeout(default_timeout_seconds),
            ensure_ascii=False,
        ),
        output_type=ParallelExecutorTool.output_type,
        params={"default_timeout_seconds": default_timeout_seconds},
        source="local",
    )


def _normalize_tool_params_request(
    tool_params: Optional[ToolParamsRequest | Dict[str, Any]],
) -> ToolParamsRequest:
    """Normalize request-scoped tool parameter overrides into a ToolParamsRequest."""
    if tool_params is None:
        return ToolParamsRequest()
    if isinstance(tool_params, ToolParamsRequest):
        return tool_params
    if not isinstance(tool_params, dict):
        raise ValidationError("tool_params must be an object.")
    try:
        return ToolParamsRequest.model_validate(tool_params)
    except Exception as exc:
        raise ValidationError(f"Invalid tool_params payload: {exc}") from exc


def _get_agent_tool_overrides(
    tool_params: Optional[ToolParamsRequest],
    agent_name: Optional[str],
) -> Dict[str, Dict[str, Any]]:
    """Resolve tool overrides for a specific agent by its name."""
    if tool_params is None:
        return {}
    if not agent_name:
        return {}
    agent_override = tool_params.agents.get(agent_name)
    if agent_override is None:
        return {}
    return dict(agent_override.tools)


def _merge_tool_params(
    tool_record: Dict[str, Any],
    override_params: Optional[Dict[str, Any]],
    extra_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Merge request overrides on top of tool instance defaults from DB.

    Args:
        tool_record: Tool configuration from database
        override_params: Request-scoped overrides from tool_params
        extra_params: Additional internal params not in DB schema (e.g., document_paths)

    Returns:
        Merged params dict with DB defaults, overrides, and extra params
    """
    merged_params: Dict[str, Any] = {}
    for param in tool_record.get("params", []):
        merged_params[param["name"]] = param.get("default")

    if override_params:
        merged_params.update(override_params)

    # Extra params (e.g., internal access control params) always take precedence
    if extra_params:
        merged_params.update(extra_params)

    return merged_params


def _get_skill_script_tools(
    agent_id: int,
    tenant_id: str,
    version_no: int = 0,
    runtime_file_context: Optional[Dict[str, Any]] = None,
    runtime_skill_snapshot: Optional[List[Dict[str, Any]]] = None,
) -> List[ToolConfig]:
    """Build fixed file tools and skill tools for the current Agent.

    Args:
        agent_id: Agent ID for filtering available skills in error messages.
        tenant_id: Tenant ID for filtering available skills in error messages.
        version_no: Version number for filtering available skills.

    Returns:
        Fixed file-transfer tools plus skill tools when this Agent has skills.
    """
    from consts.const import CONTAINER_SKILLS_PATH

    skill_context = {
        "agent_id": agent_id,
        "tenant_id": tenant_id,
        "version_no": version_no,
    }
    file_context = dict(runtime_file_context or {})
    tool_prose_en = get_builtin_tool_descriptions("en")
    tool_prose_zh = get_builtin_tool_descriptions("zh")
    skill_snapshot_root = next(
        (
            str(skill.get("_snapshot_root"))
            for skill in (runtime_skill_snapshot or [])
            if skill.get("_snapshot_root")
        ),
        None,
    )

    skill_config_values: Dict[str, Dict[str, Any]] = {}
    try:
        from management.services.skill.service import SkillService

        enabled_skills = (
            SkillService(tenant_id=tenant_id).get_enabled_skills_for_agent(
                agent_id=agent_id,
                tenant_id=tenant_id,
                version_no=version_no,
            )
            if runtime_skill_snapshot is None
            else runtime_skill_snapshot
        )
        skill_config_values = {
            skill.get("name", ""): dict(skill.get("config_values") or {})
            for skill in enabled_skills
            if skill.get("name")
        }
    except Exception as exc:
        logger.warning(
            f"Failed to resolve effective skill configuration: {exc}", exc_info=True
        )

    try:
        tools: List[ToolConfig] = []
        if skill_config_values:
            tools.extend(
                [
                    ToolConfig(
                        class_name="RunSkillScriptTool",
                        name="run_skill_script",
                        description=tool_prose_en["run_skill_script"],
                        description_zh=tool_prose_zh["run_skill_script"],
                        inputs=(
                            '{"skill_name": "str", "script_path": "str", '
                            '"params": "str", "source": "str"}'
                        ),
                        output_type="string",
                        params={
                            "local_skills_dir": skill_snapshot_root
                            or CONTAINER_SKILLS_PATH,
                            "isolated_skills_root": bool(skill_snapshot_root),
                            "workspace_path": file_context.get("workspace_path"),
                            "authorized_skill_names": sorted(skill_config_values),
                        },
                        source="builtin",
                        usage="builtin",
                        metadata=skill_context,
                    ),
                    ToolConfig(
                        class_name="ReadSkillMdTool",
                        name="read_skill_md",
                        description=tool_prose_en["read_skill_md"],
                        description_zh=tool_prose_zh["read_skill_md"],
                        inputs='{"skill_name": "str", "additional_files": "list[str]"}',
                        output_type="string",
                        params={
                            "local_skills_dir": skill_snapshot_root
                            or CONTAINER_SKILLS_PATH,
                            "isolated_skills_root": bool(skill_snapshot_root),
                            **(
                                {"authorized_skill_names": sorted(skill_config_values)}
                                if runtime_skill_snapshot is not None
                                else {}
                            ),
                        },
                        source="builtin",
                        usage="builtin",
                        metadata=skill_context,
                    ),
                    ToolConfig(
                        class_name="ReadSkillConfigTool",
                        name="read_skill_config",
                        description=tool_prose_en["read_skill_config"],
                        description_zh=tool_prose_zh["read_skill_config"],
                        inputs='{"skill_name": "str"}',
                        output_type="string",
                        params={
                            "local_skills_dir": skill_snapshot_root
                            or CONTAINER_SKILLS_PATH,
                            "config_overrides": skill_config_values,
                            **(
                                {"authorized_skill_names": sorted(skill_config_values)}
                                if runtime_skill_snapshot is not None
                                else {}
                            ),
                        },
                        source="builtin",
                        usage="builtin",
                        metadata=skill_context,
                    ),
                ]
            )

        tools.extend(
            [
                ToolConfig(
                    class_name="DownloadFromS3Tool",
                    name="download_from_s3",
                    description=tool_prose_en["download_from_s3"],
                    description_zh=tool_prose_zh["download_from_s3"],
                    inputs=json.dumps(
                        {
                            "s3_path": {
                                "type": "string",
                                "description": tool_prose_en["s3_path"],
                                "description_zh": tool_prose_zh["s3_path"],
                            },
                            "local_filename": {
                                "type": "string",
                                "description": tool_prose_en["local_filename"],
                                "description_zh": tool_prose_zh["local_filename"],
                                "nullable": True,
                            },
                        }
                    ),
                    output_type="string",
                    params={
                        "workspace_path": file_context.get(
                            "workspace_path", "/mnt/nexent/workdir"
                        )
                    },
                    source="builtin",
                    usage="builtin",
                    metadata=file_context,
                ),
                ToolConfig(
                    class_name="UploadToS3Tool",
                    name="upload_to_s3",
                    description=tool_prose_en["upload_to_s3"],
                    description_zh=tool_prose_zh["upload_to_s3"],
                    inputs=json.dumps(
                        {
                            "file_path": {
                                "type": "string",
                                "description": tool_prose_en["file_path"],
                                "description_zh": tool_prose_zh["file_path"],
                            },
                            "target_filename": {
                                "type": "string",
                                "description": tool_prose_en["target_filename"],
                                "description_zh": tool_prose_zh["target_filename"],
                                "nullable": True,
                            },
                        }
                    ),
                    output_type="string",
                    params={
                        "workspace_path": file_context.get(
                            "workspace_path", "/mnt/nexent/workdir"
                        )
                    },
                    source="builtin",
                    usage="builtin",
                    metadata=file_context,
                ),
            ]
        )
        return tools
    except Exception as e:
        logger.warning(f"Failed to load skill script tool: {e}")
        return []


def _inject_plan_tools(tools: List[ToolConfig], enable_planning: bool) -> None:
    """Inject plan tool configs into the given tools list if enable_planning is True."""
    if not enable_planning:
        return

    plan_names = {"create_plan", "update_plan_step"}
    if any(t.name in plan_names for t in tools):
        return

    # Protocol fields stay fixed while prose follows the run language at render time.
    tool_prose_en = get_builtin_tool_descriptions("en")
    tool_prose_zh = get_builtin_tool_descriptions("zh")
    tools.extend(
        [
            ToolConfig(
                class_name="CreatePlanTool",
                name="create_plan",
                description=tool_prose_en["create_plan"],
                description_zh=tool_prose_zh["create_plan"],
                inputs='{"title": "string", "steps": "array"}',
                output_type="object",
                params={},
                source="builtin",
            ),
            ToolConfig(
                class_name="UpdatePlanStepTool",
                name="update_plan_step",
                description=tool_prose_en["update_plan_step"],
                description_zh=tool_prose_zh["update_plan_step"],
                inputs='{"step_id": "string", "status": "string"}',
                output_type="object",
                params={},
                source="builtin",
            ),
        ]
    )


async def create_tool_config_list(
    agent_id,
    tenant_id,
    user_id,
    version_no: int = 0,
    tool_params: Optional[ToolParamsRequest | Dict[str, Any]] = None,
    runtime_skill_snapshot: Optional[List[Dict[str, Any]]] = None,
    runtime_knowledge_tools: Optional[List[Dict[str, Any]]] = None,
    language: str = "zh",
):
    tool_config_list = []
    langchain_tools = await discover_langchain_tools()
    normalized_tool_params = _normalize_tool_params_request(tool_params)

    tools_list = _resolve_runtime_tool_records(
        agent_id=agent_id,
        tenant_id=tenant_id,
        version_no=version_no,
        runtime_skill_snapshot=runtime_skill_snapshot,
    )

    # Look up agent name for use in error messages.
    if runtime_knowledge_tools is not None:
        from management.services.knowledge_base.mount import MANAGED_CLASSES

        tools_list = [
            tool for tool in tools_list if tool.get("class_name") not in MANAGED_CLASSES
        ]
        tools_list.extend(
            copy.deepcopy(
                [
                    tool
                    for tool in runtime_knowledge_tools
                    if tool.get("class_name") in MANAGED_CLASSES
                ]
            )
        )

    # Agent name is optional for tool_params matching (matching uses tool identifiers only),
    # but we include it in error messages so callers can identify which agent/tool caused a failure.
    agent_info = search_agent_info_by_agent_id(
        agent_id=agent_id, tenant_id=tenant_id, version_no=version_no
    )
    agent_name = agent_info.get("name") if agent_info else None
    agent_tool_overrides = _get_agent_tool_overrides(normalized_tool_params, agent_name)

    tool_keys_seen = set()
    for tool in tools_list:
        tool_identifier = tool.get("name") or tool.get("class_name")
        # System-managed tools are injected below with run-scoped metadata. Ignore
        # legacy agent bindings so they cannot create duplicate tool definitions.
        if tool_identifier in SYSTEM_MANAGED_TOOL_NAMES:
            continue
        if tool_identifier in tool_keys_seen:
            raise ValidationError(
                f"Duplicate tool identifier '{tool_identifier}' found in agent '{agent_name or agent_id}'."
            )
        tool_keys_seen.add(tool_identifier)

        override_params = None
        if tool.get("name") in agent_tool_overrides:
            override_params = agent_tool_overrides[tool.get("name")]
        elif tool.get("class_name") in agent_tool_overrides:
            override_params = agent_tool_overrides[tool.get("class_name")]

        # Independent AIDP endpoint, credential, and default KDS scope are
        # instance configuration. Request-level config overrides must not
        # rewrite them; forward() may still receive a per-call kds_list.
        effective_override_params = (
            None
            if tool.get("class_name") == "IndependentAidpSearchTool"
            else override_params
        )
        param_dict = _merge_tool_params(tool, effective_override_params)
        if tool.get("class_name") == "DeepSeekSearchTool":
            param_dict.pop("localization", None)
            param_dict.pop("max_content_chars", None)
            # Run language is authoritative over persisted or request-level tool parameters.
            param_dict["language"] = language
        if tool.get("class_name") == "AidpSearchTool":
            # Credentials are backend-owned since the v7.1 permission
            # redesign; populate them from the central constants (the
            # database row may carry a stale value).
            param_dict.pop("server_url", None)
            param_dict.pop("api_key", None)
            param_dict.pop("tenant_id", None)
            param_dict.update(
                {
                    "server_url": AIDP_SERVER_URL,
                    "api_key": AIDP_API_KEY,
                    "tenant_id": AIDP_TENANT_ID,
                }
            )

        if tool.get("class_name") == "IndependentAidpSearchTool":
            if not param_dict.get("server_url") or not param_dict.get("api_key"):
                raise ValidationError(
                    "Independent AIDP search requires server_url and api_key in its tool configuration."
                )

        # Inject the runtime whitelist for AidpSearchTool. ``param_dict``
        # already contains the resolved per-run range (inherit/override/
        # disabled). Intersect it with the current remote catalog and local
        # permissions, but never intersect it with the agent defaults again.
        _allowed_kds_set: set[str] = set()
        _kds_name_to_id_map: dict[str, str] = {}
        if tool.get("class_name") == "AidpSearchTool":
            try:
                from ext_components.aidp.services.aidp_access_service import (
                    resolve_current_aidp_access,
                )

                snapshot = await run_blocking(
                    "resolve-runtime-aidp-access",
                    resolve_current_aidp_access,
                    server_url=AIDP_SERVER_URL,
                    api_key=AIDP_API_KEY,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    aidp_tenant_id=AIDP_TENANT_ID,
                    lane="control-io",
                    owner="agents.create_agent_info",
                )
                _allowed_kds_set = set(snapshot.accessible_id_set)
                _kds_name_to_id_map = {
                    **snapshot.name_to_id,
                    **snapshot.tenant_name_to_id,
                }
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "AIDP access snapshot lookup failed: %s",
                    exc,
                )

            configured_kds = param_dict.get("kds_list") or []
            if isinstance(configured_kds, str):
                try:
                    configured_kds = json.loads(configured_kds)
                except json.JSONDecodeError:
                    configured_kds = []
            if not isinstance(configured_kds, list):
                configured_kds = []
            configured_kds = [str(kds_id) for kds_id in configured_kds]
            configured_kds_set = set(configured_kds)
            # The execution whitelist is the effective tool range, not every
            # KDS the user could access. This prevents model-supplied arguments
            # from expanding a conversation-scoped selection.
            _allowed_kds_set.intersection_update(configured_kds_set)
            # Keep the full per-run scope in params so the SDK can distinguish
            # configured-but-denied knowledge bases from unavailable ones.
            param_dict["kds_list"] = configured_kds
            _kds_name_to_id_map = {
                name: kds_id
                for name, kds_id in _kds_name_to_id_map.items()
                if kds_id in configured_kds_set
            }

        tool_config = ToolConfig(
            class_name=tool.get("class_name"),
            name=tool.get("name"),
            description=tool.get("description"),
            description_zh=tool.get("description_zh"),
            inputs=tool.get("inputs"),
            output_type=tool.get("output_type"),
            params=param_dict,
            source=tool.get("source"),
            usage=tool.get("usage"),
        )

        if tool.get("class_name") == "AidpSearchTool":
            # Carry over the runtime whitelist; merge into any existing
            # metadata so langchain_tool references that may already be
            # attached are preserved. ``tool_config.metadata`` defaults to
            # None on ToolConfig, so guard the spread accordingly.
            existing = (
                tool_config.metadata if isinstance(tool_config.metadata, dict) else {}
            )
            tool_config.metadata = {
                **existing,
                "allowed_kds_set": sorted(_allowed_kds_set),
                "kds_name_to_id_map": _kds_name_to_id_map,
            }
            tool_class_name = tool.get("class_name")
            for langchain_tool in langchain_tools:
                if langchain_tool.name == tool_class_name:
                    existing2 = (
                        tool_config.metadata
                        if isinstance(tool_config.metadata, dict)
                        else {}
                    )
                    tool_config.metadata = {
                        **existing2,
                        "langchain_tool": langchain_tool,
                    }
                    break

        if tool.get("class_name") == "IndependentAidpSearchTool":
            existing = (
                tool_config.metadata if isinstance(tool_config.metadata, dict) else {}
            )
            tool_config.metadata = {
                **existing,
                "image_url_builder": create_ind_aidp_image_url_builder(
                    agent_id=agent_id,
                    tool_id=tool.get("tool_id"),
                    tenant_id=tenant_id,
                    version_no=version_no,
                    aidp_tenant_id=param_dict.get("tenant_id") or "aidp",
                ),
            }

        if (
            tool.get("source") == "langchain"
            and tool.get("class_name") != "AidpSearchTool"
        ):
            tool_class_name = tool.get("class_name")
            for langchain_tool in langchain_tools:
                if langchain_tool.name == tool_class_name:
                    tool_config.metadata = langchain_tool
                    break

        # Extract document_paths for KnowledgeBaseSearchTool (internal access control, not in DB schema)
        document_paths = None
        if override_params and "document_paths" in override_params:
            document_paths = override_params.get("document_paths")
        # Also check using the tool name as key
        if not document_paths:
            kb_overrides = agent_tool_overrides.get("knowledge_base_search")
            if kb_overrides and "document_paths" in kb_overrides:
                document_paths = kb_overrides.get("document_paths")

        # special logic for search tools that may use reranking models
        if tool_config.class_name == "KnowledgeBaseSearchTool":
            rerank = tool_config.params.get("rerank", False)
            rerank_model_name = tool_config.params.get("rerank_model_name", "")
            rerank_model = None
            if rerank and rerank_model_name:
                rerank_model = get_rerank_model(
                    tenant_id=tenant_id, model_name=rerank_model_name
                )

            # Build display_name to index_name mapping for LLM parameter conversion
            # Also build reverse mapping (index_name -> display_name) for knowledge_base_summary
            configured_index_names = tool_config.params.get("index_names") or []
            tool_config.params["index_names"] = configured_index_names

            # Enforce knowledge-base-level read permission for the chatting user.
            # Agent-level permission controls "who can use this agent", but each knowledge
            # base has its own "who can read" permission (group_ids + ingroup_permission).
            # Keep the complete configured scope in params so the SDK can distinguish
            # configured-but-denied indices from unconfigured ones.
            allowed_index_names = configured_index_names
            if configured_index_names:
                allowed_index_names = ElasticSearchService.filter_accessible_indices(
                    configured_index_names,
                    user_id=user_id,
                    tenant_id=tenant_id,
                )

            display_name_to_index_map = {}
            index_name_to_display_map = {}
            if configured_index_names:
                knowledge_name_map = get_knowledge_name_map_by_index_names(
                    configured_index_names,
                    tenant_id=tenant_id,
                )
                # Reverse the mapping: display_name (knowledge_name) -> index_name
                for idx_name, kb_name in knowledge_name_map.items():
                    display_name_to_index_map[kb_name] = idx_name
                    index_name_to_display_map[idx_name] = kb_name

            tool_config.metadata = {
                "vdb_core": get_vector_db_core(),
                "embedding_model": None,
                "rerank_model": rerank_model,
                "display_name_to_index_map": display_name_to_index_map,
                "index_name_to_display_map": index_name_to_display_map,
                # Internal access control: restrict results to specific document paths (path_or_urls)
                "document_paths": document_paths,
                # Defense-in-depth whitelist: forward() will reject any index not in this list,
                # even if the LLM fabricates an unauthorized index name.
                "allowed_index_names": list(allowed_index_names),
            }

            if not allowed_index_names:
                # Keep the tool so the SDK can report which configured indices lack read access.
                logger.warning(
                    "Keeping knowledge_base_search tool for agent '%s' with no accessible "
                    "knowledge bases for user '%s' after permission filtering. "
                    "Tool will return a permission-denial message at search time.",
                    agent_name or agent_id,
                    user_id,
                )
                # Append the tool and skip embedding model lookup (no index to lookup from)
                tool_config_list.append(tool_config)
                continue

            embedding_model, _, _ = get_embedding_model_by_index_name(
                tenant_id,
                allowed_index_names[0],
            )
            if not embedding_model:
                raise ValidationError(
                    f"No embedding model found for index '{allowed_index_names[0]}'. "
                    f"Please configure an embedding model for this knowledge base."
                )
            tool_config.metadata["embedding_model"] = embedding_model
        elif tool_config.class_name in [
            "DifySearchTool",
            "DataMateSearchTool",
            "RAGFlowSearchTool",
        ]:
            rerank = tool_config.params.get("rerank", False)
            rerank_model_name = tool_config.params.get("rerank_model_name", "")
            rerank_model = None
            if rerank and rerank_model_name:
                rerank_model = get_rerank_model(
                    tenant_id=tenant_id, model_name=rerank_model_name
                )

            tool_config.metadata = {
                "rerank_model": rerank_model,
            }
        elif tool_config.class_name == "AnalyzeTextFileTool":
            selected_model_id = param_dict.get("selected_model_id")
            tool_config.metadata = {
                "llm_model": get_llm_adapter(
                    tenant_id, selected_model_id, modality="llm_long_context"
                ),
                "storage_client": minio_client,
                "data_process_service_url": DATA_PROCESS_SERVICE,
                "validate_url_access": lambda urls: validate_urls_access(urls, user_id),
            }
        elif tool_config.class_name == "AnalyzeImageTool":
            selected_model_id = param_dict.get("selected_model_id")
            tool_config.metadata = {
                "vlm_model": get_vlm_adapter(tenant_id, selected_model_id, slot="vlm"),
                "storage_client": minio_client,
                "validate_url_access": lambda urls: validate_urls_access(urls, user_id),
            }
        elif tool_config.class_name == "AnalyzeAudioTool":
            selected_model_id = param_dict.get("selected_model_id")
            tool_config.metadata = {
                "vlm_model": get_vlm_adapter(tenant_id, selected_model_id, slot="vlm4"),
                "storage_client": minio_client,
                "validate_url_access": lambda urls: validate_urls_access(urls, user_id),
            }
        elif tool_config.class_name == "AnalyzeVideoTool":
            selected_model_id = param_dict.get("selected_model_id")
            tool_config.metadata = {
                "vlm_model": get_vlm_adapter(tenant_id, selected_model_id, slot="vlm3"),
                "storage_client": minio_client,
                "validate_url_access": lambda urls: validate_urls_access(urls, user_id),
            }
        elif tool_config.class_name in ["DownloadFromS3Tool", "UploadToS3Tool"]:
            tool_config.metadata = {
                "minio_client": minio_client,
                "user_id": user_id,
                "tenant_id": tenant_id,
            }

        tool_config_list.append(tool_config)

    return tool_config_list


async def discover_langchain_tools():
    """
    Discover LangChain tools implemented with the `@tool` decorator.

    Returns:
        list: List of discovered LangChain tool instances
    """
    from management.services.tool.langchain import discover_langchain_modules

    langchain_tools = []

    # ----------------------------------------------
    # Discover LangChain tools implemented with the
    # `@tool` decorator and convert them to ToolConfig
    # ----------------------------------------------
    try:
        # Use the utility function to discover all BaseTool objects
        discovered_tools = discover_langchain_modules()

        for obj, filename in discovered_tools:
            try:
                # Log successful tool discovery
                logger.info(f"Loaded LangChain tool '{obj.name}' from {filename}")
                langchain_tools.append(obj)
            except Exception as e:
                logger.error(f"Error processing LangChain tool from {filename}: {e}")

    except Exception as e:
        logger.error(f"Unexpected error scanning LangChain tools directory: {e}")

    return langchain_tools


def filter_mcp_servers_and_tools(
    input_agent_config: AgentConfig, mcp_info_dict
) -> list:
    """
    Filter mcp servers and tools, only keep the actual used mcp servers
    Support multi-level agent, recursively check all sub-agent tools
    """
    used_mcp_urls = set()

    # Recursively check all agent tools
    def check_agent_tools(agent_config: AgentConfig):
        # Check current agent tools
        for tool in agent_config.tools:
            if tool.source == "mcp" and tool.usage in mcp_info_dict:
                used_mcp_urls.add(mcp_info_dict[tool.usage]["remote_mcp_server"])

        # Recursively check sub-agents (only internal AgentConfig, not external A2A)
        for sub_agent_config in agent_config.worker_agents:
            check_agent_tools(sub_agent_config)

    # Check all agent tools
    check_agent_tools(input_agent_config)

    return list(used_mcp_urls)
