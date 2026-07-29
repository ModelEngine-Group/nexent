"""Recipe service — variable extraction, placeholder substitution, and template instantiation.

Supports the template detail page by:
1. Extracting a RecipeDefinition (variables + layers) from a frozen agent snapshot.
2. Applying user-provided variable values to replace ``<<TO_CONFIG:xxx>>`` placeholders.
3. Prechecking model/KB/MCP dependencies against the target tenant.
4. Instantiating a new agent from a template via the existing import flow.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from consts.model import (
    AgentRepositorySnapshot,
    RecipeVariable,
    RecipeVariableOption,
)
from database.market_db import get_market_agent_detail
from database.agent_db import query_all_agent_info_by_tenant_id
from services.repository_import_precheck import build_repository_import_precheck

logger = logging.getLogger("recipe_service")

# Placeholder pattern: <<TO_CONFIG:variable_key>>
_PLACEHOLDER_PATTERN = re.compile(r"<<TO_CONFIG:(\w+)>>")

# Default recipe variables that are always available when no explicit recipe is defined
_DEFAULT_VARIABLES = [
    RecipeVariable(
        key="model_name",
        label="Model Name",
        description="The LLM model to use for this agent",
        type="string",
        required=True,
        default="gpt-4o",
    ),
    RecipeVariable(
        key="output_language",
        label="Output Language",
        description="The language for agent responses",
        type="string",
        required=True,
        default="中文",
    ),
    RecipeVariable(
        key="search_depth",
        label="Search Depth",
        description="Depth of web search: quick or comprehensive",
        type="select",
        required=True,
        default="comprehensive",
        options=[
            RecipeVariableOption(label="Quick", value="quick"),
            RecipeVariableOption(label="Comprehensive", value="comprehensive"),
        ],
    ),
]


def extract_recipe_from_snapshot(
    agent_info_json: Any,
    root_agent: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Extract a RecipeDefinition from a frozen agent snapshot.

    If the snapshot contains an explicit ``recipe`` key, it is returned directly.
    Otherwise, a default recipe is built from the snapshot's agent/skill/mcp layers
    and a set of common variables (model_name, output_language, search_depth).

    Returns a plain dict (not a Pydantic model) for JSON serialization.
    """
    if not isinstance(agent_info_json, dict):
        return _build_default_recipe(root_agent or {})

    # Check if snapshot has an explicit recipe field
    explicit_recipe = agent_info_json.get("recipe")
    if isinstance(explicit_recipe, dict):
        return explicit_recipe

    # Build default recipe from snapshot layers
    return _build_default_recipe(root_agent or {}, agent_info_json)


