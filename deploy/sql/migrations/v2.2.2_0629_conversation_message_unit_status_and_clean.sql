-- Migration: Add status / unit_status fields to support streaming persistence
-- Date: 2026-06-29
-- Description: Allow per-message and per-unit lifecycle tracking so the
-- frontend can recover partial agent runs when the SSE connection is lost

SET search_path TO nexent;

BEGIN;

-- Message-level lifecycle. Assistant messages start as 'pending' / 'streaming'
-- and transition to one of completed / failed / stopped. User messages default
-- to 'completed' (existing rows are backfilled below).
ALTER TABLE nexent.conversation_message_t
    ADD COLUMN IF NOT EXISTS status VARCHAR(30);

COMMENT ON COLUMN nexent.conversation_message_t.status IS
    'Lifecycle status: pending / streaming / completed / failed / stopped.';

-- Unit-level lifecycle. Once a unit is fully persisted we mark it 'completed';
-- while the boundary is still being detected it remains 'streaming'.
ALTER TABLE nexent.conversation_message_unit_t
    ADD COLUMN IF NOT EXISTS unit_status VARCHAR(30);

COMMENT ON COLUMN nexent.conversation_message_unit_t.unit_status IS
    'Lifecycle status: streaming (still aggregating) or completed (fully persisted).';

-- Index for incremental recovery queries (since_message_unit_id filters).
CREATE INDEX IF NOT EXISTS idx_message_unit_message_id_unit_id
    ON nexent.conversation_message_unit_t (message_id, unit_id);

-- Cleanup stale deep_thinking units.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'nexent'
          AND table_name = 'conversation_message_unit_t'
          AND column_name = 'unit_status'
    ) THEN
        DELETE FROM nexent.conversation_message_unit_t
        WHERE unit_type = 'model_output_deep_thinking'
          AND unit_status IS NULL;
    END IF;
END $$;

-- Cleanup corrupted records of thinking units
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'nexent'
          AND table_name = 'conversation_message_unit_t'
          AND column_name = 'unit_status'
    ) THEN
        DELETE FROM nexent.conversation_message_unit_t
        WHERE unit_type = 'model_output_thinking'
          AND unit_content = ''
          AND unit_status IS NULL;
    END IF;
END $$;

COMMIT;
