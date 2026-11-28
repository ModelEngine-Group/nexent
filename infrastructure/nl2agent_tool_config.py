# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared NL2Agent tool names and schemas for Management and Runtime."""
import json
from nexent.core.agents.contracts.config import ToolConfig
from contracts.nl2agent_resources import MAX_REQUIREMENTS

NL2A_MCP_SERVICE_NAME = "nl2a"
SEARCH_INSTALLED_MCP_TOOLS_LOCAL_NAME = "search_installed_mcp_tools"
SEARCH_INSTALLED_RESOURCES_LOCAL_NAME = "search_installed_resources"
SEARCH_UNINSTALLED_RESOURCES_LOCAL_NAME = "search_uninstalled_resources"
RECOMMEND_RESOURCES_LOCAL_NAME = "recommend_resources"
SAVE_AGENT_DRAFT_FIELDS_LOCAL_NAME = "save_agent_draft_fields"
VALIDATE_AGENT_GENERATION_COMPLETE_LOCAL_NAME = "validate_agent_generation_complete"
NL2A_WRAPPER_LOCAL_NAME = "wrapper"
NL2A_MCP_LOCAL_TOOL_NAMES = (
    SEARCH_INSTALLED_MCP_TOOLS_LOCAL_NAME,
    SEARCH_INSTALLED_RESOURCES_LOCAL_NAME,
    SEARCH_UNINSTALLED_RESOURCES_LOCAL_NAME,
    RECOMMEND_RESOURCES_LOCAL_NAME,
    SAVE_AGENT_DRAFT_FIELDS_LOCAL_NAME,
    VALIDATE_AGENT_GENERATION_COMPLETE_LOCAL_NAME,
    NL2A_WRAPPER_LOCAL_NAME,
)
(
    SEARCH_INSTALLED_MCP_TOOLS_NAME,
    SEARCH_INSTALLED_RESOURCES_NAME,
    SEARCH_UNINSTALLED_RESOURCES_NAME,
    RECOMMEND_RESOURCES_NAME,
    SAVE_AGENT_DRAFT_FIELDS_NAME,
    VALIDATE_AGENT_GENERATION_COMPLETE_NAME,
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
    VALIDATE_AGENT_GENERATION_COMPLETE_NAME,
    NL2A_WRAPPER_NAME,
)
NL2A_MCP_LEGACY_TOOL_NAMES = (
    SEARCH_INSTALLED_MCP_TOOLS_LOCAL_NAME,
    SEARCH_INSTALLED_RESOURCES_LOCAL_NAME,
    SEARCH_UNINSTALLED_RESOURCES_LOCAL_NAME,
    RECOMMEND_RESOURCES_LOCAL_NAME,
    SAVE_AGENT_DRAFT_FIELDS_LOCAL_NAME,
    VALIDATE_AGENT_GENERATION_COMPLETE_LOCAL_NAME,
    NL2A_WRAPPER_NAME,
)
DISCOVER_REQUIREMENTS_LOCAL_NAME = "discover_requirements"
VERIFY_REQUIREMENTS_LOCAL_NAME = "verify_requirements"
SHOW_RESOURCE_CARD_LOCAL_NAME = "show_resource_card"
READ_CONFIGURATION_LOCAL_NAME = "read_agent_configuration"
SAVE_CONFIGURATION_LOCAL_NAME = "save_agent_configuration"
READ_GENERATION_CONTEXT_LOCAL_NAME = "read_generation_context"
RESOURCE_TOOL_LOCAL_NAMES = (DISCOVER_REQUIREMENTS_LOCAL_NAME, VERIFY_REQUIREMENTS_LOCAL_NAME,
                             SHOW_RESOURCE_CARD_LOCAL_NAME)
DISCOVER_REQUIREMENTS_NAME, VERIFY_REQUIREMENTS_NAME, SHOW_RESOURCE_CARD_NAME = (
    f"{NL2A_MCP_SERVICE_NAME}_{name}" for name in RESOURCE_TOOL_LOCAL_NAMES
)
READ_CONFIGURATION_NAME = f"{NL2A_MCP_SERVICE_NAME}_{READ_CONFIGURATION_LOCAL_NAME}"
SAVE_CONFIGURATION_NAME = f"{NL2A_MCP_SERVICE_NAME}_{SAVE_CONFIGURATION_LOCAL_NAME}"
READ_GENERATION_CONTEXT_NAME = f"{NL2A_MCP_SERVICE_NAME}_{READ_GENERATION_CONTEXT_LOCAL_NAME}"
NL2A_MCP_TOOL_NAMES += (DISCOVER_REQUIREMENTS_NAME, VERIFY_REQUIREMENTS_NAME, SHOW_RESOURCE_CARD_NAME,
                       READ_CONFIGURATION_NAME, SAVE_CONFIGURATION_NAME, READ_GENERATION_CONTEXT_NAME)
