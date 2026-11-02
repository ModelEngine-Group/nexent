# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


from __future__ import annotations

import json
import logging
from copy import copy, deepcopy

import nexent.core.tools as tool_types
from nexent.core.agents.contracts.config import ToolConfig
from nexent.core.agents.resources.compatibility.smolagents_tools import from_langchain
from nexent.core.agents.resources.tool_parameters import apply_mcp_tool_parameters
from nexent.core.agents.resources.tool_user_context import apply_user_context_to_mcp_tool


logger = logging.getLogger(__name__)


class ToolResources:
    """Create authorized bindings without owning an Agent decision loop."""

    def _resolve_tool_class(self, name):
        return getattr(tool_types, name, None)

    def create_local_tool(self, tool_config: ToolConfig):
        class_name = tool_config.class_name
        params = tool_config.params
        tool_class = self._resolve_tool_class(class_name)
        if tool_class is None:
            raise ValueError(f"{class_name} not found in local")
        else:
            if class_name == "KnowledgeBaseSearchTool":
                # Filter out conflicting parameters from params to avoid conflicts.
                # Parameters declared with exclude=True cannot be passed to __init__
                # due to smolagents.tools.Tool wrapper restrictions; they are set as
                # attributes on the instance after construction, sourced from metadata.
                # `document_paths` is intentionally hidden from the LLM and only
                # populated via tool_params from the northbound interface.
                filtered_params = {k: v for k, v in params.items()
                                   if k not in ["vdb_core", "embedding_model", "observer", "rerank_model", "display_name_to_index_map"]}
                # Create instance with only non-excluded parameters
                tools_obj = tool_class(**filtered_params)
                # Set excluded parameters directly as attributes after instantiation
                # This bypasses smolagents wrapper restrictions
                tools_obj.observer = self.observer
                tools_obj.vdb_core = tool_config.metadata.get(
                    "vdb_core", None) if tool_config.metadata else None
                tools_obj.embedding_model = tool_config.metadata.get(
                    "embedding_model", None) if tool_config.metadata else None
                tools_obj.rerank_model = tool_config.metadata.get(
                    "rerank_model", None) if tool_config.metadata else None
                tools_obj.display_name_to_index_map = tool_config.metadata.get(
                    "display_name_to_index_map", {}) if tool_config.metadata else {}
                # Internal access control: restrict results to documents whose
                # path_or_url is in the allow list. Only the northbound interface
                # may populate this; never the LLM.
                tools_obj.set_document_paths(
                    tool_config.metadata.get(
                        "document_paths") if tool_config.metadata else None
                )
                tools_obj.set_allowed_index_names(
                    tool_config.metadata.get("allowed_index_names")
                    if tool_config.metadata else None
                )
            elif class_name in ["DifySearchTool", "DataMateSearchTool"]:
                # These parameters have exclude=True and cannot be passed to __init__
                filtered_params = {k: v for k, v in params.items()
                                   if k not in ["observer", "rerank_model"]}
                tools_obj = tool_class(**filtered_params)
                tools_obj.observer = self.observer
                tools_obj.rerank_model = tool_config.metadata.get(
                    "rerank_model", None) if tool_config.metadata else None
            elif class_name == "RAGFlowSearchTool":
                # RAGFlowSearchTool does not accept rerank/rerank_model_name as
                # init params — RAGFlow handles reranking internally via its API.
                # The rerank_model attribute is set post-init for display and
                # observability purposes only (e.g., showing model info in the UI).
                filtered_params = {k: v for k, v in params.items()
                                   if k not in ["observer", "rerank_model", "rerank", "rerank_model_name"]}
                tools_obj = tool_class(**filtered_params)
                tools_obj.observer = self.observer
                tools_obj.rerank_model = tool_config.metadata.get(
                    "rerank_model", None) if tool_config.metadata else None
            elif class_name == "HaotianSearchTool":
                # Haotian uses reranking_enable/reranking_model_name (not rerank/rerank_model_name)
                filtered_params = {k: v for k, v in params.items()
                                   if k not in ["observer", "rerank_model", "rerank"]}
                tools_obj = tool_class(**filtered_params)
                tools_obj.observer = self.observer
            elif class_name == "AnalyzeTextFileTool":
                # Extract validate_url_access from metadata if it's callable
                validate_url_access = tool_config.metadata.get("validate_url_access") if tool_config.metadata else None
                if validate_url_access is not None and not callable(validate_url_access):
                    validate_url_access = None
                tools_obj = tool_class(observer=self.observer,
                                       llm_model=tool_config.metadata.get("llm_model", []),
                                       storage_client=tool_config.metadata.get("storage_client", []),
                                       data_process_service_url=tool_config.metadata.get("data_process_service_url", []),
                                       validate_url_access=validate_url_access,
                                       **params)
            elif class_name in ["AnalyzeImageTool", "AnalyzeAudioTool", "AnalyzeVideoTool"]:
                # Extract validate_url_access from metadata if it's callable
                validate_url_access = tool_config.metadata.get("validate_url_access") if tool_config.metadata else None
                if validate_url_access is not None and not callable(validate_url_access):
                    validate_url_access = None
                tools_obj = tool_class(observer=self.observer,
                                       vlm_model=tool_config.metadata.get("vlm_model", []),
                                       storage_client=tool_config.metadata.get("storage_client", []),
                                       validate_url_access=validate_url_access,
                                       **params)
            elif class_name in ["StoreMemoryTool", "SearchMemoryTool"]:
                metadata = tool_config.metadata or {}
                tools_obj = tool_class()
                if tool_config.description is not None:
                    tools_obj.description = tool_config.description
                if tool_config.inputs is not None:
                    tools_obj.inputs = json.loads(tool_config.inputs)
                if tool_config.output_type is not None:
                    tools_obj.output_type = tool_config.output_type
                tools_obj.observer = self.observer
                tools_obj.memory_config = metadata.get(
                    "memory_config", {}) if metadata else {}
                tools_obj.tenant_id = metadata.get(
                    "tenant_id", "") if metadata else ""
                tools_obj.user_id = metadata.get(
                    "user_id", "") if metadata else ""
                tools_obj.agent_id = metadata.get(
                    "agent_id", "") if metadata else ""
                raw_conversation_id = (
                    metadata.get("conversation_id", "") if metadata else ""
                )
                tools_obj.conversation_id = (
                    str(raw_conversation_id)
                    if raw_conversation_id not in (None, "")
                    else ""
                )
                tools_obj.memory_user_config = metadata.get(
                    "memory_user_config", None) if metadata else None
                tools_obj.memory_service = metadata.get(
                    "memory_service", None) if metadata else None
                tools_obj.embedding_configured = metadata.get(
                    "embedding_configured", True
                ) if metadata else True
                if class_name == "SearchMemoryTool":
                    tools_obj.memory_context_service = metadata.get(
                        "memory_context_service", None) if metadata else None
                else:
                    tools_obj.memory_context_service = None
            elif class_name == "AidpSearchTool":
                # kds_name_to_id_map is exclude=True; inject via metadata after init
                filtered_params = {k: v for k, v in params.items()
                                   if k not in ["kds_name_to_id_map"]}
                tools_obj = tool_class(**filtered_params)
                tools_obj.observer = self.observer
                tools_obj.kds_name_to_id_map = tool_config.metadata.get(
                    "kds_name_to_id_map", {}) if tool_config.metadata else {}
                # Install the KDS whitelist so the tool only retrieves from
                # KBs the current user is permitted to see.  Guard against
                # ``metadata=None`` the same way every other branch does
                # (``.get(...) if tool_config.metadata else ...``).
                allowed_raw = (
                    tool_config.metadata.get("allowed_kds_set")
                    if tool_config.metadata else None
                )
                if allowed_raw is not None:
                    try:
                        tools_obj.set_allowed_kds([str(k) for k in allowed_raw])
                    except Exception as exc:
                        logger.warning(
                            "Failed to install Aidp whitelist from metadata: %s; "
                            "falling back to an empty whitelist", exc,
                        )
                        tools_obj.set_allowed_kds([])
                else:
                    # Whitelist not set by backend → treat as uninstalled.
                    tools_obj.set_allowed_kds(None)
            elif class_name == "IndependentAidpSearchTool":
                filtered_params = {
                    key: value
                    for key, value in params.items()
                    if key not in ["observer", "image_url_builder", "rerank_model", "rerank"]
                }
                tools_obj = tool_class(**filtered_params)
                tools_obj.observer = self.observer
                tools_obj.image_url_builder = (
                    tool_config.metadata.get("image_url_builder")
                    if tool_config.metadata else None
                )
            elif class_name in ["DownloadFromS3Tool", "UploadToS3Tool"]:
                metadata = tool_config.metadata or {}
                tools_obj = tool_class(
                    workspace_path=params.get("workspace_path", "/mnt/nexent"),
                    minio_client=metadata.get("minio_client"),
                    user_id=metadata.get("user_id", ""),
                    tenant_id=metadata.get("tenant_id", ""),
                    observer=self.observer,
                )
            else:
                tools_obj = tool_class(**params)
                if hasattr(tools_obj, 'observer'):
                    tools_obj.observer = self.observer
            if tool_config.inputs and hasattr(tools_obj, "inputs"):
                parsed_inputs = tool_config.inputs
                if isinstance(parsed_inputs, str):
                    try:
                        parsed_inputs = json.loads(parsed_inputs)
                    except (TypeError, ValueError):
                        parsed_inputs = None
                if isinstance(parsed_inputs, dict):
                    tools_obj.inputs = parsed_inputs
            if tool_config.output_type and hasattr(tools_obj, "output_type"):
                tools_obj.output_type = tool_config.output_type
            return tools_obj


    def create_langchain_tool(self, tool_config: ToolConfig):
        tool_obj = tool_config.metadata
        return from_langchain(tool_obj)


    def create_mcp_tool(self, class_name):
        if self.mcp_tool_collection is None:
            raise ValueError("MCP tool collection is not initialized")
        tool_obj = next(
            (tool for tool in self.mcp_tool_collection.tools if tool.name == class_name),
            None
        )
        if tool_obj is None:
            raise ValueError(f"{class_name} not found in MCP server")
        # Collections may be shared by multiple runs; never wrap their template.
        tool_obj = copy(tool_obj)
        tool_obj.inputs = deepcopy(tool_obj.inputs)
        return apply_user_context_to_mcp_tool(tool_obj, self.user_context)


    def create_builtin_tool(self, tool_config: ToolConfig):
        """Create a builtin tool instance.

        Args:
            tool_config: Tool configuration with class_name, params, and optional metadata.

        Returns:
            Tool instance

        Raises:
            ValueError: If builtin tool is not found
        """
        class_name = tool_config.class_name
        params = tool_config.params or {}

        if class_name == "RunSkillScriptTool":
            from nexent.core.tools.run_skill_script_tool import RunSkillScriptTool
            metadata = tool_config.metadata or {}
            kwargs = dict(
                local_skills_dir=params.get("local_skills_dir"),
                agent_id=metadata.get("agent_id"),
                tenant_id=metadata.get("tenant_id"),
                version_no=metadata.get("version_no", 0),
                observer=self.observer,
                authorized_skill_names=params.get("authorized_skill_names"),
            )
            if params.get("isolated_skills_root"):
                kwargs["isolated_skills_root"] = True
            if params.get("workspace_path"):
                kwargs["workspace_path"] = params["workspace_path"]
                kwargs["on_complete"] = lambda _result: self._push_file_workspace_to_sandbox()
            return RunSkillScriptTool(**kwargs)
        elif class_name == "ReadSkillMdTool":
            from nexent.core.tools.read_skill_md_tool import ReadSkillMdTool
            metadata = tool_config.metadata or {}
            kwargs = dict(
                local_skills_dir=params.get("local_skills_dir"),
                agent_id=metadata.get("agent_id"),
                tenant_id=metadata.get("tenant_id"),
                version_no=metadata.get("version_no", 0),
            )
            if params.get("authorized_skill_names") is not None:
                kwargs["authorized_skill_names"] = params["authorized_skill_names"]
            if params.get("isolated_skills_root"):
                kwargs["isolated_skills_root"] = True
            return ReadSkillMdTool(**kwargs)
        elif class_name == "ReadSkillConfigTool":
            from nexent.core.tools.read_skill_config_tool import ReadSkillConfigTool
            metadata = tool_config.metadata or {}
            kwargs = dict(
                local_skills_dir=params.get("local_skills_dir"),
                agent_id=metadata.get("agent_id"),
                tenant_id=metadata.get("tenant_id"),
                version_no=metadata.get("version_no", 0),
                config_overrides=params.get("config_overrides"),
            )
            if params.get("authorized_skill_names") is not None:
                kwargs["authorized_skill_names"] = params["authorized_skill_names"]
            return ReadSkillConfigTool(**kwargs)
        elif class_name == "DownloadFromS3Tool":
            from nexent.core.tools.download_from_s3_tool import DownloadFromS3Tool
            metadata = tool_config.metadata or {}
            return DownloadFromS3Tool(
                workspace_path=params.get("workspace_path", self.workspace_path or "/mnt/nexent/workdir"),
                minio_client=metadata.get("minio_client"),
                user_id=metadata.get("user_id", self.user_id or ""),
                tenant_id=metadata.get("tenant_id", self.tenant_id or ""),
                observer=self.observer,
                validate_url_access=metadata.get("validate_url_access"),
                on_download=lambda _result: self._push_file_workspace_to_sandbox(),
            )
        elif class_name == "UploadToS3Tool":
            from nexent.core.tools.upload_to_s3_tool import UploadToS3Tool
            metadata = tool_config.metadata or {}
            return UploadToS3Tool(
                workspace_path=params.get("workspace_path", self.workspace_path or "/mnt/nexent/workdir"),
                minio_client=metadata.get("minio_client"),
                user_id=metadata.get("user_id", self.user_id or ""),
                tenant_id=metadata.get("tenant_id", self.tenant_id or ""),
                observer=self.observer,
                run_id=metadata.get("run_id", self.workspace_run_id or ""),
                on_upload=self._record_workspace_upload,
                ensure_local_file=lambda _path: self._pull_file_workspace_from_sandbox(),
                uploaded_paths=self._workspace_uploaded_paths,
            )
        elif class_name == "CreatePlanTool":
            from nexent.core.tools.plan_tools import CreatePlanTool
            return CreatePlanTool()
        elif class_name == "UpdatePlanStepTool":
            from nexent.core.tools.plan_tools import UpdatePlanStepTool
            return UpdatePlanStepTool()
        elif class_name == "CreateScheduledTaskProposalTool":
            from nexent.core.tools.create_scheduled_task_tool import CreateScheduledTaskProposalTool
            metadata = tool_config.metadata or {}
            return CreateScheduledTaskProposalTool(
                create_proposal=metadata.get("create_proposal"),
                observer=self.observer,
            )
        else:
            raise ValueError(f"Unknown builtin tool: {class_name}")


    def create_tool(self, tool_config: ToolConfig):
        """create a tool instance according to the tool config"""
        if not isinstance(tool_config, ToolConfig):
            raise TypeError("tool_config must be a ToolConfig object")
        class_name = tool_config.class_name
        source = tool_config.source

        if source == "local":
            tool_obj = self.create_local_tool(tool_config)
        elif source == "mcp":
            tool_obj = self.create_mcp_tool(class_name)
            tool_obj = apply_mcp_tool_parameters(tool_obj, tool_config.params)
        elif source == "langchain":
            tool_obj = self.create_langchain_tool(tool_config)
        elif source == "builtin":
            tool_obj = self.create_builtin_tool(tool_config)
        else:
            raise ValueError(f"unsupported tool source: {source}")
        mapping = getattr(self, "workspace_mapping", None)
        if mapping is not None and class_name in {
            "CreateFileTool", "ReadFileTool", "DeleteFileTool", "DownloadFromS3Tool", "UploadToS3Tool",
        }:
            tool_obj.workspace_mapping = mapping
            if class_name in {"CreateFileTool", "ReadFileTool", "DeleteFileTool"}:
                tool_obj.init_path = str(mapping.host_root / "outputs")
        if source in {"local", "builtin", "mcp"}:
            try:
                setattr(tool_obj, "_nexent_execute_on_host", True)
            except (AttributeError, TypeError):
                pass
        return tool_obj
