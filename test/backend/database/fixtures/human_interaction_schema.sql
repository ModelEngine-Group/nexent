-- Standalone HITL schema fixture for PostgreSQL integration tests.
-- Keep this test snapshot independent of versioned deployment scripts.
-- Technical keys and internal references use INT4; public identifiers use UUID strings.
-- Services validate business states, references and uniqueness under transaction locks.

CREATE TABLE IF NOT EXISTS nexent.human_run_t (
    run_record_id SERIAL PRIMARY KEY,
    run_id VARCHAR(36) NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    conversation_id INTEGER NOT NULL,
    status VARCHAR(30) NOT NULL,
    request_payload TEXT NOT NULL,
    checkpoint TEXT,
    catalog_digest VARCHAR(64),
    executor_digest VARCHAR(64),
    plan TEXT,
    plan_version INTEGER DEFAULT 0 NOT NULL,
    fence INTEGER DEFAULT 0 NOT NULL,
    lock_owner VARCHAR(200),
    lock_until TIMESTAMP WITH TIME ZONE,
    pause_requested INTEGER DEFAULT 0 NOT NULL,
    event_seq BIGINT DEFAULT 0 NOT NULL,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT timezone('UTC', now()) NOT NULL,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT timezone('UTC', now()) NOT NULL,
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100) NOT NULL,
    delete_flag VARCHAR(1) DEFAULT 'N' NOT NULL
);

CREATE TABLE IF NOT EXISTS nexent.human_request_t (
    request_record_id SERIAL PRIMARY KEY,
    request_id VARCHAR(36) NOT NULL,
    run_record_id INTEGER NOT NULL,
    kind VARCHAR(30) NOT NULL,
    status VARCHAR(30) NOT NULL,
    version INTEGER DEFAULT 1 NOT NULL,
    slot VARCHAR(100) NOT NULL,
    digest VARCHAR(64) NOT NULL,
    payload TEXT NOT NULL,
    decision TEXT,
    idempotency_key VARCHAR(100),
    decision_digest VARCHAR(64),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT timezone('UTC', now()) NOT NULL,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT timezone('UTC', now()) NOT NULL,
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100) NOT NULL,
    delete_flag VARCHAR(1) DEFAULT 'N' NOT NULL
);

CREATE TABLE IF NOT EXISTS nexent.human_execution_t (
    execution_id SERIAL PRIMARY KEY,
    run_record_id INTEGER NOT NULL,
    slot VARCHAR(100) NOT NULL,
    tool VARCHAR(200) NOT NULL,
    digest VARCHAR(64) NOT NULL,
    arguments TEXT NOT NULL,
    status VARCHAR(30) NOT NULL,
    result TEXT,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT timezone('UTC', now()) NOT NULL,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT timezone('UTC', now()) NOT NULL,
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100) NOT NULL,
    delete_flag VARCHAR(1) DEFAULT 'N' NOT NULL
);

CREATE TABLE IF NOT EXISTS nexent.human_event_t (
    event_id SERIAL PRIMARY KEY,
    run_record_id INTEGER NOT NULL,
    seq BIGINT NOT NULL,
    payload JSONB NOT NULL,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT timezone('UTC', now()) NOT NULL,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT timezone('UTC', now()) NOT NULL,
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100) NOT NULL,
    delete_flag VARCHAR(1) DEFAULT 'N' NOT NULL
);

-- Keep raw SQL and ORM updates consistent; callers supply the updating actor.
DO $create_function$
BEGIN
    IF to_regprocedure('nexent.human_interaction_audit_timestamp()') IS NULL THEN
        CREATE FUNCTION nexent.human_interaction_audit_timestamp()
        RETURNS TRIGGER LANGUAGE plpgsql AS $function$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                NEW.create_time := COALESCE(NEW.create_time, timezone('UTC', clock_timestamp()));
            ELSE
                NEW.create_time := OLD.create_time;
                NEW.created_by := OLD.created_by;
            END IF;
            NEW.update_time := timezone('UTC', clock_timestamp());
            RETURN NEW;
        END;
        $function$;
    END IF;
END;
$create_function$;

DO $create_triggers$
DECLARE
    target_table REGCLASS;
