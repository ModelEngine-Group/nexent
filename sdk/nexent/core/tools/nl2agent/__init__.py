"""NL2AGENT builtin tools.

These tools are run by the NL2AGENT default agent. They are pure SDK with no
backend coupling — keyword scoring replaces LLM-based ranking, and catalogs are
injected by the backend at session start via ToolConfig.metadata.

Dispatched by `NexentAgent.create_builtin_tool` when the tool's `class_name`
matches one of the NL2AGENT_* class names.

Each tool instance owns its session context (draft agent_id, user_id, tenant_id,
language, and catalogs), so concurrent agent runs cannot overwrite each other.
"""
