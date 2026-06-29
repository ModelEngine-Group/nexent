-- Add labels column to ag_tool_info_t table for tool filtering/grouping
ALTER TABLE nexent.ag_tool_info_t 
ADD COLUMN IF NOT EXISTS labels JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN nexent.ag_tool_info_t.labels IS 'JSON array of label strings for filtering/grouping tools';

-- Seed built-in labels for well-known local tools
-- These labels serve as suggested defaults and can be modified by users.

-- Database tools
UPDATE nexent.ag_tool_info_t SET labels = '["database"]'::jsonb
WHERE name IN ('mysql_database', 'postgres_database', 'mssql_database');

-- File system tools
UPDATE nexent.ag_tool_info_t SET labels = '["file"]'::jsonb
WHERE name IN ('read_file', 'create_file', 'delete_file', 'create_directory', 'delete_directory', 'list_directory', 'move_item');

-- Search tools
UPDATE nexent.ag_tool_info_t SET labels = '["search"]'::jsonb
WHERE name IN ('tavily_search', 'exa_search', 'linkup_search', 'search_memory', 'knowledge_base_search');

-- Knowledge base tools
UPDATE nexent.ag_tool_info_t SET labels = '["knowledge-base"]'::jsonb
WHERE name IN ('dify_search', 'datamate_search', 'idata_search', 'haotian_search', 'aidp_search');

-- Multimodal / analyze tools
UPDATE nexent.ag_tool_info_t SET labels = '["multimodal"]'::jsonb
WHERE name IN ('analyze_image', 'analyze_audio', 'analyze_video', 'analyze_text_file');

-- Email tools
UPDATE nexent.ag_tool_info_t SET labels = '["email"]'::jsonb
WHERE name IN ('get_email', 'send_email');

-- Memory tools
UPDATE nexent.ag_tool_info_t SET labels = '["memory"]'::jsonb
WHERE name IN ('store_memory');

-- Terminal tools
UPDATE nexent.ag_tool_info_t SET labels = '["terminal"]'::jsonb
WHERE name IN ('terminal');
