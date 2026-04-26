-- Add access_token field to user_oauth_account_t for SSO auto-login support
-- This allows Nexent to store the OAuth access token and use it for SSO

ALTER TABLE nexent.user_oauth_account_t
ADD COLUMN IF NOT EXISTS access_token TEXT;

ALTER TABLE nexent.user_oauth_account_t
ADD COLUMN IF NOT EXISTS token_expires_at TIMESTAMP WITHOUT TIME ZONE;

-- Add comments
COMMENT ON COLUMN nexent.user_oauth_account_t.access_token IS 'OAuth access token for SSO auto-login';
COMMENT ON COLUMN nexent.user_oauth_account_t.token_expires_at IS 'Access token expiration time';
