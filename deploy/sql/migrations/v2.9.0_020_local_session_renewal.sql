-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

CREATE TABLE IF NOT EXISTS nexent.user_local_session_t (
    session_id varchar(100) PRIMARY KEY,
    user_id varchar(100) NOT NULL,
    refresh_digest char(64) NOT NULL,
    idle_expires_at timestamp NOT NULL,
    absolute_expires_at timestamp NOT NULL,
    revoked_at timestamp,
    previous_refresh_digest char(64),
    previous_access_digest char(64),
    request_id varchar(64),
    retry_until timestamp,
    rotation_nonce varchar(64),
    access_issued_at timestamp,
    access_expires_at timestamp,
    created_by varchar(100) NOT NULL,
    create_time timestamp NOT NULL,
    updated_by varchar(100) NOT NULL,
    update_time timestamp NOT NULL,
    delete_flag varchar(1) NOT NULL DEFAULT 'N'
);

CREATE INDEX IF NOT EXISTS ix_user_local_session_idle_expiry
    ON nexent.user_local_session_t (idle_expires_at);

COMMENT ON TABLE nexent.user_local_session_t IS 'Credential state for renewable local account sessions.';
COMMENT ON COLUMN nexent.user_local_session_t.session_id IS 'Identifier signed into the session access JWT.';
COMMENT ON COLUMN nexent.user_local_session_t.user_id IS 'Account that owns this login session.';
COMMENT ON COLUMN nexent.user_local_session_t.refresh_digest IS 'SHA-256 digest of the current refresh token.';
COMMENT ON COLUMN nexent.user_local_session_t.idle_expires_at IS 'UTC time when the session expires without renewal.';
COMMENT ON COLUMN nexent.user_local_session_t.absolute_expires_at IS 'Latest allowed session expiration time in UTC.';
COMMENT ON COLUMN nexent.user_local_session_t.revoked_at IS 'UTC revocation time, null while unrevoked.';
COMMENT ON COLUMN nexent.user_local_session_t.previous_refresh_digest IS 'Digest of the refresh token from the preceding rotation.';
COMMENT ON COLUMN nexent.user_local_session_t.previous_access_digest IS 'Digest of the access JWT used in the preceding rotation.';
COMMENT ON COLUMN nexent.user_local_session_t.request_id IS 'Optional retry identifier for the preceding rotation.';
COMMENT ON COLUMN nexent.user_local_session_t.retry_until IS 'UTC time when the rotation retry window ends.';
COMMENT ON COLUMN nexent.user_local_session_t.rotation_nonce IS 'Random value for reconstructing the last rotation result.';
COMMENT ON COLUMN nexent.user_local_session_t.access_issued_at IS 'Original UTC JWT issue time used to reconstruct the last rotation result.';
COMMENT ON COLUMN nexent.user_local_session_t.access_expires_at IS 'Original UTC JWT expiration used to reconstruct the last rotation result.';
COMMENT ON COLUMN nexent.user_local_session_t.created_by IS 'Actor that created the session.';
COMMENT ON COLUMN nexent.user_local_session_t.create_time IS 'UTC time when the session was inserted.';
COMMENT ON COLUMN nexent.user_local_session_t.updated_by IS 'Actor that most recently rotated or revoked the session.';
COMMENT ON COLUMN nexent.user_local_session_t.update_time IS 'UTC time when the session was last updated.';
COMMENT ON COLUMN nexent.user_local_session_t.delete_flag IS 'Soft-delete marker, N for current rows and Y for deleted rows.';
