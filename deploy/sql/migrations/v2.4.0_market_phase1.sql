-- Migration: Market Phase 1 — Create review / rating / category / tag tables
-- Date: 2026-07-22
-- Description: Create market_review_t, market_rating_summary_t, market_category_t, market_tag_t
--              to support the unified market page category/tag filters and template detail
--              review/rating features.
-- Idempotent: uses CREATE TABLE IF NOT EXISTS and CREATE SEQUENCE IF NOT EXISTS.

SET search_path TO nexent;

BEGIN;

-- ============================================================================
-- 1) market_category_t — unified market categories
-- ============================================================================
CREATE SEQUENCE IF NOT EXISTS nexent.market_category_t_category_id_seq;

CREATE TABLE IF NOT EXISTS nexent.market_category_t (
    category_id       SERIAL       PRIMARY KEY,
    entity_type       VARCHAR(20)  NOT NULL DEFAULT 'agent',
    name              VARCHAR(100) NOT NULL,
    display_name      VARCHAR(100),
    display_name_zh   VARCHAR(100),
    description       TEXT,
    description_zh    TEXT,
    icon              VARCHAR(50),
    sort_order        INT          DEFAULT 0,
    is_active         BOOLEAN      DEFAULT TRUE,
    create_time       TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time       TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by        VARCHAR(100),
    updated_by        VARCHAR(100),
    delete_flag       VARCHAR(1)   DEFAULT 'N'
);

COMMENT ON TABLE  nexent.market_category_t IS 'Unified market category definitions';
COMMENT ON COLUMN nexent.market_category_t.entity_type IS 'Entity type: agent / skill / mcp / recipe / expert';
COMMENT ON COLUMN nexent.market_category_t.name IS 'Category programmatic name (unique per entity_type)';
COMMENT ON COLUMN nexent.market_category_t.display_name IS 'Category display name (English)';
COMMENT ON COLUMN nexent.market_category_t.display_name_zh IS 'Category display name (Chinese)';
COMMENT ON COLUMN nexent.market_category_t.icon IS 'Category icon (emoji or URL)';
COMMENT ON COLUMN nexent.market_category_t.sort_order IS 'Sort order, lower = earlier';
COMMENT ON COLUMN nexent.market_category_t.is_active IS 'Whether this category is active';

CREATE UNIQUE INDEX IF NOT EXISTS uq_market_category_entity_name
    ON nexent.market_category_t (entity_type, name)
    WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS ix_market_category_entity_type
    ON nexent.market_category_t (entity_type, sort_order)
    WHERE delete_flag = 'N' AND is_active = TRUE;

-- ============================================================================
-- 2) market_tag_t — unified market tags
-- ============================================================================
CREATE SEQUENCE IF NOT EXISTS nexent.market_tag_t_tag_id_seq;

CREATE TABLE IF NOT EXISTS nexent.market_tag_t (
    tag_id            SERIAL       PRIMARY KEY,
    name              VARCHAR(100) NOT NULL,
    display_name      VARCHAR(100),
    description       TEXT,
    create_time       TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time       TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by        VARCHAR(100),
    updated_by        VARCHAR(100),
    delete_flag       VARCHAR(1)   DEFAULT 'N'
);

COMMENT ON TABLE  nexent.market_tag_t IS 'Unified market tag definitions';
COMMENT ON COLUMN nexent.market_tag_t.name IS 'Tag programmatic name';
COMMENT ON COLUMN nexent.market_tag_t.display_name IS 'Tag display name';

CREATE UNIQUE INDEX IF NOT EXISTS uq_market_tag_name
    ON nexent.market_tag_t (name)
    WHERE delete_flag = 'N';

-- ============================================================================
-- 3) market_review_t — user reviews for market entities
-- ============================================================================
CREATE SEQUENCE IF NOT EXISTS nexent.market_review_t_review_id_seq;

CREATE TABLE IF NOT EXISTS nexent.market_review_t (
    review_id         BIGSERIAL    PRIMARY KEY,
    entity_type       VARCHAR(20)  NOT NULL,
    entity_id         BIGINT       NOT NULL,
    tenant_id         VARCHAR(36),
    user_id           VARCHAR(64)  NOT NULL,
    rating            SMALLINT     NOT NULL CHECK (rating >= 1 AND rating <= 5),
    comment           TEXT,
    parent_review_id  BIGINT,
    status            VARCHAR(20)  DEFAULT 'visible',
    create_time       TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time       TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by        VARCHAR(100),
    updated_by        VARCHAR(100),
    delete_flag       VARCHAR(1)   DEFAULT 'N'
);

COMMENT ON TABLE  nexent.market_review_t IS 'User reviews/ratings for market entities';
COMMENT ON COLUMN nexent.market_review_t.entity_type IS 'Entity type: agent / skill / mcp / recipe / expert';
COMMENT ON COLUMN nexent.market_review_t.entity_id IS 'Entity ID (e.g. agent_repository_id)';
COMMENT ON COLUMN nexent.market_review_t.rating IS 'Rating 1-5 stars';
COMMENT ON COLUMN nexent.market_review_t.parent_review_id IS 'Parent review ID for threaded replies';
COMMENT ON COLUMN nexent.market_review_t.status IS 'Review status: visible / hidden / pending';

CREATE UNIQUE INDEX IF NOT EXISTS uq_market_review_entity_user
    ON nexent.market_review_t (entity_type, entity_id, user_id)
    WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS ix_market_review_entity
    ON nexent.market_review_t (entity_type, entity_id, review_id DESC)
    WHERE delete_flag = 'N' AND status = 'visible';

-- ============================================================================
-- 4) market_rating_summary_t — aggregated rating summary per entity
-- ============================================================================
CREATE TABLE IF NOT EXISTS nexent.market_rating_summary_t (
    entity_type       VARCHAR(20)  NOT NULL,
    entity_id         BIGINT       NOT NULL,
    avg_rating        DECIMAL(3,2) DEFAULT 0.00,
    rating_count      INT          DEFAULT 0,
    review_count      INT          DEFAULT 0,
    updated_at        TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (entity_type, entity_id)
);

COMMENT ON TABLE  nexent.market_rating_summary_t IS 'Aggregated rating summary per market entity';
COMMENT ON COLUMN nexent.market_rating_summary_t.avg_rating IS 'Average rating (0.00-5.00)';
COMMENT ON COLUMN nexent.market_rating_summary_t.rating_count IS 'Total number of ratings';
COMMENT ON COLUMN nexent.market_rating_summary_t.review_count IS 'Total number of visible reviews with comments';

COMMIT;
