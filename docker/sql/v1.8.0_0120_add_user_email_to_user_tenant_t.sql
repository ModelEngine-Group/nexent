-- Add user_email column to user_tenant_t table
-- Migration: v1.8.1_0120_add_user_email_to_user_tenant_t

-- Add user_email column to user_tenant_t table
ALTER TABLE nexent.user_tenant_t
ADD COLUMN user_email VARCHAR(255);

-- Add comment to the new column
COMMENT ON COLUMN nexent.user_tenant_t.user_email IS 'User email address';

-- Create index on user_email for faster queries (optional)
CREATE INDEX IF NOT EXISTS idx_user_tenant_t_user_email
ON nexent.user_tenant_t(user_email);
