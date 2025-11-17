-- 1. 为knowledge_record_t表添加knowledge_sources列
ALTER TABLE nexent.knowledge_record_t
ADD COLUMN IF NOT EXISTS "knowledge_sources" varchar(100) COLLATE "pg_catalog"."default";

-- 添加列注释
COMMENT ON COLUMN nexent.knowledge_record_t."knowledge_sources" IS 'Knowledge base sources';


-- 2. 创建tenant_config_t表
CREATE TABLE IF NOT EXISTS nexent.tenant_config_t (
    tenant_config_id SERIAL PRIMARY KEY NOT NULL,
    tenant_id VARCHAR(100),
    user_id VARCHAR(100),
    value_type VARCHAR(100),
    config_key VARCHAR(100),
    config_value VARCHAR(10000),
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

-- 添加表注释
COMMENT ON TABLE nexent.tenant_config_t IS 'Tenant configuration information table';

-- 添加列注释
COMMENT ON COLUMN nexent.tenant_config_t.tenant_config_id IS 'ID';
COMMENT ON COLUMN nexent.tenant_config_t.tenant_id IS 'Tenant ID';
COMMENT ON COLUMN nexent.tenant_config_t.user_id IS 'User ID';
COMMENT ON COLUMN nexent.tenant_config_t.value_type IS 'Value type';
COMMENT ON COLUMN nexent.tenant_config_t.config_key IS 'Config key';
COMMENT ON COLUMN nexent.tenant_config_t.config_value IS 'Config value';
COMMENT ON COLUMN nexent.tenant_config_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.tenant_config_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.tenant_config_t.created_by IS 'Creator';
COMMENT ON COLUMN nexent.tenant_config_t.updated_by IS 'Updater';
COMMENT ON COLUMN nexent.tenant_config_t.delete_flag IS 'Whether it is deleted. Optional values: Y/N';

-- 创建更新update_time的函数
CREATE OR REPLACE FUNCTION update_tenant_config_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 添加函数注释
COMMENT ON FUNCTION update_tenant_config_update_time() IS 'Function to update the update_time column when a record in tenant_config_t is updated';

-- 创建触发器
CREATE TRIGGER update_tenant_config_update_time_trigger
BEFORE UPDATE ON nexent.tenant_config_t
FOR EACH ROW
EXECUTE FUNCTION update_tenant_config_update_time();

-- 添加触发器注释
COMMENT ON TRIGGER update_tenant_config_update_time_trigger ON nexent.tenant_config_t
IS 'Trigger to call update_tenant_config_update_time function before each update on tenant_config_t table';

ALTER TABLE model_record_t
ADD COLUMN tenant_id varchar(100) COLLATE pg_catalog.default DEFAULT 'tenant_id';
COMMENT ON COLUMN "model_record_t"."tenant_id" IS 'Tenant ID for filtering';