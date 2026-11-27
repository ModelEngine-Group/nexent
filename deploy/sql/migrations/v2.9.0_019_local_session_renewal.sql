-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

CREATE TABLE IF NOT EXISTS nexent.user_local_session_t (
    session_id varchar(100) PRIMARY KEY,
    user_id varchar(100) NOT NULL,
    refresh_digest char(64) NOT NULL,
    created_at bigint NOT NULL,
    last_refreshed_at bigint NOT NULL,
    idle_expires_at bigint NOT NULL,
    absolute_expires_at bigint NOT NULL,
    revoked_at bigint,
    previous_refresh_digest char(64),
    previous_access_digest char(64),
    request_id varchar(64),
    retry_until bigint,
    rotation_nonce varchar(64),
    access_issued_at bigint,
    access_expires_at bigint
);

CREATE INDEX IF NOT EXISTS ix_user_local_session_idle_expiry
    ON nexent.user_local_session_t (idle_expires_at);
