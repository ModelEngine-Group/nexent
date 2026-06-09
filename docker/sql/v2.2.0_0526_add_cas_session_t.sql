CREATE TABLE IF NOT EXISTS nexent.user_cas_session_t (
    cas_session_id SERIAL PRIMARY KEY,
    session_id VARCHAR(100) NOT NULL UNIQUE,
    user_id VARCHAR(100) NOT NULL,
    cas_user_id VARCHAR(200) NOT NULL,
    cas_session_index VARCHAR(500),
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    expires_at TIMESTAMP NOT NULL,
    revoked_at TIMESTAMP,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag VARCHAR(1) DEFAULT 'N'
);

CREATE INDEX IF NOT EXISTS ix_user_cas_session_session_id
    ON nexent.user_cas_session_t (session_id);
CREATE INDEX IF NOT EXISTS ix_user_cas_session_user_id
    ON nexent.user_cas_session_t (user_id);
CREATE INDEX IF NOT EXISTS ix_user_cas_session_cas_user_id
    ON nexent.user_cas_session_t (cas_user_id);

COMMENT ON TABLE nexent.user_cas_session_t IS 'Server-side session records for CAS SSO login and logout synchronization';
COMMENT ON COLUMN nexent.user_cas_session_t.session_id IS 'JWT sid claim for revocation checks';
COMMENT ON COLUMN nexent.user_cas_session_t.cas_user_id IS 'User identifier returned by CAS';
COMMENT ON COLUMN nexent.user_cas_session_t.cas_session_index IS 'CAS SessionIndex or service ticket';
