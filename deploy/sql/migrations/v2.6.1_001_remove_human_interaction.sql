-- Deploy only after all processes using the retired interaction engine have stopped.
-- Ordinary conversation messages and units are intentionally preserved.
DROP TABLE IF EXISTS nexent.human_event_t;
DROP TABLE IF EXISTS nexent.human_execution_t;
DROP TABLE IF EXISTS nexent.human_request_t;
DROP TABLE IF EXISTS nexent.human_run_t;
-- This function is used exclusively by the four tables removed above.
DROP FUNCTION IF EXISTS nexent.human_interaction_audit_timestamp();
