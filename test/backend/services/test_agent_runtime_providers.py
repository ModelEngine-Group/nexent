import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

backend_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../backend")
)
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from consts import const
from services.agent_runtime.assembly import assemble_agent_run_plan
from services.agent_runtime.models import (
    AgentRunRequestContext,
    AssemblyState,
    CapabilityContribution,
    ContextMode,
    MCPConnectionConfig,
    OperatorSpec,
    ToolSource,
    ToolSpec,
)
from services.agent_runtime.providers import (
    ContextProvider,
    KnowledgeProvider,
    MCPProvider,
    MemoryProvider,
    ModelProvider,
    SkillProvider,
    SubAgentProvider,
    ToolProvider,
    memory_prompt_fragment,
)
from services.agent_runtime.assembly import DuplicateToolIdentifierError


@dataclass
class ContributionProvider:
    name: str
    priority: int
    contribution: CapabilityContribution
    depends_on: tuple[str, ...] = ()

    def contribute(
        self,
        request: AgentRunRequestContext,
        state: AssemblyState,
    ) -> CapabilityContribution:
        _ = (request, state)
        return self.contribution


def _request(**overrides: Any) -> AgentRunRequestContext:
    payload = {
        "request_id": "req-1",
        "runtime_provider": const.AGENT_RUNTIME_PROVIDER_SMOLAGENTS,
        "agent_id": 1,
        "conversation_id": 10,
        "query": "hello",
        "history": [],
        "minio_files": [],
        "user_id": "user-1",
        "tenant_id": "tenant-1",
        "language": "zh",
        "is_debug": False,
        "version_no": 3,
    }
    payload.update(overrides)
    return AgentRunRequestContext(**payload)


def _agent_record(**overrides: Any) -> dict[str, Any]:
    record = {
        "agent_id": 1,
        "name": "root",
        "description": "Root agent",
        "model_id": 100,
        "model_name": "main_model",
        "max_steps": 8,
        "duty_prompt": "Answer questions.",
        "constraint_prompt": "Be precise.",
        "few_shots_prompt": "",
        "enable_context_manager": False,
    }
    record.update(overrides)
    return record


def _model_records() -> list[dict[str, Any]]:
    return [
        {
            "model_id": 100,
            "display_name": "gpt-4o",
            "api_key": "key",
            "model_repo": "openai",
            "model_name": "gpt-4o",
            "base_url": "https://api.example",
            "ssl_verify": True,
            "model_factory": "openai",
            "max_output_tokens": 4096,
            "context_window_tokens": 128000,
            "default_output_reserve_tokens": 2048,
            "capacity_source": "operator",
            "capability_profile_version": "openai/gpt-4o@1",
        }
    ]


def _model_provider() -> ModelProvider:
    return ModelProvider(
        model_records_resolver=lambda tenant_id: _model_records(),
        legacy_model_config_resolver=lambda tenant_id: {
            "api_key": "legacy-key",
            "model_repo": "openai",
            "model_name": "gpt-4o-mini",
            "base_url": "https://legacy.example",
            "model_factory": "openai",
        },
        prompt_cache_resolver=lambda model_factory: {"provider": model_factory},
    )


def _context_provider(agent_record: dict[str, Any] | None = None) -> ContextProvider:
    agent_record = agent_record or _agent_record()
    return ContextProvider(
        agent_record_resolver=lambda agent_id, tenant_id, version_no: agent_record,
        app_config_resolver=lambda key, tenant_id: {
            "APP_NAME": "Nexent",
            "APP_DESCRIPTION": "Nexent test app",
        }.get(key),
        prompt_template_resolver=lambda is_manager, language: {
            "system_prompt": (
                "{{ duty }}\n{{ constraint }}\n{{ APP_NAME }}\n"
                "{{ knowledge_base_summary | default('') }}\n"
                "{{ memory_list | default('') }}"
            )
        },
    )


def _summary(plan) -> dict[str, Any]:
    return {
        "root_name": plan.root_agent.name,
        "model_name": plan.root_agent.model_name,
        "context_mode": plan.root_agent.context_policy.mode.value,
        "tool_names": [tool.name for tool in plan.root_agent.tools],
        "tool_params": {
            tool.name: tool.params for tool in plan.root_agent.tools if tool.params
        },
        "prompt_fragments": {
            key: plan.root_agent.prompt.fragments[key]
            for key in sorted(plan.root_agent.prompt.fragments)
            if key
            in {
                "APP_NAME",
                "constraint",
                "duty",
                "few_shots",
                "skills",
                "knowledge_base_summary",
                "memory_list",
            }
        },
        "mcp_connections": [
            {
                "name": connection.name,
                "transport": connection.transport,
                "url": connection.url,
            }
            for connection in plan.mcp_connections
        ],
        "managed_agent_names": [agent.name for agent in plan.root_agent.managed_agents],
        "external_a2a_count": len(plan.root_agent.external_a2a_agents),
    }


