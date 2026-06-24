-- Migration: Split mcp_community_record_t into mcp_market_record_t + mcp_market_review_t
-- Date: 2026-06-23
-- Description: Approved MCPs live permanently in mcp_market_record_t so they never
-- disappear from the Repository tab during version updates. Each review submission
-- (initial listing or version update) gets its own row in mcp_market_review_t.

SET search_path TO nexent;

BEGIN;

-- ============================================================================
-- 1. Create mcp_market_record_t (always-approved MCPs for the Repository tab)
-- ============================================================================

CREATE TABLE IF NOT EXISTS nexent.mcp_market_record_t (
    market_id SERIAL PRIMARY KEY NOT NULL,
    tenant_id VARCHAR(100),
    user_id VARCHAR(100),
    mcp_name VARCHAR(100) NOT NULL,
    mcp_server VARCHAR(500),
    source VARCHAR(30) DEFAULT 'community',
    version VARCHAR(50),
    registry_json JSONB,
    transport_type VARCHAR(30),
    config_json JSON,
    tags TEXT[],
    description TEXT,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE nexent.mcp_market_record_t OWNER TO root;

COMMENT ON TABLE nexent.mcp_market_record_t IS 'Approved MCP market records — always visible in the Repository tab';
COMMENT ON COLUMN nexent.mcp_market_record_t.market_id IS 'Market record ID, unique primary key';
COMMENT ON COLUMN nexent.mcp_market_record_t.tenant_id IS 'Publisher tenant ID';
COMMENT ON COLUMN nexent.mcp_market_record_t.user_id IS 'Publisher user ID';
COMMENT ON COLUMN nexent.mcp_market_record_t.mcp_name IS 'MCP name';
COMMENT ON COLUMN nexent.mcp_market_record_t.mcp_server IS 'MCP server URL';
COMMENT ON COLUMN nexent.mcp_market_record_t.source IS 'Source type, fixed to community for this table';
COMMENT ON COLUMN nexent.mcp_market_record_t.version IS 'Current approved MCP version';
COMMENT ON COLUMN nexent.mcp_market_record_t.registry_json IS 'Full MCP server metadata JSON for discovery and quick import';
COMMENT ON COLUMN nexent.mcp_market_record_t.transport_type IS 'Transport type: url/container';
COMMENT ON COLUMN nexent.mcp_market_record_t.config_json IS 'Public-shareable MCP configuration JSON';
COMMENT ON COLUMN nexent.mcp_market_record_t.tags IS 'Tags';
COMMENT ON COLUMN nexent.mcp_market_record_t.description IS 'Description';
COMMENT ON COLUMN nexent.mcp_market_record_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.mcp_market_record_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.mcp_market_record_t.created_by IS 'Creator ID';
COMMENT ON COLUMN nexent.mcp_market_record_t.updated_by IS 'Updater ID';
COMMENT ON COLUMN nexent.mcp_market_record_t.delete_flag IS 'Soft delete flag: Y/N';

-- Indices
CREATE INDEX IF NOT EXISTS idx_mcp_market_tenant_delete
    ON nexent.mcp_market_record_t (tenant_id, delete_flag);
CREATE INDEX IF NOT EXISTS idx_mcp_market_name_delete
    ON nexent.mcp_market_record_t (mcp_name, delete_flag);
CREATE INDEX IF NOT EXISTS idx_mcp_market_transport_delete
    ON nexent.mcp_market_record_t (transport_type, delete_flag);
CREATE INDEX IF NOT EXISTS idx_mcp_market_user_delete
    ON nexent.mcp_market_record_t (user_id, delete_flag);
CREATE INDEX IF NOT EXISTS idx_mcp_market_tags_gin
    ON nexent.mcp_market_record_t USING GIN (tags);

-- update_time trigger
CREATE OR REPLACE FUNCTION update_mcp_market_record_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_mcp_market_record_update_time() IS 'Auto-update update_time for mcp_market_record_t';

DROP TRIGGER IF EXISTS update_mcp_market_record_update_time_trigger ON nexent.mcp_market_record_t;
CREATE TRIGGER update_mcp_market_record_update_time_trigger
BEFORE UPDATE ON nexent.mcp_market_record_t
FOR EACH ROW
EXECUTE FUNCTION update_mcp_market_record_update_time();

COMMENT ON TRIGGER update_mcp_market_record_update_time_trigger ON nexent.mcp_market_record_t IS 'Trigger to maintain update_time';

-- ============================================================================
-- 2. Migrate approved records from mcp_community_record_t → mcp_market_record_t
--    (preserves the same ID so FK references from mcp_record_t remain valid)
-- ============================================================================

INSERT INTO nexent.mcp_market_record_t (
    market_id, tenant_id, user_id, mcp_name, mcp_server, source, version,
    registry_json, transport_type, config_json, tags, description,
    create_time, update_time, created_by, updated_by, delete_flag
)
SELECT
    community_id, tenant_id, user_id, mcp_name, mcp_server, source, version,
    registry_json, transport_type, config_json, tags, description,
    create_time, update_time, created_by, updated_by, delete_flag
FROM nexent.mcp_community_record_t
WHERE review_status = 'approved'
  AND delete_flag != 'Y';

-- Also create market records for version_update records (they were approved
-- before the version update was submitted, so a market record must exist
-- for the original approved version). Extract the original version from
-- registry_json.version when available.
INSERT INTO nexent.mcp_market_record_t (
    market_id, tenant_id, user_id, mcp_name, mcp_server, source,
    version, registry_json, transport_type, config_json, tags, description,
    create_time, update_time, created_by, updated_by, delete_flag
)
SELECT
    community_id, tenant_id, user_id, mcp_name, mcp_server, source,
    CASE
        WHEN registry_json IS NOT NULL AND jsonb_typeof(registry_json) = 'object' AND registry_json ? 'version'
            THEN registry_json->>'version'
        ELSE version
    END,
    CASE WHEN registry_json IS NOT NULL AND jsonb_typeof(registry_json) = 'object'
        THEN registry_json - '_pendingVersion' - '_previousVersion'
        ELSE NULL
    END,
    transport_type, config_json, tags, description,
    create_time, update_time, created_by, updated_by, delete_flag
FROM nexent.mcp_community_record_t
WHERE review_status = 'pending'
  AND review_type = 'version_update'
  AND delete_flag != 'Y';

-- ============================================================================
-- 3. Create mcp_market_review_t (review submissions)
-- ============================================================================

CREATE TABLE IF NOT EXISTS nexent.mcp_market_review_t (
    review_id SERIAL PRIMARY KEY NOT NULL,
    market_id INTEGER REFERENCES nexent.mcp_market_record_t(market_id),
    source_mcp_id INTEGER,
    tenant_id VARCHAR(100),
    user_id VARCHAR(100),
    mcp_name VARCHAR(100) NOT NULL,
    mcp_server VARCHAR(500),
    source VARCHAR(30) DEFAULT 'community',
    version VARCHAR(50),
    registry_json JSONB,
    transport_type VARCHAR(30),
    config_json JSON,
    review_status VARCHAR(30) DEFAULT 'pending',
    review_type VARCHAR(30) DEFAULT 'initial_listing',
    previous_version VARCHAR(50),
    tags TEXT[],
    description TEXT,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE nexent.mcp_market_review_t OWNER TO root;

COMMENT ON TABLE nexent.mcp_market_review_t IS 'MCP market review submissions — one row per initial listing or version update';
COMMENT ON COLUMN nexent.mcp_market_review_t.review_id IS 'Review record ID, unique primary key';
COMMENT ON COLUMN nexent.mcp_market_review_t.market_id IS 'FK to mcp_market_record_t(market_id), NULL for unapproved initial listings';
COMMENT ON COLUMN nexent.mcp_market_review_t.source_mcp_id IS 'Local MCP record ID that created this review';
COMMENT ON COLUMN nexent.mcp_market_review_t.tenant_id IS 'Submitter tenant ID';
COMMENT ON COLUMN nexent.mcp_market_review_t.user_id IS 'Submitter user ID';
COMMENT ON COLUMN nexent.mcp_market_review_t.mcp_name IS 'MCP name at submission time';
COMMENT ON COLUMN nexent.mcp_market_review_t.mcp_server IS 'MCP server URL at submission time';
COMMENT ON COLUMN nexent.mcp_market_review_t.source IS 'Source type, fixed to community for this table';
COMMENT ON COLUMN nexent.mcp_market_review_t.version IS 'Version submitted for review';
COMMENT ON COLUMN nexent.mcp_market_review_t.registry_json IS 'Snapshot of MCP metadata at submission time';
COMMENT ON COLUMN nexent.mcp_market_review_t.transport_type IS 'Transport type: url/container';
COMMENT ON COLUMN nexent.mcp_market_review_t.config_json IS 'Snapshot of MCP config at submission time';
COMMENT ON COLUMN nexent.mcp_market_review_t.review_status IS 'Review status: pending/approved/rejected';
COMMENT ON COLUMN nexent.mcp_market_review_t.review_type IS 'Review submission type: initial_listing/version_update';
COMMENT ON COLUMN nexent.mcp_market_review_t.previous_version IS 'Previous approved version (only for version_update)';
COMMENT ON COLUMN nexent.mcp_market_review_t.tags IS 'Tags at submission time';
COMMENT ON COLUMN nexent.mcp_market_review_t.description IS 'Description at submission time';
COMMENT ON COLUMN nexent.mcp_market_review_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.mcp_market_review_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.mcp_market_review_t.created_by IS 'Creator ID';
COMMENT ON COLUMN nexent.mcp_market_review_t.updated_by IS 'Updater ID';
COMMENT ON COLUMN nexent.mcp_market_review_t.delete_flag IS 'Soft delete flag: Y/N';

-- Indices
CREATE INDEX IF NOT EXISTS idx_mcp_review_market_delete
    ON nexent.mcp_market_review_t (market_id, delete_flag);
CREATE INDEX IF NOT EXISTS idx_mcp_review_source_mcp_delete
    ON nexent.mcp_market_review_t (source_mcp_id, delete_flag);
CREATE INDEX IF NOT EXISTS idx_mcp_review_tenant_delete
    ON nexent.mcp_market_review_t (tenant_id, delete_flag);
CREATE INDEX IF NOT EXISTS idx_mcp_review_status_delete
    ON nexent.mcp_market_review_t (review_status, delete_flag);
CREATE INDEX IF NOT EXISTS idx_mcp_review_tenant_status_delete
    ON nexent.mcp_market_review_t (tenant_id, review_status, delete_flag);
CREATE INDEX IF NOT EXISTS idx_mcp_review_user_delete
    ON nexent.mcp_market_review_t (user_id, delete_flag);
CREATE INDEX IF NOT EXISTS idx_mcp_review_name_delete
    ON nexent.mcp_market_review_t (mcp_name, delete_flag);

-- update_time trigger
CREATE OR REPLACE FUNCTION update_mcp_market_review_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_mcp_market_review_update_time() IS 'Auto-update update_time for mcp_market_review_t';

DROP TRIGGER IF EXISTS update_mcp_market_review_update_time_trigger ON nexent.mcp_market_review_t;
CREATE TRIGGER update_mcp_market_review_update_time_trigger
BEFORE UPDATE ON nexent.mcp_market_review_t
FOR EACH ROW
EXECUTE FUNCTION update_mcp_market_review_update_time();

COMMENT ON TRIGGER update_mcp_market_review_update_time_trigger ON nexent.mcp_market_review_t IS 'Trigger to maintain update_time';

-- ============================================================================
-- 4. Migrate all records from mcp_community_record_t → mcp_market_review_t
--    Approved + version_update records get market_id set (market record already
--    exists); pending initial_listing ones get NULL market_id.
-- ============================================================================

INSERT INTO nexent.mcp_market_review_t (
    market_id, source_mcp_id, tenant_id, user_id, mcp_name, mcp_server, source, version,
    registry_json, transport_type, config_json,
    review_status, review_type, previous_version,
    tags, description,
    create_time, update_time, created_by, updated_by, delete_flag
)
SELECT
    CASE WHEN review_status = 'approved' OR review_type = 'version_update' THEN community_id ELSE NULL END,
    NULL,
    tenant_id, user_id, mcp_name, mcp_server, source,
    CASE
        WHEN registry_json IS NOT NULL AND jsonb_typeof(registry_json) = 'object' AND registry_json ? '_pendingVersion'
            THEN (registry_json->>'_pendingVersion')::VARCHAR
        ELSE version
    END,
    CASE WHEN registry_json IS NOT NULL AND jsonb_typeof(registry_json) = 'object'
        THEN registry_json - '_pendingVersion' - '_previousVersion'
        ELSE registry_json
    END,
    transport_type, config_json,
    review_status, review_type,
    registry_json->>'_previousVersion',
    tags, description,
    create_time, update_time, created_by, updated_by, delete_flag
FROM nexent.mcp_community_record_t
WHERE delete_flag != 'Y';

-- ============================================================================
-- 5. Rename mcp_record_t.community_id → market_id and update FK comment
-- ============================================================================

ALTER TABLE IF EXISTS nexent.mcp_record_t
    RENAME COLUMN community_id TO market_id;

COMMENT ON COLUMN nexent.mcp_record_t.market_id IS 'Published market record ID (FK to mcp_market_record_t)';

-- Rebuild index to reflect the renamed column
DROP INDEX IF EXISTS idx_mcp_record_t_community_id;
CREATE INDEX IF NOT EXISTS idx_mcp_record_t_market_id
    ON nexent.mcp_record_t (market_id, delete_flag);

COMMIT;
