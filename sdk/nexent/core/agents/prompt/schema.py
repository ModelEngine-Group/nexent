"""Immutable schema constants for Agent prompt templates."""

from types import MappingProxyType


FIELD_VARIABLES = MappingProxyType({
    "system_sections": MappingProxyType({
        "duty": frozenset({"duty"}),
        "constraint": frozenset({"constraint"}),
        "footer": frozenset({"few_shots"}),
        "restricted_python_execution": frozenset({"authorized_imports"}),
    }),
    "manager_agent": MappingProxyType({
        "task": frozenset({"task", "name"}),
        "report": frozenset({"final_answer", "name"}),
    }),
    "managed_agent": MappingProxyType({
        "task": frozenset({"task", "name"}),
        "report": frozenset({"final_answer", "name"}),
    }),
    "final_answer": MappingProxyType({
        "post_messages": frozenset({"task"}),
    }),
})

REQUIRED_SYSTEM_SECTIONS = frozenset({
    "outline_identity",
    "outline_execution",
    "outline_constraints",
    "header",
    "duty",
    "execution_flow",
    "final_answer_guidance",
    "constraint",
    "code_norms",
    "restricted_python_execution",
    "footer",
    "available_resources_header",
    "knowledge_guidance_scoped",
    "knowledge_guidance_unscoped",
    "planning_guidance",
    "self_verification_guidance",
    "sandbox_workspace_guidance",
    "skill_usage",
})

FINAL_ANSWER_FIELDS = frozenset({"pre_messages", "post_messages"})
SUPPORTED_LANGUAGES = frozenset({"zh", "en"})
SUPPORTED_ROLES = frozenset({"manager", "managed"})
