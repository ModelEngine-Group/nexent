"""NL2AGENT tool: search web MCP marketplaces for individual install."""

import json
import re
from typing import Any, Dict, List, Optional

from smolagents.tools import Tool

from ._context import (
    Nl2AgentContext,
    _score_candidates,
    canonical_search_query,
    create_nl2agent_context,
    error_response,
    online_recommendation_batch_id,
)


def _field_type(spec: Dict[str, Any], name: str) -> str:
    format_name = str(spec.get("format") or "").lower()
    if format_name in {"number", "integer", "port"} or name.lower() == "port":
        return "number"
    if format_name in {"url", "uri"} or "url" in name.lower():
        return "url"
    if format_name == "json" or name.lower().endswith("json"):
        return "json"
    return "text"


def _normalize_fields(value: Any, category: str) -> List[Dict[str, Any]]:
    if isinstance(value, dict):
        entries = [
            (str(name), spec if isinstance(spec, dict) else {"value": spec})
            for name, spec in value.items()
        ]
    elif isinstance(value, list):
        entries = [
            (str(spec.get("name") or f"{category}_{index + 1}"), spec)
            for index, spec in enumerate(value)
            if isinstance(spec, dict)
        ]
    else:
        entries = []
    fields = []
    for index, (name, spec) in enumerate(entries):
        secret = bool(spec.get("isSecret")) or (
            category in {"header", "environment"}
            and bool(re.search(r"token|secret|password|api[_-]?key|authorization", name, re.I))
        )
        default = spec.get("value", spec.get("default"))
        fields.append(
            {
                "key": f"{category}:{name}:{index}",
                "name": name,
                "label": str(spec.get("label") or name),
                "description": str(spec.get("description") or ""),
                "type": _field_type(spec, name),
                "required": bool(spec.get("isRequired")) or (secret and default in (None, "")),
                "secret": secret,
                "default": None if secret or default is None else str(default),
                "placeholder": str(spec.get("placeholder") or spec.get("valueHint") or ""),
                "choices": [str(choice) for choice in spec.get("choices", [])]
                if isinstance(spec.get("choices"), list)
                else [],
                "category": category,
            }
        )
    return fields


def _normalize_arguments(value: Any, category: str) -> List[Dict[str, Any]]:
    fields = _normalize_fields(value, category)
    raw_items = value if isinstance(value, list) else []
    for field, raw_item in zip(fields, raw_items):
        field["argument_type"] = (
            "named" if str(raw_item.get("type") or "").lower() == "named" else "positional"
        )
        field["argument_name"] = raw_item.get("name")
        field["repeated"] = bool(raw_item.get("isRepeated"))
    return fields


def _container_environment_fields(config_json: Any) -> List[Dict[str, Any]]:
    if not isinstance(config_json, dict):
        return []
    servers = config_json.get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        return []
    server_config = next((value for value in servers.values() if isinstance(value, dict)), {})
    environment = server_config.get("env")
    if not isinstance(environment, dict):
        return []
    specs = []
    for name, value in environment.items():
        secret = bool(re.search(r"token|secret|password|api[_-]?key|authorization", str(name), re.I))
        specs.append({
            "name": str(name),
            "label": str(name),
            "description": f"Environment variable {name}.",
            "isRequired": secret or value in (None, ""),
            "isSecret": secret,
            "value": value,
        })
    return _normalize_fields(specs, "environment")


