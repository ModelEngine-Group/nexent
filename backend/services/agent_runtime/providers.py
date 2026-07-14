"""Built-in capability providers for the framework-neutral assembly layer."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from jinja2 import StrictUndefined, Template

from skill_tool_schema import get_builtin_skill_tool_inputs

from .assembly import DuplicateToolIdentifierError
from .models import (
    AgentRunRequestContext,
    AgentSpec,
    AssemblyState,
    CapabilityContribution,
    ContextMode,
    ContextPolicy,
    MCPConnectionConfig,
    OperatorSpec,
    PromptBundle,
    RuntimeWarningInfo,
    ToolSource,
    ToolSpec,
)
from .tool_schema import tool_spec_from_legacy_tool_config


ModelRecordsResolver = Callable[[str], Sequence[Mapping[str, Any]]]
LegacyModelConfigResolver = Callable[[str], Mapping[str, Any] | None]
PromptCacheResolver = Callable[[str | None], Mapping[str, Any] | None]
AgentRecordResolver = Callable[[int, str, int | None], Mapping[str, Any] | None]
ToolRecordsResolver = Callable[[int, str, int | None], Sequence[Mapping[str, Any]]]
SubAgentRelationsResolver = Callable[
    [int, str, int | None], Sequence[Mapping[str, Any]]
]
SubAgentVersionResolver = Callable[[int, int | None, str], int | None]
ExternalA2AResolver = Callable[[int, str, int | None], Sequence[Any]]
AppConfigResolver = Callable[[str, str], str | None]
PromptTemplateResolver = Callable[[bool, str], Mapping[str, Any]]
MCPRecordsResolver = Callable[[str], Sequence[Mapping[str, Any]]]
MCPToolRecordsResolver = Callable[[int, str, int | None], Sequence[Mapping[str, Any]]]
SkillRecordsResolver = Callable[[int, str, int | None], Sequence[Mapping[str, Any]]]
MemoryContextResolver = Callable[[str, str, int, bool], Any]
MemorySearcher = Callable[..., Mapping[str, Any] | Awaitable[Mapping[str, Any]]]
EmbeddingModelResolver = Callable[[str, str], Any]
RerankModelResolver = Callable[[str, str], Any]
KnowledgeNameMapResolver = Callable[[Sequence[str]], Mapping[str, str]]
KnowledgeSummaryResolver = Callable[[str], Mapping[str, Any]]
VectorDbResolver = Callable[[], Any]


def _none_model_records_resolver(tenant_id: str) -> Sequence[Mapping[str, Any]]:
    _ = tenant_id
    return []


def _none_legacy_model_config_resolver(tenant_id: str) -> Mapping[str, Any] | None:
    _ = tenant_id
    return None


def _none_prompt_cache_resolver(model_factory: str | None) -> Mapping[str, Any] | None:
    _ = model_factory
    return None


def _none_agent_record_resolver(
    agent_id: int,
    tenant_id: str,
    version_no: int | None,
) -> Mapping[str, Any] | None:
    _ = (agent_id, tenant_id, version_no)
    return None


def _none_tool_records_resolver(
    agent_id: int,
    tenant_id: str,
    version_no: int | None,
) -> Sequence[Mapping[str, Any]]:
    _ = (agent_id, tenant_id, version_no)
    return []


def _none_sub_agent_relations_resolver(
    agent_id: int,
    tenant_id: str,
    version_no: int | None,
) -> Sequence[Mapping[str, Any]]:
    _ = (agent_id, tenant_id, version_no)
    return []


def _none_sub_agent_version_resolver(
    selected_agent_id: int,
    selected_agent_version_no: int | None,
    tenant_id: str,
) -> int | None:
    _ = (selected_agent_id, tenant_id)
    return selected_agent_version_no


def _none_external_a2a_resolver(
    agent_id: int,
    tenant_id: str,
    version_no: int | None,
) -> Sequence[Any]:
    _ = (agent_id, tenant_id, version_no)
    return []


def _none_app_config_resolver(key: str, tenant_id: str) -> str | None:
    _ = (key, tenant_id)
    return None


def _none_mcp_records_resolver(tenant_id: str) -> Sequence[Mapping[str, Any]]:
    _ = tenant_id
    return []


def _none_mcp_tool_records_resolver(
    agent_id: int,
    tenant_id: str,
    version_no: int | None,
) -> Sequence[Mapping[str, Any]]:
    _ = (agent_id, tenant_id, version_no)
    return []


def _none_skill_records_resolver(
    agent_id: int,
    tenant_id: str,
    version_no: int | None,
) -> Sequence[Mapping[str, Any]]:
    _ = (agent_id, tenant_id, version_no)
    return []


def _disabled_memory_context_resolver(
    user_id: str,
    tenant_id: str,
    agent_id: int,
    skip_query: bool,
) -> Any:
    _ = skip_query
    return SimpleNamespace(
        user_config=SimpleNamespace(
            memory_switch=False,
            agent_share_option="never",
            disable_agent_ids=[],
            disable_user_agent_ids=[],
        ),
        memory_config={},
        tenant_id=tenant_id,
        user_id=user_id,
        agent_id=str(agent_id),
    )


async def _none_memory_searcher(**kwargs: Any) -> Mapping[str, Any]:
    _ = kwargs
    return {"results": []}


def _none_embedding_model_resolver(tenant_id: str, index_name: str) -> Any:
    _ = (tenant_id, index_name)
    return None


def _none_rerank_model_resolver(tenant_id: str, model_name: str) -> Any:
    _ = (tenant_id, model_name)
    return None


def _none_knowledge_name_map_resolver(
    index_names: Sequence[str],
) -> Mapping[str, str]:
    return {index_name: index_name for index_name in index_names}


def _none_knowledge_summary_resolver(index_name: str) -> Mapping[str, Any]:
    _ = index_name
    return {}


def _none_vector_db_resolver() -> Any:
    return None


def _default_prompt_template_resolver(
    is_manager: bool, language: str
) -> Mapping[str, Any]:
    _ = (is_manager, language)
    return {
        "system_prompt": (
            "{{ duty }}\n{{ constraint }}\n{{ few_shots }}\n"
            "{{ knowledge_base_summary }}\n{{ memory_list }}"
        )
    }


@dataclass
class ModelProvider:
    """Contribute tenant model configs and model budget metadata."""

    model_records_resolver: ModelRecordsResolver = _none_model_records_resolver
    legacy_model_config_resolver: LegacyModelConfigResolver = (
        _none_legacy_model_config_resolver
    )
    prompt_cache_resolver: PromptCacheResolver = _none_prompt_cache_resolver
    name: str = "model"
    priority: int = 0
    depends_on: tuple[str, ...] = ()

    def contribute(
        self,
        request: AgentRunRequestContext,
        state: AssemblyState,
    ) -> CapabilityContribution:
        model_configs = [
            self._model_record_to_config(record)
            for record in self.model_records_resolver(request.tenant_id)
        ]
        legacy_config = self.legacy_model_config_resolver(request.tenant_id)
        if legacy_config:
            model_configs.extend(self._legacy_alias_configs(legacy_config))

        selected_model_id = request.override_model_id or state.agent_record.get(
            "model_id"
        )
        selected_model = self._find_model_record(model_configs, selected_model_id)
        selected_model_name = (
            selected_model.get("cite_name")
            if selected_model is not None
            else state.agent_record.get("model_name") or "main_model"
        )

        monitoring_metadata = {
            "model.selected_model_id": selected_model_id,
            "model.selected_model_name": selected_model_name,
            "model.requested_output_tokens": request.requested_output_tokens,
        }
        if selected_model is not None:
            monitoring_metadata["model.capacity_snapshot"] = {
                key: selected_model.get(key)
                for key in (
                    "context_window_tokens",
                    "max_input_tokens",
                    "max_output_tokens",
                    "default_output_reserve_tokens",
                    "capacity_source",
                    "capability_profile_version",
                )
                if selected_model.get(key) is not None
            }
            safe_input_budget_snapshot = _safe_input_budget_snapshot(
                selected_model,
                agent_requested_output_tokens=state.agent_record.get(
                    "requested_output_tokens"
                ),
                request_requested_output_tokens=request.requested_output_tokens,
            )
            if safe_input_budget_snapshot is not None:
                monitoring_metadata["model.safe_input_budget_snapshot"] = (
                    safe_input_budget_snapshot
                )

        return CapabilityContribution(
            model_configs=model_configs,
            agent_record={"model_name": selected_model_name},
            runtime_resources={"model.selected": selected_model_name},
            monitoring_metadata=monitoring_metadata,
        )

    def _model_record_to_config(self, record: Mapping[str, Any]) -> dict[str, Any]:
        model_factory = record.get("model_factory")
        model_name = _add_repo_to_name(
            record.get("model_repo"), record.get("model_name")
        )
        return {
            "cite_name": record.get("display_name"),
            "api_key": record.get("api_key", ""),
            "model_name": model_name,
            "url": record.get("base_url", ""),
            "ssl_verify": record.get("ssl_verify", True),
            "model_factory": model_factory,
            "timeout_seconds": record.get("timeout_seconds"),
            "concurrency_limit": record.get("concurrency_limit"),
            "prompt_cache": self.prompt_cache_resolver(model_factory),
            "model_id": record.get("model_id"),
            "max_output_tokens": record.get("max_output_tokens"),
            "max_tokens": record.get("max_tokens"),
            "context_window_tokens": record.get("context_window_tokens"),
            "max_input_tokens": record.get("max_input_tokens"),
            "default_output_reserve_tokens": record.get(
                "default_output_reserve_tokens"
            ),
            "tokenizer_family": record.get("tokenizer_family"),
            "capacity_source": record.get("capacity_source"),
            "capability_profile_version": record.get("capability_profile_version"),
        }

    def _legacy_alias_configs(
        self, legacy_config: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        model_factory = legacy_config.get("model_factory")
        model_config = {
            "api_key": legacy_config.get("api_key", ""),
            "model_name": _add_repo_to_name(
                legacy_config.get("model_repo"),
                legacy_config.get("model_name"),
            )
            if legacy_config.get("model_name")
            else "",
            "url": legacy_config.get("base_url", ""),
            "ssl_verify": legacy_config.get("ssl_verify", True),
            "model_factory": model_factory,
            "timeout_seconds": legacy_config.get("timeout_seconds"),
            "concurrency_limit": legacy_config.get("concurrency_limit"),
            "prompt_cache": self.prompt_cache_resolver(model_factory),
        }
        return [
            {"cite_name": "main_model", **model_config},
            {"cite_name": "sub_model", **model_config},
        ]

    @staticmethod
    def _find_model_record(
        model_configs: Sequence[Mapping[str, Any]],
        selected_model_id: Any,
    ) -> Mapping[str, Any] | None:
        if selected_model_id is None:
            return None
        for model_config in model_configs:
            if model_config.get("model_id") == selected_model_id:
                return model_config
        return None


@dataclass
class SubAgentProvider:
    """Contribute internal managed agents and external A2A declarations."""

    agent_record_resolver: AgentRecordResolver = _none_agent_record_resolver
    relations_resolver: SubAgentRelationsResolver = _none_sub_agent_relations_resolver
    version_resolver: SubAgentVersionResolver = _none_sub_agent_version_resolver
    external_a2a_resolver: ExternalA2AResolver = _none_external_a2a_resolver
    name: str = "sub-agent"
    priority: int = 100
    depends_on: tuple[str, ...] = ("model",)

    def contribute(
        self,
        request: AgentRunRequestContext,
        state: AssemblyState,
    ) -> CapabilityContribution:
        managed_agents = self._build_managed_agents(
            request.agent_id,
            request.tenant_id,
            state.version_no,
            seen={request.agent_id},
        )
        return CapabilityContribution(
            managed_agents=managed_agents,
            external_a2a_agents=list(
                self.external_a2a_resolver(
                    request.agent_id,
                    request.tenant_id,
                    state.version_no,
                )
            ),
        )

    def _build_managed_agents(
        self,
        agent_id: int,
        tenant_id: str,
        version_no: int | None,
        *,
        seen: set[int],
    ) -> list[AgentSpec]:
        managed_agents: list[AgentSpec] = []
        for relation in self.relations_resolver(agent_id, tenant_id, version_no):
            child_id = int(relation["selected_agent_id"])
            if child_id in seen:
                continue
            child_version_no = self.version_resolver(
                child_id,
                relation.get("selected_agent_version_no"),
                tenant_id,
            )
            child_record = self.agent_record_resolver(
                child_id,
                tenant_id,
                child_version_no,
            ) or {"agent_id": child_id}
            child_seen = set(seen)
            child_seen.add(child_id)
            managed_agents.append(
                AgentSpec(
                    agent_id=child_id,
                    name=str(child_record.get("name") or f"agent-{child_id}"),
                    description=str(child_record.get("description") or ""),
                    model_name=str(child_record.get("model_name") or "main_model"),
                    max_steps=int(child_record.get("max_steps") or 15),
                    prompt=PromptBundle(
                        fragments=_agent_prompt_fragments(child_record),
                    ),
                    managed_agents=self._build_managed_agents(
                        child_id,
                        tenant_id,
                        child_version_no,
                        seen=child_seen,
                    ),
                    verification_config=child_record.get("verification_config"),
                    runtime_hints={"version_no": child_version_no},
                )
            )
        return managed_agents


@dataclass
class ToolProvider:
    """Contribute framework-neutral tool declarations for the root agent."""

    tool_records_resolver: ToolRecordsResolver = _none_tool_records_resolver
    name: str = "tool"
    priority: int = 200
    depends_on: tuple[str, ...] = ("sub-agent",)

    def contribute(
        self,
        request: AgentRunRequestContext,
        state: AssemblyState,
    ) -> CapabilityContribution:
        agent_name = str(
            state.agent_record.get("name")
            or state.agent_record.get("agent_name")
            or "root"
        )
        overrides = _tool_overrides_for_agent(request.tool_params, agent_name)
        tools: list[ToolSpec] = []
        seen_identifiers: set[str] = set()
        for record in self.tool_records_resolver(
            request.agent_id,
            request.tenant_id,
            state.version_no,
        ):
            tool_name = record.get("name")
            class_name = record.get("class_name")
            identifiers = _tool_record_identifiers(tool_name, class_name)
            duplicated = sorted(seen_identifiers & identifiers)
            if duplicated:
                raise DuplicateToolIdentifierError(
                    f"Duplicate tool identifier '{duplicated[0]}' for agent '{agent_name}'."
                )
            seen_identifiers.update(identifiers)

            override_params = (
                overrides.get(str(tool_name)) or overrides.get(str(class_name)) or {}
            )
            params = _merge_tool_record_params(record, override_params)
            metadata = dict(record.get("metadata") or {})
            if record.get("source") == "langchain":
                metadata["langchain_tool_name"] = class_name

            tools.append(
                tool_spec_from_legacy_tool_config(
                    SimpleNamespace(
                        class_name=class_name,
                        name=tool_name,
                        description=record.get("description"),
                        inputs=record.get("inputs"),
                        output_type=record.get("output_type"),
                        params=params,
                        source=record.get("source") or "local",
                        usage=record.get("usage"),
                        metadata=metadata,
                    )
                )
            )

        return CapabilityContribution(tools_by_agent={agent_name: tools})


@dataclass
class MCPProvider:
    """Contribute MCP connections and optional MCP tool declarations."""

    mcp_records_resolver: MCPRecordsResolver = _none_mcp_records_resolver
    mcp_tool_records_resolver: MCPToolRecordsResolver = _none_mcp_tool_records_resolver
    name: str = "mcp"
    priority: int = 600
    depends_on: tuple[str, ...] = ("tool",)

    def contribute(
        self,
        request: AgentRunRequestContext,
        state: AssemblyState,
    ) -> CapabilityContribution:
        agent_name = str(
            state.agent_record.get("name")
            or state.agent_record.get("agent_name")
            or "root"
        )
        contributed_tools = self._mcp_tool_specs(request, state)
        used_server_names = {
            server_name
            for server_name in _used_mcp_server_names(state.tools_by_agent)
            if server_name
        }
        used_server_names.update(tool.usage for tool in contributed_tools if tool.usage)

        records_by_name = {
            _mcp_record_name(record): record
            for record in self.mcp_records_resolver(request.tenant_id)
            if _mcp_record_name(record)
        }
        connections: list[MCPConnectionConfig] = []
        warnings: list[RuntimeWarningInfo] = []
        runtime_resources: dict[str, Any] = {}
        for server_name in sorted(used_server_names):
            record = records_by_name.get(server_name)
            if record is None:
                warnings.append(
                    RuntimeWarningInfo(
                        code="mcp_server_missing",
                        message=f"MCP server '{server_name}' is not configured.",
                        metadata={"server_name": server_name},
                    )
                )
                continue
            connection = _mcp_connection_from_record(server_name, record)
            connections.append(connection)
            runtime_resources[f"mcp.{server_name}.headers"] = dict(connection.headers)
            runtime_resources[f"mcp.{server_name}.required"] = connection.required

        return CapabilityContribution(
            mcp_connections=connections,
            tools_by_agent={agent_name: contributed_tools} if contributed_tools else {},
            runtime_resources=runtime_resources,
            warnings=warnings,
        )

    def _mcp_tool_specs(
        self,
        request: AgentRunRequestContext,
        state: AssemblyState,
    ) -> list[ToolSpec]:
        tools: list[ToolSpec] = []
        for record in self.mcp_tool_records_resolver(
            request.agent_id,
            request.tenant_id,
            state.version_no,
        ):
            if str(record.get("source") or "").lower() != ToolSource.MCP.value:
                continue
            tools.append(
                tool_spec_from_legacy_tool_config(
                    SimpleNamespace(
                        class_name=record.get("class_name"),
                        name=record.get("name"),
                        description=record.get("description"),
                        inputs=record.get("inputs") or "{}",
                        output_type=record.get("output_type") or "string",
                        params=dict(record.get("params") or {}),
                        source=ToolSource.MCP.value,
                        usage=record.get("usage") or record.get("server_name"),
                        metadata=dict(record.get("metadata") or {}),
                    )
                )
            )
        return tools


@dataclass
class SkillProvider:
    """Contribute enabled skill summaries, builtin tools and runtime metadata."""

    skill_records_resolver: SkillRecordsResolver = _none_skill_records_resolver
    local_skills_dir: str | None = None
    name: str = "skill"
    priority: int = 400
    depends_on: tuple[str, ...] = ("tool",)

    def contribute(
        self,
        request: AgentRunRequestContext,
        state: AssemblyState,
    ) -> CapabilityContribution:
        version_no = _effective_skill_version_no(request, state)
        enabled_skills = [
            dict(record)
            for record in self.skill_records_resolver(
                request.agent_id,
                request.tenant_id,
                version_no,
            )
            if bool(record.get("enabled", True))
        ]
        if not enabled_skills:
            return CapabilityContribution()

        agent_name = str(
            state.agent_record.get("name")
            or state.agent_record.get("agent_name")
            or "root"
        )
        skill_context = {
            "agent_id": request.agent_id,
            "tenant_id": request.tenant_id,
            "version_no": version_no,
            "capability": "skill",
            "enabled_skill_names": [
                _skill_name(record) for record in enabled_skills if _skill_name(record)
            ],
        }
        injected_params = {
            "local_skills_dir": self.local_skills_dir,
            "agent_id": request.agent_id,
            "tenant_id": request.tenant_id,
            "version_no": version_no,
        }
        tools = [
            _with_injected_params(tool, injected_params)
            for tool in _skill_builtin_tools(
                local_skills_dir=self.local_skills_dir,
                metadata=skill_context,
            )
        ]
        return CapabilityContribution(
            tools_by_agent={agent_name: tools},
            prompt_fragments={
                "skills": [_skill_prompt_summary(record) for record in enabled_skills]
            },
            runtime_resources={
                "skill.local_skills_dir": self.local_skills_dir,
                "skill.enabled_skills": [
                    _skill_runtime_record(record) for record in enabled_skills
                ],
            },
            operators=[
                OperatorSpec(
                    name="skill_file_upload",
                    stages={"after_tool_call", "after_run"},
                    priority=400,
                    required=False,
                )
            ],
            monitoring_metadata={
                "skill.enabled_count": len(enabled_skills),
            },
        )


@dataclass
class MemoryProvider:
    """Contribute memory prompt context, active tools and lifecycle hooks."""

    memory_context_resolver: MemoryContextResolver = _disabled_memory_context_resolver
    memory_searcher: MemorySearcher = _none_memory_searcher
    name: str = "memory"
    priority: int = 500
    depends_on: tuple[str, ...] = ("skill",)

    async def contribute(
        self,
        request: AgentRunRequestContext,
        state: AssemblyState,
    ) -> CapabilityContribution:
        memory_context = self.memory_context_resolver(
            request.user_id,
            request.tenant_id,
            request.agent_id,
            request.is_debug,
        )
        user_config = getattr(memory_context, "user_config", None)
        memory_config = dict(getattr(memory_context, "memory_config", {}) or {})
        monitoring_metadata = {
            "memory.enabled": bool(getattr(user_config, "memory_switch", False)),
            "memory.agent_share_option": getattr(
                user_config, "agent_share_option", None
            ),
            "memory.disabled_agent_ids": list(
                getattr(user_config, "disable_agent_ids", []) or []
            ),
            "memory.disabled_user_agent_ids": list(
                getattr(user_config, "disable_user_agent_ids", []) or []
            ),
        }
        runtime_resources = {
            "memory.user_config": _dump_memory_user_config(user_config),
            "memory.config": memory_config,
            "memory.tenant_id": getattr(memory_context, "tenant_id", request.tenant_id),
            "memory.user_id": getattr(memory_context, "user_id", request.user_id),
            "memory.agent_id": str(
                getattr(memory_context, "agent_id", request.agent_id)
            ),
        }
        if request.is_debug:
            monitoring_metadata["memory.disabled_reason"] = "debug"
            return CapabilityContribution(
                runtime_resources=runtime_resources,
                monitoring_metadata=monitoring_metadata,
            )
        if not getattr(user_config, "memory_switch", False):
            monitoring_metadata["memory.disabled_reason"] = "switch_off"
            return CapabilityContribution(
                runtime_resources=runtime_resources,
                monitoring_metadata=monitoring_metadata,
            )
        if not memory_config:
            monitoring_metadata["memory.disabled_reason"] = "missing_config"
            return CapabilityContribution(
                runtime_resources=runtime_resources,
                monitoring_metadata=monitoring_metadata,
            )

        memory_levels = _memory_retrieval_levels(memory_context)
        runtime_resources["memory.retrieval_levels"] = memory_levels
        monitoring_metadata["memory.retrieval_levels"] = memory_levels
        memory_list: list[Any] = []
        warnings: list[RuntimeWarningInfo] = []
        try:
            search_result = self.memory_searcher(
                query_text=request.query,
                memory_config=memory_config,
                tenant_id=getattr(memory_context, "tenant_id", request.tenant_id),
                user_id=getattr(memory_context, "user_id", request.user_id),
                agent_id=str(getattr(memory_context, "agent_id", request.agent_id)),
                memory_levels=memory_levels,
            )
            if hasattr(search_result, "__await__"):
                search_result = await search_result
            memory_list = list(dict(search_result).get("results", []))
            monitoring_metadata["memory.retrieval_status"] = "ok"
            monitoring_metadata["memory.retrieved_count"] = len(memory_list)
        except Exception as exc:
            monitoring_metadata["memory.retrieval_status"] = "soft_failure"
            monitoring_metadata["memory.retrieval_error"] = str(exc)
            warnings.append(
                RuntimeWarningInfo(
                    code="memory_retrieval_failed",
                    message=f"Memory retrieval failed: {exc}",
                    metadata={"agent_id": request.agent_id},
                )
            )

        agent_name = str(
            state.agent_record.get("name")
            or state.agent_record.get("agent_name")
            or "root"
        )
        runtime_resources["memory.items"] = memory_list
        runtime_resources["memory.retrieval_status"] = monitoring_metadata[
            "memory.retrieval_status"
        ]
        if monitoring_metadata.get("memory.retrieval_error"):
            runtime_resources["memory.retrieval_error"] = monitoring_metadata[
                "memory.retrieval_error"
            ]
        return CapabilityContribution(
            tools_by_agent={
                agent_name: _memory_tool_specs(
                    memory_context=memory_context,
                    memory_config=memory_config,
                    user_config=user_config,
                )
            },
            prompt_fragments=memory_prompt_fragment(memory_list),
            context_components=[
                {
                    "type": "memory",
                    "items": memory_list,
                    "query": request.query,
                    "levels": memory_levels,
                    "retrieval_status": monitoring_metadata["memory.retrieval_status"],
                }
            ],
            runtime_resources=runtime_resources,
            operators=[
                OperatorSpec(
                    name="memory_retrieval",
                    stages={"before_run", "prepare_context"},
                    priority=500,
                    required=False,
                ),
                OperatorSpec(
                    name="memory_persistence",
                    stages={"after_run"},
                    priority=500,
                    required=False,
                ),
            ],
            monitoring_metadata=monitoring_metadata,
            warnings=warnings,
        )


@dataclass
class KnowledgeProvider:
    """Contribute knowledge search metadata and summary prompt fragments."""

    embedding_model_resolver: EmbeddingModelResolver = _none_embedding_model_resolver
    rerank_model_resolver: RerankModelResolver = _none_rerank_model_resolver
    vector_db_resolver: VectorDbResolver = _none_vector_db_resolver
    knowledge_name_map_resolver: KnowledgeNameMapResolver = (
        _none_knowledge_name_map_resolver
    )
    knowledge_summary_resolver: KnowledgeSummaryResolver = (
        _none_knowledge_summary_resolver
    )
    name: str = "knowledge"
    priority: int = 300
    depends_on: tuple[str, ...] = ("tool",)

    def contribute(
        self,
        request: AgentRunRequestContext,
        state: AssemblyState,
    ) -> CapabilityContribution:
        agent_name = str(
            state.agent_record.get("name")
            or state.agent_record.get("agent_name")
            or "root"
        )
        existing_tools = list(state.tools_by_agent.get(agent_name, []))
        knowledge_tools = [tool for tool in existing_tools if _is_knowledge_tool(tool)]
        if not knowledge_tools:
            return CapabilityContribution()

        state.tools_by_agent[agent_name] = [
            tool for tool in existing_tools if not _is_knowledge_tool(tool)
        ]
        enhanced_tools: list[ToolSpec] = []
        runtime_resources: dict[str, Any] = {}
        warnings: list[RuntimeWarningInfo] = []
        summary_fragments: list[str] = []
        kb_ids: list[str] = []
        for tool in knowledge_tools:
            enhanced_tool, tool_resources, tool_warnings, tool_summaries = (
                self._enhance_knowledge_tool(tool, request)
            )
            enhanced_tools.append(enhanced_tool)
            runtime_resources.update(tool_resources)
            warnings.extend(tool_warnings)
            summary_fragments.extend(tool_summaries)
            kb_ids.extend(_knowledge_index_names(enhanced_tool))

        knowledge_summary = "".join(summary_fragments)
        display_name_to_index_map: dict[str, str] = {}
        index_name_to_display_map: dict[str, str] = {}
        for tool in enhanced_tools:
            display_name_to_index_map.update(
                dict(tool.metadata.get("display_name_to_index_map") or {})
            )
            index_name_to_display_map.update(
                dict(tool.metadata.get("index_name_to_display_map") or {})
            )
        runtime_resources["knowledge.kb_ids"] = kb_ids
        runtime_resources["knowledge.summary"] = knowledge_summary
        runtime_resources["knowledge.summary_status"] = (
            "soft_failure"
            if any(warning.code == "knowledge_summary_failed" for warning in warnings)
            else "ok"
        )
        runtime_resources["knowledge.display_name_to_index_map"] = (
            display_name_to_index_map
        )
        runtime_resources["knowledge.index_name_to_display_map"] = (
            index_name_to_display_map
        )
        return CapabilityContribution(
            tools_by_agent={agent_name: enhanced_tools},
            prompt_fragments={"knowledge_base_summary": knowledge_summary},
            context_components=[
                {
                    "type": "knowledge_summary",
                    "summary": knowledge_summary,
                    "kb_ids": kb_ids,
                    "status": runtime_resources["knowledge.summary_status"],
                }
            ],
            runtime_resources=runtime_resources,
            operators=[
                OperatorSpec(
                    name="knowledge_summary",
                    stages={"prepare_context"},
                    priority=300,
                    required=False,
                )
            ],
            monitoring_metadata={
                "knowledge.tool_count": len(enhanced_tools),
                "knowledge.kb_ids": kb_ids,
                "knowledge.summary_status": runtime_resources[
                    "knowledge.summary_status"
                ],
            },
            warnings=warnings,
        )

    def _enhance_knowledge_tool(
        self,
        tool: ToolSpec,
        request: AgentRunRequestContext,
    ) -> tuple[ToolSpec, dict[str, Any], list[RuntimeWarningInfo], list[str]]:
        params = dict(tool.params)
        index_names = _normalize_index_names(params.get("index_names"))
        if not index_names:
            raise ValueError(
                f"KnowledgeBaseSearchTool '{tool.name}' requires index_names."
            )

        document_paths = params.pop("document_paths", None)
        if document_paths is None:
            document_paths = tool.metadata.get("document_paths")
        document_paths = _normalize_optional_str_list(document_paths)

        knowledge_name_map = dict(self.knowledge_name_map_resolver(index_names))
        index_name_to_display_map = {
            index_name: knowledge_name_map.get(index_name, index_name)
            for index_name in index_names
        }
        display_name_to_index_map = {
            display_name: index_name
            for index_name, display_name in index_name_to_display_map.items()
        }

        rerank = bool(params.get("rerank", False))
        rerank_model_name = str(params.get("rerank_model_name") or "")
        rerank_model = (
            self.rerank_model_resolver(request.tenant_id, rerank_model_name)
            if rerank and rerank_model_name
            else None
        )
        embedding_model = _resolved_model_value(
            self.embedding_model_resolver(
                request.tenant_id,
                index_names[0],
            )
        )
        if not embedding_model:
            raise ValueError(f"No embedding model found for index '{index_names[0]}'.")
        vdb_core = self.vector_db_resolver()

        metadata = dict(tool.metadata)
        metadata.update(
            {
                "vdb_core": vdb_core,
                "embedding_model": embedding_model,
                "rerank_model": rerank_model,
                "display_name_to_index_map": display_name_to_index_map,
                "index_name_to_display_map": index_name_to_display_map,
                "document_paths": document_paths,
                "capability": "knowledge",
            }
        )
        injected_params = {
            **dict(tool.injected_params),
            "vdb_core": vdb_core,
            "embedding_model": embedding_model,
            "rerank_model": rerank_model,
            "display_name_to_index_map": display_name_to_index_map,
            "index_name_to_display_map": index_name_to_display_map,
            "document_paths": document_paths,
        }
        input_schema = {
            key: value
            for key, value in dict(tool.input_schema).items()
            if key not in {"document_paths", "embedding_model", "rerank_model"}
        }
        raw_inputs = json.dumps(input_schema, ensure_ascii=False)
        enhanced_tool = tool.model_copy(
            update={
                "params": params,
                "metadata": metadata,
                "injected_params": injected_params,
                "input_schema": input_schema,
                "raw_inputs": raw_inputs,
                "source": ToolSource.KNOWLEDGE,
            },
            deep=True,
        )

        warnings: list[RuntimeWarningInfo] = []
        summaries: list[str] = []
        for index_name in index_names:
            display_name = index_name_to_display_map.get(index_name, index_name)
            try:
                summary_result = self.knowledge_summary_resolver(index_name)
                summary = _knowledge_summary_text(summary_result)
                summaries.append(f"**{display_name}**: {summary}\n\n")
            except Exception as exc:
                warnings.append(
                    RuntimeWarningInfo(
                        code="knowledge_summary_failed",
                        message=f"Knowledge summary failed for '{index_name}': {exc}",
                        metadata={"index_name": index_name},
                    )
                )

        resources = {
            f"knowledge.{tool.name}.index_names": index_names,
            f"knowledge.{tool.name}.document_paths": document_paths,
            f"knowledge.{tool.name}.display_name_to_index_map": display_name_to_index_map,
            f"knowledge.{tool.name}.index_name_to_display_map": index_name_to_display_map,
            f"knowledge.{tool.name}.vdb_core": vdb_core,
            f"knowledge.{tool.name}.embedding_model": embedding_model,
            f"knowledge.{tool.name}.rerank_model": rerank_model,
        }
        return enhanced_tool, resources, warnings, summaries


def _is_knowledge_tool(tool: ToolSpec) -> bool:
    return (
        tool.source == ToolSource.KNOWLEDGE
        or str(tool.class_name or "").strip() == "KnowledgeBaseSearchTool"
    )


def _knowledge_index_names(tool: ToolSpec) -> list[str]:
    return _normalize_index_names(
        tool.params.get("index_names")
        or tool.metadata.get("index_names")
        or tool.injected_params.get("index_names")
    )


def _normalize_index_names(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                return _normalize_index_names(json.loads(stripped))
            except json.JSONDecodeError:
                pass
        if "," in stripped:
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return [stripped]
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        normalized: list[str] = []
        for item in value:
            normalized.extend(_normalize_index_names(item))
        return normalized
    return [str(value).strip()] if str(value).strip() else []


def _normalize_optional_str_list(value: Any) -> list[str] | None:
    normalized = _normalize_index_names(value)
    return normalized or None


def _resolved_model_value(value: Any) -> Any:
    if isinstance(value, tuple | list):
        return value[0] if value else None
    return value


def _knowledge_summary_text(summary_result: Any) -> str:
    if isinstance(summary_result, Mapping):
        return str(summary_result.get("summary") or "")
    if summary_result is None:
        return ""
    return str(summary_result)


@dataclass
class ContextProvider:
    """Contribute root AgentSpec, prompt bundle and context policy."""

    agent_record_resolver: AgentRecordResolver = _none_agent_record_resolver
    app_config_resolver: AppConfigResolver = _none_app_config_resolver
    prompt_template_resolver: PromptTemplateResolver = _default_prompt_template_resolver
    name: str = "context"
    priority: int = 700
    depends_on: tuple[str, ...] = ()

    def contribute(
        self,
        request: AgentRunRequestContext,
        state: AssemblyState,
    ) -> CapabilityContribution:
        agent_record = (
            self.agent_record_resolver(
                request.agent_id,
                request.tenant_id,
                state.version_no,
            )
            or state.agent_record
        )
        state.agent_record.update(dict(agent_record))
        agent_name = str(agent_record.get("name") or "root")
        is_manager = bool(state.managed_agents or state.external_a2a_agents)
        app_name = self.app_config_resolver("APP_NAME", request.tenant_id) or "Nexent"
        app_description = self.app_config_resolver(
            "APP_DESCRIPTION", request.tenant_id
        ) or _default_app_description(request.language)
        fragments = {
            **_agent_prompt_fragments(agent_record),
            **state.prompt_fragments,
            "APP_NAME": app_name,
            "APP_DESCRIPTION": app_description,
            "language": request.language,
            "user_id": request.user_id,
        }
        context_components = list(state.context_components)
        enable_context_manager = bool(agent_record.get("enable_context_manager", False))
        compression = dict(agent_record.get("compression") or {})
        legacy_managed_normalized = (
            enable_context_manager
            and request.runtime_provider == "openjiuwen"
            and not compression
        )
        rendered_legacy_system_prompt = None
        context_policy = ContextPolicy(
            mode=(
                ContextMode.RUNTIME_NATIVE
                if legacy_managed_normalized
                else ContextMode.MANAGED
                if enable_context_manager
                else ContextMode.LEGACY
            ),
            token_threshold=agent_record.get("context_token_threshold"),
            soft_input_budget_tokens=agent_record.get("soft_input_budget_tokens"),
            hard_input_budget_tokens=agent_record.get("hard_input_budget_tokens"),
            compression=compression,
        )
        if enable_context_manager:
            context_components.append(
                {
                    "type": "agent_profile",
                    "agent_name": agent_name,
                    "app_name": app_name,
                    "is_manager": is_manager,
                    "fragments": fragments,
                }
            )
        else:
            prompt_template = self.prompt_template_resolver(
                is_manager,
                request.language,
            )
            rendered_legacy_system_prompt = Template(
                str(prompt_template.get("system_prompt") or ""),
                undefined=StrictUndefined,
            ).render(fragments)

        model_name = (
            str(agent_record.get("model_name"))
            if agent_record.get("model_name")
            else str(state.runtime_resources.get("model.selected") or "main_model")
        )
        root_agent = AgentSpec(
            agent_id=request.agent_id,
            name=agent_name,
            description=str(agent_record.get("description") or ""),
            model_name=model_name,
            max_steps=int(agent_record.get("max_steps") or 15),
            prompt=PromptBundle(
                fragments=fragments,
                context_components=context_components,
                rendered_legacy_system_prompt=rendered_legacy_system_prompt,
                templates=dict(agent_record.get("prompt_templates") or {}),
            ),
            context_policy=context_policy,
            verification_config=agent_record.get("verification_config"),
            runtime_hints={
                "version_no": state.version_no,
                "context_compatibility": {
                    "legacy_managed_normalized": True,
                    "source_mode": ContextMode.MANAGED.value,
                    "target_mode": ContextMode.RUNTIME_NATIVE.value,
                }
                if legacy_managed_normalized
                else {},
            },
        )
        return CapabilityContribution(
            root_agent=root_agent,
            agent_record=dict(agent_record),
            warnings=[
                RuntimeWarningInfo(
                    code="context_policy_normalized",
                    message=(
                        "OpenJiuwen uses runtime-native context for the legacy default "
                        "context manager; Nexent managed compression is not enabled."
                    ),
                    metadata={
                        "source_mode": ContextMode.MANAGED.value,
                        "target_mode": ContextMode.RUNTIME_NATIVE.value,
                    },
                )
            ]
            if legacy_managed_normalized
            else [],
        )


def _add_repo_to_name(model_repo: Any, model_name: Any) -> str:
    if not model_name:
        return ""
    if not model_repo:
        return str(model_name)
    return f"{model_repo}/{model_name}"


def _agent_prompt_fragments(agent_record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "duty": agent_record.get("duty_prompt", ""),
        "constraint": agent_record.get("constraint_prompt", ""),
        "few_shots": agent_record.get("few_shots_prompt", ""),
    }


def _default_app_description(language: str) -> str:
    if language == "zh":
        return "Nexent 是一个开源智能体SDK和平台"
    return "Nexent is an open-source agent SDK and platform"


def _tool_record_identifiers(tool_name: Any, class_name: Any) -> set[str]:
    return {
        str(identifier).strip().lower()
        for identifier in (tool_name, class_name)
        if str(identifier or "").strip()
    }


def _merge_tool_record_params(
    tool_record: Mapping[str, Any],
    override_params: Mapping[str, Any],
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for param in tool_record.get("params") or []:
        if isinstance(param, Mapping) and param.get("name"):
            params[str(param["name"])] = param.get("default")
    params.update(dict(override_params or {}))
    return params


def _used_mcp_server_names(
    tools_by_agent: Mapping[str, Sequence[ToolSpec]],
) -> set[str]:
    server_names: set[str] = set()
    for tools in tools_by_agent.values():
        for tool in tools:
            if tool.source == ToolSource.MCP and tool.usage:
                server_names.add(tool.usage)
    return server_names


def _mcp_record_name(record: Mapping[str, Any]) -> str:
    return str(
        record.get("remote_mcp_server_name")
        or record.get("name")
        or record.get("server_name")
        or ""
    ).strip()


def _mcp_connection_from_record(
    server_name: str,
    record: Mapping[str, Any],
) -> MCPConnectionConfig:
    url = str(
        record.get("remote_mcp_server")
        or record.get("url")
        or record.get("server_url")
        or ""
    ).strip()
    if not url:
        raise ValueError(f"MCP server '{server_name}' is missing url.")
    headers = _mcp_headers_from_record(record)
    return MCPConnectionConfig(
        name=server_name,
        url=url,
        transport=_normalize_mcp_transport(url, record.get("transport")),
        headers=headers,
        required=bool(record.get("required", True)),
    )


def _mcp_headers_from_record(record: Mapping[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {}
    authorization = (
        record.get("authorization_token")
        or record.get("authorization")
        or record.get("Authorization")
    )
    if authorization:
        headers["Authorization"] = str(authorization)
    custom_headers = record.get("custom_headers") or record.get("headers") or {}
    if isinstance(custom_headers, Mapping):
        headers.update(
            {
                str(key): str(value)
                for key, value in custom_headers.items()
                if value is not None
            }
        )
    return headers


def _normalize_mcp_transport(url: str, transport: Any) -> str:
    normalized = str(transport or "").strip().lower()
    if normalized in {"sse", "streamable-http"}:
        return normalized
    if url.rstrip("/").endswith("/sse"):
        return "sse"
    return "streamable-http"


def _effective_skill_version_no(
    request: AgentRunRequestContext,
    state: AssemblyState,
) -> int:
    if state.version_no is not None:
        return int(state.version_no)
    if request.version_no is not None:
        return int(request.version_no)
    return 0


def _skill_name(record: Mapping[str, Any]) -> str:
    return str(record.get("name") or record.get("skill_name") or "").strip()


def _skill_description(record: Mapping[str, Any]) -> str:
    return str(record.get("description") or record.get("skill_description") or "")


def _skill_prompt_summary(record: Mapping[str, Any]) -> dict[str, Any]:
    summary = {
        "name": _skill_name(record),
        "description": _skill_description(record),
    }
    if record.get("skill_id") is not None:
        summary["skill_id"] = record.get("skill_id")
    return summary


def _skill_runtime_record(record: Mapping[str, Any]) -> dict[str, Any]:
    runtime_record = _skill_prompt_summary(record)
    for key in ("config_values", "config_schemas", "tool_ids"):
        if record.get(key) is not None:
            runtime_record[key] = record.get(key)
    return runtime_record


def _skill_builtin_tools(
    *,
    local_skills_dir: str | None,
    metadata: dict[str, Any],
) -> list[ToolSpec]:
    tool_records = [
        {
            "class_name": "RunSkillScriptTool",
            "name": "run_skill_script",
            "description": (
                "Execute a skill script with given parameters. Use this to run "
                "Python or shell scripts that are part of a skill."
            ),
            "inputs": get_builtin_skill_tool_inputs("run_skill_script"),
        },
        {
            "class_name": "ReadSkillMdTool",
            "name": "read_skill_md",
            "description": (
                "Read skill execution guide and optional additional files. Always "
                "reads SKILL.md first, then optionally reads additional files."
            ),
            "inputs": get_builtin_skill_tool_inputs("read_skill_md"),
        },
        {
            "class_name": "ReadSkillConfigTool",
            "name": "read_skill_config",
            "description": (
                "Read the config.yaml file from a skill directory. Returns JSON "
                "containing configuration variables needed for skill workflows."
            ),
            "inputs": get_builtin_skill_tool_inputs("read_skill_config"),
        },
        {
            "class_name": "WriteSkillFileTool",
            "name": "write_skill_file",
            "description": (
                "Write content to a file within a skill directory. Creates parent "
                "directories if they do not exist."
            ),
            "inputs": get_builtin_skill_tool_inputs("write_skill_file"),
        },
    ]
    return [
        tool_spec_from_legacy_tool_config(
            SimpleNamespace(
                class_name=record["class_name"],
                name=record["name"],
                description=record["description"],
                inputs=record["inputs"],
                output_type="string",
                params={"local_skills_dir": local_skills_dir},
                source=ToolSource.BUILTIN.value,
                usage="builtin",
                metadata=dict(metadata),
            )
        )
        for record in tool_records
    ]


def _with_injected_params(
    tool: ToolSpec,
    injected_params: Mapping[str, Any],
) -> ToolSpec:
    clean_injected_params = {
        key: value for key, value in injected_params.items() if value is not None
    }
    return tool.model_copy(
        update={
            "input_schema": dict(tool.input_schema),
            "params": dict(tool.params),
            "metadata": dict(tool.metadata),
            "injected_params": clean_injected_params,
        },
    )


def _memory_retrieval_levels(memory_context: Any) -> list[str]:
    user_config = getattr(memory_context, "user_config", None)
    agent_id = str(getattr(memory_context, "agent_id", ""))
    levels = ["tenant", "agent", "user", "user_agent"]
    if getattr(user_config, "agent_share_option", "never") == "never":
        levels = [level for level in levels if level != "agent"]
    if agent_id in {
        str(item) for item in getattr(user_config, "disable_agent_ids", []) or []
    }:
        levels = [level for level in levels if level != "agent"]
    if agent_id in {
        str(item) for item in getattr(user_config, "disable_user_agent_ids", []) or []
    }:
        levels = [level for level in levels if level != "user_agent"]
    return levels


def _dump_memory_user_config(user_config: Any) -> Any:
    if hasattr(user_config, "model_dump"):
        return user_config.model_dump()
    if hasattr(user_config, "__dict__"):
        return dict(user_config.__dict__)
    return user_config


def _memory_tool_specs(
    *,
    memory_context: Any,
    memory_config: Mapping[str, Any],
    user_config: Any,
) -> list[ToolSpec]:
    metadata = {
        "memory_config": dict(memory_config),
        "memory_user_config": user_config,
        "tenant_id": getattr(memory_context, "tenant_id", ""),
        "user_id": getattr(memory_context, "user_id", ""),
        "agent_id": str(getattr(memory_context, "agent_id", "")),
        "capability": "memory",
    }
    injected_params = {
        "memory_config": dict(memory_config),
        "memory_user_config": _dump_memory_user_config(user_config),
        "tenant_id": getattr(memory_context, "tenant_id", ""),
        "user_id": getattr(memory_context, "user_id", ""),
        "agent_id": str(getattr(memory_context, "agent_id", "")),
    }
    return [
        ToolSpec(
            name="store_memory",
            class_name="StoreMemoryTool",
            description=(
                "Save important information to long-term memory for future recall. "
                "Use this when the user shares personal preferences, facts about "
                "themselves, project context, or instructions that should persist "
                "across conversations. Do NOT store transient information like "
                "temporary calculations, information already in the knowledge base, "
                "or data the user explicitly says to forget."
            ),
            input_schema={
                "content": {
                    "type": "string",
                    "description": "The information to remember",
                }
            },
            raw_inputs=json.dumps(
                {
                    "content": {
                        "type": "string",
                        "description": "The information to remember",
                    }
                },
                ensure_ascii=False,
            ),
            output_type="string",
            source=ToolSource.MEMORY,
            metadata=metadata,
            injected_params=injected_params,
        ),
        ToolSpec(
            name="search_memory",
            class_name="SearchMemoryTool",
            description=(
                "Search long-term memory for relevant information from previous "
                "interactions. Use this when you need context about the user's "
                "preferences, past decisions, or previously discussed topics that "
                "aren't in the current conversation. The system already provides "
                "some memory context automatically -- use this tool when you need "
                "to search for specific information not already available."
            ),
            input_schema={
                "query": {
                    "type": "string",
                    "description": "Natural language query describing what to search for",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Maximum number of results to return",
                    "default": 5,
                    "nullable": True,
                },
            },
            raw_inputs=json.dumps(
                {
                    "query": {
                        "type": "string",
                        "description": "Natural language query describing what to search for",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Maximum number of results to return",
                        "default": 5,
                        "nullable": True,
                    },
                },
                ensure_ascii=False,
            ),
            output_type="string",
            source=ToolSource.MEMORY,
            metadata=metadata,
            injected_params=injected_params,
        ),
    ]


def _safe_input_budget_snapshot(
    model_config: Mapping[str, Any],
    *,
    agent_requested_output_tokens: Any,
    request_requested_output_tokens: Any,
) -> dict[str, Any] | None:
    context_window = model_config.get("context_window_tokens")
    max_input_tokens = model_config.get("max_input_tokens")
    if context_window is None and max_input_tokens is None:
        return None

    if request_requested_output_tokens is not None:
        requested_output_tokens = int(request_requested_output_tokens)
        requested_output_source = "request"
    elif agent_requested_output_tokens is not None:
        requested_output_tokens = int(agent_requested_output_tokens)
        requested_output_source = "agent"
    else:
        requested_output_tokens = int(
            model_config.get("default_output_reserve_tokens")
            or model_config.get("max_output_tokens")
            or 0
        )
        requested_output_source = "model_default"

    if requested_output_tokens <= 0:
        return None

    if max_input_tokens is not None:
        hard_input_budget_tokens = int(max_input_tokens)
    else:
        hard_input_budget_tokens = max(int(context_window) - 1, 1)

    if context_window is not None:
        soft_input_budget_tokens = max(int(context_window) - requested_output_tokens, 1)
        soft_input_budget_tokens = min(
            soft_input_budget_tokens, hard_input_budget_tokens
        )
    else:
        soft_input_budget_tokens = hard_input_budget_tokens

    return {
        "requested_output_tokens": requested_output_tokens,
        "requested_output_source": requested_output_source,
        "soft_input_budget_tokens": soft_input_budget_tokens,
        "hard_input_budget_tokens": hard_input_budget_tokens,
    }


def _tool_overrides_for_agent(
    tool_params: Any, agent_name: str
) -> dict[str, dict[str, Any]]:
    if not tool_params:
        return {}
    if isinstance(tool_params, Mapping):
        agents = tool_params.get("agents", {})
    else:
        agents = getattr(tool_params, "agents", {})
    agent_override = agents.get(agent_name) if isinstance(agents, Mapping) else None
    if agent_override is None:
        return {}
    tools = (
        agent_override.get("tools", {})
        if isinstance(agent_override, Mapping)
        else getattr(agent_override, "tools", {})
    )
    return {str(tool_name): dict(params) for tool_name, params in dict(tools).items()}


def memory_prompt_fragment(memory_items: Sequence[Any]) -> dict[str, str]:
    """Build a stable memory prompt fragment for provider tests and fixtures."""
    return {"memory_list": json.dumps(list(memory_items), ensure_ascii=False)}
