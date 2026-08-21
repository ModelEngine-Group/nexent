-- Add a stable API URL for user-uploaded agent icons.
ALTER TABLE nexent.ag_tenant_agent_t
    ADD COLUMN IF NOT EXISTS icon_url VARCHAR(1024);

COMMENT ON COLUMN nexent.ag_tenant_agent_t.icon_url IS
    'Stable API URL for the user-uploaded agent icon';
