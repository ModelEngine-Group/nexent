-- Context-budget P1 nullable governance metadata.
-- Fresh installs and upgrades both replay this idempotent migration after the
-- deploy/sql/init.sql baseline. No row backfill or network work is performed.

SET search_path TO nexent;

BEGIN;

ALTER TABLE nexent.model_record_t
    ADD COLUMN IF NOT EXISTS canonical_model_id VARCHAR(512) DEFAULT NULL;

ALTER TABLE nexent.model_record_t
    ADD COLUMN IF NOT EXISTS capacity_field_metadata JSONB DEFAULT NULL;

ALTER TABLE nexent.model_record_t
    ADD COLUMN IF NOT EXISTS model_identity_metadata JSONB DEFAULT NULL;

ALTER TABLE nexent.model_record_t
    ADD COLUMN IF NOT EXISTS tokenizer_match_metadata JSONB DEFAULT NULL;

ALTER TABLE nexent.model_record_t
    ADD COLUMN IF NOT EXISTS token_count_probe_metadata JSONB DEFAULT NULL;

COMMENT ON COLUMN nexent.model_record_t.canonical_model_id IS
    'Versioned canonical model identity used for independent capacity and tokenizer matching.';
COMMENT ON COLUMN nexent.model_record_t.capacity_field_metadata IS
    'Versioned field-level source, confidence, evidence, and verification metadata. Contains no secrets.';
COMMENT ON COLUMN nexent.model_record_t.model_identity_metadata IS
    'Versioned canonical parsing and capacity-match evidence. Contains no credentials or raw payloads.';
COMMENT ON COLUMN nexent.model_record_t.tokenizer_match_metadata IS
    'Versioned independent tokenizer profile match and conformance state.';
COMMENT ON COLUMN nexent.model_record_t.token_count_probe_metadata IS
    'Versioned sanitized Provider token-count capability probe state. Contains no keys or raw bodies.';

COMMIT;
