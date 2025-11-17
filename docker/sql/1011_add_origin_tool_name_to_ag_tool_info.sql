-- Add origin_name column to ag_tool_info_t table
-- This field stores the original tool name before any transformations

ALTER TABLE nexent.ag_tool_info_t 
ADD COLUMN IF NOT EXISTS origin_name VARCHAR(100);

-- Add comment to document the purpose of this field
COMMENT ON COLUMN nexent.ag_tool_info_t.origin_name IS 'Original tool name before any transformations or mappings';
