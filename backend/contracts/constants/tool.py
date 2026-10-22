# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Domain constants for MCP marketplace listing statuses.

Built-in labels for well-known local tools.

These are applied when a tool is first created for a tenant via
update_tool_table_from_scan_tool_list() — which runs during the first
API call for a new tenant (init_tool_list_for_tenant).

Why not in SQL?
  - init.sql runs before the backend starts, so the ag_tool_info_t table
    is empty and UPDATE statements would hit zero rows.
  - Migration SQL (docker/sql/) covers the upgrade path from v2.2.x,
    but cannot cover fresh v2.3.0+ installs where tools don't exist yet.
  - This module is the only hook that fires at the exact moment tools are
    inserted — the earliest lifecycle point where the data exists.

Keep in sync with: deploy/sql/migrations/v2.3_merged_migrations.sql

Centralized definitions for tool parameter constraints.

These constants are shared by tool configuration validation
(``management.services.tool.configuration``) and the error message
module (``backend.contracts.errors.messages``).
"""

# Listing status: not_shared (未共享), pending_review (待审核),
# rejected (审核驳回), shared (已共享)
STATUS_NOT_SHARED = "not_shared"
STATUS_PENDING_REVIEW = "pending_review"
STATUS_REJECTED = "rejected"
STATUS_SHARED = "shared"

VALID_MARKET_STATUSES = frozenset(
    {
        STATUS_NOT_SHARED,
        STATUS_PENDING_REVIEW,
        STATUS_REJECTED,
        STATUS_SHARED,
    }
)


# tool_name → [label, ...]
# Built per-category to avoid cross-file duplication with the matching SQL seed data.
_category_database = {
    "mysql_database": ["database"],
    "postgres_database": ["database"],
    "mssql_database": ["database"],
}
_category_file = {
    "read_file": ["file"],
    "create_file": ["file"],
    "delete_file": ["file"],
    "download_from_s3": ["file"],
    "upload_to_s3": ["file"],
    "create_directory": ["file"],
    "delete_directory": ["file"],
    "list_directory": ["file"],
    "move_item": ["file"],
}
_category_search = {
    "deepseek_search": ["search"],
    "tavily_search": ["search"],
    "exa_search": ["search"],
    "linkup_search": ["search"],
    "search_memory": ["search"],
    "knowledge_base_search": ["search"],
}
_category_kb = {
    "dify_search": ["knowledge-base"],
    "datamate_search": ["knowledge-base"],
    "idata_search": ["knowledge-base"],
    "haotian_search": ["knowledge-base"],
    "ragflow_search": ["knowledge-base"],
    "aidp_search": ["knowledge-base"],
}
_category_multimodal = {
    "analyze_image": ["multimodal"],
    "analyze_audio": ["multimodal"],
    "analyze_video": ["multimodal"],
    "analyze_text_file": ["multimodal"],
}
_category_email = {"get_email": ["email"], "send_email": ["email"]}
_category_memory = {"store_memory": ["memory"]}
_category_terminal = {"terminal": ["terminal"]}

BUILTIN_LABEL_MAP: dict[str, list[str]] = {}
BUILTIN_LABEL_MAP.update(_category_database)
BUILTIN_LABEL_MAP.update(_category_file)
BUILTIN_LABEL_MAP.update(_category_search)
BUILTIN_LABEL_MAP.update(_category_kb)
BUILTIN_LABEL_MAP.update(_category_multimodal)
BUILTIN_LABEL_MAP.update(_category_email)
BUILTIN_LABEL_MAP.update(_category_memory)
BUILTIN_LABEL_MAP.update(_category_terminal)

PARALLEL_EXECUTOR_TOOL_NAME = "parallel_executor"
SYSTEM_MANAGED_TOOL_NAMES = frozenset(
    {
        "store_memory",
        "search_memory",
        "download_from_s3",
        "upload_to_s3",
        PARALLEL_EXECUTOR_TOOL_NAME,
    }
)
"""Centralized definitions for tool parameter constraints.

These constants are shared by tool configuration validation
(``management.services.tool.configuration``) and the error message
module (``contracts.errors.messages``).
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
    # ``multiple_of`` is disabled until a built-in tool exposes a Pydantic
    # ``multiple_of`` constraint; add it back here (and the matching rule in
    # ``TOOL_PARAM_CONSTRAINT_RULES``) when divisibility validation is required.
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
    # Enable ``multiple_of`` together with its key in
    # ``TOOL_PARAM_CONSTRAINT_KEYS`` when a tool param needs divisibility
    # validation. The lambda guards against ``c == 0`` before the modulo to
    # avoid ``ZeroDivisionError``.
    # ("multiple_of", lambda v, c: c != 0 and v % c != 0),
)

# Tool Type Mapping (for display normalization)
TOOL_TYPE_MAPPING = {
    "mcp": "MCP",
    "langchain": "LangChain",
    "local": "Local",
}
