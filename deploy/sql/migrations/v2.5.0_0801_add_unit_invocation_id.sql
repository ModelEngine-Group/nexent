-- Persist `invocation_id` on message units so the frontend can attribute
-- model deep-thinking output to the correct sub-agent card on history replay.

SET search_path TO nexent;

ALTER TABLE nexent.conversation_message_unit_t
    ADD COLUMN IF NOT EXISTS invocation_id VARCHAR(36);

COMMENT ON COLUMN nexent.conversation_message_unit_t.invocation_id IS
    'Identifies which sub-agent invocation produced this unit. Used by the '
    'frontend history adapter to route deep-thinking / reasoning chunks into '
    'the correct nested sub-agent card.';
