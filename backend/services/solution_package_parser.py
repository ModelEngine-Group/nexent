"""Solution package parser.

Parses a WorkBuddy-style solution directory into the ``agent_info_json``
snapshot shape that the agent import flow expects.

Directory layout (per design doc / WorkBuddy expert-package convention):

    <solution_dir>/
    ├── plugin.json              # manifest: name, display, type, members, mcp_info, recipe, industry_rule
    ├── agents/<name>.md         # role: YAML frontmatter (tools/skill_names/model_names/managed_agents) + body=duty_prompt
    ├── skills/<skill>/…        # nested skill packages (SKILL.md + scripts/ + references/)
    ├── avatars/                # optional
    └── README.md

The parser resolves tool **names** (declared in agent frontmatter) to
``class_name`` via the SDK tool registry at seed time, so authoring stays
name-based and WorkBuddy-aligned. Output is a plain dict identical in shape
to the legacy single-JSON template, so ``recipe_service`` / ``import_agent_*``
need no changes.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

import yaml

from services.skill_package_builder import build_skill_zip_entries
from utils.tool_utils import get_local_tools_classes

logger = logging.getLogger(__name__)


def _snake_to_pascal_tool(name: str) -> str:
    """Convert a snake_case tool function name to PascalCase + 'Tool' suffix.

    e.g. ``read_skill_md`` -> ``ReadSkillMdTool``,
    ``run_skill_script`` -> ``RunSkillScriptTool``.
    This matches the class_name the SDK agent constructor dispatches on.
    """
    parts = name.split("_")
    return "".join(p.capitalize() for p in parts) + "Tool"


def _load_tool_name_to_class() -> Dict[str, str]:
    """Map tool ``name`` -> ``class_name`` from the SDK tool registry.

    Handles both class-based tools (e.g. ``TerminalTool``) and ``@tool``-decorated
    function tools (e.g. ``read_skill_md`` which becomes a ``SimpleTool`` instance).
    For class-based tools, ``class_name`` is the class's ``__name__``. For
    ``@tool`` instances, ``class_name`` is derived from the function name via
    ``_snake_to_pascal_tool`` so it matches the SDK's agent construction dispatch
    (e.g. ``read_skill_md`` -> ``ReadSkillMdTool``).
    """
    mapping: Dict[str, str] = {}
    for cls in get_local_tools_classes():
        tool_name = getattr(cls, "name", None)
        if tool_name:
            if isinstance(cls, type):
                mapping[tool_name] = cls.__name__
            else:
                mapping[tool_name] = _snake_to_pascal_tool(tool_name)
    return mapping


def _split_frontmatter(text: str) -> tuple:
    """Split a markdown file into (frontmatter_dict, body_str).

    Frontmatter is the YAML block delimited by ``---`` lines at the top.
    """
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    frontmatter_text = parts[1]
    body = parts[2].lstrip("\n")
    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML frontmatter: {exc}") from exc
    return frontmatter, body


def _build_tools_entry(tool_names: List[str], tool_map: Dict[str, str]) -> List[Dict[str, Any]]:
    """Turn a list of tool names into ToolConfig-shaped dicts."""
    tools: List[Dict[str, Any]] = []
    for name in tool_names or []:
        class_name = tool_map.get(name)
        if not class_name:
            logger.warning(
                "Tool '%s' not found in SDK registry; skipping (MCP tools come from mcp_info)",
                name,
            )
            continue
        tools.append({
            "class_name": class_name,
            "name": name,
            "description": "",
            "params": {},
            "source": "local",
        })
    return tools


def _build_agent_entry(
    agent_name: str,
    solution_dir: str,
    agent_id: int,
    tool_map: Dict[str, str],
) -> Dict[str, Any]:
    """Parse ``agents/<agent_name>.md`` into an ExportAndImportAgentInfo-shaped dict."""
    md_path = os.path.join(solution_dir, "agents", f"{agent_name}.md")
    if not os.path.isfile(md_path):
        raise FileNotFoundError(f"Agent definition not found: {md_path}")

    with open(md_path, "r", encoding="utf-8") as f:
        raw = f.read()

    frontmatter, body = _split_frontmatter(raw)
    if not frontmatter.get("name"):
        raise ValueError(f"Agent '{agent_name}' frontmatter missing 'name'")

    managed_names = frontmatter.get("managed_agents") or []
    # managed_agents names are resolved to ids by the caller (team case);
    # store the raw names here, caller overwrites with ids.
    return {
        "agent_id": agent_id,
        "name": frontmatter.get("name"),
        "display_name": frontmatter.get("display_name"),
        "description": frontmatter.get("description", ""),
        "business_description": frontmatter.get("business_description", ""),
        "author": frontmatter.get("author", "nexent-official"),
        "max_steps": int(frontmatter.get("max_steps", 20)),
        "is_main_agent": bool(frontmatter.get("is_main_agent", False)),
        "provide_run_summary": bool(frontmatter.get("provide_run_summary", False)),
        "enabled": bool(frontmatter.get("enabled", True)),
        "duty_prompt": body,
        "constraint_prompt": frontmatter.get("constraint_prompt"),
        "few_shots_prompt": frontmatter.get("few_shots_prompt"),
        "tools": _build_tools_entry(frontmatter.get("tools") or [], tool_map),
        "managed_agents": managed_names,  # name list; caller resolves to ids
        "model_names": frontmatter.get("model_names") or [],
        "skill_names": frontmatter.get("skill_names") or [],
    }


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_mcp_info(solution_dir: str, manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Load MCP connectors. Prefer split files under mcp/*.json; fall back to
    an embedded ``mcp_info`` in the manifest."""
    mcp_dir = os.path.join(solution_dir, "mcp")
    if os.path.isdir(mcp_dir):
        connectors: List[Dict[str, Any]] = []
        for name in sorted(os.listdir(mcp_dir)):
            if not name.endswith(".json"):
                continue
            try:
                data = _load_json(os.path.join(mcp_dir, name))
            except (OSError, json.JSONDecodeError) as exc:
                logger.error("Failed to load MCP config %s: %s", name, exc)
                continue
            if isinstance(data, dict):
                connectors.append(data)
        return connectors
    embedded = manifest.get("mcp_info")
    return embedded if isinstance(embedded, list) else []


