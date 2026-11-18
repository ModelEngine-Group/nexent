-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

CREATE TABLE IF NOT EXISTS nexent.runtime_knowledge_chunk_change_t (
	mutation_id VARCHAR(64) NOT NULL,
	tenant_id VARCHAR(100) NOT NULL,
	knowledge_id BIGINT NOT NULL,
	user_id VARCHAR(100) NOT NULL,
	chunk_id VARCHAR(1024) NOT NULL,
	chunk_key VARCHAR(64) NOT NULL,
	operation VARCHAR(30) NOT NULL,
	request_sha256 VARCHAR(64) NOT NULL,
	resource_revision VARCHAR(64) NOT NULL,
	file_id VARCHAR(32),
	file_version BIGINT,
	generation VARCHAR(256),
	chunk_index BIGINT,
	status VARCHAR(30) NOT NULL,
	writer_ended BOOLEAN NOT NULL,
	count_delta INTEGER,
	commit_epoch BIGINT,
	error_code VARCHAR(100),
	revision INTEGER DEFAULT '0' NOT NULL,
	create_time TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	update_time TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by VARCHAR(100) NOT NULL,
	updated_by VARCHAR(100) NOT NULL,
	PRIMARY KEY (mutation_id),
	CONSTRAINT ck_chunk_change_operation CHECK (operation IN ('create','update','delete')),
	CONSTRAINT ck_chunk_change_status CHECK (status IN ('reserved','writing','completed','failed','unknown')),
	CONSTRAINT ck_chunk_change_revision CHECK (knowledge_id > 0 AND revision >= 0),
	CONSTRAINT ck_chunk_change_writing CHECK (status <> 'writing' OR NOT writer_ended),
	CONSTRAINT ck_chunk_change_ended CHECK (status NOT IN ('reserved','completed','failed') OR writer_ended),
	CONSTRAINT ck_chunk_change_file CHECK ((file_id IS NULL AND file_version IS NULL AND generation IS NULL AND chunk_index IS NULL) OR (file_id IS NOT NULL AND file_version IS NOT NULL AND file_version >= 0 AND generation IS NOT NULL AND chunk_index IS NOT NULL AND chunk_index >= 0)),
	CONSTRAINT ck_chunk_change_effect CHECK ((status = 'completed' AND count_delta IS NOT NULL AND commit_epoch IS NOT NULL AND commit_epoch > 0) OR (status <> 'completed' AND count_delta IS NULL AND commit_epoch IS NULL)),
	CONSTRAINT ck_chunk_change_delta CHECK (count_delta IS NULL OR (operation = 'create' AND count_delta IN (0,1)) OR (operation = 'update' AND count_delta = 0) OR (operation = 'delete' AND count_delta IN (-1,0)))
);

CREATE INDEX IF NOT EXISTS idx_chunk_change_active ON nexent.runtime_knowledge_chunk_change_t (tenant_id, knowledge_id, status);

CREATE INDEX IF NOT EXISTS idx_chunk_change_epoch ON nexent.runtime_knowledge_chunk_change_t (tenant_id, knowledge_id, commit_epoch);

CREATE INDEX IF NOT EXISTS idx_chunk_change_file ON nexent.runtime_knowledge_chunk_change_t (tenant_id, knowledge_id, file_id, file_version, generation);

CREATE INDEX IF NOT EXISTS idx_chunk_change_key ON nexent.runtime_knowledge_chunk_change_t (tenant_id, knowledge_id, chunk_key, status);

COMMENT ON TABLE nexent.runtime_knowledge_chunk_change_t IS 'Runtime chunk mutation receipts; hashes and scalar effects only, never a replayable payload queue.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_change_t.mutation_id IS 'Deterministic digest of tenant, issuer, KB and idempotency key.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_change_t.tenant_id IS 'Tenant owning the chunk mutation.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_change_t.knowledge_id IS 'Existing Management KB identifier; no cross-service foreign key.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_change_t.user_id IS 'Actual request issuer; never borrowed from the resource creator.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_change_t.chunk_id IS 'Original opaque logical chunk identifier.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_change_t.chunk_key IS 'Digest of tenant, KB and logical chunk ID for bounded active-chunk lookup.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_change_t.operation IS 'Requested single-chunk create, update or delete operation.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_change_t.request_sha256 IS 'Canonical intent digest for idempotency; no raw chunk content is stored.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_change_t.resource_revision IS 'Authorized knowledge resource revision at request preparation.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_change_t.file_id IS 'Optional genuine canonical file ID; NULL for standalone chunks.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_change_t.file_version IS 'Pinned genuine file version; NULL for standalone chunks.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_change_t.generation IS 'Pinned published vector generation; NULL for standalone chunks.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_change_t.chunk_index IS 'Original ordinal within the pinned file generation; NULL for standalone chunks.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_change_t.status IS 'reserved, writing, completed, failed or unknown; unknown blocks replay and cleanup.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_change_t.writer_ended IS 'Whether local execution ended; this alone does not resolve an unknown provider write.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_change_t.count_delta IS 'Confirmed single-chunk cardinality effect; NULL until confirmed completion.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_change_t.commit_epoch IS 'KB mutation epoch assigned atomically at confirmed completion.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_change_t.error_code IS 'Bounded diagnostic code without provider details or request content.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_change_t.revision IS 'Conditional metadata revision maintained by RecordStore.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_change_t.create_time IS 'UTC creation audit time.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_change_t.update_time IS 'UTC latest metadata update time.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_change_t.created_by IS 'Actual actor that first created this metadata record.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_change_t.updated_by IS 'Actual actor performing the latest metadata update.';

CREATE TABLE IF NOT EXISTS nexent.runtime_knowledge_chunk_state_t (
	state_id VARCHAR(64) NOT NULL,
	tenant_id VARCHAR(100) NOT NULL,
	knowledge_id BIGINT NOT NULL,
	epoch BIGINT DEFAULT '0' NOT NULL,
	active_count INTEGER DEFAULT '0' NOT NULL,
	revision INTEGER DEFAULT '0' NOT NULL,
	create_time TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	update_time TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_by VARCHAR(100) NOT NULL,
	updated_by VARCHAR(100) NOT NULL,
	PRIMARY KEY (state_id),
	CONSTRAINT uq_chunk_state_scope UNIQUE (tenant_id, knowledge_id),
	CONSTRAINT ck_chunk_state_revision CHECK (knowledge_id > 0 AND epoch >= 0 AND revision >= 0 AND active_count >= 0)
);

COMMENT ON TABLE nexent.runtime_knowledge_chunk_state_t IS 'Runtime per-KB CAS admission and successful mutation revision; no file is invented for standalone chunks.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_state_t.state_id IS 'Deterministic per-tenant KB mutation marker key.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_state_t.tenant_id IS 'Tenant owning the revision and admission marker.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_state_t.knowledge_id IS 'Existing KB identifier in the owning tenant.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_state_t.epoch IS 'Successful mutation epoch; failures do not advance it.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_state_t.active_count IS 'Reserved, writing or unknown mutations; confirmed completion or failure releases one admission.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_state_t.revision IS 'Conditional metadata revision maintained by RecordStore.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_state_t.create_time IS 'UTC creation audit time.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_state_t.update_time IS 'UTC latest metadata update time.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_state_t.created_by IS 'Actual actor that first created this metadata record.';

COMMENT ON COLUMN nexent.runtime_knowledge_chunk_state_t.updated_by IS 'Actual actor performing the latest metadata update.';
