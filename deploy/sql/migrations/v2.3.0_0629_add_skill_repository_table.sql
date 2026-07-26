-- Migration: Add ag_skill_repository_t table
-- Date: 2026-06-29
-- Description: Skill marketplace repository for frozen installable skill snapshots.

SET search_path TO nexent;

CREATE SEQUENCE IF NOT EXISTS nexent.ag_skill_repository_t_skill_repository_id_seq;

CREATE TABLE IF NOT EXISTS nexent.ag_skill_repository_t (
    skill_repository_id BIGINT NOT NULL DEFAULT nextval('nexent.ag_skill_repository_t_skill_repository_id_seq'),
    publisher_tenant_id VARCHAR(100) NOT NULL,
    publisher_user_id VARCHAR(100) NOT NULL,
    skill_id INTEGER NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    source VARCHAR(30),
    submitted_by VARCHAR(100),
    category_id INTEGER,
    tags TEXT[],
    icon VARCHAR(100),
    downloads INTEGER DEFAULT 0,
    skill_info_json JSONB NOT NULL,
    skill_zip_base64 TEXT NOT NULL,
    status VARCHAR(30) DEFAULT 'not_shared',
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N',
    CONSTRAINT ag_skill_repository_t_pkey PRIMARY KEY (skill_repository_id)
);

ALTER SEQUENCE nexent.ag_skill_repository_t_skill_repository_id_seq
    OWNED BY nexent.ag_skill_repository_t.skill_repository_id;

ALTER TABLE nexent.ag_skill_repository_t OWNER TO root;

ALTER TABLE nexent.ag_skill_repository_t
  ADD COLUMN IF NOT EXISTS submitted_by VARCHAR(100),
  ADD COLUMN IF NOT EXISTS icon VARCHAR(100),
  ADD COLUMN IF NOT EXISTS downloads INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS skill_zip_base64 TEXT;

COMMENT ON TABLE nexent.ag_skill_repository_t IS 'Skill marketplace repository for frozen installable skill snapshots';
COMMENT ON COLUMN nexent.ag_skill_repository_t.skill_repository_id IS 'Skill repository listing ID, unique primary key';
COMMENT ON COLUMN nexent.ag_skill_repository_t.publisher_tenant_id IS 'Publisher tenant ID';
COMMENT ON COLUMN nexent.ag_skill_repository_t.publisher_user_id IS 'Publisher user ID';
COMMENT ON COLUMN nexent.ag_skill_repository_t.skill_id IS 'Source skill ID from ag_skill_info_t; unique when active (delete_flag = N)';
COMMENT ON COLUMN nexent.ag_skill_repository_t.name IS 'Skill name for display and search';
COMMENT ON COLUMN nexent.ag_skill_repository_t.description IS 'Skill description';
COMMENT ON COLUMN nexent.ag_skill_repository_t.source IS 'Skill source';
COMMENT ON COLUMN nexent.ag_skill_repository_t.submitted_by IS 'Submitter email when listing enters pending_review';
COMMENT ON COLUMN nexent.ag_skill_repository_t.category_id IS 'Optional marketplace category ID';
COMMENT ON COLUMN nexent.ag_skill_repository_t.tags IS 'Marketplace tags';
COMMENT ON COLUMN nexent.ag_skill_repository_t.icon IS 'Marketplace card icon (emoji or URL)';
COMMENT ON COLUMN nexent.ag_skill_repository_t.downloads IS 'Marketplace install count for card display';
COMMENT ON COLUMN nexent.ag_skill_repository_t.skill_info_json IS 'Frozen skill metadata snapshot';
COMMENT ON COLUMN nexent.ag_skill_repository_t.skill_zip_base64 IS 'Frozen skill ZIP payload encoded as base64';
COMMENT ON COLUMN nexent.ag_skill_repository_t.status IS 'Listing status: not_shared / pending_review / rejected / shared';
COMMENT ON COLUMN nexent.ag_skill_repository_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.ag_skill_repository_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.ag_skill_repository_t.created_by IS 'Creator ID';
COMMENT ON COLUMN nexent.ag_skill_repository_t.updated_by IS 'Updater ID';
COMMENT ON COLUMN nexent.ag_skill_repository_t.delete_flag IS 'Soft delete flag: Y/N';

CREATE UNIQUE INDEX IF NOT EXISTS uq_skill_repository_skill_active
    ON nexent.ag_skill_repository_t (skill_id)
    WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS idx_skill_repository_publisher_delete
    ON nexent.ag_skill_repository_t (publisher_tenant_id, delete_flag);

CREATE INDEX IF NOT EXISTS idx_skill_repository_status_delete
    ON nexent.ag_skill_repository_t (status, delete_flag);

CREATE INDEX IF NOT EXISTS idx_skill_repository_name_delete
    ON nexent.ag_skill_repository_t (name, delete_flag);

CREATE INDEX IF NOT EXISTS idx_skill_repository_tags_gin
    ON nexent.ag_skill_repository_t USING GIN (tags);

CREATE OR REPLACE FUNCTION update_ag_skill_repository_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_ag_skill_repository_update_time() IS 'Auto-update update_time for ag_skill_repository_t';

DROP TRIGGER IF EXISTS update_ag_skill_repository_update_time_trigger ON nexent.ag_skill_repository_t;
CREATE TRIGGER update_ag_skill_repository_update_time_trigger
BEFORE UPDATE ON nexent.ag_skill_repository_t
FOR EACH ROW
EXECUTE FUNCTION update_ag_skill_repository_update_time();

COMMENT ON TRIGGER update_ag_skill_repository_update_time_trigger
ON nexent.ag_skill_repository_t IS 'Trigger to maintain update_time';
