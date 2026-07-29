-- Migration: Market Phase 0 — Extend ag_agent_repository_t for unified market
-- Date: 2026-07-22
-- Description: Add source/is_official_template/expert_type/category_id/default_init_prompt/
--              quick_prompts/members_info/is_featured/featured_weight columns to
--              ag_agent_repository_t to support the unified market page and template detail page.
-- Idempotent: all ALTER use ADD COLUMN IF NOT EXISTS.

SET search_path TO nexent;

BEGIN;

-- ============================================================================
-- Extend ag_agent_repository_t for unified market (idempotent)
-- ============================================================================
ALTER TABLE IF EXISTS nexent.ag_agent_repository_t
    ADD COLUMN IF NOT EXISTS source                 VARCHAR(30) DEFAULT 'community',
    ADD COLUMN IF NOT EXISTS is_official_template  BOOLEAN     DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS expert_type           VARCHAR(10) DEFAULT 'agent',
    ADD COLUMN IF NOT EXISTS category_id           VARCHAR(30),
    ADD COLUMN IF NOT EXISTS default_init_prompt    TEXT,
    ADD COLUMN IF NOT EXISTS quick_prompts          JSONB,
    ADD COLUMN IF NOT EXISTS members_info           JSONB,
    ADD COLUMN IF NOT EXISTS is_featured            BOOLEAN     DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS featured_weight       INT         DEFAULT 0;

COMMENT ON COLUMN nexent.ag_agent_repository_t.source IS 'Listing source: community / official';
COMMENT ON COLUMN nexent.ag_agent_repository_t.is_official_template IS 'Whether this listing is an official template';
COMMENT ON COLUMN nexent.ag_agent_repository_t.expert_type IS 'Expert type: agent / expert (for future expert tab)';
COMMENT ON COLUMN nexent.ag_agent_repository_t.category_id IS 'Market category ID (FK to market_category_t)';
COMMENT ON COLUMN nexent.ag_agent_repository_t.default_init_prompt IS 'Default initial prompt shown on template detail page';
COMMENT ON COLUMN nexent.ag_agent_repository_t.quick_prompts IS 'Quick prompt suggestions JSON array for template detail';
COMMENT ON COLUMN nexent.ag_agent_repository_t.members_info IS 'Members info JSON for expert/recipe composition display';
COMMENT ON COLUMN nexent.ag_agent_repository_t.is_featured IS 'Whether this listing is featured on the market';
COMMENT ON COLUMN nexent.ag_agent_repository_t.featured_weight IS 'Featured sort weight, higher = earlier';

-- Index for market listing queries (shared or official templates)
CREATE INDEX IF NOT EXISTS ix_ag_agent_repository_market_status
    ON nexent.ag_agent_repository_t (status)
    WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS ix_ag_agent_repository_featured
    ON nexent.ag_agent_repository_t (is_featured, featured_weight DESC)
    WHERE delete_flag = 'N' AND is_featured = TRUE;

COMMIT;
