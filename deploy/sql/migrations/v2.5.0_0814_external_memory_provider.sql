-- Phase 3: External Memory Provider schema
-- Provider configuration, EAV parameters, and ingest event logging.

-- 7.1 Provider configuration main table
CREATE TABLE IF NOT EXISTS nexent.memory_provider_config_t (
    provider_config_id  SERIAL PRIMARY KEY,
    tenant_id           VARCHAR(100) NOT NULL,
    provider_name       VARCHAR(100) NOT NULL,
    connection_type     VARCHAR(20)  NOT NULL DEFAULT 'plugin',
    enabled             BOOLEAN      NOT NULL DEFAULT FALSE,
    timeout_seconds     INTEGER      NOT NULL DEFAULT 30,
    last_error_code     VARCHAR(50),
    create_time         TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    update_time         TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    created_by          VARCHAR(100),
    updated_by          VARCHAR(100),
    delete_flag         VARCHAR(1)   NOT NULL DEFAULT 'N'
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_provider_config_tenant_name
    ON nexent.memory_provider_config_t (tenant_id, provider_name)
    WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS idx_memory_provider_config_enabled
    ON nexent.memory_provider_config_t (tenant_id, enabled)
    WHERE delete_flag = 'N';

COMMENT ON TABLE nexent.memory_provider_config_t IS 'External memory provider configuration';
COMMENT ON COLUMN nexent.memory_provider_config_t.provider_config_id IS 'Provider configuration ID';
COMMENT ON COLUMN nexent.memory_provider_config_t.tenant_id IS 'Tenant ID';
COMMENT ON COLUMN nexent.memory_provider_config_t.provider_name IS 'Provider name, unique per tenant';
COMMENT ON COLUMN nexent.memory_provider_config_t.connection_type IS 'Connection type: plugin (Phase 3)';
COMMENT ON COLUMN nexent.memory_provider_config_t.enabled IS 'Whether this provider is enabled';
COMMENT ON COLUMN nexent.memory_provider_config_t.timeout_seconds IS 'Request timeout in seconds';
COMMENT ON COLUMN nexent.memory_provider_config_t.last_error_code IS 'Last error code from test-search or test-ingest';
COMMENT ON COLUMN nexent.memory_provider_config_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.memory_provider_config_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.memory_provider_config_t.created_by IS 'Creator ID';
COMMENT ON COLUMN nexent.memory_provider_config_t.updated_by IS 'Last updater ID';
COMMENT ON COLUMN nexent.memory_provider_config_t.delete_flag IS 'Soft delete flag: Y/N';

-- 7.2 Provider configuration parameter table (EAV)
CREATE TABLE IF NOT EXISTS nexent.memory_provider_config_param_t (
    param_id            SERIAL PRIMARY KEY,
    provider_config_id  INTEGER      NOT NULL,
    param_name          VARCHAR(200) NOT NULL,
    param_value         TEXT,
    create_time         TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    update_time         TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    created_by          VARCHAR(100),
    updated_by          VARCHAR(100),
    delete_flag         VARCHAR(1)   NOT NULL DEFAULT 'N'
);

CREATE INDEX IF NOT EXISTS idx_provider_config_param_provider
    ON nexent.memory_provider_config_param_t (provider_config_id)
    WHERE delete_flag = 'N';

CREATE UNIQUE INDEX IF NOT EXISTS uq_provider_config_param_name
    ON nexent.memory_provider_config_param_t (provider_config_id, param_name)
    WHERE delete_flag = 'N';

COMMENT ON TABLE nexent.memory_provider_config_param_t IS 'External memory provider configuration parameters (EAV)';
COMMENT ON COLUMN nexent.memory_provider_config_param_t.param_id IS 'Parameter ID';
COMMENT ON COLUMN nexent.memory_provider_config_param_t.provider_config_id IS 'Foreign key to memory_provider_config_t';
COMMENT ON COLUMN nexent.memory_provider_config_param_t.param_name IS 'Parameter name';
COMMENT ON COLUMN nexent.memory_provider_config_param_t.param_value IS 'Parameter value';
COMMENT ON COLUMN nexent.memory_provider_config_param_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.memory_provider_config_param_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.memory_provider_config_param_t.delete_flag IS 'Soft delete flag: Y/N';

-- 7.3 Ingest event log table
CREATE TABLE IF NOT EXISTS nexent.memory_external_ingest_event_log_t (
    log_id              SERIAL PRIMARY KEY,
    provider            VARCHAR(100),
    tenant_id           VARCHAR(100),
    user_id             VARCHAR(100),
    agent_id            VARCHAR(100),
    conversation_id     VARCHAR(100),
    event_id            VARCHAR(255),
    idempotency_key     TEXT,
    unit_ids            TEXT,
    response_status     VARCHAR(30),
    response_summary    TEXT,
    sent_at             TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    create_time         TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    update_time         TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    created_by          VARCHAR(100),
    updated_by          VARCHAR(100),
    delete_flag         VARCHAR(1)   NOT NULL DEFAULT 'N'
);

CREATE INDEX IF NOT EXISTS idx_external_ingest_log_tenant
    ON nexent.memory_external_ingest_event_log_t (tenant_id, user_id, agent_id, sent_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_external_ingest_log_idem
    ON nexent.memory_external_ingest_event_log_t (idempotency_key)
    WHERE delete_flag = 'N';

COMMENT ON TABLE nexent.memory_external_ingest_event_log_t IS 'External memory ingest event log';
COMMENT ON COLUMN nexent.memory_external_ingest_event_log_t.log_id IS 'Log ID';
COMMENT ON COLUMN nexent.memory_external_ingest_event_log_t.provider IS 'Provider name';
COMMENT ON COLUMN nexent.memory_external_ingest_event_log_t.tenant_id IS 'Tenant ID';
COMMENT ON COLUMN nexent.memory_external_ingest_event_log_t.user_id IS 'User ID';
COMMENT ON COLUMN nexent.memory_external_ingest_event_log_t.agent_id IS 'Agent ID';
COMMENT ON COLUMN nexent.memory_external_ingest_event_log_t.conversation_id IS 'Conversation ID';
COMMENT ON COLUMN nexent.memory_external_ingest_event_log_t.event_id IS 'Event ID';
COMMENT ON COLUMN nexent.memory_external_ingest_event_log_t.idempotency_key IS 'Idempotency key for deduplication';
COMMENT ON COLUMN nexent.memory_external_ingest_event_log_t.unit_ids IS 'Comma-separated unit ID list';
COMMENT ON COLUMN nexent.memory_external_ingest_event_log_t.response_status IS 'Response status';
COMMENT ON COLUMN nexent.memory_external_ingest_event_log_t.response_summary IS 'Response summary';
COMMENT ON COLUMN nexent.memory_external_ingest_event_log_t.sent_at IS 'Timestamp when the event was sent';
COMMENT ON COLUMN nexent.memory_external_ingest_event_log_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.memory_external_ingest_event_log_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.memory_external_ingest_event_log_t.created_by IS 'Creator ID';
COMMENT ON COLUMN nexent.memory_external_ingest_event_log_t.updated_by IS 'Last updater ID';
COMMENT ON COLUMN nexent.memory_external_ingest_event_log_t.delete_flag IS 'Soft delete flag: Y/N';

-- 8. Permission seed data: MEM.PROVIDER (CREATE, READ, UPDATE, DELETE)
-- Granted to ADMIN and SPEED roles only (per Functional Design §14.5)
INSERT INTO nexent.role_permission_t (
    role_permission_id, user_role, permission_category, permission_type, permission_subtype
) VALUES
    (1122, 'ADMIN', 'RESOURCE', 'MEM.PROVIDER', 'CREATE'),
    (1119, 'ADMIN', 'RESOURCE', 'MEM.PROVIDER', 'READ'),
    (1120, 'ADMIN', 'RESOURCE', 'MEM.PROVIDER', 'UPDATE'),
    (1121, 'ADMIN', 'RESOURCE', 'MEM.PROVIDER', 'DELETE'),
    (1415, 'SPEED', 'RESOURCE', 'MEM.PROVIDER', 'CREATE'),
    (1416, 'SPEED', 'RESOURCE', 'MEM.PROVIDER', 'READ'),
    (1417, 'SPEED', 'RESOURCE', 'MEM.PROVIDER', 'UPDATE'),
    (1418, 'SPEED', 'RESOURCE', 'MEM.PROVIDER', 'DELETE')
ON CONFLICT (role_permission_id) DO UPDATE SET
    user_role = EXCLUDED.user_role, permission_category = EXCLUDED.permission_category,
    permission_type = EXCLUDED.permission_type, permission_subtype = EXCLUDED.permission_subtype;