def test_model_provider_contributes_model_aliases_prompt_cache_and_capacity_metadata():
    state = AssemblyState(agent_record=_agent_record(), version_no=3)
    request = _request(requested_output_tokens=1024)

    contribution = _model_provider().contribute(request, state)

    assert [model["cite_name"] for model in contribution.model_configs] == [
        "gpt-4o",
        "main_model",
        "sub_model",
    ]
    assert contribution.model_configs[0]["prompt_cache"] == {"provider": "openai"}
    assert contribution.agent_record["model_name"] == "gpt-4o"
    assert contribution.monitoring_metadata["model.requested_output_tokens"] == 1024
    assert contribution.monitoring_metadata["model.capacity_snapshot"] == {
        "context_window_tokens": 128000,
        "max_output_tokens": 4096,
        "default_output_reserve_tokens": 2048,
        "capacity_source": "operator",
        "capability_profile_version": "openai/gpt-4o@1",
    }
    assert contribution.monitoring_metadata["model.safe_input_budget_snapshot"] == {
        "requested_output_tokens": 1024,
        "requested_output_source": "request",
        "soft_input_budget_tokens": 126976,
        "hard_input_budget_tokens": 127999,
    }


def test_sub_agent_provider_resolves_internal_children_and_external_a2a():
    provider = SubAgentProvider(
        agent_record_resolver=lambda agent_id, tenant_id, version_no: {
            2: {
                "agent_id": 2,
                "name": "researcher",
                "description": "Research",
                "model_name": "sub_model",
                "max_steps": 4,
                "duty_prompt": "Research facts.",
            },
            3: {
                "agent_id": 3,
                "name": "critic",
                "description": "Critique",
                "model_name": "sub_model",
                "max_steps": 3,
                "duty_prompt": "Review answers.",
            },
        }.get(agent_id),
        relations_resolver=lambda agent_id, tenant_id, version_no: {
            1: [{"selected_agent_id": 2, "selected_agent_version_no": 5}],
            2: [{"selected_agent_id": 3, "selected_agent_version_no": 6}],
        }.get(agent_id, []),
        version_resolver=lambda selected_agent_id, selected_version, tenant_id: (
            selected_version
        ),
        external_a2a_resolver=lambda agent_id, tenant_id, version_no: [
            {"agent_id": "a2a-1", "name": "remote"}
        ],
    )

    contribution = provider.contribute(_request(), AssemblyState(version_no=3))

    assert contribution.managed_agents[0].name == "researcher"
    assert contribution.managed_agents[0].runtime_hints["version_no"] == 5
    assert contribution.managed_agents[0].managed_agents[0].name == "critic"
    assert contribution.external_a2a_agents == [{"agent_id": "a2a-1", "name": "remote"}]


def test_tool_provider_applies_request_overrides_and_keeps_langchain_as_reference():
    provider = ToolProvider(
        tool_records_resolver=lambda agent_id, tenant_id, version_no: [
            {
                "name": "search",
                "class_name": "SearchTool",
                "description": "Search",
                "inputs": '{"query": {"type": "string"}}',
                "output_type": "string",
                "params": [{"name": "top_k", "default": 3}],
                "source": "local",
            },
            {
                "name": "calendar",
                "class_name": "CalendarTool",
                "description": "Calendar",
                "inputs": "{}",
                "output_type": "string",
                "params": [],
                "source": "langchain",
            },
        ]
    )
    request = _request(
        tool_params={
            "agents": {
                "root": {
                    "tools": {
                        "SearchTool": {"top_k": 8},
                    }
                }
            }
        }
    )
    state = AssemblyState(agent_record={"name": "root"}, version_no=3)

    contribution = provider.contribute(request, state)

    search, calendar = contribution.tools_by_agent["root"]
    assert search.params == {"top_k": 8}
    assert search.input_schema == {"query": {"type": "string"}}
    assert calendar.source == ToolSource.LANGCHAIN
    assert calendar.metadata == {"langchain_tool_name": "CalendarTool"}


def test_tool_provider_rejects_duplicate_tool_identifier():
    provider = ToolProvider(
        tool_records_resolver=lambda agent_id, tenant_id, version_no: [
            {"name": "search", "class_name": "SearchTool", "inputs": "{}"},
            {"name": "SEARCH", "class_name": "OtherTool", "inputs": "{}"},
        ]
    )

    with pytest.raises(DuplicateToolIdentifierError, match="search"):
        provider.contribute(_request(), AssemblyState(agent_record={"name": "root"}))


def test_context_provider_renders_legacy_prompt():
    state = AssemblyState(
        agent_record=_agent_record(model_name="gpt-4o"),
        prompt_fragments={"knowledge_base_summary": "**Docs**: facts"},
        version_no=3,
    )

    contribution = _context_provider(_agent_record(model_name="gpt-4o")).contribute(
        _request(),
        state,
    )

    assert contribution.root_agent.name == "root"
    assert contribution.root_agent.model_name == "gpt-4o"
    assert contribution.root_agent.context_policy.mode == ContextMode.LEGACY
    assert (
        "Answer questions."
        in contribution.root_agent.prompt.rendered_legacy_system_prompt
    )
    assert (
        "**Docs**: facts"
        in contribution.root_agent.prompt.rendered_legacy_system_prompt
    )


