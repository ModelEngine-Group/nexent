-- Add labels column to ag_tool_info_t table for tool filtering/grouping
ALTER TABLE nexent.ag_tool_info_t 
ADD COLUMN IF NOT EXISTS labels JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN nexent.ag_tool_info_t.labels IS 'JSON array of label strings for filtering/grouping tools';

-- Seed built-in labels for well-known local tools.
-- These labels serve as suggested defaults and can be modified by users.
-- Keep in sync with: backend/consts/tool_labels.py

WITH label_map AS (
    SELECT key AS tool_name, value AS label FROM jsonb_each_text('{
        "mysql_database": "database", "postgres_database": "database", "mssql_database": "database",
        "read_file": "file", "create_file": "file", "delete_file": "file",
        "create_directory": "file", "delete_directory": "file", "list_directory": "file",
        "move_item": "file",
        "tavily_search": "search", "exa_search": "search", "linkup_search": "search",
        "search_memory": "search", "knowledge_base_search": "search",
        "dify_search": "knowledge-base", "datamate_search": "knowledge-base",
        "idata_search": "knowledge-base", "haotian_search": "knowledge-base",
        "ragflow_search": "knowledge-base",
        "aidp_search": "knowledge-base",
        "analyze_image": "multimodal", "analyze_audio": "multimodal",
        "analyze_video": "multimodal", "analyze_text_file": "multimodal",
        "get_email": "email", "send_email": "email",
        "store_memory": "memory",
        "terminal": "terminal"
    }'::jsonb)
)
UPDATE nexent.ag_tool_info_t t
SET labels = to_jsonb(ARRAY[m.label])
FROM label_map m
WHERE t.name = m.tool_name AND t.labels = '[]'::jsonb;