def _load_recipe(solution_dir: str, manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Load recipe. Prefer recipe/variables.json; fall back to manifest."""
    recipe_path = os.path.join(solution_dir, "recipe", "variables.json")
    if os.path.isfile(recipe_path):
        try:
            data = _load_json(recipe_path)
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to load recipe: %s", exc)
    embedded = manifest.get("recipe")
    return embedded if isinstance(embedded, dict) else {
        "variables": [], "layers": [], "post_actions": []
    }


def _load_industry_rule(solution_dir: str, manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Load industry rule. Prefer industry_rule/rule.json; fall back to manifest."""
    rule_path = os.path.join(solution_dir, "industry_rule", "rule.json")
    if os.path.isfile(rule_path):
        try:
            data = _load_json(rule_path)
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to load industry_rule: %s", exc)
    embedded = manifest.get("industry_rule")
    return embedded if isinstance(embedded, dict) else {}


def parse_solution_package(solution_dir: str) -> Dict[str, Any]:
    """Parse a solution directory into the ``agent_info_json`` snapshot dict.

    Supports the split layout (``solution.json`` + ``mcp/*.json`` +
    ``recipe/variables.json`` + ``industry_rule/rule.json``) with a fallback to
    the legacy single-manifest layout where these sections are embedded in
    the manifest (``plugin.json``/``solution.json``).

    Returns ``{agent_id, agent_info, mcp_info, skills, recipe, industry_rule}``.
    """
    # Accept either solution.json (preferred) or plugin.json (legacy).
    solution_path = os.path.join(solution_dir, "solution.json")
    if not os.path.isfile(solution_path):
        solution_path = os.path.join(solution_dir, "plugin.json")
    if not os.path.isfile(solution_path):
        raise FileNotFoundError(
            f"solution.json (or plugin.json) not found in solution dir: {solution_dir}"
        )

    manifest = _load_json(solution_path)

    members: List[str] = manifest.get("members") or []
    if not members:
        raise ValueError(f"Solution '{manifest.get('name')}' has no members")

    lead_name = manifest.get("lead") or members[0]

    tool_map = _load_tool_name_to_class()

    # Assign ids by member order, optionally offset by manifest's start_agent_id;
    # collect the skill names across members.
    start_id = int(manifest.get("start_agent_id") or 1)
    name_to_id: Dict[str, int] = {
        name: start_id + idx for idx, name in enumerate(members)
    }
    agent_info: Dict[str, Dict[str, Any]] = {}
    all_skill_names: List[str] = []
    for name in members:
        entry = _build_agent_entry(name, solution_dir, name_to_id[name], tool_map)
        agent_info[str(name_to_id[name])] = entry
        for sn in entry.get("skill_names") or []:
            if sn not in all_skill_names:
                all_skill_names.append(sn)

    # Team: resolve the lead's managed_agents names -> member ids.
    if manifest.get("type") == "team":
        lead_entry = agent_info.get(str(name_to_id[lead_name]))
        if lead_entry:
            resolved = [
                name_to_id[n] for n in (lead_entry.get("managed_agents") or []) if n in name_to_id
            ]
            lead_entry["managed_agents"] = resolved
    else:
        # single: no managed_agents
        for entry in agent_info.values():
            entry["managed_agents"] = []

    # Skills: package the nested skills/ dir.
    skills_dir = os.path.join(solution_dir, "skills")
    skill_names = all_skill_names
    if not skill_names and os.path.isdir(skills_dir):
        skill_names = [
            d for d in os.listdir(skills_dir)
            if os.path.isdir(os.path.join(skills_dir, d))
        ]
    skills = build_skill_zip_entries(skill_names, skills_dir=skills_dir) if skill_names else []

    return {
        "agent_id": name_to_id[lead_name],
        "agent_info": agent_info,
        "mcp_info": _load_mcp_info(solution_dir, manifest),
        "skills": skills,
        "recipe": _load_recipe(solution_dir, manifest),
        "industry_rule": _load_industry_rule(solution_dir, manifest),
    }
