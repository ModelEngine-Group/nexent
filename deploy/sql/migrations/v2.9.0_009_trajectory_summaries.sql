-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Deploy with all old trajectory writers/readers/cleaners stopped before switching lock layout.

BEGIN;


CREATE TABLE IF NOT EXISTS nexent.trajectory_execution_t (
	trajectory_id UUID NOT NULL,
	conversation_id INTEGER NOT NULL,
	turn_no INTEGER NOT NULL,
	agent_id INTEGER,
	agent_version_no INTEGER,
	models VARCHAR(100)[] DEFAULT '{}' NOT NULL,
	status VARCHAR(30) NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE,
	finished_at TIMESTAMP WITH TIME ZONE,
	duration_ms DOUBLE PRECISION,
	input_tokens BIGINT,
	output_tokens BIGINT,
	total_tokens BIGINT,
	create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
	update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
	created_by VARCHAR(100),
	updated_by VARCHAR(100),
	delete_flag VARCHAR(1) DEFAULT 'N',
	PRIMARY KEY (trajectory_id)
)

;

COMMENT ON COLUMN nexent.trajectory_execution_t.trajectory_id IS 'Stable root execution UUID shared with OTLP';

COMMENT ON COLUMN nexent.trajectory_execution_t.conversation_id IS 'Existing conversation business identifier';

COMMENT ON COLUMN nexent.trajectory_execution_t.turn_no IS 'Serialized execution order; zero denotes a historical placeholder';

COMMENT ON COLUMN nexent.trajectory_execution_t.agent_id IS 'Actual root Agent for this execution';

COMMENT ON COLUMN nexent.trajectory_execution_t.agent_version_no IS 'Captured root Agent version; zero is a draft';

COMMENT ON COLUMN nexent.trajectory_execution_t.models IS 'Distinct physical model names, at most 1000 values';

COMMENT ON COLUMN nexent.trajectory_execution_t.status IS 'Capture availability or terminal business result';

COMMENT ON COLUMN nexent.trajectory_execution_t.started_at IS 'Observed execution start in UTC';

COMMENT ON COLUMN nexent.trajectory_execution_t.finished_at IS 'Observed execution finish in UTC';

COMMENT ON COLUMN nexent.trajectory_execution_t.duration_ms IS 'Root elapsed milliseconds, never a sum of child spans';

COMMENT ON COLUMN nexent.trajectory_execution_t.input_tokens IS 'Input tokens; NULL if any model call has unknown input usage';

COMMENT ON COLUMN nexent.trajectory_execution_t.output_tokens IS 'Output tokens; NULL if any model call has unknown output usage';

COMMENT ON COLUMN nexent.trajectory_execution_t.total_tokens IS 'Total tokens; NULL if any model call has unknown total usage';

COMMENT ON COLUMN nexent.trajectory_execution_t.create_time IS 'Creation time';

COMMENT ON COLUMN nexent.trajectory_execution_t.update_time IS 'Update time';

COMMENT ON COLUMN nexent.trajectory_execution_t.created_by IS 'Creator';

COMMENT ON COLUMN nexent.trajectory_execution_t.updated_by IS 'Updater';

COMMENT ON COLUMN nexent.trajectory_execution_t.delete_flag IS 'Whether it is deleted. Optional values: Y/N';

CREATE INDEX IF NOT EXISTS idx_trajectory_agent_started ON nexent.trajectory_execution_t (agent_id, started_at DESC, trajectory_id);

CREATE INDEX IF NOT EXISTS idx_trajectory_conversation_turn ON nexent.trajectory_execution_t (conversation_id, turn_no DESC) WHERE delete_flag = 'N';

CREATE INDEX IF NOT EXISTS idx_trajectory_models ON nexent.trajectory_execution_t USING gin (models);

CREATE INDEX IF NOT EXISTS idx_trajectory_started ON nexent.trajectory_execution_t (started_at DESC, trajectory_id);


CREATE TABLE IF NOT EXISTS nexent.trajectory_statistics_t (
	statistics_id UUID NOT NULL,
	scope_type VARCHAR(30) NOT NULL,
	scope_id VARCHAR(100) NOT NULL,
	conversation_count BIGINT,
	execution_count BIGINT,
	duration_sum_ms DOUBLE PRECISION,
	duration_mean_ms DOUBLE PRECISION,
	duration_sample_count BIGINT,
	duration_p50_ms DOUBLE PRECISION,
	duration_p90_ms DOUBLE PRECISION,
	duration_p99_ms DOUBLE PRECISION,
	conversation_duration_p50_ms DOUBLE PRECISION,
	conversation_duration_p90_ms DOUBLE PRECISION,
	conversation_duration_p99_ms DOUBLE PRECISION,
	conversation_duration_sample_count BIGINT,
	ttft_p50_ms DOUBLE PRECISION,
	ttft_p90_ms DOUBLE PRECISION,
	ttft_p99_ms DOUBLE PRECISION,
	ttft_sample_count BIGINT,
	computed_at TIMESTAMP WITH TIME ZONE,
	next_refresh_at TIMESTAMP WITH TIME ZONE,
	source_revision BIGINT DEFAULT 0 NOT NULL,
	computed_revision BIGINT DEFAULT 0 NOT NULL,
	complete BOOLEAN DEFAULT false NOT NULL,
	definition_version INTEGER DEFAULT 1 NOT NULL,
	create_time TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
	update_time TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
	created_by VARCHAR(100),
	updated_by VARCHAR(100),
	delete_flag VARCHAR(1) DEFAULT 'N',
	PRIMARY KEY (statistics_id)
)

