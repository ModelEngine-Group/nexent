-- Durable human interaction. This migration has not been merged into develop.
-- Public UUIDs remain stable; all technical keys and internal references are INT4.
-- Business states, references and uniqueness are checked by the service under locks.
-- Apply with HITL workers stopped, inside the migration runner transaction.

CREATE TABLE IF NOT EXISTS nexent.human_run_t (
    run_record_id SERIAL NOT NULL,
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
    delete_flag VARCHAR(1) DEFAULT 'N' NOT NULL,
    PRIMARY KEY (run_record_id)
);

CREATE TABLE IF NOT EXISTS nexent.human_request_t (
    request_record_id SERIAL NOT NULL,
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
    delete_flag VARCHAR(1) DEFAULT 'N' NOT NULL,
    PRIMARY KEY (request_record_id)
);

CREATE TABLE IF NOT EXISTS nexent.human_execution_t (
    execution_id SERIAL NOT NULL,
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
    delete_flag VARCHAR(1) DEFAULT 'N' NOT NULL,
    PRIMARY KEY (execution_id)
);

CREATE TABLE IF NOT EXISTS nexent.human_event_t (
    event_id SERIAL NOT NULL,
    run_record_id INTEGER NOT NULL,
    seq BIGINT NOT NULL,
    payload JSONB NOT NULL,
    create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT timezone('UTC', now()) NOT NULL,
    update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT timezone('UTC', now()) NOT NULL,
    created_by VARCHAR(100) NOT NULL,
    updated_by VARCHAR(100) NOT NULL,
    delete_flag VARCHAR(1) DEFAULT 'N' NOT NULL,
    PRIMARY KEY (event_id)
);

