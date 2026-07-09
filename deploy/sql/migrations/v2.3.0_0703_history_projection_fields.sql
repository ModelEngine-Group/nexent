-- Migration: Add step_index for ReAct step tracking
-- Date: 2026-07-03 (revised 2026-07-09)
-- Description: Add step_index column to conversation_message_unit_t.
-- Drops previously added run_id, tool_call_id, event_time columns
-- that are no longer needed after review.

SET search_path TO nexent;
BEGIN;

-- Add step_index (renamed from step_id)
ALTER TABLE nexent.conversation_message_unit_t
    ADD COLUMN IF NOT EXISTS step_index INTEGER DEFAULT NULL;

COMMENT ON COLUMN nexent.conversation_message_unit_t.step_index IS
    'ReAct step sequence number within this message. Increments on step_count chunks.';

-- Drop columns from previous revision (idempotent)
ALTER TABLE nexent.conversation_message_unit_t
    DROP COLUMN IF EXISTS run_id;
ALTER TABLE nexent.conversation_message_unit_t
    DROP COLUMN IF EXISTS step_id;
ALTER TABLE nexent.conversation_message_unit_t
    DROP COLUMN IF EXISTS tool_call_id;
ALTER TABLE nexent.conversation_message_unit_t
    DROP COLUMN IF EXISTS event_time;
ALTER TABLE nexent.conversation_message_t
    DROP COLUMN IF EXISTS run_id;

-- Drop obsolete indexes
DROP INDEX IF EXISTS nexent.idx_message_unit_conversation_run;
DROP INDEX IF EXISTS nexent.idx_message_unit_tool_call;

-- New index for step-based queries
CREATE INDEX IF NOT EXISTS idx_message_unit_message_step
    ON nexent.conversation_message_unit_t (message_id, step_index);

COMMIT;