;

COMMENT ON COLUMN nexent.trajectory_statistics_t.statistics_id IS 'UUID deterministically derived from scope';

COMMENT ON COLUMN nexent.trajectory_statistics_t.scope_type IS 'Statistics scope: tenant or global';

COMMENT ON COLUMN nexent.trajectory_statistics_t.scope_id IS 'Tenant identifier or global scope identifier';

COMMENT ON COLUMN nexent.trajectory_statistics_t.conversation_count IS 'All active conversations including uncaptured conversations';

COMMENT ON COLUMN nexent.trajectory_statistics_t.execution_count IS 'Actual executions excluding turn-zero placeholders';

COMMENT ON COLUMN nexent.trajectory_statistics_t.duration_sum_ms IS 'Sum of known readable root execution durations';

COMMENT ON COLUMN nexent.trajectory_statistics_t.duration_mean_ms IS 'Mean over known execution durations';

COMMENT ON COLUMN nexent.trajectory_statistics_t.duration_sample_count IS 'Number of valid execution duration samples';

COMMENT ON COLUMN nexent.trajectory_statistics_t.duration_p50_ms IS 'Execution duration percentile 50 with linear interpolation';

COMMENT ON COLUMN nexent.trajectory_statistics_t.duration_p90_ms IS 'Execution duration percentile 90 with linear interpolation';

COMMENT ON COLUMN nexent.trajectory_statistics_t.duration_p99_ms IS 'Execution duration percentile 99 with linear interpolation';

COMMENT ON COLUMN nexent.trajectory_statistics_t.conversation_duration_p50_ms IS 'Percentile 50 of complete per-conversation duration sums';

COMMENT ON COLUMN nexent.trajectory_statistics_t.conversation_duration_p90_ms IS 'Percentile 90 of complete per-conversation duration sums';

COMMENT ON COLUMN nexent.trajectory_statistics_t.conversation_duration_p99_ms IS 'Percentile 99 of complete per-conversation duration sums';

COMMENT ON COLUMN nexent.trajectory_statistics_t.conversation_duration_sample_count IS 'Number of valid conversation duration sums';

COMMENT ON COLUMN nexent.trajectory_statistics_t.ttft_p50_ms IS 'Model first-token percentile 50 from verified OTLP files';

COMMENT ON COLUMN nexent.trajectory_statistics_t.ttft_p90_ms IS 'Model first-token percentile 90 from verified OTLP files';

COMMENT ON COLUMN nexent.trajectory_statistics_t.ttft_p99_ms IS 'Model first-token percentile 99 from verified OTLP files';

COMMENT ON COLUMN nexent.trajectory_statistics_t.ttft_sample_count IS 'Number of valid model TTFT samples including zero';

COMMENT ON COLUMN nexent.trajectory_statistics_t.computed_at IS 'Publication time of the last complete snapshot';

COMMENT ON COLUMN nexent.trajectory_statistics_t.next_refresh_at IS 'Next background refresh deadline';

COMMENT ON COLUMN nexent.trajectory_statistics_t.source_revision IS 'Monotonic source change counter';

COMMENT ON COLUMN nexent.trajectory_statistics_t.computed_revision IS 'Source counter used by the published result';

COMMENT ON COLUMN nexent.trajectory_statistics_t.complete IS 'A complete snapshot has been published';

COMMENT ON COLUMN nexent.trajectory_statistics_t.definition_version IS 'Metric definition revision';

COMMENT ON COLUMN nexent.trajectory_statistics_t.create_time IS 'Creation time';

COMMENT ON COLUMN nexent.trajectory_statistics_t.update_time IS 'Update time';

COMMENT ON COLUMN nexent.trajectory_statistics_t.created_by IS 'Creator';

COMMENT ON COLUMN nexent.trajectory_statistics_t.updated_by IS 'Updater';

COMMENT ON COLUMN nexent.trajectory_statistics_t.delete_flag IS 'Whether it is deleted. Optional values: Y/N';

INSERT INTO nexent.trajectory_execution_t (trajectory_id,conversation_id,turn_no,agent_id,models,status,created_by,updated_by,delete_flag)

SELECT md5('trajectory:placeholder:' || c.conversation_id)::uuid,c.conversation_id,0,c.agent_id,'{}','not_captured',c.created_by,c.created_by,'N'

FROM nexent.conversation_record_t c WHERE c.delete_flag='N'

AND NOT EXISTS (SELECT 1 FROM nexent.trajectory_execution_t e WHERE e.conversation_id=c.conversation_id)

ON CONFLICT (trajectory_id) DO NOTHING;

COMMIT;
