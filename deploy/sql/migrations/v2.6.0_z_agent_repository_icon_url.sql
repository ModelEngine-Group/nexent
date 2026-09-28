-- Repository listings now store an optional uploaded image URL. Legacy emoji
-- values fall back to the deterministic agent icon after this migration.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'nexent' AND table_name = 'ag_agent_repository_t'
      AND column_name = 'icon'
  ) AND NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'nexent' AND table_name = 'ag_agent_repository_t'
      AND column_name = 'icon_url'
  ) THEN
    ALTER TABLE nexent.ag_agent_repository_t RENAME COLUMN icon TO icon_url;
    UPDATE nexent.ag_agent_repository_t SET icon_url = NULL;
  END IF;
END $$;

ALTER TABLE nexent.ag_agent_repository_t
  ALTER COLUMN icon_url TYPE VARCHAR(1024);

COMMENT ON COLUMN nexent.ag_agent_repository_t.icon_url IS
  'Repository icon URL; NULL uses the agent ID based default icon';
