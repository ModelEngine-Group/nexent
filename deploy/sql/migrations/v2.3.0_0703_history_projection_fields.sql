-- Migration: Add history projection fields for ReAct process persistence
-- Date: 2026-07-03
-- Description: Add run_id, step_id, tool_call_id, event_time columns to
-- conversation_message_unit_t and run_id to conversation_message_t so the
-- frontend can reconstruct ReAct step timelines from persisted history.

SET search_path TO nexent;

BEGIN;

-- Unit-level: agent run sequence number
ALTER TABLE nexent.conversation_message_unit_t
    ADD COLUMN IF NOT EXISTS run_id INTEGER DEFAULT NULL;

COMMENT ON COLUMN nexent.conversation_message_unit_t.run_id IS
    'Agent run sequence number within this conversation. Increments per new agent invocation.';

-- Unit-level: ReAct step sequence number
ALTER TABLE nexent.conversation_message_unit_t
    ADD COLUMN IF NOT EXISTS step_id INTEGER DEFAULT NULL;

COMMENT ON COLUMN nexent.conversation_message_unit_t.step_id IS
    'ReAct step sequence number within this run. Increments on step_count chunks.';

-- Unit-level: tool call pairing UUID
ALTER TABLE nexent.conversation_message_unit_t
    ADD COLUMN IF NOT EXISTS tool_call_id VARCHAR(100) DEFAULT NULL;

COMMENT ON COLUMN nexent.conversation_message_unit_t.tool_call_id IS
    'UUID pairing tool call with its execution result. NULL for non-tool units.';

-- Unit-level: actual event timestamp
ALTER TABLE nexent.conversation_message_unit_t
    ADD COLUMN IF NOT EXISTS event_time TIMESTAMP DEFAULT NULL;

COMMENT ON COLUMN nexent.conversation_message_unit_t.event_time IS
    'Actual event timestamp when chunk was processed. Not batch insert time.';

-- Message-level: agent run sequence number
ALTER TABLE nexent.conversation_message_t
    ADD COLUMN IF NOT EXISTS run_id INTEGER DEFAULT NULL;

COMMENT ON COLUMN nexent.conversation_message_t.run_id IS
    'Agent run sequence number. Matches unit run_id for assistant messages.';

-- Index for history projection queries (filter by conversation + run)
CREATE INDEX IF NOT EXISTS idx_message_unit_conversation_run
    ON nexent.conversation_message_unit_t (conversation_id, run_id);

-- Index for tool call pairing lookups
CREATE INDEX IF NOT EXISTS idx_message_unit_tool_call
    ON nexent.conversation_message_unit_t (message_id, tool_call_id);

COMMIT;
