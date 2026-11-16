-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Runtime-owned KB jobs and file visibility; existing Management rows are not modified.

CREATE SCHEMA IF NOT EXISTS nexent;

CREATE TABLE IF NOT EXISTS nexent.runtime_knowledge_job_t (
	job_id VARCHAR(32) NOT NULL,
	tenant_id VARCHAR(100) NOT NULL,
	user_id VARCHAR(100) NOT NULL,
	knowledge_id INTEGER NOT NULL,
	file_id VARCHAR(32) NOT NULL,
	file_version INTEGER NOT NULL,
	operation VARCHAR(30) NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	request_payload JSONB NOT NULL,
	status VARCHAR(30) NOT NULL,
	owner_id VARCHAR(100),
	attempt_id VARCHAR(32),
	lease_until TIMESTAMP WITH TIME ZONE,
	write_started BOOLEAN NOT NULL,
	writer_ended BOOLEAN NOT NULL,
	reconcile_required BOOLEAN NOT NULL,
	chunk_count INTEGER,
	error_code VARCHAR(128),
	physical_cleanup_complete BOOLEAN NOT NULL,
	revision INTEGER DEFAULT '1' NOT NULL,
	create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
	update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
	created_by VARCHAR(100) NOT NULL,
	updated_by VARCHAR(100) NOT NULL,
	delete_flag VARCHAR(1) DEFAULT 'N' NOT NULL,
	PRIMARY KEY (job_id),
	CONSTRAINT ck_runtime_knowledge_job_t_identity CHECK (revision > 0 AND knowledge_id > 0),
	CONSTRAINT ck_runtime_knowledge_job_operation CHECK (file_version >= 0 AND operation IN ('upload', 'delete')),
	CONSTRAINT ck_runtime_knowledge_job_status CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled', 'cleanup_pending', 'deleted')),
	CONSTRAINT ck_runtime_knowledge_job_owner CHECK (status <> 'running' OR (owner_id IS NOT NULL AND attempt_id IS NOT NULL AND lease_until IS NOT NULL)),
	CONSTRAINT ck_runtime_knowledge_job_writer CHECK (writer_ended OR (write_started AND reconcile_required)),
	CONSTRAINT ck_runtime_knowledge_job_chunks CHECK (chunk_count IS NULL OR chunk_count >= 0),
	CONSTRAINT ck_runtime_knowledge_job_cleanup CHECK (NOT physical_cleanup_complete OR (operation = 'delete' AND status = 'deleted')),
	CONSTRAINT ck_runtime_knowledge_job_payload CHECK (jsonb_typeof(request_payload) = 'object' AND octet_length(request_payload::text) <= 16384)
);

CREATE INDEX IF NOT EXISTS idx_runtime_knowledge_job_file ON nexent.runtime_knowledge_job_t (tenant_id, knowledge_id, file_id, file_version);

CREATE INDEX IF NOT EXISTS idx_runtime_knowledge_job_ready ON nexent.runtime_knowledge_job_t (tenant_id, status, lease_until);

COMMENT ON TABLE nexent.runtime_knowledge_job_t IS 'Runtime KB execution and deletion requests with durable writer fencing.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.job_id IS 'Deterministic UUID technical identifier for one authorized idempotent request.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.tenant_id IS 'Tenant owning the KB request.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.user_id IS 'User holding inspect and execution ownership of this request.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.knowledge_id IS 'Logical knowledge resource reference, validated by Runtime authorization.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.file_id IS 'Stable file reference authorized for the knowledge resource.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.file_version IS 'Authorized file generation affected by this request.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.operation IS 'Upload execution or deletion cleanup operation.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.request_hash IS 'SHA256 of the canonical strict operation payload.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.request_payload IS 'Strict upload or delete DTO, at most 16 KiB, without credentials or document bytes.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.status IS 'Queued, running, completed, failed, cancelled, cleanup_pending or deleted outcome.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.owner_id IS 'Runtime instance currently owning this execution attempt.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.attempt_id IS 'Unique fencing token used as vector generation by the current attempt.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.lease_until IS 'UTC deadline of the current owner''s execution lease.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.write_started IS 'Execution intent committed before model or vector side effects begin.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.writer_ended IS 'Explicit confirmation that no model or storage request from this attempt can write later.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.reconcile_required IS 'Unconfirmed execution or write outcome forbids automatic replay.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.chunk_count IS 'Number of confirmed chunks published by a completed upload.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.error_code IS 'Stable sanitized execution failure code without provider details.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.physical_cleanup_complete IS 'Delete request has confirmed physical absence after all covered writers ended.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.revision IS 'RecordStore optimistic concurrency revision.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.create_time IS 'UTC admission time of this Runtime record.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.update_time IS 'UTC time of the latest Runtime lifecycle update.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.created_by IS 'Trusted actor creating the Runtime record.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.updated_by IS 'Trusted actor performing the latest lifecycle update.';

