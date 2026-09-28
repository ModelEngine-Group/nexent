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
