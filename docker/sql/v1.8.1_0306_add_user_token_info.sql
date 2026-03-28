-- Migration: Add user_token_info_t and user_token_usage_log_t tables
-- Date: 2026-03-06
-- Description: Create user token (AK/SK) management tables with audit fields

-- Set search path to nexent schema
SET search_path TO nexent;

-- Create the user_token_info_t table in the nexent schema
CREATE TABLE IF NOT EXISTS nexent.user_token_info_t (
    token_id SERIAL4 PRIMARY KEY NOT NULL,
    access_key VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE "user_token_info_t" OWNER TO "root";

-- Add comment to the table
COMMENT ON TABLE nexent.user_token_info_t IS 'User token (AK/SK) information table';

-- Add comments to the columns
COMMENT ON COLUMN nexent.user_token_info_t.token_id IS 'Token ID, unique primary key';
COMMENT ON COLUMN nexent.user_token_info_t.access_key IS 'Access Key (AK)';
COMMENT ON COLUMN nexent.user_token_info_t.user_id IS 'User ID who owns this token';
COMMENT ON COLUMN nexent.user_token_info_t.create_time IS 'Creation time, audit field';
COMMENT ON COLUMN nexent.user_token_info_t.update_time IS 'Update time, audit field';
COMMENT ON COLUMN nexent.user_token_info_t.created_by IS 'Creator ID, audit field';
COMMENT ON COLUMN nexent.user_token_info_t.updated_by IS 'Last updater ID, audit field';
COMMENT ON COLUMN nexent.user_token_info_t.delete_flag IS 'Soft delete flag, Y means deleted';


-- Create the user_token_usage_log_t table in the nexent schema
CREATE TABLE IF NOT EXISTS nexent.user_token_usage_log_t (
    token_usage_id SERIAL4 PRIMARY KEY NOT NULL,
    token_id INT4 NOT NULL,
    call_function_name VARCHAR(100),
    related_id INT4,
    meta_data JSONB,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

ALTER TABLE "user_token_usage_log_t" OWNER TO "root";

-- Add comment to the table
COMMENT ON TABLE nexent.user_token_usage_log_t IS 'User token usage log table';

-- Add comments to the columns
COMMENT ON COLUMN nexent.user_token_usage_log_t.token_usage_id IS 'Token usage log ID, unique primary key';
COMMENT ON COLUMN nexent.user_token_usage_log_t.token_id IS 'Foreign key to user_token_info_t.token_id';
COMMENT ON COLUMN nexent.user_token_usage_log_t.call_function_name IS 'API function name being called';
COMMENT ON COLUMN nexent.user_token_usage_log_t.related_id IS 'Related resource ID (e.g., conversation_id)';
COMMENT ON COLUMN nexent.user_token_usage_log_t.meta_data IS 'Additional metadata for this usage log entry, stored as JSON';
COMMENT ON COLUMN nexent.user_token_usage_log_t.create_time IS 'Creation time, audit field';
COMMENT ON COLUMN nexent.user_token_usage_log_t.update_time IS 'Update time, audit field';
COMMENT ON COLUMN nexent.user_token_usage_log_t.created_by IS 'Creator ID, audit field';
COMMENT ON COLUMN nexent.user_token_usage_log_t.updated_by IS 'Last updater ID, audit field';
COMMENT ON COLUMN nexent.user_token_usage_log_t.delete_flag IS 'Soft delete flag, Y means deleted';

-- Migration: Remove partner_mapping_id_t table for northbound conversation ID mapping
-- Date: 2026-03-10
-- Description: Remove the external-internal conversation ID mapping table as northbound APIs now use internal conversation IDs directly
-- Note: This table is no longer needed after refactoring northbound authentication logic

-- Drop the partner_mapping_id_t table if it exists
DROP TABLE IF EXISTS nexent.partner_mapping_id_t CASCADE;

-- Drop the associated sequence if it exists
DROP SEQUENCE IF EXISTS nexent.partner_mapping_id_t_id_seq;
