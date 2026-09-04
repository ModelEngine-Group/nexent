from __future__ import annotations

import functools
import inspect
import io
import json
import logging
import os
import re
import shutil
import tarfile
import time
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence
from uuid import uuid4

from smolagents import ActionStep, AgentText, TaskStep, Timing
from smolagents.tools import Tool

from ...monitor import AgentRunMetadata, get_agent_monitoring_context, get_monitoring_manager
from ..models.openai_llm import OpenAIModel
from ..tools import *  # Used for tool creation, do not delete!!!
from ..utils.constants import THINK_PREFIX_PATTERN, THINK_TAG_PATTERN
from ..utils.observer import MessageObserver, ProcessType
from .agent_model import AgentConfig, AgentHistory, ModelConfig, ToolConfig
from .core_agent import CoreAgent, convert_code_format

if TYPE_CHECKING:
    from .context import ContextItemInput
    from .subagent_wrapper import SubAgentToolWrapper


# Safe base imports for Python interpreter - excludes file modification and system access modules
SAFE_PYTHON_INTERPRETER_IMPORTS = [
    "math", "cmath", "statistics", "decimal", "fractions", "random",
    "collections", "itertools", "functools", "heapq", "bisect", "array", "copy",
    "re", "string", "textwrap", "unicodedata",
    "datetime", "time", "calendar",
    "base64", "hashlib", "hmac",
    "json", "csv",
    "uuid", "pprint", "operator", "typing",
]


def get_local_python_authorized_imports() -> List[str]:
    """Return the imports permitted by Nexent's default local code executor."""
    from smolagents.local_python_executor import BASE_BUILTIN_MODULES

    return sorted(set(BASE_BUILTIN_MODULES) | set(SAFE_PYTHON_INTERPRETER_IMPORTS))


logger = logging.getLogger(__name__)

_WORKSPACE_UPLOAD_EXCLUDED_DIRS = {
    ".cache",
    ".npm",
    ".parcel-cache",
    ".pnpm-store",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}


def cleanup_run_workspace(
    workspace_path: str | None,
    workspace_run_id: str | None,
    logger_: logging.Logger | None = None,
) -> bool:
    """Delete one exact run workspace and its empty user directory."""
    if not workspace_path or not workspace_run_id:
        return False

    cleanup_logger = logger_ or logger
    workspace = Path(workspace_path).resolve()
    if workspace.name != workspace_run_id:
        cleanup_logger.error(
            "Refusing to clean workspace whose final component does not match run id: %s",
            workspace,
        )
        return False

    try:
        removed = workspace.exists()
        if removed:
            shutil.rmtree(workspace)
        try:
            workspace.parent.rmdir()
        except OSError:
            pass
        return removed
    except Exception as exc:
        cleanup_logger.error("Failed to clean run workspace %s: %s", workspace, exc)
        return False


def _ensure_non_empty_final_answer(answer: str, lang: str) -> str:
    """Return a user-visible fallback when final-answer cleanup removes all content."""
    if answer.strip():
        return answer
    logger.warning("Final answer was empty after removing reasoning content")
    if lang == "zh":
        return "智能体未能生成有效的最终回复，请重试或换一种方式描述需求。"
    return "The agent could not generate a valid final response. Please try again or rephrase your request."


def _tool_name(tool_obj: Any) -> str:
    """Return the most useful tool name for monitoring."""
    return (
        getattr(tool_obj, "name", None)
        or getattr(tool_obj, "__name__", None)
        or type(tool_obj).__name__
    )


def _has_host_tools(tools: List[Any]) -> bool:
    """Return whether the agent has tools marked for host-process execution."""
    return any(getattr(tool, "_nexent_execute_on_host", False) for tool in tools)


def _is_retriever_tool(tool_obj: Any) -> bool:
    """Classify tools that should use RETRIEVER rather than TOOL semantics."""
    name = type(tool_obj).__name__
    return name in ("KnowledgeBaseSearchTool", "SearchMemoryTool")


