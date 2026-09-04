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

-- Creation-mode permissions intentionally exclude the ordinary USER role.
INSERT INTO nexent.role_permission_t (
    role_permission_id,
    user_role,
    permission_category,
    permission_type,
    permission_subtype
) VALUES
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
ON CONFLICT (role_permission_id) DO UPDATE SET
    user_role = EXCLUDED.user_role,
    permission_category = EXCLUDED.permission_category,
    permission_type = EXCLUDED.permission_type,
    permission_subtype = EXCLUDED.permission_subtype;
