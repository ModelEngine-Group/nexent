"""Centralized definitions for tool parameter constraints.

These constants are shared by tool configuration validation
(``backend.services.tool_configuration_service``) and the error message
module (``backend.consts.error_message``).
"""

# Constraint keys persisted in the DB ``ag_tool_info_t.params`` column.
# ``_extract_field_constraints`` reads these same names from Pydantic ``Field``.
TOOL_PARAM_CONSTRAINT_KEYS = (
    "ge",
    "gt",
    "le",
    "lt",
    "min_length",
    "max_length",
    # "multiple_of",
)

# Per-constraint violation checks: (key, check_fn(value, constraint)).
# A check returns True when the value violates the constraint.
TOOL_PARAM_CONSTRAINT_RULES = (
    ("ge", lambda v, c: v < c),
    ("gt", lambda v, c: v <= c),
    ("le", lambda v, c: v > c),
    ("lt", lambda v, c: v >= c),
    ("min_length", lambda v, c: v < c),
    ("max_length", lambda v, c: v > c),
    # ("multiple_of", lambda v, c: c != 0 and v % c != 0),
)
