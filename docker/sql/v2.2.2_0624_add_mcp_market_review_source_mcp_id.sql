SET search_path TO nexent;

BEGIN;

ALTER TABLE IF EXISTS nexent.mcp_market_review_t
    ADD COLUMN IF NOT EXISTS source_mcp_id INTEGER;

COMMENT ON COLUMN nexent.mcp_market_review_t.source_mcp_id IS 'Local MCP record ID that created this review';

CREATE INDEX IF NOT EXISTS idx_mcp_review_source_mcp_delete
    ON nexent.mcp_market_review_t (source_mcp_id, delete_flag);

COMMIT;
