"""
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

Keep in sync with: deploy/sql/migrations/v2.3.0_0624_add_labels_to_ag_tool_info.sql
"""

# tool_name → [label, ...]
# Built per-category to avoid cross-file duplication with the matching SQL seed data.
_category_database = {
    "mysql_database": ["database"], "postgres_database": ["database"], "mssql_database": ["database"],
}
_category_file = {
    "read_file": ["file"], "create_file": ["file"], "delete_file": ["file"],
    "create_directory": ["file"], "delete_directory": ["file"],
    "list_directory": ["file"], "move_item": ["file"],
}
_category_search = {
    "tavily_search": ["search"], "exa_search": ["search"], "linkup_search": ["search"],
    "search_memory": ["search"], "knowledge_base_search": ["search"],
}
_category_kb = {
    "dify_search": ["knowledge-base"], "datamate_search": ["knowledge-base"],
    "idata_search": ["knowledge-base"], "haotian_search": ["knowledge-base"],
    "aidp_search": ["knowledge-base"],
}
_category_multimodal = {
    "analyze_image": ["multimodal"], "analyze_audio": ["multimodal"],
    "analyze_video": ["multimodal"], "analyze_text_file": ["multimodal"],
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
