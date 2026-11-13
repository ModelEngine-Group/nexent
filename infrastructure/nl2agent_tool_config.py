# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared names, descriptions and presentation metadata for NL2Agent tools."""

import json

from nexent.core.agents.agent_model import ToolConfig

NL2A_MCP_SERVICE_NAME = "nl2a"
MAX_BINDING_CANDIDATES = 12
SEARCH_INSTALLED_MCP_TOOLS_LOCAL_NAME = "search_installed_mcp_tools"
SEARCH_INSTALLED_RESOURCES_LOCAL_NAME = "search_installed_resources"
SEARCH_UNINSTALLED_RESOURCES_LOCAL_NAME = "search_uninstalled_resources"
RECOMMEND_RESOURCES_LOCAL_NAME = "recommend_resources"
SAVE_AGENT_DRAFT_FIELDS_LOCAL_NAME = "save_agent_draft_fields"
NL2A_WRAPPER_LOCAL_NAME = "wrapper"
NL2A_MCP_LOCAL_TOOL_NAMES = (
    SEARCH_INSTALLED_MCP_TOOLS_LOCAL_NAME,
    SEARCH_INSTALLED_RESOURCES_LOCAL_NAME,
    SEARCH_UNINSTALLED_RESOURCES_LOCAL_NAME,
    RECOMMEND_RESOURCES_LOCAL_NAME,
    SAVE_AGENT_DRAFT_FIELDS_LOCAL_NAME,
    NL2A_WRAPPER_LOCAL_NAME,
)
(
    SEARCH_INSTALLED_MCP_TOOLS_NAME,
    SEARCH_INSTALLED_RESOURCES_NAME,
    SEARCH_UNINSTALLED_RESOURCES_NAME,
    RECOMMEND_RESOURCES_NAME,
    SAVE_AGENT_DRAFT_FIELDS_NAME,
    NL2A_WRAPPER_NAME,
) = tuple(
    f"{NL2A_MCP_SERVICE_NAME}_{name}"
    for name in NL2A_MCP_LOCAL_TOOL_NAMES
)
NL2A_MCP_TOOL_NAMES = (
    SEARCH_INSTALLED_MCP_TOOLS_NAME,
    SEARCH_INSTALLED_RESOURCES_NAME,
    SEARCH_UNINSTALLED_RESOURCES_NAME,
    RECOMMEND_RESOURCES_NAME,
    SAVE_AGENT_DRAFT_FIELDS_NAME,
    NL2A_WRAPPER_NAME,
)
NL2A_MCP_LEGACY_TOOL_NAMES = (
    SEARCH_INSTALLED_MCP_TOOLS_LOCAL_NAME,
    SEARCH_INSTALLED_RESOURCES_LOCAL_NAME,
    SEARCH_UNINSTALLED_RESOURCES_LOCAL_NAME,
    RECOMMEND_RESOURCES_LOCAL_NAME,
    SAVE_AGENT_DRAFT_FIELDS_LOCAL_NAME,
    NL2A_WRAPPER_NAME,
)
SEARCH_INSTALLED_MCP_TOOLS_DESCRIPTION = (
    "Search the current tenant's installed and available MCP tools using keywords. "
    "Returns JSON text ordered by relevance. Decode the result with json.loads "
    f"before passing it to {NL2A_WRAPPER_NAME}, preserve the decoded content unchanged, "
    "and use print(result) to expose the decoded observation."
)
SEARCH_INSTALLED_RESOURCES_DESCRIPTION = (
    "Search all current-user-visible installed Local Tools, MCP Tools, and Skills "
    "for a structured set of capability requirements. Return no more than 12 "
    "ranked candidates as JSON text. Decode the result with json.loads before "
    "indexing it, and preserve the decoded candidates unchanged when calling "
    f"{RECOMMEND_RESOURCES_NAME}."
)
SEARCH_UNINSTALLED_RESOURCES_DESCRIPTION = (
    "Search installable Nexent Skills and tenant Skill/MCP repositories for "
    "structured capability requirements. Pass skipped candidate_ref values "
    "unchanged in exclude_refs, and preserve returned candidates unchanged when "
    f"calling {RECOMMEND_RESOURCES_NAME}."
)
RECOMMEND_RESOURCES_DESCRIPTION = (
    "Resolve installed or installable resource candidates into verified card "
    "details. Pass unchanged candidates returned by resource searches and a "
    "unique recommended_refs subset. Decode the JSON result, then pass it "
    f"unchanged to {NL2A_WRAPPER_NAME} with the matching installation or binding subtype."
)
NL2A_WRAPPER_DESCRIPTION = (
    "Build one NL2Agent output for the existing draft. Always pass the current "
    "`agent_id` and `subtype`. For `requirement_clarification`, pass structured "
    "`questions`. For resource installation or binding, pass `agent_id` and the "
    "verified `resource_result`. JSON parameters must be decoded dictionaries, "
    "never raw JSON strings. An empty installed-resource result returns a "
    "non-interactive success result so Prompt generation can continue immediately. "
    f"Call the tool as `result = {NL2A_WRAPPER_NAME}(...)`, then use `print(result)`."
)
SAVE_AGENT_DRAFT_FIELDS_DESCRIPTION = (
    "Partially update the current tenant's existing ordinary agent draft. "
    "Always pass the current agent_id and only whitelisted fields, never null. "
    "Allowed fields: name, display_name, description, prompt, greeting_message, example_questions, "
    "enable_protocol_repair_retry. "
    "enable_protocol_repair_retry must be a boolean: explicit true enables strict output validation and silent "
    "protocol repair for the target Agent, false disables it; omit it unless requested. "
    "It does not control model-service retries or the NL2Agent creator itself. "
    "prompt contains complete responsibilities, constraints, tool-use rules, output requirements and necessary few-shot. "
    "For partial edits, read draft_fields.prompt, preserve unrelated instructions, and save the full merged prompt. "
    "greeting_message and example_questions are separate conversation settings; "
    "example_questions must be a list of strings, never a newline-delimited string. "
    "Only submit the fields determined by the current action. "
    "The name field may be set only when the existing draft name is empty; "
    "display_name may be set only alongside the first name on an empty Workbench Draft; "
    "all other display names are immutable. Call the tool as "
    f"`result = {SAVE_AGENT_DRAFT_FIELDS_NAME}(...)`, then use `print(result)` exactly once."
)

