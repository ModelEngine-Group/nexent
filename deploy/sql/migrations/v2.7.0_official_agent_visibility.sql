-- Per-tenant visibility overrides for official Agent repository listings.
-- Missing row means visible; rows are soft-deleted when visibility is restored.
CREATE SEQUENCE IF NOT EXISTS nexent.ag_official_agent_tenant_visibility_t_visibility_id_seq;

CREATE TABLE IF NOT EXISTS nexent.ag_official_agent_tenant_visibility_t (
    visibility_id BIGINT NOT NULL DEFAULT nextval(
        'nexent.ag_official_agent_tenant_visibility_t_visibility_id_seq'
    ),
    agent_repository_id BIGINT NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) NOT NULL DEFAULT 'N',
    CONSTRAINT ag_official_agent_tenant_visibility_t_pkey PRIMARY KEY (visibility_id),
    CONSTRAINT ux_official_agent_tenant_visibility
        UNIQUE (agent_repository_id, tenant_id)
);

CREATE INDEX IF NOT EXISTS ix_official_agent_tenant_visibility_tenant
    ON nexent.ag_official_agent_tenant_visibility_t (tenant_id);