NL2A_MCP_LEGACY_TOOL_NAMES += (*RESOURCE_TOOL_LOCAL_NAMES, READ_CONFIGURATION_LOCAL_NAME,
                             SAVE_CONFIGURATION_LOCAL_NAME, READ_GENERATION_CONTEXT_LOCAL_NAME)
NL2A_MCP_LOCAL_TOOL_NAMES += (*RESOURCE_TOOL_LOCAL_NAMES, READ_CONFIGURATION_LOCAL_NAME,
                             SAVE_CONFIGURATION_LOCAL_NAME, READ_GENERATION_CONTEXT_LOCAL_NAME)
DISCOVER_REQUIREMENTS_DESCRIPTION = (
    "Find safe candidates using each requirement's prepared capability queries. "
    "Prepare bilingual search_queries from reusable resource capabilities, not runtime search content or business topics. "
    "Keep requested content in query and preserve explicitly required tools, platforms and data sources. "
    "Omit requirements to resume accepted requirements."
)
VERIFY_REQUIREMENTS_DESCRIPTION = (
    "Submit one entry per requirement with its requirement_id and accepted candidate references. "
    "Omit checked; the runtime already knows which candidates were offered. "
    "The final batch publishes the current resource card."
)
SHOW_RESOURCE_CARD_DESCRIPTION = "Show the current recommendation, coverage, or binding card from the verified requirements."
READ_CONFIGURATION_DESCRIPTION = "Read safe current values and choices for model, collaborators, permissions, tags, guardrails or advanced settings."
SAVE_CONFIGURATION_DESCRIPTION = (
    "Save explicit changes to one supported configuration section on the target draft. "
    "For guardrails, changes accepts enabled (boolean master switch), upsert_rules (list of rules), "
    "and remove_rules (list of rule names). Each rule accepts only name (non-empty string), "
    "pattern (non-empty valid Python regex), severity (block, mask, or pass; defaults to block), "
    "and optional description (string). severity is the matching action, not a risk level: "
    "use block to reject, mask to redact, or pass to allow. Do not use error/high or an action field. "
    "enabled belongs to changes, never to an individual rule. Example: "
    'section="guardrails", changes={"enabled":True,"upsert_rules":'
    '[{"name":"sensitive_info","pattern":"password","severity":"block"}]}. '
    "Only include requested changes; unrelated rules and verification settings are preserved."
)
READ_GENERATION_CONTEXT_DESCRIPTION = (
    "Read current safe draft and bound resource contracts before generating or synchronizing Prompt. "
    "Use goal=complete for full Agent creation, including creation without resources; "
    "use the default goal=prompt for independent prompt generation or optimization."
)
NL2AGENT_AGENT_ID_HEADER = "X-Nexent-NL2Agent-Agent-ID"
NL2AGENT_POLICY_CLARIFICATION_HEADER = "X-Nexent-NL2Agent-Policy-Clarification-Required"
NL2AGENT_RESOURCE_PENDING_HEADER = "X-Nexent-NL2Agent-Resource-Confirmation-Pending"
NL2AGENT_RUN_ID_HEADER = "X-Nexent-NL2Agent-Run-ID"
NL2AGENT_CONVERSATION_ID_HEADER = "X-Nexent-NL2Agent-Conversation-ID"
NL2AGENT_RECEIPT_KEY = "nexent.nl2agent.receipt"
MAX_RESOURCE_REQUIREMENTS_PER_SEARCH = MAX_REQUIREMENTS
RESOURCE_REQUIREMENT_LIMIT_DESCRIPTION = (
    f"Use at most {MAX_RESOURCE_REQUIREMENTS_PER_SEARCH} requirements per search. "
    "If the batch exceeds the limit, ask the user to split the request or narrow its scope."
)
SEARCH_INSTALLED_MCP_TOOLS_DESCRIPTION = (
    "Search the current tenant's installed and available MCP tools using keywords. "
    "Returns JSON text ordered by relevance. Decode the JSON result "
    f"before passing it unchanged to {NL2A_WRAPPER_NAME}."
)
SEARCH_INSTALLED_RESOURCES_DESCRIPTION = (
    "Search all current-user-visible installed Local Tools, MCP Tools, and Skills "
    "for a structured set of capability requirements. Return no more than 12 "
    "ranked candidates as JSON text. Decode the JSON result before "
    "indexing it, and preserve the decoded candidates unchanged when calling "
    f"{RECOMMEND_RESOURCES_NAME}. {RESOURCE_REQUIREMENT_LIMIT_DESCRIPTION}"
)
SEARCH_UNINSTALLED_RESOURCES_DESCRIPTION = (
    "Search installable Nexent Skills and tenant Skill/MCP repositories for "
    "structured capability requirements. Pass skipped candidate_ref values "
    "unchanged in exclude_refs, and preserve returned candidates unchanged when "
    f"calling {RECOMMEND_RESOURCES_NAME}. {RESOURCE_REQUIREMENT_LIMIT_DESCRIPTION}"
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
    "non-interactive success result so Prompt generation can continue immediately."
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
    "Before any prompt save, call nl2a_read_generation_context (goal=complete for full creation). "
    "Save prompt separately. Existing prompts return pending_confirmation and a preview card; stop immediately "
    "without saving dependent settings or reporting success until the user confirms. Empty prompts save directly. "
    "greeting_message and example_questions are separate conversation settings; "
    "example_questions must be a list of strings, never a newline-delimited string. "
    "Only submit the fields determined by the current action. A save does not validate full generation. "
    "The name field may be set only when the existing draft name is empty; "
    "display_name may be set only alongside the first name on an empty Workbench Draft; "
    "all other display names are immutable."
)
VALIDATE_AGENT_GENERATION_COMPLETE_DESCRIPTION = (
    "Read the authorized target draft and validate full generation after all requested fields "
    "have been saved. This tool does not write fields. Call only for full generation."
)