def _build_default_recipe(
    root_agent: Dict[str, Any],
    agent_info_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a default recipe from the snapshot's agent/skill/mcp layers."""
    layers: List[Dict[str, Any]] = []

    # Agent layer
    agent_name = root_agent.get("name") or root_agent.get("display_name") or "Agent"
    layers.append({
        "layer_type": "agent",
        "entity_type": "agent",
        "entity_name": agent_name,
        "source": "official",
    })

    # Skill layers
    skill_names = root_agent.get("skill_names") or []
    for skill_name in skill_names:
        if skill_name:
            layers.append({
                "layer_type": "skill",
                "entity_type": "skill",
                "entity_name": str(skill_name),
                "source": "official",
            })

    # MCP layers
    if agent_info_json and isinstance(agent_info_json, dict):
        mcp_info = agent_info_json.get("mcp_info") or []
        for mcp in mcp_info:
            if isinstance(mcp, dict):
                server_name = mcp.get("mcp_server_name")
                if server_name:
                    layers.append({
                        "layer_type": "mcp",
                        "entity_type": "mcp",
                        "entity_name": str(server_name),
                        "source": "official",
                    })

    return {
        "variables": [v.model_dump() for v in _DEFAULT_VARIABLES],
        "layers": layers,
        "post_actions": [],
    }


def apply_recipe_variables(
    snapshot: Any,
    variable_values: Dict[str, Any],
) -> Any:
    """Recursively replace all ``<<TO_CONFIG:xxx>>`` placeholders in a snapshot.

    Traverses dicts, lists, and strings. Returns a new object with substitutions applied.
    """
    if isinstance(snapshot, dict):
        return {
            key: apply_recipe_variables(value, variable_values)
            for key, value in snapshot.items()
        }
    if isinstance(snapshot, list):
        return [apply_recipe_variables(item, variable_values) for item in snapshot]
    if isinstance(snapshot, str):
        return _replace_placeholders_in_string(snapshot, variable_values)
    return snapshot


def _replace_placeholders_in_string(text: str, variable_values: Dict[str, Any]) -> str:
    """Replace all ``<<TO_CONFIG:key>>`` placeholders in a string with variable values."""
    def replacer(match: re.Match) -> str:
        key = match.group(1)
        value = variable_values.get(key)
        if value is None:
            # Leave placeholder if no value provided — the import flow can handle it
            return match.group(0)
        return str(value)

    return _PLACEHOLDER_PATTERN.sub(replacer, text)


def _inject_industry_rule(snapshot_json: Dict[str, Any]) -> None:
    """Append industry-rule text into every agent's ``duty_prompt``.

    Reads the optional top-level ``industry_rule`` key of the snapshot dict
    (carried inside ``agent_info_json``, not a field of ``AgentRepositorySnapshot``
    itself) and appends a ``## 行业规则`` + ``## 场景路由规则`` section to each
    agent entry's ``duty_prompt``.

    Fault-tolerant by design (DFX §10.1): if ``industry_rule`` is absent or an
    agent has no ``duty_prompt``, the injection is silently skipped so the
    agent is still created without industry rules.
    """
    industry_rule = snapshot_json.get("industry_rule")
    if not isinstance(industry_rule, dict):
        return

    sections: List[str] = []

    guardrails = industry_rule.get("guardrails") or []
    if isinstance(guardrails, list) and guardrails:
        lines = []
        for g in guardrails:
            if not isinstance(g, dict):
                continue
            rule_text = g.get("rule")
            if rule_text:
                lines.append(f"- {rule_text}")
        if lines:
            sections.append("## 行业规则\n" + "\n".join(lines))

    scene_mappings = industry_rule.get("scene_mappings") or []
    if isinstance(scene_mappings, list) and scene_mappings:
        lines = []
        for s in scene_mappings:
            if not isinstance(s, dict):
                continue
            scene = s.get("scene")
            behavior = s.get("behavior")
            if scene and behavior:
                lines.append(f"  场景 {scene}: {behavior}")
        if lines:
            sections.append("## 场景路由规则\n" + "\n".join(lines))

    fallback = industry_rule.get("fallback_strategy")
    if fallback:
        sections.append(f"## 兜底策略\n{fallback}")

    if not sections:
        return

    injected_text = "\n\n".join(sections)

    agent_info_map = snapshot_json.get("agent_info")
    if not isinstance(agent_info_map, dict):
        return

    for agent_entry in agent_info_map.values():
        if not isinstance(agent_entry, dict):
            continue
        duty = agent_entry.get("duty_prompt")
        if not duty:
            continue
        # Avoid double-injection if the prompt already carries the section
        if "## 行业规则" in duty:
            continue
        agent_entry["duty_prompt"] = f"{duty}\n\n{injected_text}".rstrip()


def precheck_dependencies(
    snapshot: Any,
    tenant_id: str,
    display_name: str = "",
    agent_repository_id: int = 0,
) -> Dict[str, Any]:
    """Check model/KB/MCP/skill availability for a snapshot in the target tenant.

    Returns ``{missing: [...], has_abnormal: bool, details: {...}}``.
    """
    try:
        # Use the existing repository import precheck
        precheck_response = build_repository_import_precheck(
            agent_repository_id=agent_repository_id or 0,
            display_name=display_name or "Template",
            snapshot=snapshot,
            tenant_id=tenant_id,
        )

        missing_items = [
            {
                "type": item.type,
                "key": item.key,
                "name": item.name,
                "reason_code": item.reason_code,
            }
            for item in precheck_response.items
            if not item.available
        ]

        return {
            "missing": missing_items,
            "has_abnormal": precheck_response.has_abnormal,
            "total_count": precheck_response.total_count,
            "available_count": precheck_response.available_count,
        }
    except Exception as exc:
        logger.error("Failed to precheck dependencies: %s", str(exc))
        return {
            "missing": [],
            "has_abnormal": False,
            "total_count": 0,
            "available_count": 0,
            "error": str(exc),
        }


async def instantiate_from_template_impl(
    template_id: int,
    variable_values: Dict[str, Any],
    user_id: str,
    tenant_id: str,
    authorization: str,
    force_import: bool = False,
) -> Dict[str, Any]:
    """Instantiate a new agent from a market template.

    Steps:
    1. Load the template (frozen snapshot) from the market.
    2. Apply recipe variable substitutions.
    3. Precheck dependencies (optional — warn but proceed if force_import).
    4. Reuse ``import_agent_with_skills_impl`` or ``import_agent_impl`` to import.
    5. Return ``{agent_id}`` for the newly created agent.
    """
    from services.agent_service import (
        import_agent_impl,
        import_agent_with_skills_impl,
    )

    # Step 1: Load template snapshot
    record = get_market_agent_detail(template_id)
    if not record:
        raise ValueError("Template not found")

    agent_info_json = record.get("agent_info_json")
    if not isinstance(agent_info_json, dict):
        raise ValueError("Template snapshot is invalid")

    # Step 2: Apply recipe variables
    processed_json = apply_recipe_variables(agent_info_json, variable_values)

    # Step 6: Inject industry rule into each agent's duty_prompt.
    # Done on the raw dict BEFORE model_validate so the injected text is
    # persisted into the imported agent. Fault-tolerant: missing industry_rule
    # or duty_prompt is silently skipped (DFX §10.1).
    _inject_industry_rule(processed_json)

    # Step 3: Validate with Pydantic snapshot model
    snapshot = AgentRepositorySnapshot.model_validate(processed_json)

    # Step 4: Precheck dependencies (warn but proceed if force_import)
    precheck = precheck_dependencies(
        snapshot,
        tenant_id,
        display_name=record.get("display_name") or "Template",
        agent_repository_id=template_id,
    )
    if precheck.get("has_abnormal") and not force_import:
        logger.warning(
            "Template %s has missing dependencies: %d items",
            template_id,
            len(precheck.get("missing", [])),
        )
        # Return precheck info without proceeding unless force_import is True
        return {
            "agent_id": None,
            "precheck": precheck,
            "message": "Dependencies missing. Set force_import=true to proceed anyway.",
        }

    # Step 5: Import via existing flow
    if snapshot.skills:
        agent_id_mapping = await import_agent_with_skills_impl(
            snapshot,
            snapshot.skills,
            authorization,
            force_import=force_import,
        )
    else:
        agent_id_mapping = await import_agent_impl(
            snapshot,
            authorization,
            force_import=force_import,
        )

    # Resolve the new root agent ID
    original_agent_id = snapshot.agent_id
    new_agent_id = agent_id_mapping.get(original_agent_id) if agent_id_mapping else None

    if new_agent_id is None and isinstance(agent_id_mapping, dict):
        # Fallback: take first value
        for key, value in agent_id_mapping.items():
            new_agent_id = value
            break

    return {
        "agent_id": new_agent_id,
        "precheck": precheck,
    }


def _extract_root_agent_name(agent_info_json: Any) -> Optional[str]:
    """Resolve the root agent's ``name`` from a frozen snapshot."""
    if not isinstance(agent_info_json, dict):
        return None
    root_agent_id = agent_info_json.get("agent_id")
    agent_info_map = agent_info_json.get("agent_info")
    if not isinstance(agent_info_map, dict):
        return None
    entry = agent_info_map.get(str(root_agent_id)) if root_agent_id is not None else None
    entry = entry or (agent_info_map.get(root_agent_id) if root_agent_id is not None else None)
    if isinstance(entry, dict):
        return entry.get("name")
    return None


def _resolve_model_variable_defaults(
    variables: List[Any],
    variable_values: Dict[str, Any],
    tenant_id: str,
) -> Dict[str, Any]:
    """Fill empty ``model``-typed recipe variables with a real tenant LLM.

    For variables declared ``type == "model"`` whose value is missing/empty or
    not an actual tenant LLM display_name, substitute the first available LLM
    display_name. The import flow resolves display_name -> model_id, so the
    zero-config launch works without hardcoding a model the tenant may lack.
    """
    model_vars = [v for v in variables if isinstance(v, dict) and v.get("type") == "model"]
    if not model_vars:
        return variable_values

    try:
        from database.model_management_db import get_model_records
        records = get_model_records({"model_type": "llm"}, tenant_id)
    except Exception as exc:
        logger.warning("Failed to load LLM records for tenant %s: %s", tenant_id, exc)
        return variable_values

    # Prefer connected/available LLMs; fall back to any LLM record.
    available = [r for r in records if (r.get("connect_status") or "").lower() == "available"]
    candidates = available or records
    if not candidates:
        return variable_values
    first_display = candidates[0].get("display_name")
    if not first_display:
        return variable_values

    resolved = dict(variable_values)
    valid_names = {r.get("display_name") for r in records if r.get("display_name")}
    for var in model_vars:
        key = var.get("key")
        current = resolved.get(key)
        if not current or current not in valid_names:
            resolved[key] = first_display
    return resolved


async def launch_solution_impl(
    template_id: int,
    user_id: str,
    tenant_id: str,
    authorization: str,
) -> Dict[str, Any]:
    """Get-or-create a runnable Agent from a Solution, then return its id.

    WorkBuddy-style entry point: clicking a solution card should drop the
    user straight into a conversation with an agent that already has the
    solution's tools/skills/mcp/industry-rule baked in — no Recipe form step.

    Behaviour:
    1. Load the solution template snapshot.
    2. If the tenant already has an enabled agent with the solution's root
       agent name, reuse it (idempotent — no duplicate agents per click).
    3. Otherwise instantiate from the template using each Recipe variable's
       default value (zero-config), force_import=True so a missing optional
       MCP (e.g. feishu) does not block creation.
    """
    record = get_market_agent_detail(template_id)
    if not record:
        raise ValueError("Template not found")

    agent_info_json = record.get("agent_info_json")
    if not isinstance(agent_info_json, dict):
        raise ValueError("Template snapshot is invalid")

    solution_name = _extract_root_agent_name(agent_info_json)

    # Step 2: reuse an existing enabled agent with the same name, if any.
    if solution_name:
        existing = query_all_agent_info_by_tenant_id(tenant_id=tenant_id)
        for agent in existing:
            if (
                agent.get("name") == solution_name
                and agent.get("enabled")
                and agent.get("delete_flag", "N") != "Y"
            ):
                return {"agent_id": agent.get("agent_id"), "reused": True}

    # Step 3: build default variable values from the template's recipe.
    root_agent = (
        agent_info_json.get("agent_info", {}).get(
            str(agent_info_json.get("agent_id"))
        )
        if isinstance(agent_info_json.get("agent_info"), dict)
        else {}
    ) or {}
    recipe = extract_recipe_from_snapshot(agent_info_json, root_agent)
    variable_values: Dict[str, Any] = {}
    for var in recipe.get("variables", []) or []:
        default = var.get("default")
        if default is not None:
            variable_values[var.get("key")] = default

    # Resolve "model"-typed variables whose value is empty/unresolved to the
    # tenant's first available LLM display_name (the import flow resolves
    # display_name -> model_id). This keeps zero-config launch working without
    # hardcoding a model name that may not exist in the tenant.
    variable_values = _resolve_model_variable_defaults(
        recipe.get("variables") or [], variable_values, tenant_id
    )

    result = await instantiate_from_template_impl(
        template_id=template_id,
        variable_values=variable_values,
        user_id=user_id,
        tenant_id=tenant_id,
        authorization=authorization,
        force_import=True,
    )
    return {
        "agent_id": result.get("agent_id"),
        "reused": False,
        "precheck": result.get("precheck"),
    }
