-- Add user-selection metadata for agent tool configuration.
ALTER TABLE nexent.ag_tool_info_t
    ADD COLUMN IF NOT EXISTS is_user_selectable BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN nexent.ag_tool_info_t.is_user_selectable IS
    'Whether users can actively select the tool in agent configuration';

UPDATE nexent.ag_tool_info_t
SET is_user_selectable = FALSE
WHERE name = 'knowledge_base_search' OR name = 'aidp_search';