def test_context_provider_uses_managed_components_without_legacy_rendering():
    state = AssemblyState(
        agent_record=_agent_record(enable_context_manager=True),
        version_no=3,
    )
    provider = _context_provider(_agent_record(enable_context_manager=True))

    contribution = provider.contribute(_request(), state)

    assert contribution.root_agent.context_policy.mode == ContextMode.MANAGED
    assert contribution.root_agent.prompt.rendered_legacy_system_prompt is None
    assert (
        contribution.root_agent.prompt.context_components[0]["type"] == "agent_profile"
    )


def test_context_provider_normalizes_legacy_default_for_openjiuwen():
    agent_record = _agent_record(enable_context_manager=True)
    state = AssemblyState(agent_record=agent_record, version_no=3)
    provider = _context_provider(agent_record)

    contribution = provider.contribute(
        _request(runtime_provider=const.AGENT_RUNTIME_PROVIDER_OPENJIUWEN),
        state,
    )

    assert contribution.root_agent.context_policy.mode == ContextMode.RUNTIME_NATIVE
    assert contribution.warnings[0].code == "context_policy_normalized"

    compressed_record = _agent_record(
        enable_context_manager=True,
        compression={"strategy": "summary"},
    )
    compressed = _context_provider(compressed_record).contribute(
        _request(runtime_provider=const.AGENT_RUNTIME_PROVIDER_OPENJIUWEN),
        AssemblyState(agent_record=compressed_record, version_no=3),
    )
    assert compressed.root_agent.context_policy.mode == ContextMode.MANAGED


@pytest.mark.asyncio
async def test_runtime_assembly_e2e_matrix_covers_core_capabilities():
    """Assemble one run plan across the core provider/runtime capability matrix."""
    memory_context = SimpleNamespace(
        user_config=SimpleNamespace(
            memory_switch=True,
            agent_share_option="always",
            disable_agent_ids=[],
            disable_user_agent_ids=[],
        ),
        memory_config={"provider": "mem0"},
        tenant_id="tenant-1",
        user_id="user-1",
        agent_id="1",
    )
    providers = [
        _model_provider(),
        SubAgentProvider(
            agent_record_resolver=lambda agent_id, tenant_id, version_no: {
                2: {
                    "agent_id": 2,
                    "name": "researcher",
                    "description": "Research",
                    "model_name": "sub_model",
                    "max_steps": 4,
                    "duty_prompt": "Research facts.",
                }
            }.get(agent_id),
            relations_resolver=lambda agent_id, tenant_id, version_no: (
                [{"selected_agent_id": 2, "selected_agent_version_no": 5}]
                if agent_id == 1
                else []
            ),
            version_resolver=lambda selected_agent_id, selected_version, tenant_id: (
                selected_version
            ),
            external_a2a_resolver=lambda agent_id, tenant_id, version_no: [
                {"agent_id": "a2a-1", "name": "remote"}
            ],
        ),
        ToolProvider(
            tool_records_resolver=lambda agent_id, tenant_id, version_no: [
                {
                    "name": "echo",
                    "class_name": "EchoTool",
                    "description": "Echo",
                    "inputs": '{"text": {"type": "string"}}',
                    "output_type": "string",
                    "params": [{"name": "style", "default": "short"}],
                    "source": "local",
                },
                {
                    "name": "knowledge_base_search",
                    "class_name": "KnowledgeBaseSearchTool",
                    "description": "Search KB",
                    "inputs": '{"query": {"type": "string"}}',
                    "output_type": "string",
                    "params": [
                        {"name": "index_names", "default": ["kb-index"]},
                        {"name": "document_paths", "default": ["/handbook"]},
                    ],
                    "source": "local",
                },
            ]
        ),
        KnowledgeProvider(
            embedding_model_resolver=lambda tenant_id, index_name: {"model": "embed"},
            knowledge_name_map_resolver=lambda index_names: {"kb-index": "Handbook"},
            knowledge_summary_resolver=lambda index_name: {"summary": "Product facts"},
        ),
        SkillProvider(
            local_skills_dir="/opt/nexent/skills",
            skill_records_resolver=lambda agent_id, tenant_id, version_no: [
                {
                    "skill_id": 10,
                    "skill_name": "report-writer",
                    "skill_description": "Create reports",
                    "enabled": True,
                }
            ],
        ),
        MemoryProvider(
            memory_context_resolver=lambda user_id, tenant_id, agent_id, skip_query: (
                memory_context
            ),
            memory_searcher=lambda **kwargs: {
                "results": [
                    {"content": "likes concise answers", "memory_level": "user"}
                ]
            },
        ),
        MCPProvider(
            mcp_records_resolver=lambda tenant_id: [
                {
                    "remote_mcp_server_name": "docs",
                    "remote_mcp_server": "https://mcp.example/mcp",
                    "authorization_token": "Bearer token",
                }
            ],
            mcp_tool_records_resolver=lambda agent_id, tenant_id, version_no: [
                {
                    "name": "docs_search",
                    "class_name": "search",
                    "description": "Search docs",
                    "inputs": '{"query": {"type": "string"}}',
                    "output_type": "string",
                    "source": "mcp",
                    "usage": "docs",
                }
            ],
        ),
        _context_provider(_agent_record(model_name="gpt-4o")),
    ]

    plan = await assemble_agent_run_plan(
        _request(),
        providers,
        agent_record=_agent_record(),
    )

    tool_names = {tool.name for tool in plan.root_agent.tools}
    assert {
        "echo",
        "knowledge_base_search",
        "read_skill_md",
        "search_memory",
        "docs_search",
    } <= tool_names
    assert plan.root_agent.managed_agents[0].name == "researcher"
    assert plan.root_agent.external_a2a_agents == [
        {"agent_id": "a2a-1", "name": "remote"}
    ]
    assert plan.mcp_connections[0].name == "docs"
    assert plan.mcp_connections[0].transport == "streamable-http"
    assert plan.root_agent.prompt.fragments["skills"][0]["name"] == "report-writer"
    assert "Product facts" in plan.root_agent.prompt.fragments["knowledge_base_summary"]
    assert "likes concise answers" in plan.root_agent.prompt.fragments["memory_list"]
    assert plan.runtime_resources["knowledge.summary_status"] == "ok"
    assert set(plan.runtime_resources["memory.retrieval_levels"]) == {
        "tenant",
        "user",
        "agent",
        "user_agent",
    }
    assert {"skill_file_upload", "memory_persistence", "knowledge_summary"} <= {
        operator.name for operator in plan.operators
    }


