ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN display_name VARCHAR(100);
COMMENT ON COLUMN nexent.ag_tenant_agent_t.display_name IS 'Agent展示名称';