-- Add labels column to ag_tool_info_t table for tool filtering/grouping
ALTER TABLE nexent.ag_tool_info_t 
ADD COLUMN IF NOT EXISTS labels JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN nexent.ag_tool_info_t.labels IS 'JSON array of label strings for filtering/grouping tools';

-- Seed built-in labels for well-known local tools.
-- These labels serve as suggested defaults and can be modified by users.
-- Keep in sync with: backend/consts/tool_labels.py

UPDATE nexent.ag_tool_info_t SET labels = CASE
    WHEN name IN ('mysql_database', 'postgres_database', 'mssql_database') THEN '["database"]'::jsonb
    WHEN name IN ('read_file', 'create_file', 'delete_file', 'create_directory', 'delete_directory', 'list_directory', 'move_item') THEN '["file"]'::jsonb
    WHEN name IN ('tavily_search', 'exa_search', 'linkup_search', 'search_memory', 'knowledge_base_search') THEN '["search"]'::jsonb
    WHEN name IN ('dify_search', 'datamate_search', 'idata_search', 'haotian_search', 'aidp_search') THEN '["knowledge-base"]'::jsonb
    WHEN name IN ('analyze_image', 'analyze_audio', 'analyze_video', 'analyze_text_file') THEN '["multimodal"]'::jsonb
    WHEN name IN ('get_email', 'send_email') THEN '["email"]'::jsonb
    WHEN name IN ('store_memory') THEN '["memory"]'::jsonb
    WHEN name IN ('terminal') THEN '["terminal"]'::jsonb
END
WHERE labels = '[]'::jsonb;
