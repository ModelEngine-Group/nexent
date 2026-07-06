"""NL2AGENT builtin tools.

These tools are run by the NL2AGENT default agent. They are thin wrappers around
`backend.services.nl2agent_service` and are dispatched by `NexentAgent.create_builtin_tool`
when the tool's `class_name` matches one of the NL2AGENT_* class names.

Each tool stores its session context (draft agent_id, user_id, tenant_id,
model_id, language) in module-level globals via a `get_*_tool()` initializer,
mirroring the pattern in `read_skill_config_tool.py`.
"""