def _build_tool_input(callable_obj: Callable, args: tuple, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort conversion of tool call arguments into span input attributes."""
    try:
        signature = inspect.signature(callable_obj)
        bound = signature.bind_partial(*args, **kwargs)
        return dict(bound.arguments)
    except (TypeError, ValueError):
        tool_input: Dict[str, Any] = {}
        if args:
            tool_input["args"] = list(args)
        if kwargs:
            tool_input.update(kwargs)
        return tool_input


def _wrap_tool_with_monitoring(tool_obj: Any, agent_name: str) -> Any:
    """Wrap smolagents tools and callables with a tool span."""
    if getattr(tool_obj, "_nexent_monitoring_wrapped", False):
        return tool_obj

    monitoring_manager = get_monitoring_manager()
    tool_name = _tool_name(tool_obj)
    is_retriever_tool = _is_retriever_tool(tool_obj)

    def monitored_span(tool_input: Dict[str, Any]):
        if is_retriever_tool:
            return monitoring_manager.trace_retriever_call(
                tool_name,
                agent_name,
                tool_input,
            )
        return monitoring_manager.trace_tool_call(tool_name, agent_name, tool_input)

    def set_monitored_output(result: Any) -> None:
        if is_retriever_tool:
            monitoring_manager.set_retriever_output(result)
        else:
            monitoring_manager.set_tool_output(result)

    if hasattr(tool_obj, "forward") and callable(tool_obj.forward):
        original_forward = tool_obj.forward

        if inspect.iscoroutinefunction(original_forward):
            @functools.wraps(original_forward)
            async def monitored_forward(*args, **kwargs):
                tool_input = _build_tool_input(original_forward, args, kwargs)
                with monitored_span(tool_input):
                    result = await original_forward(*args, **kwargs)
                    set_monitored_output(result)
                    return result
        else:
            @functools.wraps(original_forward)
            def monitored_forward(*args, **kwargs):
                tool_input = _build_tool_input(original_forward, args, kwargs)
                with monitored_span(tool_input):
                    result = original_forward(*args, **kwargs)
                    set_monitored_output(result)
                    return result

        tool_obj.forward = monitored_forward
        setattr(tool_obj, "_nexent_monitoring_wrapped", True)
        return tool_obj

    if callable(tool_obj):
        original_callable = tool_obj

        if inspect.iscoroutinefunction(original_callable):
            @functools.wraps(original_callable)
            async def monitored_callable(*args, **kwargs):
                tool_input = _build_tool_input(original_callable, args, kwargs)
                with monitored_span(tool_input):
                    result = await original_callable(*args, **kwargs)
                    set_monitored_output(result)
                    return result
        else:
            @functools.wraps(original_callable)
            def monitored_callable(*args, **kwargs):
                tool_input = _build_tool_input(original_callable, args, kwargs)
                with monitored_span(tool_input):
                    result = original_callable(*args, **kwargs)
                    set_monitored_output(result)
                    return result

        setattr(monitored_callable, "_nexent_monitoring_wrapped", True)
        return monitored_callable

    return tool_obj


class NexentAgent:
    def __init__(self, observer: MessageObserver,
                 model_config_list: List[ModelConfig],
                 stop_event: Event,
                 mcp_tool_collection=None,
                 redis_client=None,
                 sandbox_config=None,
                 minio_client=None,
                 conversation_id=None,
                 user_id=None,
                 tenant_id=None,
                 workspace_path=None,
                 workspace_run_id=None,
                 minio_files=None):
        """
        Initialize the NexentAgent factory.

        Args:
            observer: MessageObserver instance
            model_config_list: List of model configurations
            stop_event: Threading event for stop control
            mcp_tool_collection: Optional MCP tool collection
            redis_client: Redis client for plan persistence
            sandbox_config: Optional SandboxConfig for sandbox isolation.
                When None, uses LocalPythonExecutor (backwards-compatible).
            minio_client: Optional MinIO client for output file sync.
                Required when sandbox_config.auto_sync_outputs is True.
            conversation_id: Optional conversation id for plan persistence.
            user_id: Optional user id for plan persistence.
            tenant_id: Optional tenant id for file isolation.
            workspace_path: Run-scoped host workspace path.
            workspace_run_id: Opaque run id used to validate cleanup scope.
            minio_files: Authorized files attached to the current request.
        """
        if not isinstance(observer, MessageObserver):
            raise TypeError("Create Observer Object with MessageObserver")

        self.observer = observer
        self.model_config_list = model_config_list
        self.stop_event = stop_event
        self.mcp_tool_collection = mcp_tool_collection
        self.redis_client = redis_client
        self.sandbox_config = sandbox_config
        self.minio_client = minio_client
        self.conversation_id = conversation_id
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.workspace_path = workspace_path
        self.workspace_run_id = workspace_run_id
        self.minio_files = list(minio_files or [])
        self._workspace_uploads: List[Dict[str, Any]] = []
        self._workspace_uploaded_paths: set[str] = set()
        self._sandbox_executors: List[Any] = []
        self._sandbox_skill_runners: List[Any] = []

        self.agent = None

    def create_model(self, model_cite_name: str):
        """create a model instance"""
        # Filter out None values and find matching model config
        model_config = next(
            (model_config for model_config in self.model_config_list
             if model_config is not None and model_config.cite_name == model_cite_name),
            None
        )
        if model_config is None:
            raise ValueError(f"Model {model_cite_name} not found")
        model = OpenAIModel(
            observer=self.observer,
            model_id=model_config.model_name,
            api_key=model_config.api_key,
            api_base=model_config.url,
            temperature=model_config.temperature,
            top_p=model_config.top_p,
            ssl_verify=model_config.ssl_verify if model_config.ssl_verify is not None else True,
            model_factory=model_config.model_factory,
            display_name=model_config.cite_name,
            extra_body=model_config.extra_body,
            max_output_tokens=model_config.max_output_tokens,
            timeout_seconds=model_config.timeout_seconds,
            prompt_cache=model_config.prompt_cache,
            **{
                key: value
                for key, value in {
                    "provider_usage_profile": model_config.provider_usage_profile,
                    "feature_capabilities": model_config.feature_capabilities,
                    "feature_preferences": model_config.feature_preferences,
                    "canonical_model_id": model_config.canonical_model_id,
                    "model_identity_metadata": model_config.model_identity_metadata,
                    "tokenizer_match_metadata": model_config.tokenizer_match_metadata,
                    "token_count_probe_metadata": model_config.token_count_probe_metadata,
                    "tokenizer_family": model_config.tokenizer_family,
                }.items()
                if value is not None
            },
        )
        model.stop_event = self.stop_event
        return model


    def create_local_tool(self, tool_config: ToolConfig):
        class_name = tool_config.class_name
        params = tool_config.params
        tool_class = globals().get(class_name)
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
        return Tool.from_langchain(tool_obj)

    def create_mcp_tool(self, class_name):
        if self.mcp_tool_collection is None:
            raise ValueError("MCP tool collection is not initialized")
        tool_obj = next(
            (tool for tool in self.mcp_tool_collection.tools if tool.name == class_name),
            None
        )
        if tool_obj is None:
            raise ValueError(f"{class_name} not found in MCP server")
        return tool_obj

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
            if params.get("workspace_path"):
                kwargs["workspace_path"] = params["workspace_path"]
                kwargs["on_complete"] = lambda _result: self._push_file_workspace_to_sandbox()
            return RunSkillScriptTool(**kwargs)
        elif class_name == "ReadSkillMdTool":
            from nexent.core.tools.read_skill_md_tool import ReadSkillMdTool
            metadata = tool_config.metadata or {}
            return ReadSkillMdTool(
                local_skills_dir=params.get("local_skills_dir"),
                agent_id=metadata.get("agent_id"),
                tenant_id=metadata.get("tenant_id"),
                version_no=metadata.get("version_no", 0),
            )
        elif class_name == "WriteSkillFileTool":
            from nexent.core.tools.write_skill_file_tool import WriteSkillFileTool
            metadata = tool_config.metadata or {}
            return WriteSkillFileTool(
                local_skills_dir=params.get("local_skills_dir"),
                agent_id=metadata.get("agent_id"),
                tenant_id=metadata.get("tenant_id"),
                version_no=metadata.get("version_no", 0),
            )
        elif class_name == "ReadSkillConfigTool":
            from nexent.core.tools.read_skill_config_tool import ReadSkillConfigTool
            metadata = tool_config.metadata or {}
            return ReadSkillConfigTool(
                local_skills_dir=params.get("local_skills_dir"),
                agent_id=metadata.get("agent_id"),
                tenant_id=metadata.get("tenant_id"),
                version_no=metadata.get("version_no", 0),
                config_overrides=params.get("config_overrides"),
            )
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
            from nexent.core.tools.create_scheduled_task_tool import (
                CreateScheduledTaskProposalTool,
            )
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
        try:
            class_name = tool_config.class_name
            source = tool_config.source

            if source == "local":
                tool_obj = self.create_local_tool(tool_config)
            elif source == "mcp":
                tool_obj = self.create_mcp_tool(class_name)
            elif source == "langchain":
                tool_obj = self.create_langchain_tool(tool_config)
            elif source == "builtin":
                tool_obj = self.create_builtin_tool(tool_config)
            else:
                raise ValueError(f"unsupported tool source: {source}")
            if source in {"local", "builtin", "mcp"}:
                try:
                    setattr(tool_obj, "_nexent_execute_on_host", True)
                except (AttributeError, TypeError):
                    pass
            return tool_obj
        except Exception as e:
            raise ValueError(f"Error in creating tool: {e}")

    def _wrap_subagent(
        self,
        inner_agent: Any,
        sub_agent_config: Any,
        agent_id: Any = None,
    ) -> "SubAgentToolWrapper":
        """Wrap a sub-agent ``Tool`` so the observer sees nesting boundaries.

        Both internal ``AgentConfig``-derived managed agents and external
        ``ExternalA2AAgentConfig``-derived wrappers funnel through here, so
        every nested invocation emits ``subagent_start``/``subagent_end``
        regardless of which kind of sub-agent was added to ``managed_agents``.
        """
        from .subagent_wrapper import SubAgentToolWrapper

        resolved_id = (
            agent_id
            if agent_id is not None
            else getattr(sub_agent_config, "agent_id", None)
            or getattr(sub_agent_config, "_sub_agent_id", None)
        )
        agent_name = (
            getattr(sub_agent_config, "name", None)
            or getattr(inner_agent, "name", None)
            or "subagent"
        )
        return SubAgentToolWrapper(
            inner_agent=inner_agent,
            observer=self.observer,
            agent_id=resolved_id,
            agent_name=str(agent_name),
        )

    def create_single_agent(
        self,
        agent_config: AgentConfig,
        _managed_context: bool = False,
        *,
        context_items_override: Sequence["ContextItemInput"] | None = None,
        _sandbox_tree_context: Optional[Dict[str, Any]] = None,
    ) -> CoreAgent:
        """
        Build a CoreAgent from ``agent_config``.

        Args:
            agent_config: AgentConfig describing this agent.
            _managed_context: Internal compatibility flag for managed agents.
            _sandbox_tree_context: Internal construction context used to share
                one session Docker container across the agent tree while each
                agent retains an isolated kernel.
        """
        if not isinstance(agent_config, AgentConfig):
            raise TypeError("agent_config must be a AgentConfig object")
        if _sandbox_tree_context is None:
            _sandbox_tree_context = {}

        try:
            model = self.create_model(agent_config.model_name)
            model.safe_input_budget_snapshot = getattr(
                agent_config,
                "safe_input_budget_snapshot",
                None,
            )
            model.capacity_snapshot = getattr(
                agent_config,
                "capacity_snapshot",
                None,
            )
            prompt_templates = agent_config.prompt_templates

            try:
                tool_list = [
                    _wrap_tool_with_monitoring(
                        self.create_tool(tool_config),
                        agent_config.name,
                    )
                    for tool_config in agent_config.tools
                ]
            except Exception as e:
                raise ValueError(f"Error in creating tool: {e}")

            try:
                # Create managed agents recursively. Session-scoped Docker agents
                # share one container for the tree but retain independent kernels.
                raw_managed_agents = []
                for sub_agent_config in agent_config.managed_agents:
                    inner_agent = self.create_single_agent(
                        sub_agent_config,
                        _managed_context=True,
                        _sandbox_tree_context=_sandbox_tree_context,
                    )
                    raw_managed_agents.append((inner_agent, sub_agent_config))
                managed_agents_list = [
                    self._wrap_subagent(inner_agent, sub_agent_config)
                    for inner_agent, sub_agent_config in raw_managed_agents
                ]
            except Exception as e:
                raise ValueError(f"Error in creating managed agent: {e}")

            # Create wrapper agents for external A2A agents - add them to managed_agents
            # so model can call them like: external_agent_name(task="...")
            if agent_config.external_a2a_agents:
                try:
                    from .a2a_agent_proxy import ExternalA2AAgentWrapper
                    for ext_agent_config in agent_config.external_a2a_agents:
                        a2a_agent_info = ext_agent_config.to_a2a_agent_info()
                        wrapper = ExternalA2AAgentWrapper(
                            agent_info=a2a_agent_info,
                            stop_event=self.stop_event,
                            observer=self.observer
                        )
                        managed_agents_list.append(
                            self._wrap_subagent(
                                wrapper,
                                ext_agent_config,
                                agent_id=str(ext_agent_config.agent_id),
                            )
                        )
                except Exception as e:
                    raise ValueError(f"Error in creating external A2A agent wrapper: {e}")

            # ContextManager is the only production context assembly path.
            # ContextPolicy controls whether adaptive compaction is active.
            from .context import ContextManager, ContextManagerConfig, ManagedContextRuntime

            ctx_config = (
                getattr(agent_config, "context_manager_config", None)
                or ContextManagerConfig()
            )
            context_manager = ContextManager(
                config=ctx_config,
                max_steps=agent_config.max_steps,
            )
            context_items = (
                list(context_items_override)
                if context_items_override is not None
                else (getattr(agent_config, "context_items", None) or [])
            )
            context_runtime = ManagedContextRuntime(
                context_manager,
                items=context_items,
            )

            # Build one code executor for this agent. Managed-agent orchestration
            # is a host-marked tool, so every agent needs its own kernel to avoid
            # nested execution deadlocks; session containers can still be shared.
            python_executor = None
            if self.sandbox_config is not None:
                from .sandbox import SandboxLevel, build_python_executor
                has_managed = bool(
                    agent_config.managed_agents
                    or getattr(agent_config, "external_a2a_agents", [])
                )
                python_executor = build_python_executor(
                    config=self.sandbox_config,
                    logger_=logger,
                    managed_agents_exist=has_managed,
                    host_tools_exist=_has_host_tools([
                        *tool_list,
                        *managed_agents_list,
                    ]),
                    session_container_group=_sandbox_tree_context.get(
                        "session_container_group"
                    ),
                )
                session_container_group = None
                if (
                    self.sandbox_config.level == SandboxLevel.DOCKER
                    and self.sandbox_config.scope.value == "session"
                ):
                    session_container_group = getattr(
                        python_executor,
                        "_nexent_session_container_group",
                        None,
                    )
                if session_container_group is not None:
                    existing_group = _sandbox_tree_context.setdefault(
                        "session_container_group",
                        session_container_group,
                    )
                    if existing_group is not session_container_group:
                        raise RuntimeError(
                            "Agent tree received multiple session sandbox containers"
                        )
                self._sandbox_executors.append(python_executor)
                if self.sandbox_config.level != SandboxLevel.LOCAL:
                    from .sandbox import SandboxSkillScriptRunner

                    configured_timeout = getattr(self.sandbox_config, "timeout_seconds", None)
                    skill_timeout = (
                        max(1, int(configured_timeout))
                        if isinstance(configured_timeout, (int, float))
                        and not isinstance(configured_timeout, bool)
                        else 300
                    )
                    script_runner = SandboxSkillScriptRunner(
                        python_executor,
                        timeout_seconds=skill_timeout,
                        workspace_path=self.workspace_path,
                        network_enabled=not self.sandbox_config.network_disabled,
                    )
                    for tool in tool_list:
                        bind_backend = getattr(tool, "bind_execution_backend", None)
                        if callable(bind_backend) and _tool_name(tool) == "run_skill_script":
                            bind_backend(
                                script_runner,
                                on_complete=lambda _result: self._pull_file_workspace_from_sandbox(),
                            )
                    self._sandbox_skill_runners.append(script_runner)
                # Eager warm-up for remote executors (skip for LOCAL which is instant).
                if self.sandbox_config.level != SandboxLevel.LOCAL:
                    try:
                        warm_start = time.time()
                        python_executor("[0, None]")
                        warm_dur = time.time() - warm_start
                        backend = getattr(python_executor, "_nexent_backend", "unknown")
                        if backend == "local":
                            logger.warning(
                                "Sandbox level '%s' unavailable; using LocalPythonExecutor instead "
                                "(scope=%s, warm-up %.2fs)",
                                self.sandbox_config.level.value,
                                self.sandbox_config.scope.value,
                                warm_dur,
                            )
                        else:
                            logger.info(
                                "Sandbox warmed up in %.2fs (backend=%s, level=%s, scope=%s)",
                                warm_dur,
                                backend,
                                self.sandbox_config.level.value,
                                self.sandbox_config.scope.value,
                            )
                    except Exception as warm_err:
                        logger.warning(
                            "Sandbox warm-up failed (%s): %s",
                            self.sandbox_config.level.value,
                            warm_err,
                        )
                # Store scope on NexentAgent so _cleanup_sandbox() can read it.
                self._sandbox_scope = self.sandbox_config.scope.value

            # Create the agent
            agent = CoreAgent(
                observer=self.observer,
                tools=tool_list,
                model=model,
                name=agent_config.name,
                description=agent_config.description,
                max_steps=agent_config.max_steps,
                prompt_templates=prompt_templates,
                provide_run_summary=agent_config.provide_run_summary,
                managed_agents=managed_agents_list,
                additional_authorized_imports=SAFE_PYTHON_INTERPRETER_IMPORTS,
                instructions=agent_config.instructions,
                context_runtime=context_runtime,
                enable_planning=agent_config.enable_planning,
                redis_client=self.redis_client,
                conversation_id=self.conversation_id,
                user_id=self.user_id,
                executor=python_executor,
                verification_config=getattr(agent_config, "verification_config", None),
                workspace_path=self.workspace_path,
            )
            agent.stop_event = self.stop_event

            # Wire plan tool deps if the plan tools are present in agent_config.tools.
            # CoreAgent already knows enable_planning (set above); use that to gate wiring.
            if agent.enable_planning:
                if (create_plan := agent.tools.get("create_plan")) is not None:
                    create_plan.observer = agent.observer
                    create_plan.plan_repo = agent.plan_repo
                    create_plan._on_plan_created = agent._on_plan_created
                    create_plan._get_conversation_id = agent._get_conversation_id
                    create_plan._get_user_id = agent._get_user_id
                if (update_step := agent.tools.get("update_plan_step")) is not None:
                    update_step.observer = agent.observer
                    update_step.plan_repo = agent.plan_repo
                    update_step._on_step_updated = agent._on_step_updated
                    update_step._get_conversation_id = agent._get_conversation_id
                    update_step._get_user_id = agent._get_user_id

            return agent
        except Exception as e:
            raise ValueError(f"Error in creating agent, agent name: {agent_config.name}, Error: {e}")

    def add_history_to_agent(self, history: List[AgentHistory]):
        """
        Add conversation history to agent's memory

        Args:
            history: List of conversation messages with role and content
        """
        if history is None:
            return

        if not isinstance(self.agent, CoreAgent):
            raise TypeError(f"agent must be a CoreAgent object, not {type(self.agent)}")

        if not all(isinstance(msg, AgentHistory) for msg in history):
            raise TypeError("history must be a list of AgentHistory objects")

        self.agent.memory.reset()
        # Add conversation history to memory sequentially
        for msg in history:
            if msg.role == 'user':
                # Create task step for user message
                self.agent.memory.steps.append(TaskStep(task=msg.content))
            elif msg.role == 'assistant':
                self.agent.memory.steps.append(ActionStep(step_number=len(self.agent.memory.steps) + 1,
                                                          timing=Timing(start_time=time.time()),
                                                          action_output=msg.content, model_output=msg.content))

        self.agent._history_step_count = len(self.agent.memory.steps)
    @staticmethod
    def _set_runtime_metadata_for_agent_tree(root_agent: CoreAgent, metadata: Dict[str, Any]):
        """Set isolated runtime metadata on internal and external sub-agents."""

        snapshots = []
        pending = [root_agent]
        visited = set()
        while pending:
            current = pending.pop()
            if not isinstance(current, CoreAgent) or id(current) in visited:
                continue
            visited.add(id(current))
            snapshots.append(("core", current, "metadata" in current.state, current.state.get("metadata")))
            current.state["metadata"] = deepcopy(metadata)
            children = getattr(current, "managed_agents", {}) or {}
            if isinstance(children, dict):
                child_values = children.values()
            elif isinstance(children, (list, tuple)):
                child_values = children
            else:
                child_values = ()
            for child in child_values:
                inner_agent = (
                    child
                    if isinstance(child, CoreAgent)
                    else getattr(child, "_inner", child)
                )
                if isinstance(inner_agent, CoreAgent):
                    pending.append(inner_agent)
                    continue

                set_runtime_metadata = getattr(inner_agent, "set_runtime_metadata", None)
                get_runtime_metadata = getattr(inner_agent, "get_runtime_metadata", None)
                if callable(set_runtime_metadata) and callable(get_runtime_metadata):
                    snapshots.append(("external", inner_agent, True, get_runtime_metadata()))
                    set_runtime_metadata(deepcopy(metadata))
        return snapshots

    @staticmethod
    def _restore_runtime_metadata_for_agent_tree(snapshots) -> None:
        """Restore agent state after one run, including failure and cancellation."""

        for agent_type, agent, existed, previous_value in snapshots:
            if agent_type == "external":
                agent.set_runtime_metadata(previous_value)
            elif existed:
                agent.state["metadata"] = previous_value
            else:
                agent.state.pop("metadata", None)

    def agent_run_with_observer(
        self,
        query: str,
        reset: bool = True,
        additional_args: Optional[Dict[str, Any]] = None,
    ):
        if not isinstance(self.agent, CoreAgent):
            raise TypeError(f"agent must be a CoreAgent object, not {type(self.agent)}")

        monitoring_manager = get_monitoring_manager()
        current_metadata = get_agent_monitoring_context() or AgentRunMetadata()
        metadata = replace(
            current_metadata,
            agent_name=current_metadata.agent_name or self.agent.agent_name,
            query=current_metadata.query if current_metadata.query is not None else query,
        )
        observer = self.agent.observer
        total_output_tokens = 0
        final_answer_for_trace = None
        turn_id = str(uuid4())
        self.agent._usage_turn_id = turn_id
        active_model = getattr(self.agent, "model", None)
        if active_model is not None:
            active_model.default_usage_turn_id = turn_id
        turn_call_records = []
        emitted_call_ids: set[str] = set()
        with monitoring_manager.start_agent_run(metadata):
            with monitoring_manager.trace_agent_step(
                "agent.run.loop",
                metadata,
                step_type="agent_loop",
            ):
                runtime_state_snapshots = []
                try:
                    query = self._prepare_file_workspace(query)
                    runtime_state_snapshots = self._set_runtime_metadata_for_agent_tree(
                        self.agent,
                        (additional_args or {}).get("metadata", {}),
                    )
                    step_log = None
                    run_kwargs = {"stream": True, "reset": reset}
                    if additional_args is not None:
                        run_kwargs["additional_args"] = additional_args
                    for step_log in self.agent.run(query, **run_kwargs):
                        # Add content to observer
                        if not isinstance(step_log, ActionStep):
                            continue

                        # Real tool-call chunks are emitted by CoreAgent
                        # (_emit_real_tool_chunks_from_code) right after the
                        # PARSE chunk, so we deliberately skip re-emitting them
                        # here to avoid duplicating the synthetic
                        # ``python_interpreter`` ToolCall that smolagents
                        # stamps on every action step.

                        # Emit token stats after each action step
                        step_duration = getattr(step_log.timing, "duration", None)
                        step_input = None
                        step_output = None
                        if hasattr(step_log, "token_usage") and step_log.token_usage is not None:
                            step_input = getattr(step_log.token_usage, "input_tokens", None)
                            step_output = getattr(step_log.token_usage, "output_tokens", None)
                        if step_output:
                            total_output_tokens += step_output

                        estimated_context = None
                        last_metric = None
                        if hasattr(self.agent, "step_metrics") and self.agent.step_metrics:
                            last_metric = self.agent.step_metrics[-1]
                            estimated_context = last_metric.get(
                                "memory_state", {}
                            ).get("estimated_input_tokens")

                        token_threshold = None
                        context_window_tokens = None
                        hard_input_budget_tokens = None
                        context_processing_mode = None
                        context_runtime = getattr(self.agent, "context_runtime", None)
                        if context_runtime is not None:
                            token_threshold = context_runtime.token_threshold
                            context_window_tokens = context_runtime.context_window_tokens
                            hard_input_budget_tokens = context_runtime.hard_input_budget_tokens
                            context_processing_mode = context_runtime.processing_mode

                        token_data = {
                            "step_number": step_log.step_number,
                            "duration": round(float(step_duration), 2) if step_duration is not None else 0.0,
                            "step_input_tokens": step_input,
                            "step_output_tokens": step_output,
                            "total_output_tokens": total_output_tokens,
                            "estimated_context_tokens": estimated_context,
                            "token_threshold": token_threshold,
                            "context_window_tokens": context_window_tokens,
                            "hard_input_budget_tokens": hard_input_budget_tokens,
                            "context_processing_mode": context_processing_mode,
                            "output_finish_reason": getattr(
                                getattr(self.agent, "model", None),
                                "last_finish_reason",
                                None,
                            ),
                        }
                        if last_metric:
                            compression = last_metric.get("compression", {}) or {}
                            token_data.update({
                                "compression_calls": compression.get("calls", 0),
                                "compression_input_tokens": compression.get("input_tokens", 0),
                                "compression_output_tokens": compression.get("output_tokens", 0),
                                "compression_cache_hits": compression.get("cache_hits", 0),
                                "compression_cache_types": compression.get("cache_types", []),
                                "compression_ratio": last_metric.get("compression_ratio", 0.0),
                                "uncompressed_est_tokens": last_metric.get("uncompressed_mem_est_input", 0),
                            })
                        active_model = getattr(self.agent, "model", None)
                        step_call_records = list(
                            getattr(active_model, "turn_provider_call_usages", ()) or ()
                        )
                        for call_record in step_call_records:
                            if call_record.call_id in emitted_call_ids:
                                continue
                            emitted_call_ids.add(call_record.call_id)
                            turn_call_records.append(call_record)
                        cache_usage = getattr(active_model, "last_prompt_cache_usage", None)
                        cache_advice = getattr(active_model, "last_provider_cache_advice", None)
                        if cache_usage is not None:
                            metrics_source = getattr(cache_usage, "metrics_source", "capability_unknown")
                            metrics_available = metrics_source not in {"none", "capability_unknown"}
                            capability_supported = bool(getattr(cache_advice, "supported", False))
                            token_data.update({
                                "provider_cache_status": (
                                    "available" if metrics_available else
                                    "unavailable" if capability_supported else
                                    "unsupported"
                                ),
                                "provider_cache_metrics_source": metrics_source,
                                "provider_cache_hit": bool(getattr(cache_usage, "provider_cache_hit", False)),
                                "provider_cached_input_tokens": int(
                                    getattr(cache_usage, "cached_input_tokens", 0) or 0
                                ),
                                "provider_uncached_input_tokens": int(
                                    getattr(cache_usage, "uncached_input_tokens", 0) or 0
                                ),
                            })
                        observer.add_message("", ProcessType.TOKEN_COUNT, json.dumps(token_data))

                        if hasattr(step_log, "error") and step_log.error is not None:
                            observer.add_message("", ProcessType.ERROR, str(step_log.error))

                    if step_log is None:
                        raise ValueError("Agent run produced no output")

                    final_answer = step_log.output  # Last log is the run's final_answer

                    if isinstance(final_answer, AgentText):
                        final_answer_str = convert_code_format(final_answer.to_string())
                    else:
                        # prepare for multi-modal final_answer
                        final_answer_str = convert_code_format(str(final_answer))
                    final_answer_str = re.sub(
                        THINK_TAG_PATTERN, "", final_answer_str, flags=re.DOTALL | re.IGNORECASE)
                    # Remove thinking prefix content (until two newlines)
                    final_answer_str = re.sub(
                        THINK_PREFIX_PATTERN, "", final_answer_str, flags=re.DOTALL)
                    final_answer_str = _ensure_non_empty_final_answer(
                        final_answer_str,
                        getattr(observer, "lang", "en"),
                    )
                    final_answer_for_trace = final_answer_str
                    context_limit = getattr(
                        getattr(self.agent, "context_runtime", None),
                        "context_window_tokens",
                        None,
                    )
                    from ..models.usage_aggregation import aggregate_turn_usage

                    turn_summary = aggregate_turn_usage(
                        turn_call_records,
                        context_limit_tokens=context_limit,
                    )
                    turn_summary["turn_id"] = turn_id
                    turn_usage_type = getattr(ProcessType, "TURN_USAGE", None)
                    if turn_usage_type is not None:
                        observer.add_message(
                            "",
                            turn_usage_type,
                            json.dumps(turn_summary, ensure_ascii=False),
                        )
                    monitoring_manager.set_openinference_output(final_answer_str)
                    observer.add_message(self.agent.agent_name,
                                         ProcessType.FINAL_ANSWER, final_answer_str)

                    # Check if we need to stop from external stop_event
                    if self.agent.stop_event.is_set():
                        observer.add_message(self.agent.agent_name, ProcessType.ERROR,
                                             "Agent execution interrupted by external stop signal")
                except Exception as e:
                    observer.add_message(agent_name=self.agent.agent_name, process_type=ProcessType.ERROR,
                                         content=f"Error in interaction: {str(e)}")
                    raise ValueError(f"Error in interaction: {str(e)}")

                finally:
                    self._restore_runtime_metadata_for_agent_tree(runtime_state_snapshots)
                    self._log_step_metrics()
                    try:
                        self._finalize_file_workspace()
                    finally:
                        self._cleanup_file_workspace()
                        self._cleanup_sandbox()

            if final_answer_for_trace is not None:
                if hasattr(self.agent, "step_metrics"):
                    monitoring_manager.set_agent_context_metrics(self.agent.step_metrics)
                monitoring_manager.set_openinference_output(final_answer_for_trace)

    def _record_workspace_upload(self, upload: Dict[str, Any]) -> None:
        """Collect one upload result for the frontend artifact event."""
        object_name = str(upload.get("object_name") or "")
        if object_name and any(item.get("object_name") == object_name for item in self._workspace_uploads):
            return
        self._workspace_uploads.append(upload)

    def _prepare_file_workspace(self, query: str) -> str:
        """Create the run workspace and download current-request attachments."""
        if not self.workspace_path:
            return query

        workspace = Path(self.workspace_path)
        (workspace / "inputs").mkdir(parents=True, exist_ok=True)
        (workspace / "outputs").mkdir(parents=True, exist_ok=True)
        download_tool = (getattr(self.agent, "tools", {}) or {}).get("download_from_s3")
        downloaded: List[Dict[str, str]] = []
        if self.minio_files and download_tool is None:
            raise RuntimeError("Uploaded files are present but download_from_s3 is unavailable")

        for index, item in enumerate(self.minio_files):
            if not isinstance(item, dict):
                continue
            object_name = str(item.get("object_name") or "").strip().lstrip("/")
            source_url = str(item.get("url") or "").strip()
            if object_name:
                bucket = getattr(getattr(download_tool, "minio_client", None), "default_bucket", None) or "nexent"
                source_url = f"s3://{bucket}/{object_name}"
            if not source_url:
                continue
            filename = os.path.basename(str(item.get("name") or object_name or f"file_{index}"))
            local_filename = f"inputs/{index:03d}_{filename}"
            result = json.loads(download_tool.forward(source_url, local_filename))
            downloaded.append({"name": filename, "path": result["local_path"]})

        file_lines = "\n".join(f"- {item['name']}: {item['path']}" for item in downloaded)
        workspace_note = (
            f"\n\nRun workspace: {workspace}\n"
            f"Write every generated file under: {workspace / 'outputs'}\n"
            "The code executor already runs in that outputs directory. Use bare relative "
            "paths such as 'report.pdf', not 'outputs/report.pdf', to avoid creating an "
            "outputs/outputs directory.\n"
            "Exception: run_skill_script(source='workspace') resolves script_path from the "
            "run workspace root. If code writes a generated script as bare 'build.js', call "
            "run_skill_script with script_path='outputs/build.js'. The generated script itself "
            "still writes output artifacts with bare filenames because its CWD is outputs.\n"
            "Direct subprocess, os.system, and shell calls for system commands are blocked by "
            "the code executor. Use run_skill_script with a skill-bundled wrapper, or use a "
            "shell-free Python/Node.js API instead. When sandbox networking is enabled, only a "
            "shell-free argv call to sys.executable -m pip install is permitted for dependency "
            "installation.\n"
            "For skill-creator output packages, create the new skill under outputs/<new-skill> "
            "with normal code-executor file APIs; write_skill_file edits installed tenant skills "
            "and does not create files in this run workspace.\n"
            "Files created there are uploaded to MinIO automatically when the run finishes."
        )
        if file_lines:
            workspace_note += f"\nUploaded files are available locally:\n{file_lines}"
        self._push_file_workspace_to_sandbox()
        self._initialize_sandbox_workspaces()
        return query + workspace_note

    def _sandbox_container(self) -> Any:
        """Return the active Docker container when the executor exposes one."""
        containers = self._sandbox_containers()
        return containers[0] if containers else None

    def _sandbox_containers(self) -> List[Any]:
        """Return every distinct Docker container used by this agent tree."""
        executors = list(self._sandbox_executors)
        root_executor = getattr(self.agent, "python_executor", None)
        if root_executor is not None and all(
            executor is not root_executor for executor in executors
        ):
            executors.append(root_executor)

        containers: List[Any] = []
        seen_keys = set()
        for executor in executors:
            container = getattr(executor, "container", None)
            if container is None:
                continue
            container_id = getattr(container, "id", None)
            key = container_id if isinstance(container_id, str) and container_id else id(container)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            containers.append(container)
        return containers

    def _uses_shared_file_workspace(self) -> bool:
        """Return whether the runtime and sandbox use the same workspace volume."""
        extra_kwargs = getattr(self.sandbox_config, "extra_kwargs", {}) or {}
        return bool(
            extra_kwargs.get("shared_workspace")
            and extra_kwargs.get("workspace_volume_name")
        )

    def _push_file_workspace_to_sandbox(self) -> None:
        """Copy the prepared host workspace into every Docker sandbox."""
        containers = self._sandbox_containers()
        if not containers or not self.workspace_path:
            return
        workspace = Path(self.workspace_path).resolve()
        if not workspace.exists() or workspace.drive:
            return
        shared_workspace = self._uses_shared_file_workspace()
        archive_bytes = None
        if not shared_workspace:
            archive = io.BytesIO()
            with tarfile.open(fileobj=archive, mode="w") as tar:
                tar.add(workspace, arcname=str(workspace).lstrip("/"), recursive=True)
            archive_bytes = archive.getvalue()

        for container in containers:
            if archive_bytes is not None and not container.put_archive("/", archive_bytes):
                raise RuntimeError("Failed to copy run workspace into the sandbox")
            self._grant_sandbox_output_access(container, workspace)

    def _initialize_sandbox_workspaces(self) -> None:
        """Set every Docker kernel's cwd and workspace environment for this run."""
        if not self.workspace_path:
            return
        workspace = Path(self.workspace_path).resolve()
        output_dir = workspace / "outputs"
        bootstrap_code = (
            "import os as _nexent_os\n"
            f"_nexent_workspace = {json.dumps(str(workspace))}\n"
            f"_nexent_output_dir = {json.dumps(str(output_dir))}\n"
            "_nexent_os.environ['NEXENT_WORKSPACE'] = _nexent_workspace\n"
            "_nexent_os.environ['NEXENT_OUTPUT_DIR'] = _nexent_output_dir\n"
            "_nexent_os.chdir(_nexent_output_dir)\n"
            "[_nexent_workspace, _nexent_output_dir]"
        )
        seen_executor_ids = set()
        for executor in self._sandbox_executors:
            executor_id = id(executor)
            if executor_id in seen_executor_ids:
                continue
            seen_executor_ids.add(executor_id)
            backend = getattr(executor, "_nexent_backend", None)
            if backend == "local":
                continue
            if backend != "docker" and getattr(executor, "container", None) is None:
                continue
            register_bootstrap = None
            if (
                getattr(executor, "_nexent_kernel_recovery_supported", False)
                is True
                and callable(
                    getattr(type(executor), "register_kernel_bootstrap_code", None)
                )
            ):
                register_bootstrap = executor.register_kernel_bootstrap_code
            execute_bootstrap = (
                register_bootstrap if callable(register_bootstrap) else executor
            )
            try:
                execute_bootstrap(bootstrap_code)
            except Exception as exc:
                # Workspace initialization is idempotent. If the kernel channel
                # failed and marked this lease unhealthy, retry the bootstrap in
                # the same run so the lease can replace its kernel immediately.
                # Do not apply this retry to arbitrary generated code because a
                # lost terminal message does not prove that code had no effects.
                if (
                    getattr(executor, "_nexent_kernel_recovery_supported", False)
                    and getattr(executor, "_unhealthy", False)
                ):
                    logger.warning(
                        "Retrying sandbox workspace initialization with a replacement kernel: %s",
                        exc,
                    )
                    try:
                        execute_bootstrap(bootstrap_code)
                        continue
                    except Exception as retry_exc:
                        exc = retry_exc
                raise RuntimeError(
                    f"Failed to initialize sandbox workspace '{workspace}': {exc}"
                ) from exc

    @staticmethod
    def _grant_sandbox_output_access(container: Any, workspace: Path) -> None:
        """Allow the sandbox user to read and write the exact run workspace."""
        gid_result = container.exec_run(["id", "-g"])
        gid_exit_code = getattr(gid_result, "exit_code", None)
        gid_output = getattr(gid_result, "output", b"")
        if gid_exit_code != 0:
            raise RuntimeError("Failed to determine the sandbox user's group")

        if isinstance(gid_output, bytes):
            gid_output = gid_output.decode("utf-8", errors="replace")
        sandbox_gid = str(gid_output).strip()
        if not sandbox_gid.isdigit():
            raise RuntimeError("Sandbox user returned an invalid group ID")

        workspace_dir = str(workspace)
        commands = (
            ["chgrp", "-R", sandbox_gid, workspace_dir],
            ["chmod", "-R", "g+rwX", workspace_dir],
            ["find", workspace_dir, "-type", "d", "-exec", "chmod", "g+s", "{}", "+"],
        )
        for command in commands:
            result = container.exec_run(command, user="0")
            if getattr(result, "exit_code", None) != 0:
                output = getattr(result, "output", b"")
                if isinstance(output, bytes):
                    output = output.decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"Failed to grant sandbox output access: {str(output).strip()}"
                )

    def _pull_file_workspace_from_sandbox(self) -> None:
        """Copy outputs from every Docker sandbox back to the host workspace."""
        containers = self._sandbox_containers()
        if not containers or not self.workspace_path:
            return
        if self._uses_shared_file_workspace():
            return
        workspace = Path(self.workspace_path).resolve()
        if workspace.drive:
            return
        for container in containers:
            try:
                chunks, _ = container.get_archive(str(workspace))
                archive = io.BytesIO(b"".join(chunks))
                with tarfile.open(fileobj=archive, mode="r:*") as tar:
                    members = []
                    extraction_root = workspace.parent.resolve()
                    for member in tar.getmembers():
                        if not (member.isfile() or member.isdir()):
                            raise RuntimeError("Sandbox workspace archive contains an unsupported entry")
                        target = (extraction_root / member.name).resolve()
                        try:
                            target.relative_to(extraction_root)
                        except ValueError as exc:
                            raise RuntimeError("Sandbox workspace archive escapes the run root") from exc
                        members.append(member)
                    tar.extractall(extraction_root, members=members)
            except Exception as exc:
                logger.warning("Failed to copy sandbox workspace back to host: %s", exc)

    def _finalize_file_workspace(self) -> None:
        """Upload all workspace outputs that were not already uploaded explicitly."""
        if not self.workspace_path:
            return
        self._pull_file_workspace_from_sandbox()
        workspace = Path(self.workspace_path)
        upload_tool = (getattr(self.agent, "tools", {}) or {}).get("upload_to_s3")
        if upload_tool is None:
            logger.error("Run workspace exists but upload_to_s3 is unavailable")
            return

        uploaded_paths = getattr(upload_tool, "uploaded_paths", set())
        for path in workspace.rglob("*") if workspace.exists() else ():
            if not path.is_file():
                continue
            relative = path.relative_to(workspace)
            if relative.parts and relative.parts[0] in {"inputs", "skills"}:
                continue
            if any(part in _WORKSPACE_UPLOAD_EXCLUDED_DIRS for part in relative.parts[:-1]):
                continue
            normalized = os.path.normcase(os.path.abspath(str(path)))
            if normalized in uploaded_paths:
                continue
            try:
                upload_tool.forward(str(path), relative.as_posix())
            except Exception as exc:
                logger.error("Failed to upload workspace output %s: %s", path, exc)
                self.observer.add_message("", ProcessType.ERROR, f"Failed to upload output file {relative}: {exc}")

        if self._workspace_uploads:
            self.observer.add_message(
                "",
                ProcessType.FILE_ARTIFACT,
                {"artifacts": list(self._workspace_uploads)},
            )

    def _cleanup_file_workspace(self) -> None:
        """Delete only the exact run-scoped workspace after upload finalization."""
        if not self.workspace_path or not self.workspace_run_id:
            return
        workspace = Path(self.workspace_path).resolve()
        if workspace.name != self.workspace_run_id:
            return
        try:
            for container in self._sandbox_containers():
                try:
                    result = container.exec_run(
                        ["rm", "-rf", "--", str(workspace)],
                        user="0",
                    )
                    if getattr(result, "exit_code", None) != 0:
                        output = getattr(result, "output", b"")
                        if isinstance(output, bytes):
                            output = output.decode("utf-8", errors="replace")
                        logger.warning(
                            "Failed to clean sandbox run workspace %s: %s",
                            workspace,
                            str(output).strip(),
                        )
                except Exception as exc:
                    logger.warning("Failed to clean sandbox run workspace %s: %s", workspace, exc)
            cleanup_run_workspace(
                self.workspace_path,
                self.workspace_run_id,
                logger,
            )
        except Exception as exc:
            logger.error("Failed to clean run workspace %s: %s", workspace, exc)

    def set_agent(self, agent: CoreAgent):
        if not isinstance(agent, CoreAgent):
            raise TypeError(f"agent must be a CoreAgent object, not {type(agent)}")
        self.agent = agent

    def _log_step_metrics(self):
        """Output step_metrics to log or local file for quantitative analysis of context management."""
        if not hasattr(self.agent, "step_metrics") or not self.agent.step_metrics:
            return

        metrics = self.agent.step_metrics

        # Pre-collect all values
        real_i_vals = [m['main_llm']['input_tokens'] for m in metrics]
        real_o_vals = [m['main_llm']['output_tokens'] for m in metrics]
        comp_i_vals = [m['compression']['input_tokens'] for m in metrics]
        comp_o_vals = [m['compression']['output_tokens'] for m in metrics]
        est_i_vals  = [m['memory_state']['estimated_input_tokens'] for m in metrics]
        est_o_vals  = [m['memory_state']['estimated_output_tokens'] for m in metrics]
        raw_i_vals  = [m['uncompressed_mem_est_input'] for m in metrics]
        save_vals   = [f"{m['compression_ratio']}%" for m in metrics]
        hit_vals    = [str(m['cache_hit']) for m in metrics]

        # Total summary
        total_ri   = sum(real_i_vals)
        total_ro   = sum(real_o_vals)
        total_ci   = sum(comp_i_vals)
        total_co   = sum(comp_o_vals)
        total_ei   = sum(est_i_vals)
        total_eo   = sum(est_o_vals)
        total_raw  = sum(raw_i_vals)
        hit_count  = sum(1 for m in metrics if m['cache_hit'])

        if total_raw > 0:
            total_save_str = f"{round((1 - total_ei / total_raw) * 100, 1)}%"
        else:
            total_save_str = "N/A"
        hit_total_str = f"{hit_count}/{len(metrics)}"

        # Column widths based on max value width
        def _val_width(vals, extra_val=None):
            w = 0
            for v in vals:
                w = max(w, len(str(v)))
            if extra_val is not None:
                w = max(w, len(str(extra_val)))
            return w

        w_ri   = _val_width(real_i_vals, total_ri)
        w_ro   = _val_width(real_o_vals, total_ro)
        w_ci   = _val_width(comp_i_vals, total_ci)
        w_co   = _val_width(comp_o_vals, total_co)
        w_ei   = _val_width(est_i_vals, total_ei)
        w_eo   = _val_width(est_o_vals, total_eo)
        w_raw  = _val_width(raw_i_vals, total_raw)
        w_save = _val_width(save_vals, total_save_str)
        w_hit  = _val_width(hit_vals, hit_total_str)

        # Prefix formatting
        max_step_digits = max(len(str(m['step_number'])) for m in metrics)
        step_prefix_fmt = f"Step {{:>{max_step_digits}}}:  "
        total_prefix = "Total:  " + " " * max_step_digits

        lines = []
        for i, m in enumerate(metrics):
            lines.append(
                step_prefix_fmt.format(m['step_number']) +
                f"real_i={real_i_vals[i]:>{w_ri}}  real_o={real_o_vals[i]:>{w_ro}} | "
                f"comp_i={comp_i_vals[i]:>{w_ci}}  comp_o={comp_o_vals[i]:>{w_co}} | "
                f"est_i={est_i_vals[i]:>{w_ei}}  est_o={est_o_vals[i]:>{w_eo}} | "
                f"est_raw_i={raw_i_vals[i]:>{w_raw}}  save={save_vals[i]:>{w_save}} | "
                f"hit={hit_vals[i]:>{w_hit}}"
            )

        lines.append(
            total_prefix +
            f"real_i={total_ri:>{w_ri}}  real_o={total_ro:>{w_ro}} | "
            f"comp_i={total_ci:>{w_ci}}  comp_o={total_co:>{w_co}} | "
            f"est_i={total_ei:>{w_ei}}  est_o={total_eo:>{w_eo}} | "
            f"est_raw_i={total_raw:>{w_raw}}  save={total_save_str:>{w_save}} | "
            f"hit={hit_total_str:>{w_hit}}"
        )
        context_runtime = getattr(self.agent, "context_runtime", None)
        if context_runtime is not None:
            lines.append(f"Context Manager Global: {context_runtime.global_compression_stats()}")

        lines.append(
            "-----"
        )
        logger.debug("\n".join(lines))

        # Optional: write to local file
        with open("nexent_context_metrics.log", "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def _cleanup_sandbox(self) -> None:
        """
        Clean up the sandbox executor after an agent run.

        For ``scope=session``: the executor is immediately destroyed.
        For ``scope=system``: the executor is returned to the warm pool for reuse.

        Must run AFTER any output-sync logic, because the container filesystem
        is inaccessible after the executor is released / destroyed.
        """
        root_executor = getattr(self.agent, "python_executor", None)
        executors = list(self._sandbox_executors)
        if root_executor is not None and all(
            item is not root_executor for item in executors
        ):
            executors.append(root_executor)
        if not executors:
            return

        scope = getattr(self, "_sandbox_scope", None)

        for runner in self._sandbox_skill_runners:
            runner.cleanup()
        self._sandbox_skill_runners.clear()

        # Sync outputs to MinIO before destroying the container.
        if (
            not self.workspace_path
            and self.sandbox_config is not None
            and self.sandbox_config.auto_sync_outputs
            and self.minio_client is not None
        ):
            from .sandbox import _sync_outputs_to_minio
            agent_run_id = getattr(self.agent, "agent_run_id", None) or "unknown"
            try:
                uploaded = _sync_outputs_to_minio(
                    output_dir=self.sandbox_config.output_dir,
                    agent_run_id=agent_run_id,
                    minio_client=self.minio_client,
                    bucket="nexent-artifacts",
                    logger_=logger,
                )
                if uploaded:
                    logger.info(
                        "Synced %d output file(s) to MinIO for run %s",
                        len(uploaded),
                        agent_run_id,
                    )
            except Exception as exc:
                logger.error("Output sync to MinIO failed: %s", exc)

        # Release or destroy the executor.
        seen_executor_ids = set()
        for executor in reversed(executors):
            executor_id = id(executor)
            if executor_id in seen_executor_ids:
                continue
            seen_executor_ids.add(executor_id)
            if scope == "system":
                # Return every kernel lease to the shared system sandbox.
                from .sandbox import release_python_executor
                release_python_executor(executor, logger)
            else:
                # Session kernel leases are released independently; their
                # agent-tree container is deleted after the final lease closes.
                from .sandbox import cleanup_executor
                cleanup_executor(executor, logger, timeout=5.0)

        # Clear the reference so GC can collect the wrapper objects.
        if self.agent is not None:
            self.agent.python_executor = None
        self._sandbox_executors.clear()
