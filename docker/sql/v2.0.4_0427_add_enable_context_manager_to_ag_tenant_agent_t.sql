-- Migration: Add enable_context_manager column to ag_tenant_agent_t table
-- Date: 2025-04-27
-- Description: Add enable_context_manager field to control context management (compression) per agent

-- Add enable_context_manager column to ag_tenant_agent_t table
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS enable_context_manager BOOLEAN DEFAULT FALSE;

-- Add comment to the column
COMMENT ON COLUMN nexent.ag_tenant_agent_t.enable_context_manager IS 'Whether to enable context management (compression) for this agent';