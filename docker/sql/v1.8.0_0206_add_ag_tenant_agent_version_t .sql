-- 步骤 1：添加 nullable 的 version_no 字段（不设默认值，让显式赋值）
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS version_no INTEGER NULL;

ALTER TABLE nexent.ag_tool_instance_t
ADD COLUMN IF NOT EXISTS version_no INTEGER NULL;

ALTER TABLE nexent.ag_agent_relation_t
ADD COLUMN IF NOT EXISTS version_no INTEGER NULL;

-- 步骤 2：更新所有历史数据的 version_no 为 0
UPDATE nexent.ag_tenant_agent_t SET version_no = 0 WHERE version_no IS NULL;
UPDATE nexent.ag_tool_instance_t SET version_no = 0 WHERE version_no IS NULL;
UPDATE nexent.ag_agent_relation_t SET version_no = 0 WHERE version_no IS NULL;

-- 步骤 3：将字段设为 NOT NULL，并设置默认值 0
ALTER TABLE nexent.ag_tenant_agent_t ALTER COLUMN version_no SET NOT NULL;
ALTER TABLE nexent.ag_tenant_agent_t ALTER COLUMN version_no SET DEFAULT 0;

ALTER TABLE nexent.ag_tool_instance_t ALTER COLUMN version_no SET NOT NULL;
ALTER TABLE nexent.ag_tool_instance_t ALTER COLUMN version_no SET DEFAULT 0;

ALTER TABLE nexent.ag_agent_relation_t ALTER COLUMN version_no SET NOT NULL;
ALTER TABLE nexent.ag_agent_relation_t ALTER COLUMN version_no SET DEFAULT 0;

-- 步骤 4：为 ag_tenant_agent_t 添加 current_version_no 字段
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS current_version_no INTEGER NULL;

-- 步骤5：修改主键
ALTER TABLE nexent.ag_tenant_agent_t DROP CONSTRAINT ag_tenant_agent_t_pkey;
ALTER TABLE nexent.ag_tenant_agent_t ADD CONSTRAINT ag_tenant_agent_t_pkey PRIMARY KEY (agent_id, version_no);

ALTER TABLE nexent.ag_tool_instance_t DROP CONSTRAINT ag_tool_instance_t_pkey;
ALTER TABLE nexent.ag_tool_instance_t ADD CONSTRAINT ag_tool_instance_t_pkey PRIMARY KEY (tool_instance_id, version_no);

ALTER TABLE nexent.ag_agent_relation_t DROP CONSTRAINT ag_agent_relation_t_pkey;
ALTER TABLE nexent.ag_agent_relation_t ADD CONSTRAINT ag_agent_relation_t_pkey PRIMARY KEY (relation_id, version_no);

-- 步骤6：新增agent版本管理表
CREATE TABLE IF NOT EXISTS nexent.ag_tenant_agent_version_t (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    agent_id INTEGER NOT NULL,
    version_no INTEGER NOT NULL,
    version_name VARCHAR(100),                    -- 用户自定义版本名称
    release_note TEXT,                            -- 发布备注

    source_version_no INTEGER NULL,               -- 来源版本号（回滚时记录）
    source_type VARCHAR(30) NULL,                 -- 来源类型：NORMAL(正常发布) / ROLLBACK(回滚产生)

    status VARCHAR(30) DEFAULT 'RELEASED',        -- 版本状态：RELEASED / DISABLED / ARCHIVED

    created_by VARCHAR(100) NOT NULL,
    create_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100),
    update_time TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE nexent.ag_tenant_agent_version_t OWNER TO "root";

-- 步骤 7：添加COMMENT
COMMENT ON COLUMN nexent.ag_tenant_agent_t.version_no IS 'Version number. 0 = draft/editing state, >=1 = published snapshot';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.current_version_no IS 'Current published version number. NULL means no version published yet';
COMMENT ON COLUMN nexent.ag_tool_instance_t.version_no IS 'Version number. 0 = draft/editing state, >=1 = published snapshot';
COMMENT ON COLUMN nexent.ag_agent_relation_t.version_no IS 'Version number. 0 = draft/editing state, >=1 = published snapshot';

COMMENT ON TABLE nexent.ag_tenant_agent_version_t IS 'Agent version metadata table. Stores version info, release notes, and version lineage.';

COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.id IS 'Primary key, auto-increment';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.tenant_id IS 'Tenant ID';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.agent_id IS 'Agent ID';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.version_no IS 'Version number, starts from 1. Does not include 0 (draft)';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.version_name IS 'User-defined version name for display (e.g., "Stable v2.1", "Hotfix-001"). NULL means use version_no as display.';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.release_note IS 'Release notes / publish remarks';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.source_version_no IS 'Source version number. If this version is a rollback, record the source version number.';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.source_type IS 'Source type: NORMAL (normal publish) / ROLLBACK (rollback and republish).';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.status IS 'Version status: RELEASED / DISABLED / ARCHIVED';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.created_by IS 'User who published this version';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.create_time IS 'Version creation timestamp';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.updated_by IS 'Last user who updated this version';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.update_time IS 'Last update timestamp';
COMMENT ON COLUMN nexent.ag_tenant_agent_version_t.delete_flag IS 'Soft delete flag: Y/N';