COMMENT ON COLUMN nexent.runtime_knowledge_job_t.delete_flag IS 'Soft deletion marker, N active and Y deleted; tombstones remain active.';

CREATE TABLE IF NOT EXISTS nexent.runtime_knowledge_file_t (
	record_id VARCHAR(32) NOT NULL,
	tenant_id VARCHAR(100) NOT NULL,
	knowledge_id INTEGER NOT NULL,
	file_id VARCHAR(32) NOT NULL,
	latest_version INTEGER NOT NULL,
	active_job_id VARCHAR(32),
	visible_job_id VARCHAR(32),
	visible_version INTEGER,
	visible_generation VARCHAR(32),
	tombstone_version INTEGER NOT NULL,
	revision INTEGER DEFAULT '1' NOT NULL,
	create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
	update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT now() NOT NULL,
	created_by VARCHAR(100) NOT NULL,
	updated_by VARCHAR(100) NOT NULL,
	delete_flag VARCHAR(1) DEFAULT 'N' NOT NULL,
	PRIMARY KEY (record_id),
	CONSTRAINT ck_runtime_knowledge_file_t_identity CHECK (revision > 0 AND knowledge_id > 0),
	CONSTRAINT ck_runtime_knowledge_file_version CHECK (latest_version >= -1 AND tombstone_version >= -1),
	CONSTRAINT ck_runtime_knowledge_file_visibility CHECK ((visible_job_id IS NULL AND visible_version IS NULL AND visible_generation IS NULL) OR (visible_job_id IS NOT NULL AND visible_version IS NOT NULL AND visible_generation IS NOT NULL AND visible_version > tombstone_version))
);

CREATE INDEX IF NOT EXISTS idx_runtime_knowledge_file_scope ON nexent.runtime_knowledge_file_t (tenant_id, knowledge_id, file_id);

COMMENT ON TABLE nexent.runtime_knowledge_file_t IS 'Authoritative Runtime KB file visibility and deletion high-water mark.';

COMMENT ON COLUMN nexent.runtime_knowledge_file_t.record_id IS 'Deterministic UUID technical identifier derived from tenant, knowledge and file.';

COMMENT ON COLUMN nexent.runtime_knowledge_file_t.tenant_id IS 'Tenant owning the file visibility record.';

COMMENT ON COLUMN nexent.runtime_knowledge_file_t.knowledge_id IS 'Logical authorized knowledge resource reference.';

COMMENT ON COLUMN nexent.runtime_knowledge_file_t.file_id IS 'Stable authorized file reference.';

COMMENT ON COLUMN nexent.runtime_knowledge_file_t.latest_version IS 'Highest admitted upload version, or -1 before the first upload.';

COMMENT ON COLUMN nexent.runtime_knowledge_file_t.active_job_id IS 'Current upload request allowed to begin execution or publish visibility.';

COMMENT ON COLUMN nexent.runtime_knowledge_file_t.visible_job_id IS 'Completed upload request providing the authoritative visible generation.';

COMMENT ON COLUMN nexent.runtime_knowledge_file_t.visible_version IS 'Published file version; null while no version is visible.';

COMMENT ON COLUMN nexent.runtime_knowledge_file_t.visible_generation IS 'Attempt token required on returned vectors for the visible version.';

COMMENT ON COLUMN nexent.runtime_knowledge_file_t.tombstone_version IS 'Deletion high-water mark; versions at or below it cannot publish again.';

COMMENT ON COLUMN nexent.runtime_knowledge_file_t.revision IS 'RecordStore CAS serialization revision for file lifecycle decisions.';

COMMENT ON COLUMN nexent.runtime_knowledge_file_t.create_time IS 'UTC admission time of this Runtime record.';

COMMENT ON COLUMN nexent.runtime_knowledge_file_t.update_time IS 'UTC time of the latest Runtime lifecycle update.';

COMMENT ON COLUMN nexent.runtime_knowledge_file_t.created_by IS 'Trusted actor creating the Runtime record.';

COMMENT ON COLUMN nexent.runtime_knowledge_file_t.updated_by IS 'Trusted actor performing the latest lifecycle update.';

COMMENT ON COLUMN nexent.runtime_knowledge_file_t.delete_flag IS 'Soft deletion marker, N active and Y deleted; tombstones remain active.';