@pytest.mark.asyncio
async def test_runtime_assembly_e2e_memory_switch_and_failure_downgrade():
    """Memory e2e variants keep runs usable when disabled or retrieval fails."""
    disabled_context = _memory_context(memory_switch=False)

    def failing_memory_searcher(**kwargs):
        _ = kwargs
        raise RuntimeError("mem0 down")

    disabled_plan = await assemble_agent_run_plan(
        _request(),
        [
            _model_provider(),
            ContributionProvider(
                name="skill",
                priority=400,
                contribution=CapabilityContribution(),
            ),
            MemoryProvider(
                memory_context_resolver=lambda user_id, tenant_id, agent_id, skip_query: (
                    disabled_context
                )
            ),
            _context_provider(_agent_record(model_name="gpt-4o")),
        ],
        agent_record=_agent_record(),
    )

    failed_plan = await assemble_agent_run_plan(
        _request(),
        [
            _model_provider(),
            ContributionProvider(
                name="skill",
                priority=400,
                contribution=CapabilityContribution(),
            ),
            MemoryProvider(
                memory_context_resolver=lambda user_id, tenant_id, agent_id, skip_query: (
                    _memory_context()
                ),
                memory_searcher=failing_memory_searcher,
            ),
            _context_provider(_agent_record(model_name="gpt-4o")),
        ],
        agent_record=_agent_record(),
    )

    assert "search_memory" not in {tool.name for tool in disabled_plan.root_agent.tools}
    assert disabled_plan.monitoring_metadata["memory.disabled_reason"] == "switch_off"
    assert {"search_memory", "store_memory"} <= {
        tool.name for tool in failed_plan.root_agent.tools
    }
    assert failed_plan.monitoring_metadata["memory.retrieval_status"] == "soft_failure"
    assert failed_plan.root_agent.prompt.fragments["memory_list"] == "[]"


def test_mcp_provider_filters_used_servers_and_merges_headers():
    state = AssemblyState(
        agent_record={"name": "root"},
        tools_by_agent={
            "root": [
                ToolSpec(
                    name="docs_search",
                    source=ToolSource.MCP,
                    usage="docs",
                    class_name="search",
                )
            ]
        },
        version_no=3,
    )
    provider = MCPProvider(
        mcp_records_resolver=lambda tenant_id: [
            {
                "remote_mcp_server_name": "docs",
                "remote_mcp_server": "https://mcp.example/sse",
                "authorization_token": "Bearer token",
                "custom_headers": {"X-Tenant": tenant_id},
                "required": True,
            },
            {
                "remote_mcp_server_name": "unused",
                "remote_mcp_server": "https://unused.example/mcp",
            },
        ]
    )

    contribution = provider.contribute(_request(), state)

    assert [connection.model_dump() for connection in contribution.mcp_connections] == [
        {
            "name": "docs",
            "url": "https://mcp.example/sse",
            "transport": "sse",
            "headers": {
                "Authorization": "Bearer token",
                "X-Tenant": "tenant-1",
            },
            "required": True,
        }
    ]
    assert contribution.runtime_resources == {
        "mcp.docs.headers": {
            "Authorization": "Bearer token",
            "X-Tenant": "tenant-1",
        },
        "mcp.docs.required": True,
    }