MAX_BINDING_CANDIDATES = 12

def create_nl2agent_mcp_tool_configs() -> list[ToolConfig]:
    """Create fresh SDK configs for the NL2Agent business tools."""
    return [
        ToolConfig(
            class_name=DISCOVER_REQUIREMENTS_NAME, name=DISCOVER_REQUIREMENTS_NAME,
            description=DISCOVER_REQUIREMENTS_DESCRIPTION,
            inputs='{"requirements":"list[dict] | None","purpose":"str"}',
            output_type="object", params={}, source="mcp", usage="outer-apis",
        ),
        ToolConfig(
            class_name=VERIFY_REQUIREMENTS_NAME, name=VERIFY_REQUIREMENTS_NAME,
            description=VERIFY_REQUIREMENTS_DESCRIPTION,
            inputs='{"verification_batch_id":"str","checks":"list[dict]"}',
            output_type="object", params={}, source="mcp", usage="outer-apis",
        ),
        ToolConfig(
            class_name=SHOW_RESOURCE_CARD_NAME, name=SHOW_RESOURCE_CARD_NAME,
            description=SHOW_RESOURCE_CARD_DESCRIPTION,
            inputs='{"goal": {"type": "string", "enum": ["prompt", "complete"], "default": "prompt"}}',
            output_type="object", params={}, source="mcp", usage="outer-apis",
        ),
        ToolConfig(
            class_name=READ_CONFIGURATION_NAME, name=READ_CONFIGURATION_NAME,
            description=READ_CONFIGURATION_DESCRIPTION,
            inputs='{"section":"str"}', output_type="object", params={}, source="mcp", usage="outer-apis",
        ),
        ToolConfig(
            class_name=SAVE_CONFIGURATION_NAME, name=SAVE_CONFIGURATION_NAME,
            description=SAVE_CONFIGURATION_DESCRIPTION,
            inputs='{"section":"str","changes":"dict"}',
            output_type="object", params={}, source="mcp", usage="outer-apis",
        ),
        ToolConfig(
            class_name=READ_GENERATION_CONTEXT_NAME, name=READ_GENERATION_CONTEXT_NAME,
            description=READ_GENERATION_CONTEXT_DESCRIPTION,
            inputs="{}", output_type="object", params={}, source="mcp", usage="outer-apis",
        ),
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
            class_name=VALIDATE_AGENT_GENERATION_COMPLETE_NAME,
            name=VALIDATE_AGENT_GENERATION_COMPLETE_NAME,
            description=VALIDATE_AGENT_GENERATION_COMPLETE_DESCRIPTION,
            inputs="{}",
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
