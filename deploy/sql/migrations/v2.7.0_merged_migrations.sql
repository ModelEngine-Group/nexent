-- Nexent merged SQL migrations: v2.7.0
-- Previous release tag: v2.6.1
-- Source bodies are embedded byte-for-byte in deployment order.
-- Do not reorder or rewrite sections without equivalence validation.

-- Source migration: v2.6.0_z_agent_repository_icon_url.sql
-- Source SHA-256: 5ffc0a0389f5ed3ab0538139f0870f2d35fb10fdcbb91a62555774e886842d89

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


-- Source migration: v2.6.1_001_remove_human_interaction.sql
-- Source SHA-256: 08f51328a6de8a7537265d5087be872b33ea8f1282fc892a0f5b1f4baa364479

-- Deploy only after all processes using the retired interaction engine have stopped.
-- Ordinary conversation messages and units are intentionally preserved.
DROP TABLE IF EXISTS nexent.human_event_t;
DROP TABLE IF EXISTS nexent.human_execution_t;
DROP TABLE IF EXISTS nexent.human_request_t;
DROP TABLE IF EXISTS nexent.human_run_t;
-- This function is used exclusively by the four tables removed above.
DROP FUNCTION IF EXISTS nexent.human_interaction_audit_timestamp();


-- Source migration: v2.6.1_002_remove_dev_models_menu.sql
-- Source SHA-256: e1c57d58d6754351c05820017e0bc24774c8d2728151ca517a186631338e35af

-- Remove the model management page from the DEV role menu.
-- Developers must not see or manage models; they only consume
-- administrator-configured models. RESOURCE MODEL READ is kept so
-- model pickers in agent editing keep working.
-- Pattern follows v2.3 migration that removed ASSET_OWNER /owner-manage.
DELETE FROM nexent.role_permission_t
WHERE user_role = 'DEV'
  AND permission_category = 'VISIBILITY'
  AND permission_type = 'LEFT_NAV_MENU'
  AND permission_subtype = '/models';


-- Source migration: v2.6.2_001_agent_workbench.sql
-- Source SHA-256: 5b210092620c8088caf1f39514a54c2c35d74bd578d26cd24d95ce224af241e7

-- Add protected platform Agent identity for the intelligent workbench.
ALTER TABLE nexent.ag_tenant_agent_t
    ADD COLUMN IF NOT EXISTS system_key VARCHAR(100),
    ADD COLUMN IF NOT EXISTS agent_origin VARCHAR(20) NOT NULL DEFAULT 'USER',
    ADD COLUMN IF NOT EXISTS system_revision VARCHAR(100);

COMMENT ON COLUMN nexent.ag_tenant_agent_t.system_key IS
    'Stable platform-owned Agent key; NULL for user-created Agents';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.agent_origin IS
    'Agent ownership origin: USER or SYSTEM';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.system_revision IS
    'Server-controlled Nexent release revision applied to a system Agent';

CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_system_agent_active_draft
    ON nexent.ag_tenant_agent_t (tenant_id, system_key)
    WHERE version_no = 0
      AND delete_flag != 'Y'
      AND system_key IS NOT NULL;

-- Creation permissions are required by the server-side NL2 adapters. Permission
-- IDs are migration-owned and explicit; ordinary USER is intentionally excluded.
WITH required_grants (role_permission_id,
    user_role,
    permission_category,
    permission_type,
    permission_subtype
) AS (
    VALUES
        (1701, 'SU',          'RESOURCE', 'AGENT', 'CREATE'),
        (1702, 'ADMIN',       'RESOURCE', 'AGENT', 'CREATE'),
        (1703, 'DEV',         'RESOURCE', 'AGENT', 'CREATE'),
        (1704, 'ASSET_OWNER', 'RESOURCE', 'AGENT', 'CREATE'),
        (1705, 'SPEED',       'RESOURCE', 'AGENT', 'CREATE'),
        (1706, 'SU',          'RESOURCE', 'SKILL', 'CREATE'),
        (1707, 'ADMIN',       'RESOURCE', 'SKILL', 'CREATE'),
        (1708, 'DEV',         'RESOURCE', 'SKILL', 'CREATE'),
        (1709, 'ASSET_OWNER', 'RESOURCE', 'SKILL', 'CREATE'),
        (1710, 'SPEED',       'RESOURCE', 'SKILL', 'CREATE')
)
INSERT INTO nexent.role_permission_t (
    role_permission_id,
    user_role,
    permission_category,
    permission_type,
    permission_subtype
)
SELECT
    required_grants.role_permission_id,
    required_grants.user_role,
    required_grants.permission_category,
    required_grants.permission_type,
    required_grants.permission_subtype
FROM required_grants
WHERE NOT EXISTS (
    SELECT 1
    FROM nexent.role_permission_t AS existing
    WHERE existing.user_role = required_grants.user_role
      AND existing.permission_category = required_grants.permission_category
      AND existing.permission_type = required_grants.permission_type
      AND existing.permission_subtype = required_grants.permission_subtype
);

-- Persist the canonical Workbench declaration and its optimistic-lock version.
ALTER TABLE nexent.conversation_record_t
    ADD COLUMN IF NOT EXISTS workbench_config JSONB,
    ADD COLUMN IF NOT EXISTS workbench_config_version INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN nexent.conversation_record_t.workbench_config IS
    'Canonical schema-v3 Workbench conversation declaration; resolved runtime artifacts are never persisted';

COMMENT ON COLUMN nexent.conversation_record_t.workbench_config_version IS
    'Monotonic optimistic-lock version for workbench_config';

