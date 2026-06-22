-- Migration: Add selected_agent_version_no to ag_agent_relation_t
-- Date: 2026-06-09
-- Description: Pin child agent version on parent-child relations at publish time.

SET search_path TO nexent;

BEGIN;

ALTER TABLE nexent.ag_agent_relation_t
    ADD COLUMN IF NOT EXISTS selected_agent_version_no INTEGER;

COMMENT ON COLUMN nexent.ag_agent_relation_t.selected_agent_version_no IS
    'Pinned version of selected_agent_id. NULL = use child current published version at runtime (legacy/draft).';

COMMIT;