BEGIN
    FOREACH target_table IN ARRAY ARRAY[
        'nexent.human_run_t'::regclass,
        'nexent.human_request_t'::regclass,
        'nexent.human_execution_t'::regclass,
        'nexent.human_event_t'::regclass
    ] LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger
            WHERE tgrelid = target_table AND tgname = 'human_audit_timestamp'
        ) THEN
            EXECUTE format(
                'CREATE TRIGGER human_audit_timestamp BEFORE INSERT OR UPDATE ON %s '
                'FOR EACH ROW EXECUTE FUNCTION nexent.human_interaction_audit_timestamp()',
                target_table
            );
        END IF;
    END LOOP;
END;
$create_triggers$;

-- Non-unique indexes support public lookup, owner conversation history,
-- scheduler claims, pending requests, call-slot replay and ordered SSE pagination.
-- Advisory locks protect creation; the parent row lock protects dependent writes.

CREATE INDEX IF NOT EXISTS human_run_claim_idx ON nexent.human_run_t (status, lock_until, create_time) WHERE delete_flag = 'N';
CREATE INDEX IF NOT EXISTS human_run_conversation_idx ON nexent.human_run_t (tenant_id, user_id, conversation_id, create_time) WHERE delete_flag = 'N';
CREATE INDEX IF NOT EXISTS human_run_public_id_idx ON nexent.human_run_t (run_id);
COMMENT ON COLUMN nexent.human_run_t.run_record_id IS 'Technical run record identifier';
COMMENT ON COLUMN nexent.human_run_t.run_id IS 'Public UUID retained by HTTP, checkpoints and event payloads; service enforces uniqueness';
COMMENT ON COLUMN nexent.human_run_t.tenant_id IS 'Tenant owning this run and its dependent records';
COMMENT ON COLUMN nexent.human_run_t.user_id IS 'User owning this run within the tenant';
COMMENT ON COLUMN nexent.human_run_t.conversation_id IS 'Logical conversation_record_t.conversation_id; service validates the active owner';
COMMENT ON COLUMN nexent.human_run_t.status IS 'Run lifecycle state validated by the human interaction service';
COMMENT ON COLUMN nexent.human_run_t.request_payload IS 'Fernet encrypted JSON run input and context snapshot; private service-owned payload';
COMMENT ON COLUMN nexent.human_run_t.checkpoint IS 'Fernet encrypted SDK checkpoint; null until the first durable boundary';
COMMENT ON COLUMN nexent.human_run_t.catalog_digest IS 'SHA-256 identity of the agent, model and tool catalog';
COMMENT ON COLUMN nexent.human_run_t.executor_digest IS 'SHA-256 identity of the registered executor implementation';
COMMENT ON COLUMN nexent.human_run_t.plan IS 'Fernet encrypted SDK plan snapshot; null when no plan exists';
COMMENT ON COLUMN nexent.human_run_t.plan_version IS 'Monotonic revision of the saved plan';
COMMENT ON COLUMN nexent.human_run_t.fence IS 'Lease generation rejecting stale worker writes';
COMMENT ON COLUMN nexent.human_run_t.lock_owner IS 'Scheduler worker identity, bounded to 200 characters';
COMMENT ON COLUMN nexent.human_run_t.lock_until IS 'UTC lease deadline; null when no worker owns the run';
COMMENT ON COLUMN nexent.human_run_t.pause_requested IS 'Pause request marker: 0 or 1, validated by the service';
COMMENT ON COLUMN nexent.human_run_t.event_seq IS '64-bit SSE event counter; not a record identifier, allocated under the run lock';
COMMENT ON COLUMN nexent.human_run_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.human_run_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.human_run_t.created_by IS 'Creator';
COMMENT ON COLUMN nexent.human_run_t.updated_by IS 'Updater';
COMMENT ON COLUMN nexent.human_run_t.delete_flag IS 'Whether it is deleted. Optional values: Y/N';