-- Preserve data from earlier revisions of this unmerged PR when the runner
-- reapplies the changed checksum. Already-converted schemas take the no-op path.
DO $$
DECLARE
    item RECORD;
    table_name TEXT;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = 'nexent' AND c.table_name = 'human_run_t' AND column_name = 'run_record_id'
    ) THEN
        -- Drop dependent foreign keys before replacing any primary key.
        FOR item IN
            SELECT conrelid::regclass AS relation, conname
            FROM pg_constraint
            WHERE connamespace = 'nexent'::regnamespace AND contype = 'f'
              AND conrelid IN ('nexent.human_request_t'::regclass,
                              'nexent.human_execution_t'::regclass, 'nexent.human_event_t'::regclass)
        LOOP
            EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', item.relation, item.conname);
        END LOOP;
        FOR item IN
            SELECT conrelid::regclass AS relation, conname
            FROM pg_constraint
            WHERE connamespace = 'nexent'::regnamespace AND contype IN ('p', 'c')
              AND conrelid IN ('nexent.human_run_t'::regclass, 'nexent.human_request_t'::regclass,
                              'nexent.human_execution_t'::regclass, 'nexent.human_event_t'::regclass)
        LOOP
            EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', item.relation, item.conname);
        END LOOP;

        ALTER TABLE nexent.human_run_t ADD COLUMN run_record_id SERIAL PRIMARY KEY;
        ALTER TABLE nexent.human_request_t ADD COLUMN request_record_id SERIAL PRIMARY KEY;
        ALTER TABLE nexent.human_execution_t ADD COLUMN execution_id SERIAL PRIMARY KEY;
        ALTER TABLE nexent.human_event_t ADD COLUMN event_id SERIAL PRIMARY KEY;

        ALTER TABLE nexent.human_run_t RENAME COLUMN created_at TO create_time;
        ALTER TABLE nexent.human_run_t RENAME COLUMN updated_at TO update_time;
        ALTER TABLE nexent.human_run_t
            ALTER COLUMN create_time TYPE TIMESTAMP USING create_time AT TIME ZONE 'UTC',
            ALTER COLUMN update_time TYPE TIMESTAMP USING update_time AT TIME ZONE 'UTC';
        ALTER TABLE nexent.human_request_t RENAME COLUMN created_at TO create_time;
        ALTER TABLE nexent.human_request_t
            ALTER COLUMN create_time TYPE TIMESTAMP USING create_time AT TIME ZONE 'UTC';
        ALTER TABLE nexent.human_event_t RENAME COLUMN created_at TO create_time;
        ALTER TABLE nexent.human_event_t
            ALTER COLUMN create_time TYPE TIMESTAMP USING create_time AT TIME ZONE 'UTC';
        ALTER TABLE nexent.human_execution_t ADD COLUMN create_time TIMESTAMP;

        FOREACH table_name IN ARRAY ARRAY['human_run_t', 'human_request_t', 'human_execution_t', 'human_event_t']
        LOOP
            EXECUTE format('ALTER TABLE nexent.%I ADD COLUMN created_by VARCHAR(100),
                ADD COLUMN updated_by VARCHAR(100), ADD COLUMN delete_flag VARCHAR(1) NOT NULL DEFAULT ''N''', table_name);
            IF table_name = 'human_run_t' THEN
                UPDATE nexent.human_run_t SET created_by = user_id, updated_by = user_id;
            ELSE
                EXECUTE format('ALTER TABLE nexent.%I ADD COLUMN run_record_id INTEGER, ADD COLUMN update_time TIMESTAMP', table_name);
                EXECUTE format('UPDATE nexent.%I child SET run_record_id = parent.run_record_id,
                    created_by = parent.user_id, updated_by = parent.user_id,
                    create_time = COALESCE(child.create_time, parent.create_time),
                    update_time = COALESCE(child.create_time, parent.create_time)
                    FROM nexent.human_run_t parent WHERE parent.run_id = child.run_id', table_name);
                -- Fail transactionally on an orphan rather than discard its payload.
                EXECUTE format('ALTER TABLE nexent.%I ALTER COLUMN run_record_id SET NOT NULL, DROP COLUMN run_id', table_name);
            END IF;
            EXECUTE format('ALTER TABLE nexent.%I ALTER COLUMN created_by SET NOT NULL,
                ALTER COLUMN updated_by SET NOT NULL, ALTER COLUMN create_time SET NOT NULL,
                ALTER COLUMN update_time SET NOT NULL,
                ALTER COLUMN create_time SET DEFAULT timezone(''UTC'', now()),
                ALTER COLUMN update_time SET DEFAULT timezone(''UTC'', now())', table_name);
        END LOOP;
        ALTER TABLE nexent.human_run_t ALTER COLUMN status TYPE VARCHAR(30);
        ALTER TABLE nexent.human_request_t ALTER COLUMN status TYPE VARCHAR(30), ALTER COLUMN kind TYPE VARCHAR(30);
        ALTER TABLE nexent.human_execution_t ALTER COLUMN status TYPE VARCHAR(30);
        DROP INDEX IF EXISTS nexent.human_run_active_conversation_uq;
        DROP INDEX IF EXISTS nexent.human_request_pending_uq;
        DROP INDEX IF EXISTS nexent.human_run_claim_idx;
        DROP INDEX IF EXISTS nexent.human_request_run_idx;
    END IF;
END;
$$;

-- Keep raw SQL and ORM updates consistent; callers supply the updating actor.
CREATE OR REPLACE FUNCTION nexent.human_interaction_audit_timestamp()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
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
$$;

DROP TRIGGER IF EXISTS human_audit_timestamp ON nexent.human_run_t;
CREATE TRIGGER human_audit_timestamp BEFORE INSERT OR UPDATE ON nexent.human_run_t
    FOR EACH ROW EXECUTE FUNCTION nexent.human_interaction_audit_timestamp();

DROP TRIGGER IF EXISTS human_audit_timestamp ON nexent.human_request_t;
CREATE TRIGGER human_audit_timestamp BEFORE INSERT OR UPDATE ON nexent.human_request_t
    FOR EACH ROW EXECUTE FUNCTION nexent.human_interaction_audit_timestamp();

DROP TRIGGER IF EXISTS human_audit_timestamp ON nexent.human_execution_t;
CREATE TRIGGER human_audit_timestamp BEFORE INSERT OR UPDATE ON nexent.human_execution_t
    FOR EACH ROW EXECUTE FUNCTION nexent.human_interaction_audit_timestamp();

DROP TRIGGER IF EXISTS human_audit_timestamp ON nexent.human_event_t;
CREATE TRIGGER human_audit_timestamp BEFORE INSERT OR UPDATE ON nexent.human_event_t
    FOR EACH ROW EXECUTE FUNCTION nexent.human_interaction_audit_timestamp();

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
