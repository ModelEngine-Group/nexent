-- Migration: Add MCP market tables and extend existing MCP tables
-- Date: 2026-07-09
-- Description: Create mcp_market_record_t and mcp_market_review_t, add market_id
--              to mcp_record_t, add review_status/review_type to mcp_community_record_t.

SET search_path TO nexent;

BEGIN;

-- ============================================================================
-- 1) Extend mcp_record_t for market integration (idempotent)
-- ============================================================================
ALTER TABLE IF EXISTS nexent.mcp_record_t
    ADD COLUMN IF NOT EXISTS market_id INTEGER;

COMMENT ON COLUMN nexent.mcp_record_t.market_id IS 'Published market record ID (FK to mcp_market_record_t)';

-- ============================================================================
-- 2) Extend mcp_community_record_t for review workflow (idempotent)
-- ============================================================================
ALTER TABLE IF EXISTS nexent.mcp_community_record_t
    ADD COLUMN IF NOT EXISTS review_status VARCHAR(30) DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS review_type VARCHAR(30) DEFAULT 'initial_listing';

COMMENT ON COLUMN nexent.mcp_community_record_t.review_status IS 'Review status: pending/approved/rejected/offline';
COMMENT ON COLUMN nexent.mcp_community_record_t.review_type IS 'Review submission type: initial_listing/update';

-- ============================================================================
-- 3) Create mcp_market_record_t (Repository tab data)
-- ============================================================================
CREATE TABLE IF NOT EXISTS nexent.mcp_market_record_t (
    market_id       SERIAL PRIMARY KEY NOT NULL,
    tenant_id       VARCHAR(100),
    user_id         VARCHAR(100),
    mcp_name        VARCHAR(100) NOT NULL,
    mcp_server      VARCHAR(500) NOT NULL,
    source          VARCHAR(30) DEFAULT 'community',
    registry_json   JSONB,
    transport_type  VARCHAR(30),
    config_json     JSON,
    tags            TEXT[],
    description     TEXT,
    download_count  INTEGER DEFAULT 0,
    create_time     TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time     TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by      VARCHAR(100),
    updated_by      VARCHAR(100),
    delete_flag     VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE nexent.mcp_market_record_t OWNER TO root;

COMMENT ON TABLE nexent.mcp_market_record_t IS 'Approved MCP market records (Repository tab) — never disappears during reviews';
COMMENT ON COLUMN nexent.mcp_market_record_t.market_id IS 'Market record ID, unique primary key';
COMMENT ON COLUMN nexent.mcp_market_record_t.tenant_id IS 'Publisher tenant ID';
COMMENT ON COLUMN nexent.mcp_market_record_t.user_id IS 'Publisher user ID';
COMMENT ON COLUMN nexent.mcp_market_record_t.mcp_name IS 'MCP name';
COMMENT ON COLUMN nexent.mcp_market_record_t.mcp_server IS 'MCP server URL';
COMMENT ON COLUMN nexent.mcp_market_record_t.source IS 'Source type, fixed to community';
COMMENT ON COLUMN nexent.mcp_market_record_t.registry_json IS 'Full MCP metadata JSON';
COMMENT ON COLUMN nexent.mcp_market_record_t.transport_type IS 'Transport type: http/sse/container';
COMMENT ON COLUMN nexent.mcp_market_record_t.config_json IS 'Public-shareable MCP configuration JSON';
COMMENT ON COLUMN nexent.mcp_market_record_t.tags IS 'Tags';
COMMENT ON COLUMN nexent.mcp_market_record_t.description IS 'Description';
COMMENT ON COLUMN nexent.mcp_market_record_t.download_count IS 'Cumulative download/install count';

CREATE INDEX IF NOT EXISTS idx_mcp_market_tenant_delete
    ON nexent.mcp_market_record_t (tenant_id, delete_flag);
CREATE INDEX IF NOT EXISTS idx_mcp_market_name_delete
    ON nexent.mcp_market_record_t (mcp_name, delete_flag);
CREATE INDEX IF NOT EXISTS idx_mcp_market_tags_gin
    ON nexent.mcp_market_record_t USING GIN (tags);

-- trigger: auto-update update_time
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
-- 4) Create mcp_market_review_t (Review submissions)
-- ============================================================================
CREATE TABLE IF NOT EXISTS nexent.mcp_market_review_t (
    review_id       SERIAL PRIMARY KEY NOT NULL,
    market_id       INTEGER,
    source_mcp_id   INTEGER,
    tenant_id       VARCHAR(100),
    user_id         VARCHAR(100),
    mcp_name        VARCHAR(100) NOT NULL,
    mcp_server      VARCHAR(500) NOT NULL,
    source          VARCHAR(30) DEFAULT 'community',
    registry_json   JSONB,
    transport_type  VARCHAR(30),
    config_json     JSON,
    review_status   VARCHAR(30) DEFAULT 'pending',
    review_type     VARCHAR(30) DEFAULT 'initial_listing',
    tags            TEXT[],
    description     TEXT,
    create_time     TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time     TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by      VARCHAR(100),
    updated_by      VARCHAR(100),
    delete_flag     VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE nexent.mcp_market_review_t OWNER TO root;

COMMENT ON TABLE nexent.mcp_market_review_t IS 'MCP market review submissions — one row per review request';
COMMENT ON COLUMN nexent.mcp_market_review_t.review_id IS 'Review record ID, unique primary key';
COMMENT ON COLUMN nexent.mcp_market_review_t.market_id IS 'FK to mcp_market_record_t(market_id), NULL for unapproved initial listings';
COMMENT ON COLUMN nexent.mcp_market_review_t.source_mcp_id IS 'Local MCP record ID that created this review';
COMMENT ON COLUMN nexent.mcp_market_review_t.tenant_id IS 'Submitter tenant ID';
COMMENT ON COLUMN nexent.mcp_market_review_t.user_id IS 'Submitter user ID';
COMMENT ON COLUMN nexent.mcp_market_review_t.mcp_name IS 'MCP name at submission time';
COMMENT ON COLUMN nexent.mcp_market_review_t.mcp_server IS 'MCP server URL at submission time';
COMMENT ON COLUMN nexent.mcp_market_review_t.source IS 'Source type, fixed to community';
COMMENT ON COLUMN nexent.mcp_market_review_t.registry_json IS 'Snapshot of MCP metadata at submission time';
COMMENT ON COLUMN nexent.mcp_market_review_t.transport_type IS 'Transport type: http/sse/container';
COMMENT ON COLUMN nexent.mcp_market_review_t.config_json IS 'Snapshot of MCP config at submission time';
COMMENT ON COLUMN nexent.mcp_market_review_t.review_status IS 'Review status: pending/approved/rejected';
COMMENT ON COLUMN nexent.mcp_market_review_t.review_type IS 'Review submission type: initial_listing/update';
COMMENT ON COLUMN nexent.mcp_market_review_t.tags IS 'Tags at submission time';
COMMENT ON COLUMN nexent.mcp_market_review_t.description IS 'Description at submission time';

CREATE INDEX IF NOT EXISTS idx_mcp_market_review_tenant_delete
    ON nexent.mcp_market_review_t (tenant_id, delete_flag);
CREATE INDEX IF NOT EXISTS idx_mcp_market_review_market_id
    ON nexent.mcp_market_review_t (market_id);
CREATE INDEX IF NOT EXISTS idx_mcp_market_review_status
    ON nexent.mcp_market_review_t (review_status);
CREATE INDEX IF NOT EXISTS idx_mcp_market_review_tags_gin
    ON nexent.mcp_market_review_t USING GIN (tags);

-- trigger: auto-update update_time
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
-- 5) Backfill: migrate old community records to the new market tables
-- ============================================================================
-- Old mcp_community_record_t had no review workflow — published immediately.
-- Set their review_status to approved so the old code path remains consistent,
-- then copy them to mcp_market_record_t so they appear in the new Repository tab.
-- Finally, link mcp_record_t rows to the newly created market records.
-- ============================================================================