CREATE INDEX IF NOT EXISTS human_request_run_idx ON nexent.human_request_t (run_record_id, status) WHERE delete_flag = 'N';
COMMENT ON COLUMN nexent.human_request_t.request_record_id IS 'Technical human request record identifier';
COMMENT ON COLUMN nexent.human_request_t.request_id IS 'Public request UUID; uniqueness is scoped to the owning run by the service';
COMMENT ON COLUMN nexent.human_request_t.run_record_id IS 'Logical human_run_t.run_record_id; validated under the parent run lock';
COMMENT ON COLUMN nexent.human_request_t.kind IS 'CLARIFICATION, ACTION_APPROVAL or USER_STEERING; service validated';
COMMENT ON COLUMN nexent.human_request_t.status IS 'PENDING, DECIDED, CANCELLED or EXPIRED; service validated';
COMMENT ON COLUMN nexent.human_request_t.version IS 'Positive request revision used for decision compare-and-set';
COMMENT ON COLUMN nexent.human_request_t.slot IS 'SDK action slot or composer guidance identity within the run';
COMMENT ON COLUMN nexent.human_request_t.digest IS 'SHA-256 action identity required when submitting a decision';
COMMENT ON COLUMN nexent.human_request_t.payload IS 'Fernet encrypted clarification, approval or steering payload, validated by the service';
COMMENT ON COLUMN nexent.human_request_t.decision IS 'Fernet encrypted validated DecisionCommand or composer decision; null before a decision';
COMMENT ON COLUMN nexent.human_request_t.idempotency_key IS 'Decision retry key scoped to this request, or composer message identity scoped to the run';
COMMENT ON COLUMN nexent.human_request_t.decision_digest IS 'SHA-256 of the accepted decision, detecting conflicting retries';
COMMENT ON COLUMN nexent.human_request_t.expires_at IS 'UTC deadline after which a pending decision cannot authorize execution';
COMMENT ON COLUMN nexent.human_request_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.human_request_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.human_request_t.created_by IS 'Creator';
COMMENT ON COLUMN nexent.human_request_t.updated_by IS 'Updater';
COMMENT ON COLUMN nexent.human_request_t.delete_flag IS 'Whether it is deleted. Optional values: Y/N';

CREATE INDEX IF NOT EXISTS human_execution_slot_idx ON nexent.human_execution_t (run_record_id, slot) WHERE delete_flag = 'N';
COMMENT ON COLUMN nexent.human_execution_t.execution_id IS 'Technical execution receipt identifier';
COMMENT ON COLUMN nexent.human_execution_t.run_record_id IS 'Logical human_run_t.run_record_id; validated under the parent run lock';
COMMENT ON COLUMN nexent.human_execution_t.slot IS 'Stable SDK call slot; one active receipt per run and slot is enforced by the service';
COMMENT ON COLUMN nexent.human_execution_t.tool IS 'Registered tool name, bounded to 200 characters';
COMMENT ON COLUMN nexent.human_execution_t.digest IS 'HMAC-SHA-256 of the frozen action and execution context';
COMMENT ON COLUMN nexent.human_execution_t.arguments IS 'Fernet encrypted frozen tool arguments; variable SDK-owned JSON structure';
COMMENT ON COLUMN nexent.human_execution_t.status IS 'PREPARED, STARTED, SUCCEEDED, REJECTED or UNKNOWN; service validated';
COMMENT ON COLUMN nexent.human_execution_t.result IS 'Fernet encrypted result or rejection; null before a conclusive receipt';
COMMENT ON COLUMN nexent.human_execution_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.human_execution_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.human_execution_t.created_by IS 'Creator';
COMMENT ON COLUMN nexent.human_execution_t.updated_by IS 'Updater';
COMMENT ON COLUMN nexent.human_execution_t.delete_flag IS 'Whether it is deleted. Optional values: Y/N';

CREATE INDEX IF NOT EXISTS human_event_replay_idx ON nexent.human_event_t (run_record_id, seq) WHERE delete_flag = 'N';
COMMENT ON COLUMN nexent.human_event_t.event_id IS 'Technical replay event identifier';
COMMENT ON COLUMN nexent.human_event_t.run_record_id IS 'Logical human_run_t.run_record_id; validated under the parent run lock';
COMMENT ON COLUMN nexent.human_event_t.seq IS '64-bit SSE cursor allocated from the owning run event_seq under its row lock';
COMMENT ON COLUMN nexent.human_event_t.payload IS 'Service-owned event envelope: either chunk_cipher string or type string and content object; no plaintext stream chunks';
COMMENT ON COLUMN nexent.human_event_t.create_time IS 'Creation time';
COMMENT ON COLUMN nexent.human_event_t.update_time IS 'Update time';
COMMENT ON COLUMN nexent.human_event_t.created_by IS 'Creator';
COMMENT ON COLUMN nexent.human_event_t.updated_by IS 'Updater';
COMMENT ON COLUMN nexent.human_event_t.delete_flag IS 'Whether it is deleted. Optional values: Y/N';
