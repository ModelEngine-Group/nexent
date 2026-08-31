-- Durable human interaction is opt-in. Existing migration files remain immutable.
CREATE TABLE IF NOT EXISTS nexent.human_run_t (
    run_id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    conversation_id INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL CHECK (status IN (
        'INITIALIZING', 'READY', 'RUNNING', 'WAITING_HUMAN', 'COMPLETED', 'FAILED', 'STOPPED', 'EXPIRED', 'RECOVERY_REQUIRED'
    )),
    request_payload TEXT NOT NULL,
    checkpoint TEXT,
    catalog_digest VARCHAR(64),
    executor_digest VARCHAR(64),
    plan TEXT,
    plan_version INTEGER NOT NULL DEFAULT 0,
    fence INTEGER NOT NULL DEFAULT 0,
    lock_owner VARCHAR(200),
    lock_until TIMESTAMPTZ,
    pause_requested INTEGER NOT NULL DEFAULT 0,
    event_seq BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS human_run_active_conversation_uq
    ON nexent.human_run_t (tenant_id, user_id, conversation_id)
    WHERE status IN ('INITIALIZING', 'READY', 'RUNNING', 'WAITING_HUMAN', 'RECOVERY_REQUIRED');
CREATE INDEX IF NOT EXISTS human_run_claim_idx ON nexent.human_run_t (status, lock_until);

CREATE TABLE IF NOT EXISTS nexent.human_request_t (
    request_id VARCHAR(36) PRIMARY KEY,
    run_id VARCHAR(36) NOT NULL REFERENCES nexent.human_run_t (run_id),
    kind VARCHAR(32) NOT NULL CHECK (kind IN ('CLARIFICATION', 'ACTION_APPROVAL', 'USER_STEERING')),
    status VARCHAR(32) NOT NULL CHECK (status IN ('PENDING', 'DECIDED', 'CANCELLED', 'EXPIRED')),
    version INTEGER NOT NULL DEFAULT 1,
    slot VARCHAR(100) NOT NULL,
    digest VARCHAR(64) NOT NULL,
    payload TEXT NOT NULL,
    decision TEXT,
    idempotency_key VARCHAR(100),
    decision_digest VARCHAR(64),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS human_request_run_idx ON nexent.human_request_t (run_id);
CREATE UNIQUE INDEX IF NOT EXISTS human_request_pending_uq
    ON nexent.human_request_t (run_id) WHERE status = 'PENDING';

CREATE TABLE IF NOT EXISTS nexent.human_execution_t (
    run_id VARCHAR(36) NOT NULL REFERENCES nexent.human_run_t (run_id),
    slot VARCHAR(100) NOT NULL,
    tool VARCHAR(200) NOT NULL,
    digest VARCHAR(64) NOT NULL,
    arguments TEXT NOT NULL,
    status VARCHAR(32) NOT NULL CHECK (status IN ('PREPARED', 'STARTED', 'SUCCEEDED', 'REJECTED', 'UNKNOWN')),
    result TEXT,
    PRIMARY KEY (run_id, slot)
);
CREATE TABLE IF NOT EXISTS nexent.human_event_t (
    run_id VARCHAR(36) NOT NULL REFERENCES nexent.human_run_t (run_id),
    seq BIGINT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, seq)
);
