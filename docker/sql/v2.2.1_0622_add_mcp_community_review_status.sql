-- Migration: Add MCP community review status
-- Date: 2026-06-22
-- Description: Route community MCP submissions through review before repository publication.

SET search_path TO nexent;

BEGIN;

ALTER TABLE IF EXISTS nexent.mcp_community_record_t
    ALTER COLUMN mcp_server DROP NOT NULL;

ALTER TABLE IF EXISTS nexent.mcp_community_record_t
    ADD COLUMN IF NOT EXISTS review_status VARCHAR(30) DEFAULT 'pending';

ALTER TABLE IF EXISTS nexent.mcp_community_record_t
    ADD COLUMN IF NOT EXISTS review_type VARCHAR(30) DEFAULT 'initial_listing';

UPDATE nexent.mcp_community_record_t
SET review_status = 'approved'
WHERE delete_flag != 'Y'
  AND (review_status IS NULL OR review_status = 'pending');

UPDATE nexent.mcp_community_record_t
SET review_type = 'initial_listing'
WHERE review_type IS NULL;

COMMENT ON COLUMN nexent.mcp_community_record_t.review_status IS 'Review status: pending/approved/rejected/offline';
COMMENT ON COLUMN nexent.mcp_community_record_t.review_type IS 'Review submission type: initial_listing/version_update';

CREATE INDEX IF NOT EXISTS idx_mcp_community_review_delete
    ON nexent.mcp_community_record_t (review_status, delete_flag);

CREATE INDEX IF NOT EXISTS idx_mcp_community_tenant_review_delete
    ON nexent.mcp_community_record_t (tenant_id, review_status, delete_flag);

COMMIT;