def test_mcp_provider_normalizes_streamable_http_and_optional_servers():
    state = AssemblyState(
        agent_record={"name": "root"},
        tools_by_agent={
            "root": [
                ToolSpec(
                    name="calendar",
                    source=ToolSource.MCP,
                    usage="calendar",
                    class_name="list_events",
                )
            ]
        },
    )
    provider = MCPProvider(
        mcp_records_resolver=lambda tenant_id: [
            {
                "name": "calendar",
                "url": "https://mcp.example/mcp",
                "headers": {"X-API-Key": "secret"},
                "required": False,
            }
        ]
    )

    contribution = provider.contribute(_request(), state)

    assert contribution.mcp_connections[0].transport == "streamable-http"
    assert contribution.mcp_connections[0].headers == {"X-API-Key": "secret"}
    assert contribution.mcp_connections[0].required is False
    assert contribution.runtime_resources["mcp.calendar.required"] is False


def test_mcp_provider_outputs_mcp_tool_specs_from_injected_records():
    provider = MCPProvider(
        mcp_records_resolver=lambda tenant_id: [
            {
                "remote_mcp_server_name": "docs",
                "remote_mcp_server": "https://mcp.example/mcp",
            }
        ],
        mcp_tool_records_resolver=lambda agent_id, tenant_id, version_no: [
            {
                "name": "docs_search",
                "class_name": "search",
                "description": "Search docs",
                "inputs": '{"query": {"type": "string"}}',
                "output_type": "string",
                "source": "mcp",
                "usage": "docs",
            }
        ],
    )

    contribution = provider.contribute(
        _request(),
        AssemblyState(agent_record={"name": "root"}, version_no=3),
    )

    tool = contribution.tools_by_agent["root"][0]
    assert tool.name == "docs_search"
    assert tool.source == ToolSource.MCP
    assert tool.usage == "docs"
    assert tool.class_name == "search"
    assert tool.input_schema == {"query": {"type": "string"}}
    assert contribution.mcp_connections[0].name == "docs"


def test_mcp_provider_warns_when_used_server_is_missing():
    state = AssemblyState(
        agent_record={"name": "root"},
        tools_by_agent={
            "root": [
                ToolSpec(
                    name="missing_tool",
                    source=ToolSource.MCP,
                    usage="missing",
                    class_name="search",
                )
            ]
        },
    )

    contribution = MCPProvider().contribute(_request(), state)

    assert contribution.mcp_connections == []
    assert contribution.warnings[0].code == "mcp_server_missing"
    assert contribution.warnings[0].metadata == {"server_name": "missing"}


def test_skill_provider_outputs_enabled_skill_prompt_tools_and_hidden_params():
    provider = SkillProvider(
        local_skills_dir="/opt/nexent/skills",
        skill_records_resolver=lambda agent_id, tenant_id, version_no: [
            {
                "skill_id": 10,
                "name": "report-writer",
                "description": "Create project reports",
                "enabled": True,
                "config_values": {"tone": "formal"},
                "tool_ids": [101],
            },
            {
                "skill_id": 11,
                "name": "disabled-skill",
                "description": "Should not be exposed",
                "enabled": False,
            },
        ],
    )

    contribution = provider.contribute(
        _request(),
        AssemblyState(agent_record={"name": "root"}, version_no=3),
    )

    assert contribution.prompt_fragments["skills"] == [
        {
            "skill_id": 10,
            "name": "report-writer",
            "description": "Create project reports",
        }
    ]
    tools = contribution.tools_by_agent["root"]
    assert [tool.name for tool in tools] == [
        "run_skill_script",
        "read_skill_md",
        "read_skill_config",
        "write_skill_file",
    ]
    assert all(tool.source == ToolSource.BUILTIN for tool in tools)
    assert all(tool.metadata["capability"] == "skill" for tool in tools)
    assert all(tool.metadata["agent_id"] == 1 for tool in tools)
    assert all(tool.metadata["tenant_id"] == "tenant-1" for tool in tools)
    assert all(tool.metadata["version_no"] == 3 for tool in tools)
    assert all(
        tool.injected_params["local_skills_dir"] == "/opt/nexent/skills"
        for tool in tools
    )
    assert all("local_skills_dir" not in tool.input_schema for tool in tools)
    assert all("tenant_id" not in tool.input_schema for tool in tools)
    tools_by_name = {tool.name: tool for tool in tools}
    assert tools_by_name["read_skill_md"].input_schema == {
        "type": "object",
        "properties": {
            "skill_name": {"type": "string"},
            "additional_files": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
            },
        },
        "required": ["skill_name"],
    }
    assert tools_by_name["run_skill_script"].input_schema == {
        "type": "object",
        "properties": {
            "skill_name": {"type": "string"},
            "script_path": {"type": "string"},
            "params": {
                "type": ["string", "null"],
                "default": None,
            },
        },
        "required": ["skill_name", "script_path"],
    }
    assert contribution.runtime_resources["skill.enabled_skills"] == [
        {
            "skill_id": 10,
            "name": "report-writer",
            "description": "Create project reports",
            "config_values": {"tone": "formal"},
            "tool_ids": [101],
        }
    ]
    assert contribution.operators[0].name == "skill_file_upload"
    assert contribution.operators[0].required is False
    assert contribution.monitoring_metadata == {"skill.enabled_count": 1}


