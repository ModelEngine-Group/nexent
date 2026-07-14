-- Migration kind: REQUIRED_SCHEMA
-- Required for: agent-level file preprocess (conversation-level file Q&A) configuration.
-- Reason: new code reads/writes the per-agent file_preprocess config column.

ALTER TABLE nexent.ag_tenant_agent_t
  ADD COLUMN IF NOT EXISTS file_preprocess JSONB DEFAULT NULL;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.file_preprocess IS
  'Per-agent file preprocess config: {enable, config{rerank_top_n, max_parse_length, prompt_max_token_length, prompt_strategy_name, file_mode}}. NULL means use defaults.';
