-- Add category column to ag_tool_info_t table
-- This field stores the tool category information (search, file, email, terminal)

ALTER TABLE nexent.ag_tool_info_t 
ADD COLUMN IF NOT EXISTS category VARCHAR(100);

-- Add comment to document the purpose of this field
COMMENT ON COLUMN nexent.ag_tool_info_t.category IS 'Tool category information';