def test_skill_provider_skips_prompt_tools_and_operator_when_no_skill_enabled():
    provider = SkillProvider(
        skill_records_resolver=lambda agent_id, tenant_id, version_no: [
            {
                "skill_id": 10,
                "skill_name": "disabled-skill",
                "skill_description": "Disabled",
                "enabled": False,
            }
        ],
    )

    contribution = provider.contribute(
        _request(),
        AssemblyState(agent_record={"name": "root"}, version_no=3),
    )

    assert contribution.prompt_fragments == {}
    assert contribution.tools_by_agent == {}
    assert contribution.runtime_resources == {}
    assert contribution.operators == []


def _memory_context(
    *,
    memory_switch: bool = True,
    agent_share_option: str = "always",
    disable_agent_ids: list[str] | None = None,
    disable_user_agent_ids: list[str] | None = None,
    memory_config: dict[str, Any] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        user_config=SimpleNamespace(
            memory_switch=memory_switch,
            agent_share_option=agent_share_option,
            disable_agent_ids=disable_agent_ids or [],
            disable_user_agent_ids=disable_user_agent_ids or [],
        ),
        memory_config=memory_config
        if memory_config is not None
        else {"provider": "mem0"},
        tenant_id="tenant-1",
        user_id="user-1",
        agent_id="1",
    )


@pytest.mark.asyncio
async def test_memory_provider_retrieves_context_and_outputs_active_tools():
    provider = MemoryProvider(
        memory_context_resolver=lambda user_id, tenant_id, agent_id, skip_query: (
            _memory_context()
        ),
        memory_searcher=lambda **kwargs: {
            "results": [{"content": "likes concise answers", "memory_level": "user"}]
        },
    )

    contribution = await provider.contribute(
        _request(query="remember me"),
        AssemblyState(agent_record={"name": "root"}, version_no=3),
    )

    assert contribution.prompt_fragments == {
        "memory_list": '[{"content": "likes concise answers", "memory_level": "user"}]'
    }
    assert contribution.context_components == [
        {
            "type": "memory",
            "items": [{"content": "likes concise answers", "memory_level": "user"}],
            "query": "remember me",
            "levels": ["tenant", "agent", "user", "user_agent"],
            "retrieval_status": "ok",
        }
    ]
    assert [tool.name for tool in contribution.tools_by_agent["root"]] == [
        "store_memory",
        "search_memory",
    ]
    store_memory = contribution.tools_by_agent["root"][0]
    assert store_memory.source == ToolSource.MEMORY
    assert store_memory.metadata["memory_config"] == {"provider": "mem0"}
    assert store_memory.metadata["tenant_id"] == "tenant-1"
    assert store_memory.injected_params["memory_config"] == {"provider": "mem0"}
    assert "memory_config" not in store_memory.input_schema
    assert [operator.name for operator in contribution.operators] == [
        "memory_retrieval",
        "memory_persistence",
    ]
    assert contribution.monitoring_metadata["memory.retrieved_count"] == 1


@pytest.mark.asyncio
async def test_memory_provider_skips_debug_and_switch_off_without_tools():
    provider = MemoryProvider(
        memory_context_resolver=lambda user_id, tenant_id, agent_id, skip_query: (
            _memory_context(
                memory_switch=not skip_query,
            )
        ),
    )

    debug_contribution = await provider.contribute(
        _request(is_debug=True),
        AssemblyState(agent_record={"name": "root"}, version_no=3),
    )
    off_contribution = await MemoryProvider(
        memory_context_resolver=lambda user_id, tenant_id, agent_id, skip_query: (
            _memory_context(
                memory_switch=False,
            )
        ),
    ).contribute(
        _request(),
        AssemblyState(agent_record={"name": "root"}, version_no=3),
    )

    assert debug_contribution.tools_by_agent == {}
    assert debug_contribution.monitoring_metadata["memory.disabled_reason"] == "debug"
    assert off_contribution.tools_by_agent == {}
    assert (
        off_contribution.monitoring_metadata["memory.disabled_reason"] == "switch_off"
    )


