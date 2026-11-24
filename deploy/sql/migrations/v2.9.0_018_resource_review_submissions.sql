-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Run with submission and decision writers stopped; migrate legacy pending submissions atomically.
BEGIN;
LOCK TABLE nexent.ag_agent_repository_t, nexent.ag_skill_repository_t, nexent.mcp_market_record_t IN ACCESS EXCLUSIVE MODE;
CREATE TABLE IF NOT EXISTS nexent.ag_resource_review_t (
 review_id BIGSERIAL PRIMARY KEY,
 tenant_id VARCHAR(100) NOT NULL,
 resource_type VARCHAR(30) NOT NULL CHECK (resource_type IN ('agent','skill','mcp')),
 source_resource_id BIGINT NOT NULL,
 version_no INTEGER,
 repository_id BIGINT,
 submitted_user_id VARCHAR(100) NOT NULL,
 submitted_at TIMESTAMPTZ NOT NULL,
 submit_description TEXT,
 resource_snapshot JSONB NOT NULL,
 review_status VARCHAR(30) NOT NULL DEFAULT 'pending_review' CHECK (review_status IN ('pending_review','approved','rejected')),
 review_comment TEXT,
 reviewed_by VARCHAR(100),
 reviewed_at TIMESTAMPTZ,
 created_by VARCHAR(100), create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 updated_by VARCHAR(100), update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 delete_flag VARCHAR(1) NOT NULL DEFAULT 'N',
 CHECK ((resource_type = 'agent' AND version_no IS NOT NULL AND version_no >= 0)
     OR (resource_type <> 'agent' AND version_no IS NULL))
);
COMMENT ON TABLE nexent.ag_resource_review_t IS 'Immutable submitted resource snapshots and final decisions; publishing occurs only on approval';
COMMENT ON COLUMN nexent.ag_resource_review_t.review_id IS 'Independent submission identifier';
COMMENT ON COLUMN nexent.ag_resource_review_t.tenant_id IS 'Resource owner tenant';
COMMENT ON COLUMN nexent.ag_resource_review_t.resource_type IS 'Resource kind: agent, skill or mcp';
COMMENT ON COLUMN nexent.ag_resource_review_t.source_resource_id IS 'Original local resource identifier';
COMMENT ON COLUMN nexent.ag_resource_review_t.version_no IS 'Agent version; NULL for Skill and MCP';
COMMENT ON COLUMN nexent.ag_resource_review_t.repository_id IS 'Published listing ID; nullable before initial approval';
COMMENT ON COLUMN nexent.ag_resource_review_t.submitted_user_id IS 'Internal submitter ID; legacy pending rows use submission evidence';
COMMENT ON COLUMN nexent.ag_resource_review_t.submitted_at IS 'Submission instant; legacy pending rows use original update time interpreted as UTC';
COMMENT ON COLUMN nexent.ag_resource_review_t.submit_description IS 'Submission listing description, migrated from legacy content';
COMMENT ON COLUMN nexent.ag_resource_review_t.resource_snapshot IS 'Schema-versioned immutable publication payload';
COMMENT ON COLUMN nexent.ag_resource_review_t.review_status IS 'Independent submission state: pending_review, approved or rejected';
COMMENT ON COLUMN nexent.ag_resource_review_t.review_comment IS 'Final review opinion';
COMMENT ON COLUMN nexent.ag_resource_review_t.reviewed_by IS 'Decision actor internal ID';
COMMENT ON COLUMN nexent.ag_resource_review_t.reviewed_at IS 'Decision instant; publication instant for approvals';
COMMENT ON COLUMN nexent.ag_resource_review_t.created_by IS 'Creating actor';
COMMENT ON COLUMN nexent.ag_resource_review_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.ag_resource_review_t.updated_by IS 'Last updating actor';
COMMENT ON COLUMN nexent.ag_resource_review_t.update_time IS 'Last update time';
COMMENT ON COLUMN nexent.ag_resource_review_t.delete_flag IS 'Soft deletion marker N or Y';

SET LOCAL nexent.import_legacy_reviews = 'on';
\ir v2.9.0_017_review_preflight.sql

-- Preserve notification IDs and receivers, including their read flags.
UPDATE nexent.notification_t n
SET resource_type='resource_review', unique_id=r.review_id,
    details=coalesce(n.details,'{}'::jsonb) ||
        jsonb_build_object('resource_type',r.resource_type,'review_id',r.review_id::text),
    is_active=(r.review_status='pending_review')
FROM nexent.ag_resource_review_t r
WHERE r.created_by='review_migration' AND r.delete_flag='N'
  AND n.event_type='repository_review_pending' AND n.is_active AND n.delete_flag='N'
  AND n.tenant_id=r.tenant_id AND n.resource_type=r.resource_type || '_repository'
  AND n.unique_id=r.repository_id;
CREATE INDEX IF NOT EXISTS idx_resource_review_mine ON nexent.ag_resource_review_t
 (tenant_id,submitted_user_id,review_status,submitted_at DESC,review_id DESC) WHERE delete_flag='N';
CREATE INDEX IF NOT EXISTS idx_resource_review_tenant ON nexent.ag_resource_review_t
 (tenant_id,review_status,submitted_at DESC,review_id DESC) WHERE delete_flag='N';
CREATE INDEX IF NOT EXISTS idx_resource_review_source ON nexent.ag_resource_review_t
 (resource_type,tenant_id,source_resource_id,review_status) WHERE delete_flag='N';
CREATE INDEX IF NOT EXISTS idx_resource_review_publication ON nexent.ag_resource_review_t
 (resource_type,tenant_id,repository_id,review_status,reviewed_at DESC) WHERE delete_flag='N';

COMMIT;