def create_nl2agent_mcp_tool_configs() -> list[ToolConfig]:
    """Create fresh SDK configs for the NL2Agent business tools."""
    return [
        ToolConfig(
            class_name=SEARCH_INSTALLED_RESOURCES_NAME,
            name=SEARCH_INSTALLED_RESOURCES_NAME,
            description=SEARCH_INSTALLED_RESOURCES_DESCRIPTION,
            inputs=(
                '{"agent_id":"int",'
                '"requirements":"list[ResourceRequirement]"}'
            ),
            output_type="object",
            params={},
            source="mcp",
            usage="outer-apis",
        ),
        ToolConfig(
            class_name=SEARCH_UNINSTALLED_RESOURCES_NAME,
            name=SEARCH_UNINSTALLED_RESOURCES_NAME,
            description=SEARCH_UNINSTALLED_RESOURCES_DESCRIPTION,
            inputs=(
                '{"agent_id":"int",'
                '"requirements":"list[ResourceRequirement]",'
                '"exclude_refs":"list[str]"}'
            ),
            output_type="object",
            params={},
            source="mcp",
            usage="outer-apis",
        ),
        ToolConfig(
            class_name=RECOMMEND_RESOURCES_NAME,
            name=RECOMMEND_RESOURCES_NAME,
            description=RECOMMEND_RESOURCES_DESCRIPTION,
            inputs=(
                '{"agent_id":"int",'
                '"candidates":"list[ResourceCandidate]",'
                '"recommended_refs":"list[str]"}'
            ),
            output_type="object",
            params={},
            source="mcp",
            usage="outer-apis",
        ),
        ToolConfig(
            class_name=SAVE_AGENT_DRAFT_FIELDS_NAME,
            name=SAVE_AGENT_DRAFT_FIELDS_NAME,
            description=SAVE_AGENT_DRAFT_FIELDS_DESCRIPTION,
            inputs=json.dumps(
                {
                    "agent_id": "int",
                    "fields": {
                        field_name: field_type
                        for field_name, field_type in {
                            "name": "str",
                            "description": "str",
                            "enable_protocol_repair_retry": "bool",
                            "prompt": "str",
                            "greeting_message": "str",
                            "example_questions": "list[str]",
                        }.items()
                    },
                },
                separators=(",", ":"),
            ),
            output_type="string",
            params={},
            source="mcp",
            usage="outer-apis",
        ),
        ToolConfig(
            class_name=NL2A_WRAPPER_NAME,
            name=NL2A_WRAPPER_NAME,
            description=NL2A_WRAPPER_DESCRIPTION,
            inputs=json.dumps(
                {
                    "subtype": "str",
                    "agent_id": "int",
                    "resource_result": "RecommendResourcesOutput | None",
                    "questions": "list[RequirementClarificationQuestion] | None",
                },
                separators=(",", ":"),
            ),
            output_type="string",
            params={},
            source="mcp",
            usage="outer-apis",
        ),
    ]