@pytest.mark.asyncio
async def test_memory_provider_applies_share_and_disable_lists_to_retrieval_levels():
    captured_kwargs: dict[str, Any] = {}

    async def searcher(**kwargs: Any) -> dict[str, Any]:
        captured_kwargs.update(kwargs)
        return {"results": []}

    provider = MemoryProvider(
        memory_context_resolver=lambda user_id, tenant_id, agent_id, skip_query: (
            _memory_context(
                agent_share_option="never",
                disable_agent_ids=["1"],
                disable_user_agent_ids=["1"],
            )
        ),
        memory_searcher=searcher,
    )

    contribution = await provider.contribute(
        _request(),
        AssemblyState(agent_record={"name": "root"}, version_no=3),
    )

    assert captured_kwargs["memory_levels"] == ["tenant", "user"]
    assert contribution.runtime_resources["memory.retrieval_levels"] == [
        "tenant",
        "user",
    ]
    assert contribution.context_components[0]["levels"] == ["tenant", "user"]


@pytest.mark.asyncio
async def test_memory_provider_soft_fails_retrieval_and_keeps_memory_tools():
    provider = MemoryProvider(
        memory_context_resolver=lambda user_id, tenant_id, agent_id, skip_query: (
            _memory_context()
        ),
        memory_searcher=lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("mem0 down")
        ),
    )

    contribution = await provider.contribute(
        _request(),
        AssemblyState(agent_record={"name": "root"}, version_no=3),
    )

    assert contribution.prompt_fragments == {"memory_list": "[]"}
    assert contribution.context_components[0]["retrieval_status"] == "soft_failure"
    assert [tool.name for tool in contribution.tools_by_agent["root"]] == [
        "store_memory",
        "search_memory",
    ]
    assert contribution.monitoring_metadata["memory.retrieval_status"] == "soft_failure"
    assert contribution.warnings[0].code == "memory_retrieval_failed"


def test_knowledge_provider_enhances_tool_metadata_and_summary():
    provider = KnowledgeProvider(
        embedding_model_resolver=lambda tenant_id, index_name: (
            {"model": "embedding", "index_name": index_name},
            None,
            None,
        ),
        rerank_model_resolver=lambda tenant_id, model_name: {"model": model_name},
        knowledge_name_map_resolver=lambda index_names: {"kb-index": "Handbook"},
        knowledge_summary_resolver=lambda index_name: {"summary": "Product facts"},
    )
    state = AssemblyState(
        agent_record={"name": "root"},
        tools_by_agent={
            "root": [
                ToolSpec(
                    name="knowledge_base_search",
                    class_name="KnowledgeBaseSearchTool",
                    input_schema={
                        "query": {"type": "string"},
                        "index_names": {"type": "array"},
                        "document_paths": {"type": "array"},
                    },
                    raw_inputs=json.dumps(
                        {
                            "query": {"type": "string"},
                            "index_names": {"type": "array"},
                            "document_paths": {"type": "array"},
                        }
                    ),
                    params={
                        "index_names": ["kb-index"],
                        "rerank": True,
                        "rerank_model_name": "bge-reranker",
                        "document_paths": ["/docs/handbook.md"],
                    },
                )
            ]
        },
        version_no=3,
    )

    contribution = provider.contribute(_request(), state)

    tool = contribution.tools_by_agent["root"][0]
    assert tool.source == ToolSource.KNOWLEDGE
    assert tool.params == {
        "index_names": ["kb-index"],
        "rerank": True,
        "rerank_model_name": "bge-reranker",
    }
    assert tool.metadata["embedding_model"] == {
        "model": "embedding",
        "index_name": "kb-index",
    }
    assert tool.metadata["rerank_model"] == {"model": "bge-reranker"}
    assert tool.metadata["display_name_to_index_map"] == {"Handbook": "kb-index"}
    assert tool.metadata["index_name_to_display_map"] == {"kb-index": "Handbook"}
    assert tool.metadata["document_paths"] == ["/docs/handbook.md"]
    assert tool.injected_params["document_paths"] == ["/docs/handbook.md"]
    assert tool.injected_params["embedding_model"] == {
        "model": "embedding",
        "index_name": "kb-index",
    }
    assert "document_paths" not in tool.input_schema
    assert "document_paths" not in json.loads(tool.raw_inputs)
    assert contribution.prompt_fragments == {
        "knowledge_base_summary": "**Handbook**: Product facts\n\n"
    }
    assert contribution.context_components == [
        {
            "type": "knowledge_summary",
            "summary": "**Handbook**: Product facts\n\n",
            "kb_ids": ["kb-index"],
            "status": "ok",
        }
    ]
    assert contribution.runtime_resources["knowledge.kb_ids"] == ["kb-index"]
    assert contribution.runtime_resources["knowledge.summary_status"] == "ok"
    assert contribution.runtime_resources["knowledge.display_name_to_index_map"] == {
        "Handbook": "kb-index"
    }
    assert contribution.operators[0].name == "knowledge_summary"
    assert contribution.operators[0].stages == {"prepare_context"}
    assert contribution.warnings == []


