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
COMMENT ON COLUMN nexent.ag_resource_review_t.submitted_user_id IS 'Internal submitter ID; migrated pending rows use original source creator';
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

DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM nexent.ag_agent_repository_t r LEFT JOIN nexent.ag_tenant_agent_t s ON s.agent_id=r.agent_id AND s.tenant_id=r.publisher_tenant_id AND s.delete_flag <> 'Y' AND s.version_no=r.version_no
 WHERE r.status='pending_review' AND r.delete_flag <> 'Y'
 AND (s.agent_id IS NULL OR NULLIF(s.created_by,'') IS NULL OR r.update_time IS NULL OR NOT (r.agent_info_json IS NOT NULL AND r.agent_info_json ?& ARRAY['agent_id','agent_info','mcp_info'])))
 THEN RAISE EXCEPTION 'Pending agent migration has missing source, creator, time or snapshot; inspect and repair before retry'; END IF;
END $$;
INSERT INTO nexent.ag_resource_review_t
 (tenant_id,resource_type,source_resource_id,version_no,repository_id,submitted_user_id,submitted_at,
  submit_description,resource_snapshot,review_status,created_by,updated_by,delete_flag)
SELECT r.publisher_tenant_id,'agent',r.agent_id,r.version_no,r.agent_repository_id,s.created_by,
 r.update_time AT TIME ZONE 'UTC',r.content,
 jsonb_build_object('schema_version',1,'payload',to_jsonb(r)),
 'pending_review','review_migration','review_migration','N'
FROM nexent.ag_agent_repository_t r JOIN nexent.ag_tenant_agent_t s ON s.agent_id=r.agent_id AND s.tenant_id=r.publisher_tenant_id AND s.delete_flag <> 'Y' AND s.version_no=r.version_no
WHERE r.status='pending_review' AND r.delete_flag <> 'Y'
AND NOT EXISTS (SELECT 1 FROM nexent.ag_resource_review_t a WHERE a.resource_type='agent'
 AND a.tenant_id=r.publisher_tenant_id AND a.repository_id=r.agent_repository_id AND a.delete_flag='N');

DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM nexent.ag_skill_repository_t r LEFT JOIN nexent.ag_skill_info_t s ON s.skill_id=r.skill_id AND s.tenant_id=r.publisher_tenant_id AND s.delete_flag <> 'Y'
 WHERE r.status='pending_review' AND r.delete_flag <> 'Y'
 AND (s.skill_id IS NULL OR NULLIF(s.created_by,'') IS NULL OR r.update_time IS NULL OR NOT (r.skill_info_json IS NOT NULL AND r.skill_zip_base64 IS NOT NULL AND length(decode(r.skill_zip_base64,'base64')) >= 22)))
 THEN RAISE EXCEPTION 'Pending skill migration has missing source, creator, time or snapshot; inspect and repair before retry'; END IF;
END $$;
INSERT INTO nexent.ag_resource_review_t
 (tenant_id,resource_type,source_resource_id,version_no,repository_id,submitted_user_id,submitted_at,
  submit_description,resource_snapshot,review_status,created_by,updated_by,delete_flag)
SELECT r.publisher_tenant_id,'skill',r.skill_id,NULL,r.skill_repository_id,s.created_by,
 r.update_time AT TIME ZONE 'UTC',r.content,
 jsonb_build_object('schema_version',1,'payload',to_jsonb(r)),
 'pending_review','review_migration','review_migration','N'
FROM nexent.ag_skill_repository_t r JOIN nexent.ag_skill_info_t s ON s.skill_id=r.skill_id AND s.tenant_id=r.publisher_tenant_id AND s.delete_flag <> 'Y'
WHERE r.status='pending_review' AND r.delete_flag <> 'Y'
AND NOT EXISTS (SELECT 1 FROM nexent.ag_resource_review_t a WHERE a.resource_type='skill'
 AND a.tenant_id=r.publisher_tenant_id AND a.repository_id=r.skill_repository_id AND a.delete_flag='N');

DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM nexent.mcp_market_record_t r LEFT JOIN nexent.mcp_record_t s ON s.mcp_id=r.source_mcp_id AND s.tenant_id=r.tenant_id AND s.delete_flag <> 'Y'
 WHERE r.review_status='pending_review' AND r.delete_flag <> 'Y'
 AND (s.mcp_id IS NULL OR NULLIF(s.created_by,'') IS NULL OR r.update_time IS NULL OR NOT (r.mcp_name IS NOT NULL)))
 THEN RAISE EXCEPTION 'Pending mcp migration has missing source, creator, time or snapshot; inspect and repair before retry'; END IF;
END $$;
INSERT INTO nexent.ag_resource_review_t
 (tenant_id,resource_type,source_resource_id,version_no,repository_id,submitted_user_id,submitted_at,
  submit_description,resource_snapshot,review_status,created_by,updated_by,delete_flag)
SELECT r.tenant_id,'mcp',r.source_mcp_id,NULL,r.market_id,s.created_by,
 r.update_time AT TIME ZONE 'UTC',r.content,
 jsonb_build_object('schema_version',1,'payload',to_jsonb(r)),
 'pending_review','review_migration','review_migration','N'
FROM nexent.mcp_market_record_t r JOIN nexent.mcp_record_t s ON s.mcp_id=r.source_mcp_id AND s.tenant_id=r.tenant_id AND s.delete_flag <> 'Y'
WHERE r.review_status='pending_review' AND r.delete_flag <> 'Y'
AND NOT EXISTS (SELECT 1 FROM nexent.ag_resource_review_t a WHERE a.resource_type='mcp'
 AND a.tenant_id=r.tenant_id AND a.repository_id=r.market_id AND a.delete_flag='N');

DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM nexent.ag_resource_review_t WHERE review_status='pending_review' AND delete_flag='N'
 GROUP BY tenant_id,resource_type,source_resource_id HAVING count(*)>1)
 THEN RAISE EXCEPTION 'Multiple pending applications for one source; reconcile before switching readers'; END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_resource_review_mine ON nexent.ag_resource_review_t
 (tenant_id,submitted_user_id,review_status,submitted_at DESC,review_id DESC) WHERE delete_flag='N';
CREATE INDEX IF NOT EXISTS idx_resource_review_tenant ON nexent.ag_resource_review_t
 (tenant_id,review_status,submitted_at DESC,review_id DESC) WHERE delete_flag='N';
CREATE INDEX IF NOT EXISTS idx_resource_review_source ON nexent.ag_resource_review_t
 (resource_type,tenant_id,source_resource_id,review_status) WHERE delete_flag='N';
CREATE INDEX IF NOT EXISTS idx_resource_review_publication ON nexent.ag_resource_review_t
 (resource_type,tenant_id,repository_id,review_status,reviewed_at DESC) WHERE delete_flag='N';

COMMIT;
