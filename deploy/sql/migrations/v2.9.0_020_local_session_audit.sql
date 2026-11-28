-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.user_local_session_t
    ADD COLUMN IF NOT EXISTS created_by varchar(100),
    ADD COLUMN IF NOT EXISTS create_time timestamp,
    ADD COLUMN IF NOT EXISTS updated_by varchar(100),
    ADD COLUMN IF NOT EXISTS update_time timestamp,
    ADD COLUMN IF NOT EXISTS delete_flag varchar(1) NOT NULL DEFAULT 'N';

UPDATE nexent.user_local_session_t
SET created_by = COALESCE(created_by, user_id),
    create_time = COALESCE(create_time, timezone('UTC', to_timestamp(created_at))),
    updated_by = COALESCE(updated_by, user_id),
    update_time = COALESCE(update_time, timezone('UTC', to_timestamp(COALESCE(revoked_at, last_refreshed_at))))
WHERE created_by IS NULL OR create_time IS NULL OR updated_by IS NULL OR update_time IS NULL;

ALTER TABLE nexent.user_local_session_t
    ALTER COLUMN created_by SET NOT NULL,
    ALTER COLUMN create_time SET DEFAULT timezone('UTC', CURRENT_TIMESTAMP),
    ALTER COLUMN create_time SET NOT NULL,
    ALTER COLUMN updated_by SET NOT NULL,
    ALTER COLUMN update_time SET DEFAULT timezone('UTC', CURRENT_TIMESTAMP),
    ALTER COLUMN update_time SET NOT NULL;

COMMENT ON TABLE nexent.user_local_session_t IS 'Credential state for renewable local account sessions.';
COMMENT ON COLUMN nexent.user_local_session_t.session_id IS 'Identifier signed into the session access JWT.';
COMMENT ON COLUMN nexent.user_local_session_t.user_id IS 'Account that owns this login session.';
COMMENT ON COLUMN nexent.user_local_session_t.refresh_digest IS 'SHA-256 digest of the current refresh token.';
COMMENT ON COLUMN nexent.user_local_session_t.created_at IS 'Session creation time in Unix seconds.';
COMMENT ON COLUMN nexent.user_local_session_t.last_refreshed_at IS 'Most recent successful rotation time in Unix seconds.';
COMMENT ON COLUMN nexent.user_local_session_t.idle_expires_at IS 'Idle expiration time in Unix seconds.';
COMMENT ON COLUMN nexent.user_local_session_t.absolute_expires_at IS 'Latest allowed expiration time in Unix seconds.';
COMMENT ON COLUMN nexent.user_local_session_t.revoked_at IS 'Revocation time in Unix seconds, null while unrevoked.';
COMMENT ON COLUMN nexent.user_local_session_t.previous_refresh_digest IS 'Digest of the refresh token from the preceding rotation.';
COMMENT ON COLUMN nexent.user_local_session_t.previous_access_digest IS 'Digest of the access JWT used in the preceding rotation.';
COMMENT ON COLUMN nexent.user_local_session_t.request_id IS 'Optional retry identifier for the preceding rotation.';
COMMENT ON COLUMN nexent.user_local_session_t.retry_until IS 'End of the rotation retry window in Unix seconds.';
COMMENT ON COLUMN nexent.user_local_session_t.rotation_nonce IS 'Random value for reconstructing the last rotation result.';
COMMENT ON COLUMN nexent.user_local_session_t.access_issued_at IS 'Access JWT issue time for the last rotation in Unix seconds.';
COMMENT ON COLUMN nexent.user_local_session_t.access_expires_at IS 'Access JWT expiration for the last rotation in Unix seconds.';
COMMENT ON COLUMN nexent.user_local_session_t.created_by IS 'Actor that created the session.';
COMMENT ON COLUMN nexent.user_local_session_t.create_time IS 'UTC time when the session was inserted.';
COMMENT ON COLUMN nexent.user_local_session_t.updated_by IS 'Actor that most recently rotated or revoked the session.';
COMMENT ON COLUMN nexent.user_local_session_t.update_time IS 'UTC time when the session was last updated.';
COMMENT ON COLUMN nexent.user_local_session_t.delete_flag IS 'Soft-delete marker, N for current rows and Y for deleted rows.';