def normalize_mcp_candidate(source: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    """Return the safe card/install fields for a marketplace record."""
    registry_json = raw.get("registryJson") or raw.get("registry_json")
    registry_root = registry_json if isinstance(registry_json, dict) else raw
    server = (
        registry_root.get("server")
        if isinstance(registry_root.get("server"), dict)
        else registry_root
    )
    identity = (
        server.get("name") or server.get("id")
        if source == "registry"
        else raw.get("communityId") or raw.get("community_id") or raw.get("name")
    )
    remotes = server.get("remotes") or raw.get("remotes") or []
    install_options = []
    for index, remote in enumerate(remotes):
        if not isinstance(remote, dict) or not remote.get("url"):
            continue
        fields = _normalize_fields(remote.get("variables"), "variable")
        fields += _normalize_fields(remote.get("headers"), "header")
        install_options.append({
            "option_id": f"remote-{index}",
            "type": "remote",
            "label": f"{remote.get('type') or 'HTTP'} - {remote.get('url')}",
            "description": str(remote.get("description") or "Connect to the declared remote MCP endpoint."),
            "transport": remote.get("type") or "http",
            "server_url_template": remote.get("url"),
            "requires_configuration": bool(fields),
            "fields": fields,
            "supported": True,
            "status": "configuration_required" if fields else "ready",
        })
    for index, package in enumerate(server.get("packages") or []):
        if not isinstance(package, dict) or not package.get("identifier"):
            continue
        environment_fields = _normalize_fields(package.get("environmentVariables"), "environment")
        runtime_fields = _normalize_arguments(package.get("runtimeArguments"), "runtime_argument")
        package_fields = _normalize_arguments(package.get("packageArguments"), "package_argument")
        transport = package.get("transport") if isinstance(package.get("transport"), dict) else {}
        transport_fields = _normalize_fields(transport.get("variables"), "variable")
        transport_fields += _normalize_fields(transport.get("headers"), "header")
        transport_url = transport.get("url")
        is_remote_package = bool(transport_url and str(transport.get("type") or "").lower() != "stdio")
        fields = (
            transport_fields
            if is_remote_package
            else environment_fields + runtime_fields + package_fields
        )
        if not is_remote_package:
            fields.insert(0, {
                "key": "container:port:0", "name": "port", "label": "Container port",
                "description": "Local port exposed by the MCP container.", "type": "number",
                "required": True, "secret": False, "default": None, "placeholder": "", "choices": [],
                "category": "container",
            })
        install_options.append(
            {
                "option_id": f"package-{index}",
                "type": "remote" if is_remote_package else "container",
                "label": f"{package.get('identifier')} - {transport.get('type') or 'stdio'}",
                "description": str(package.get("description") or "Run the declared registry package."),
                "transport": transport.get("type") or package.get("runtimeHint") or package.get("registryType"),
                "requires_configuration": True,
                "server_url_template": transport_url,
                "package_identifier": package.get("identifier"),
                "registry_type": package.get("registryType"),
                "runtime_hint": package.get("runtimeHint"),
                "fields": fields,
                "supported": str(package.get("registryType") or package.get("runtimeHint") or "").lower()
                in {"npm", "npx", "pypi", "uvx"} or is_remote_package,
                "status": "configuration_required" if fields else "ready",
            }
        )
    community_server_url = raw.get("serverUrl") or raw.get("server_url")
    community_transport = str(raw.get("transportType") or raw.get("transport_type") or "").lower()
    config_json = raw.get("configJson") or raw.get("config_json")
    if source == "community" and community_transport != "container":
        remote_metadata = next(
            (remote for remote in remotes if isinstance(remote, dict)), {}
        )
        fields = _normalize_fields(remote_metadata.get("variables"), "variable")
        fields += _normalize_fields(remote_metadata.get("headers"), "header")
        if not community_server_url:
            fields.insert(0, {
                "key": "remote:server_url:0", "name": "server_url", "label": "Server URL",
                "description": "MCP server URL.", "type": "url", "required": True, "secret": False,
                "default": None, "placeholder": "https://...", "choices": [], "category": "remote",
            })
        install_options.insert(0, {
            "option_id": "community-remote", "type": "remote", "label": "Community remote server",
            "transport": community_transport or "http", "server_url_template": community_server_url,
            "description": "Connect to the community MCP endpoint.",
            "requires_configuration": bool(fields), "fields": fields, "supported": True,
            "status": "configuration_required" if fields else "ready",
        })
    if source == "community" and community_transport == "container":
        fields = [{
            "key": "container:port:0", "name": "port", "label": "Container port",
            "description": "Local port exposed by the MCP container.", "type": "number", "required": True,
            "secret": False, "default": None, "placeholder": "", "choices": [], "category": "container",
        }]
        fields += _container_environment_fields(config_json)
        if not isinstance(config_json, dict):
            fields.append({
                "key": "container:config_json:0", "name": "config_json", "label": "Container configuration",
                "description": "MCP container configuration JSON.", "type": "json", "required": True,
                "secret": False, "default": None, "placeholder": "", "choices": [], "category": "container",
            })
        install_options.insert(0, {
            "option_id": "community-container", "type": "container", "label": "Community container",
            "transport": "container", "requires_configuration": True, "fields": fields, "supported": True,
            "description": "Run the community MCP container configuration.",
            "status": "configuration_required",
        })
    if not install_options and isinstance(config_json, dict):
        install_options.append({
            "option_id": "container",
            "type": "container",
            "label": "Container configuration",
            "transport": "container",
            "requires_configuration": True,
            "fields": [{
                "key": "container:port:0", "name": "port", "label": "Container port",
                "description": "Local port exposed by the MCP container.", "type": "number",
                "required": True, "secret": False, "default": None, "placeholder": "",
                "choices": [], "category": "container",
            }],
            "supported": True,
            "status": "configuration_required",
        })
    if not install_options:
        install_options.append({
            "option_id": "unsupported", "type": "unsupported", "label": "Unsupported",
            "requires_configuration": False, "fields": [], "supported": False,
            "status": "unsupported",
            "unsupported_reason": "Marketplace metadata does not define a usable remote or container option.",
        })
    return {
        "recommendation_id": f"{source}:{identity}",
        "name": server.get("name") or raw.get("name") or "MCP server",
        "description": server.get("description") or raw.get("description") or "",
        "source": source,
        "transport": install_options[0].get("transport") if install_options else None,
        "install_options": install_options,
    }


_normalize_mcp_candidate = normalize_mcp_candidate


def get_search_web_mcps_tool(
    agent_id: Optional[int] = None,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    language: Optional[str] = None,
    draft_agent_id: Optional[int] = None,
    registry_results: Optional[List[Dict[str, Any]]] = None,
    community_results: Optional[List[Dict[str, Any]]] = None,
    requirements_confirmed: bool = False,
) -> Tool:
    context = create_nl2agent_context(
        agent_id=agent_id,
        user_id=user_id,
        tenant_id=tenant_id,
        language=language,
        draft_agent_id=draft_agent_id,
        registry_results=registry_results,
        community_results=community_results,
        requirements_confirmed=requirements_confirmed,
    )
    return NL2AgentSearchWebMcpsTool(context)


class NL2AgentSearchWebMcpsTool(Tool):
    """Search web MCP marketplaces (official registry + community) for servers matching the user's intent.

    This is an executable tool, not a frontend card type. Call it with the
    query, wait for its result, and render that returned JSON with the
    ``nl2agent-web-mcps`` result-card tag. Never emit a
    ``nl2agent-search-web-mcps`` block containing the query.

    Returns a frontend card JSON string with ``agent_id`` and normalized
    installation options. The card collects declared configuration, installs
    the selected option, discovers its tools, and lets the user bind or skip
    those tools explicitly.

    Args:
        query: 1-3 short keywords matching MCP server names or tags
            (e.g. "github", "email"). Never a full sentence.

    Returns:
        JSON string ``{"agent_id": 123, "items": [...]}`` containing web MCP
        cards.
    """

    name = "nl2agent_search_web_mcps"
    description = __doc__ or "Search web MCP marketplaces."
    inputs = {"query": {"type": "string", "description": "Concise MCP search keywords."}}
    output_type = "string"

    def __init__(self, context: Nl2AgentContext):
        super().__init__()
        self.context = context

    @staticmethod
    def _deduplicate_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Deduplicate marketplace entries, preserving registry-first precedence."""
        result: List[Dict[str, Any]] = []
        seen_ids = set()
        seen_names = set()
        for candidate in candidates:
            recommendation_id = candidate.get("recommendation_id")
            normalized_name = canonical_search_query(str(candidate.get("name") or ""))
            is_duplicate = (recommendation_id and recommendation_id in seen_ids) or (
                normalized_name and normalized_name in seen_names
            )
            if recommendation_id:
                seen_ids.add(recommendation_id)
            if normalized_name:
                seen_names.add(normalized_name)
            if is_duplicate:
                continue
            result.append(candidate)
        return result

    def _rank_candidates(self, candidates: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
        deduplicated = self._deduplicate_candidates(candidates)
        return _score_candidates(deduplicated, query, "name")[:5]

    def forward(self, query: str) -> str:
        ctx = self.context
        if ctx.tenant_id is None:
            return error_response("NL2AGENT session context not initialized.")
        if not ctx.requirements_confirmed:
            return error_response(
                "NL2AGENT requirements are not confirmed for this draft."
            )
        if ctx.registry_results is None and ctx.community_results is None:
            return error_response("MCP catalog not available in context")

        candidates: List[Dict[str, Any]] = []
        if ctx.registry_results:
            candidates += [normalize_mcp_candidate("registry", r) for r in ctx.registry_results]
        if ctx.community_results:
            candidates += [normalize_mcp_candidate("community", r) for r in ctx.community_results]

        scored = self._rank_candidates(candidates, query)
        # Keep the draft identity on every recommendation as well as the
        # wrapper. This makes both plural and per-item MCP card rendering safe.
        scored = [{**item, "agent_id": ctx.target_agent_id} for item in scored]
        batch_id = online_recommendation_batch_id(
            ctx.target_agent_id,
            "mcp",
            query,
            [str(item.get("recommendation_id") or "") for item in scored],
        )
        return json.dumps(
            {
                "agent_id": ctx.target_agent_id,
                "recommendation_batch_id": batch_id,
                "items": scored,
            },
            ensure_ascii=False,
        )
