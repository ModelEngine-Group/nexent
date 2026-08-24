-- Add indexes used by tenant API key management and usage aggregation.
SET search_path TO nexent;

CREATE UNIQUE INDEX IF NOT EXISTS ux_user_token_access_key
    ON nexent.user_token_info_t (access_key);

CREATE INDEX IF NOT EXISTS ix_user_token_user_active
    ON nexent.user_token_info_t (user_id, delete_flag);

-- Keep only active usage rows in the aggregation index. Including the
-- non-null primary key allows count(token_usage_id) and max(create_time) to
-- use an index-only scan when PostgreSQL visibility permits it.
CREATE INDEX IF NOT EXISTS ix_user_token_usage_active_token_time
    ON nexent.user_token_usage_log_t (token_id, create_time DESC)
    INCLUDE (token_usage_id)
    WHERE delete_flag = 'N';

-- Remove the superseded full-history index after its replacement exists.
DROP INDEX IF EXISTS nexent.ix_user_token_usage_token_time;

CREATE INDEX IF NOT EXISTS ix_user_tenant_tenant_user_active
    ON nexent.user_tenant_t (tenant_id, user_id, delete_flag);

CREATE INDEX IF NOT EXISTS ix_user_tenant_tenant_email_active
    ON nexent.user_tenant_t (tenant_id, lower(user_email))
    WHERE delete_flag = 'N' AND user_email IS NOT NULL;
