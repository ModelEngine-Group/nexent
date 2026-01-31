-- Add user_email column to user_tenant_t table
ALTER TABLE nexent.user_tenant_t
ADD COLUMN user_email VARCHAR(255);

-- Add comment to the new column
COMMENT ON COLUMN nexent.user_tenant_t.user_email IS 'User email address';

-- Create index on user_email for faster queries (optional)
CREATE INDEX IF NOT EXISTS idx_user_tenant_t_user_email
ON nexent.user_tenant_t(user_email);


INSERT INTO nexent.user_tenant_t (user_id, tenant_id, user_role, user_email, created_by, updated_by)
VALUES ('user_id', 'tenant_id', 'SPEED', NULL, 'system', 'system')
ON CONFLICT (user_id, tenant_id) DO NOTHING;
