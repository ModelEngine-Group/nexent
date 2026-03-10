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

-- Create unique index on access_key to ensure uniqueness
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_token_info_access_key ON nexent.user_token_info_t(access_key) WHERE delete_flag = 'N';

-- Create index on user_id for query performance
CREATE INDEX IF NOT EXISTS idx_user_token_info_user_id ON nexent.user_token_info_t(user_id) WHERE delete_flag = 'N';

-- Create a function to update the update_time column
CREATE OR REPLACE FUNCTION update_user_token_info_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Add comment to the function
COMMENT ON FUNCTION update_user_token_info_update_time() IS 'Function to update the update_time column when a record in user_token_info_t is updated';

-- Create a trigger to call the function before each update
DROP TRIGGER IF EXISTS update_user_token_info_update_time_trigger ON nexent.user_token_info_t;
CREATE TRIGGER update_user_token_info_update_time_trigger
BEFORE UPDATE ON nexent.user_token_info_t
FOR EACH ROW
EXECUTE FUNCTION update_user_token_info_update_time();

-- Add comment to the trigger
COMMENT ON TRIGGER update_user_token_info_update_time_trigger ON nexent.user_token_info_t IS 'Trigger to call update_user_token_info_update_time function before each update on user_token_info_t table';


-- Create the user_token_usage_log_t table in the nexent schema
CREATE TABLE IF NOT EXISTS nexent.user_token_usage_log_t (
    token_usage_id SERIAL4 PRIMARY KEY NOT NULL,
    token_id INT4 NOT NULL,
    call_function_name VARCHAR(100),
    related_id INT4,
    meta_data JSONB,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100)
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
COMMENT ON COLUMN nexent.user_token_usage_log_t.created_by IS 'Creator ID, audit field';

-- Create index on token_id for query performance
CREATE INDEX IF NOT EXISTS idx_user_token_usage_log_token_id ON nexent.user_token_usage_log_t(token_id);

-- Create index on call_function_name for query performance
CREATE INDEX IF NOT EXISTS idx_user_token_usage_log_function_name ON nexent.user_token_usage_log_t(call_function_name);

-- Add foreign key constraint
ALTER TABLE nexent.user_token_usage_log_t
ADD CONSTRAINT fk_user_token_usage_log_token_id
FOREIGN KEY (token_id)
REFERENCES nexent.user_token_info_t(token_id)
ON DELETE CASCADE;


-- Migration: Remove partner_mapping_id_t table for northbound conversation ID mapping
-- Date: 2026-03-10
-- Description: Remove the external-internal conversation ID mapping table as northbound APIs now use internal conversation IDs directly
-- Note: This table is no longer needed after refactoring northbound authentication logic

-- Drop the partner_mapping_id_t table if it exists
DROP TABLE IF EXISTS nexent.partner_mapping_id_t CASCADE;

-- Drop the associated sequence if it exists
DROP SEQUENCE IF EXISTS nexent.partner_mapping_id_t_id_seq;
