-- Migration kind: REQUIRED_SCHEMA
-- Required for: conversation file mode tracking (full_text_reference vs chunk_search).
-- Reason: each file record needs to store which processing mode was used.

ALTER TABLE nexent.conversation_file_t
    ADD COLUMN IF NOT EXISTS file_mode VARCHAR(32) DEFAULT 'full_text_reference';

COMMENT ON COLUMN nexent.conversation_file_t.file_mode IS
    'Processing mode: full_text_reference or chunk_search';
