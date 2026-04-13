-- Create user OAuth account table for third-party login (GitHub, WeChat, etc.)
CREATE TABLE IF NOT EXISTS nexent.user_oauth_account_t (
    oauth_account_id SERIAL PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL,
    provider VARCHAR(30) NOT NULL,
    provider_user_id VARCHAR(200) NOT NULL,
    provider_email VARCHAR(255),
    provider_username VARCHAR(200),
    tenant_id VARCHAR(100),
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag CHAR(1) DEFAULT 'N',
    CONSTRAINT uq_oauth_provider_user UNIQUE (provider, provider_user_id)
);

ALTER TABLE nexent.user_oauth_account_t OWNER TO "root";

-- Create a function to update the update_time column
CREATE OR REPLACE FUNCTION update_user_oauth_account_t_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create a trigger to call the function before each update
CREATE TRIGGER update_user_oauth_account_t_update_time_trigger
BEFORE UPDATE ON nexent.user_oauth_account_t
FOR EACH ROW
EXECUTE FUNCTION update_user_oauth_account_t_update_time();

-- Add comments
COMMENT ON TABLE nexent.user_oauth_account_t IS 'User OAuth account table - third-party login bindings';
COMMENT ON COLUMN nexent.user_oauth_account_t.oauth_account_id IS 'OAuth account ID, primary key';
COMMENT ON COLUMN nexent.user_oauth_account_t.user_id IS 'Nexent user ID (Supabase UUID)';
COMMENT ON COLUMN nexent.user_oauth_account_t.provider IS 'OAuth provider name: github, wechat';
COMMENT ON COLUMN nexent.user_oauth_account_t.provider_user_id IS 'User ID from the OAuth provider';
COMMENT ON COLUMN nexent.user_oauth_account_t.provider_email IS 'Email from the OAuth provider';
COMMENT ON COLUMN nexent.user_oauth_account_t.provider_username IS 'Display name from the OAuth provider';
COMMENT ON COLUMN nexent.user_oauth_account_t.tenant_id IS 'Tenant ID at time of linking';
COMMENT ON COLUMN nexent.user_oauth_account_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.user_oauth_account_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.user_oauth_account_t.created_by IS 'Creator';
COMMENT ON COLUMN nexent.user_oauth_account_t.updated_by IS 'Updater';
COMMENT ON COLUMN nexent.user_oauth_account_t.delete_flag IS 'Whether it is deleted. Optional values: Y/N';

-- Create index for user_id queries
CREATE INDEX IF NOT EXISTS idx_user_oauth_account_t_user_id
ON nexent.user_oauth_account_t (user_id)
WHERE delete_flag = 'N';
