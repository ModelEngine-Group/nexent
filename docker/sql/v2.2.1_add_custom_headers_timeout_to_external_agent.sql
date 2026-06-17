-- Migration: Add custom_headers and timeout columns to ag_a2a_external_agent_t
-- Date: 2026-06-17
-- Description: Support custom HTTP headers and configurable timeout per A2A external agent.
--   - custom_headers: user-defined HTTP headers sent with every request to this agent
--   - timeout: per-agent request timeout in seconds (default 300)

SET search_path TO nexent;

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'nexent'
        AND table_name = 'ag_a2a_external_agent_t'
        AND column_name = 'custom_headers'
    ) THEN
        ALTER TABLE nexent.ag_a2a_external_agent_t
        ADD COLUMN custom_headers JSON DEFAULT NULL;

        COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.custom_headers
            IS 'Custom HTTP headers as JSON object for A2A agent requests';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'nexent'
        AND table_name = 'ag_a2a_external_agent_t'
        AND column_name = 'timeout'
    ) THEN
        ALTER TABLE nexent.ag_a2a_external_agent_t
        ADD COLUMN timeout DOUBLE PRECISION DEFAULT 300.0;

        COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.timeout
            IS 'Request timeout in seconds for calling this agent (default 300)';
    END IF;
END $$;

COMMIT;