def test_knowledge_provider_rejects_missing_index_names():
    provider = KnowledgeProvider(
        embedding_model_resolver=lambda tenant_id, index_name: {"model": "embedding"},
    )
    state = AssemblyState(
        agent_record={"name": "root"},
        tools_by_agent={
            "root": [
                ToolSpec(
                    name="knowledge_base_search",
                    class_name="KnowledgeBaseSearchTool",
                    input_schema={"query": {"type": "string"}},
                    params={},
                )
            ]
        },
    )

    with pytest.raises(ValueError, match="requires index_names"):
        provider.contribute(_request(), state)


def test_knowledge_provider_soft_fails_summary_and_keeps_tool():
    provider = KnowledgeProvider(
        embedding_model_resolver=lambda tenant_id, index_name: {"model": "embedding"},
        knowledge_name_map_resolver=lambda index_names: {"kb-index": "Handbook"},
        knowledge_summary_resolver=lambda index_name: (_ for _ in ()).throw(
            RuntimeError("summary down")
        ),
    )
    state = AssemblyState(
        agent_record={"name": "root"},
        tools_by_agent={
            "root": [
                ToolSpec(
                    name="knowledge_base_search",
                    class_name="KnowledgeBaseSearchTool",
                    input_schema={"query": {"type": "string"}},
                    params={"index_names": "kb-index"},
                )
            ]
        },
    )

    contribution = provider.contribute(_request(), state)

    assert contribution.tools_by_agent["root"][0].source == ToolSource.KNOWLEDGE
    assert contribution.prompt_fragments == {"knowledge_base_summary": ""}
    assert contribution.runtime_resources["knowledge.summary_status"] == "soft_failure"
    assert contribution.context_components[0]["status"] == "soft_failure"
    assert contribution.warnings[0].code == "knowledge_summary_failed"
    assert contribution.warnings[0].metadata == {"index_name": "kb-index"}


@pytest.mark.asyncio
async def test_assembly_golden_fixture_cases():
    fixture_path = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "agent_runtime"
        / "assembly_golden.json"
    )
    expected = json.loads(fixture_path.read_text(encoding="utf-8"))
    cases = {
        "ordinary": [],
        "with_tool": [
            ContributionProvider(
                name="tool",
                priority=200,
                depends_on=("sub-agent",),
                contribution=CapabilityContribution(
                    tools_by_agent={
                        "root": [
                            ToolSpec(
                                name="echo",
                                class_name="EchoTool",
                                params={"style": "short"},
                            )
                        ]
                    }
                ),
            )
        ],
        "with_skill": [
            ContributionProvider(
                name="skill",
                priority=400,
                contribution=CapabilityContribution(
                    prompt_fragments={
                        "skills": [
                            {
                                "name": "report-writer",
                                "description": "Create project reports",
                            }
                        ]
                    },
                    tools_by_agent={
                        "root": [
                            ToolSpec(
                                name="read_skill_md",
                                source=ToolSource.SKILL,
                            )
                        ]
                    },
                    operators=[
                        OperatorSpec(name="skill_file_upload", stages={"after_run"})
                    ],
                ),
            )
        ],
        "with_mcp": [
            ContributionProvider(
                name="mcp",
                priority=600,
                contribution=CapabilityContribution(
                    mcp_connections=[
                        MCPConnectionConfig(
                            name="docs",
                            url="http://mcp.example/mcp",
                            transport="streamable-http",
                            headers={"Authorization": "Bearer token"},
                        )
                    ],
                    tools_by_agent={
                        "root": [
                            ToolSpec(
                                name="docs_search",
                                source=ToolSource.MCP,
                                usage="docs",
                                class_name="search",
                            )
                        ]
                    },
                ),
            )
        ],
        "with_knowledge": [
            ContributionProvider(
                name="knowledge",
                priority=300,
                contribution=CapabilityContribution(
                    prompt_fragments={
                        "knowledge_base_summary": "**Handbook**: Product facts"
                    },
                    tools_by_agent={
                        "root": [
                            ToolSpec(
                                name="knowledge_base_search",
                                class_name="KnowledgeBaseSearchTool",
                                source=ToolSource.KNOWLEDGE,
                                metadata={"document_paths": ["/handbook"]},
                            )
                        ]
                    },
                ),
            )
        ],
        "with_memory": [
            ContributionProvider(
                name="memory",
                priority=500,
                contribution=CapabilityContribution(
                    prompt_fragments=memory_prompt_fragment(
                        [{"content": "likes concise answers"}]
                    ),
                    tools_by_agent={
                        "root": [
                            ToolSpec(
                                name="search_memory",
                                class_name="SearchMemoryTool",
                                source=ToolSource.MEMORY,
                            )
                        ]
                    },
                ),
            )
        ],
    }

    for case_name, extra_providers in cases.items():
        providers = [
            _model_provider(),
            SubAgentProvider(),
            *extra_providers,
            _context_provider(_agent_record(model_name="gpt-4o")),
        ]
        plan = await assemble_agent_run_plan(
            _request(),
            providers,
            agent_record=_agent_record(),
        )
        summary = _summary(plan)
        if not summary["tool_params"]:
            summary.pop("tool_params")
        assert summary == expected[case_name]