-- Mark old community records as approved (they were published without review)
UPDATE nexent.mcp_community_record_t
SET review_status = 'approved'
WHERE (review_status IS NULL OR review_status = 'pending')
  AND delete_flag != 'Y';

-- Backfill: copy old community records into the market table (idempotent)
WITH inserted AS (
    INSERT INTO nexent.mcp_market_record_t (
        tenant_id, user_id, mcp_name, mcp_server, source,
        registry_json, transport_type, config_json, tags, description,
        download_count, create_time, update_time, created_by, updated_by, delete_flag
    )
    SELECT
        c.tenant_id, c.user_id, c.mcp_name, c.mcp_server, c.source,
        c.registry_json, c.transport_type, c.config_json, c.tags, c.description,
        0, c.create_time, c.update_time, c.created_by, c.updated_by, c.delete_flag
    FROM nexent.mcp_community_record_t c
    WHERE c.delete_flag != 'Y'
      AND c.review_status = 'approved'
      AND NOT EXISTS (
          SELECT 1 FROM nexent.mcp_market_record_t m
          WHERE m.tenant_id = c.tenant_id
            AND m.mcp_name = c.mcp_name
      )
    RETURNING market_id, tenant_id, mcp_name
)
UPDATE nexent.mcp_record_t AS mr
SET market_id = ins.market_id
FROM inserted AS ins
WHERE mr.tenant_id = ins.tenant_id
  AND mr.mcp_name = ins.mcp_name
  AND mr.market_id IS NULL;

COMMIT;
