-- =============================================================================
-- External KB Adapter Registry — Phase 3 V4 standard
-- =============================================================================
-- Version: v2.3.0
-- Date: 2026-07-07
-- Description: Create external_kb_adapter_t for the external KB adapter
--   registry (Phase 3). Stores adapter container metadata, health status,
--   capabilities, and external KB connection config. Each registered adapter
--   proxies standard V4 knowledge-base API calls to its container.
--
-- Idempotency: every DDL statement is safe to run multiple times.
--   - CREATE SEQUENCE IF NOT EXISTS
--   - CREATE TABLE IF NOT EXISTS
--   - CREATE INDEX IF NOT EXISTS
--   - CREATE TRIGGER IF NOT EXISTS / DROP TRIGGER + CREATE OR REPLACE
-- =============================================================================

-- Primary key sequence
CREATE SEQUENCE IF NOT EXISTS nexent.external_kb_adapter_t_adapter_id_seq;

-- Adapter registry table
CREATE TABLE IF NOT EXISTS nexent.external_kb_adapter_t (
    adapter_id          INTEGER      NOT NULL DEFAULT nextval('nexent.external_kb_adapter_t_adapter_id_seq'),
    name                VARCHAR(100),
    platform            VARCHAR(50),
    image_url           VARCHAR(500),
    container_name      VARCHAR(200),
    service_host        VARCHAR(200),
    api_key             VARCHAR(500),
    capabilities        JSONB,
    external_kb_config  JSONB,
    tenant_id           VARCHAR(100),
    enabled             BOOLEAN      NOT NULL DEFAULT TRUE,
    status              VARCHAR(20)  NOT NULL DEFAULT 'running',
    health_status       VARCHAR(20)  NOT NULL DEFAULT 'unknown',
    last_health_check   TIMESTAMP,
    create_time         TIMESTAMP    NOT NULL DEFAULT NOW(),
    update_time         TIMESTAMP    NOT NULL DEFAULT NOW(),
    created_by          VARCHAR(100),
    updated_by          VARCHAR(100),
    delete_flag         VARCHAR(1)   NOT NULL DEFAULT 'N',
    CONSTRAINT pk_external_kb_adapter PRIMARY KEY (adapter_id)
);

COMMENT ON TABLE nexent.external_kb_adapter_t IS
    'Registered external KB adapter containers (Phase 3, V4 standard).';

COMMENT ON COLUMN nexent.external_kb_adapter_t.adapter_id         IS 'Primary key, auto-increment.';
COMMENT ON COLUMN nexent.external_kb_adapter_t.name               IS 'Display name, e.g. "Dify Adapter".';
COMMENT ON COLUMN nexent.external_kb_adapter_t.platform           IS 'Platform identifier: dify / aidp / ragflow / datamate / custom.';
COMMENT ON COLUMN nexent.external_kb_adapter_t.image_url          IS 'Docker image URL, e.g. registry/dify-nexent-adapter:1.0.0.';
COMMENT ON COLUMN nexent.external_kb_adapter_t.container_name     IS 'Docker container name managed by nexent.';
COMMENT ON COLUMN nexent.external_kb_adapter_t.service_host       IS 'Adapter HTTP service host:port, e.g. dify-adapter:8080.';
COMMENT ON COLUMN nexent.external_kb_adapter_t.api_key            IS 'Fernet-encrypted API key for nexent → adapter auth.';
COMMENT ON COLUMN nexent.external_kb_adapter_t.capabilities       IS 'Cached JSON from GET /capabilities (refreshed on start).';
COMMENT ON COLUMN nexent.external_kb_adapter_t.external_kb_config IS 'External KB connection config: {url, api_key, extra}.';
COMMENT ON COLUMN nexent.external_kb_adapter_t.status             IS 'Container lifecycle: stopped / running / error.';
COMMENT ON COLUMN nexent.external_kb_adapter_t.health_status      IS 'Last health probe result: ok / error / unknown.';
COMMENT ON COLUMN nexent.external_kb_adapter_t.last_health_check  IS 'Timestamp of most recent health probe.';

-- Tenant-scoped index for fast listing
CREATE INDEX IF NOT EXISTS idx_ext_kb_adapter_tenant
    ON nexent.external_kb_adapter_t (tenant_id)
    WHERE delete_flag = 'N';

-- Status index for fast health/status queries
CREATE INDEX IF NOT EXISTS idx_ext_kb_adapter_status
    ON nexent.external_kb_adapter_t (tenant_id, status)
    WHERE delete_flag = 'N';

-- Auto-update update_time trigger
CREATE OR REPLACE FUNCTION nexent.update_ext_kb_adapter_update_time()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.update_time := NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_ext_kb_adapter_update_time ON nexent.external_kb_adapter_t;
CREATE TRIGGER trg_ext_kb_adapter_update_time
    BEFORE UPDATE ON nexent.external_kb_adapter_t
    FOR EACH ROW EXECUTE FUNCTION nexent.update_ext_kb_adapter_update_time();
