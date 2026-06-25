-- Migration: Add greeting_message and example_questions columns to ag_tenant_agent_t table
-- Date: 2026-06-03
-- Description: Add greeting message and example questions fields for agent chat initial screen

-- Add greeting_message column to ag_tenant_agent_t table
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS greeting_message TEXT;

-- Add example_questions column to ag_tenant_agent_t table
ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS example_questions JSONB;

-- Add comments to the columns
COMMENT ON COLUMN nexent.ag_tenant_agent_t.greeting_message IS 'Agent greeting message displayed on chat initial screen';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.example_questions IS 'List of example questions for starting a conversation with this agent';