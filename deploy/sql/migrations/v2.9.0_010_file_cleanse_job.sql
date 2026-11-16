-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


CREATE TABLE IF NOT EXISTS nexent.file_cleanse_job_t (
	id SERIAL NOT NULL,
	job_id VARCHAR(32) NOT NULL,
	tenant_id VARCHAR(100) NOT NULL,
	user_id VARCHAR(100) NOT NULL,
	run_id VARCHAR(38) NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	request_payload JSONB NOT NULL,
	parser_version VARCHAR(128) NOT NULL,
	status VARCHAR(30) NOT NULL,
	reconcile_required BOOLEAN NOT NULL,
	attempt_id VARCHAR(32),
	owner_id VARCHAR(100),
	lease_until TIMESTAMP WITH TIME ZONE,
	artifact JSONB,
	error_code VARCHAR(128),
	revision INTEGER NOT NULL,
	create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
	update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
	created_by VARCHAR(100) NOT NULL,
	updated_by VARCHAR(100) NOT NULL,
	delete_flag VARCHAR(1) DEFAULT 'N' NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (job_id),
	CONSTRAINT ck_file_cleanse_job_1 CHECK (status IN ('queued','running','completed','failed','cancelled')),
	CONSTRAINT ck_file_cleanse_job_2 CHECK (revision > 0),
	CONSTRAINT ck_file_cleanse_job_3 CHECK ((status = 'completed') = (artifact IS NOT NULL)),
	CONSTRAINT ck_file_cleanse_job_4 CHECK (status <> 'running' OR (owner_id IS NOT NULL AND attempt_id IS NOT NULL AND lease_until IS NOT NULL)),
	CONSTRAINT ck_file_cleanse_job_5 CHECK (jsonb_typeof(request_payload) = 'object'),
	CONSTRAINT ck_file_cleanse_job_6 CHECK (octet_length(request_payload::text) <= 16384),
	CONSTRAINT ck_file_cleanse_job_7 CHECK (artifact IS NULL OR (jsonb_typeof(artifact) = 'object' AND octet_length(artifact::text) <= 16384))
);
CREATE INDEX IF NOT EXISTS idx_file_cleanse_job_owner ON nexent.file_cleanse_job_t (tenant_id, user_id, run_id);
CREATE INDEX IF NOT EXISTS idx_file_cleanse_job_ready ON nexent.file_cleanse_job_t (tenant_id, status, lease_until);
COMMENT ON TABLE nexent.file_cleanse_job_t IS 'Management-owned authorized cleansing jobs and fenced execution attempts.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.id IS 'Technical cleansing job primary key.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.job_id IS 'Stable public idempotent cleansing job identifier.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.tenant_id IS 'Tenant owning the authorized cleansing request.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.user_id IS 'User owning the request and its inspect/cancel access.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.run_id IS 'Authorized AgentOS run requiring the source file.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.request_hash IS 'SHA256 of the canonical FileCleanseRequest payload.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.request_payload IS 'Validated FileCleanseRequest only; no credentials or raw file bytes.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.parser_version IS 'Pinned parser build required when executing this job.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.status IS 'queued/running/completed/failed/cancelled lifecycle state.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.reconcile_required IS 'Unknown write outcome blocks automatic retry until reconciliation.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.attempt_id IS 'Per-claim fencing token, replaced on lease takeover.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.owner_id IS 'Worker instance holding the current attempt lease.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.lease_until IS 'UTC expiration of the current worker attempt.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.artifact IS 'Confirmed ObjectReference only after successful publication.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.error_code IS 'Sanitized stable terminal failure classification.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.revision IS 'RecordStore optimistic concurrency revision.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.create_time IS 'UTC time the job was admitted.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.update_time IS 'UTC time of the latest state change.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.created_by IS 'Trusted actor admitting the job.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.updated_by IS 'Trusted actor performing the latest state update.';
COMMENT ON COLUMN nexent.file_cleanse_job_t.delete_flag IS 'Soft deletion marker, N active and Y deleted.';
