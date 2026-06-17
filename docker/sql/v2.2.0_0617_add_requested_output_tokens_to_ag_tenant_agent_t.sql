ALTER TABLE nexent.ag_tenant_agent_t
  ADD COLUMN IF NOT EXISTS requested_output_tokens INTEGER NULL;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.requested_output_tokens IS
  'Per-agent override for W2 requested_output_tokens. NULL means inherit '
  'the resolved model-level default. Must satisfy 0 < value <= '
  'max_output_tokens from the resolved W1 capacity at save time.';
