-- Reconcile the legacy max_tokens column with max_output_tokens on existing
-- LLM/VLM rows where the two have diverged.
--
-- Why this migration exists: W1 step 7 deprecates `max_tokens` as a temporary
-- output-cap alias of `max_output_tokens`, but the per-model gear icon dialog
-- (ProviderConfigEditDialog) shipped before this fix rendered both inputs side
-- by side, letting an operator save them independently. Together with the
-- 2026-06-17 W2 catalog backfill — which writes max_output_tokens without
-- touching max_tokens — this produced rows where the SDK auto-fills max_tokens
-- from the legacy column at chat-completion time, the W2 snapshot computes its
-- output cap from max_output_tokens, and the W2 dispatch boundary then rejects
-- the divergent caller value as CallerMaxTokensOverrideForbidden (CM-030).
--
-- Observed example before this migration: glm-5.1 / dashscope had
-- max_tokens=204800 and max_output_tokens=131072, breaking the "数学思考"
-- assistant end-to-end.
--
-- Scope and safety:
--   * Only touches rows where max_output_tokens IS NOT NULL — the authoritative
--     value per the W1 design.
--   * Skips embedding rows because they reuse max_tokens as the vector
--     dimension (see W1 spec, Phases section).
--   * Only updates rows where the two columns actually disagree, so re-running
--     is a no-op.
--   * delete_flag = 'N' so soft-deleted rows are left alone.
--
-- A matching service-layer coercion (_coerce_legacy_max_tokens_alias) keeps
-- new writes in sync going forward; this SQL closes the gap for rows persisted
-- before that coercion shipped.

DO $$
DECLARE
    v_updated INTEGER := 0;
BEGIN
    UPDATE nexent.model_record_t
       SET max_tokens = max_output_tokens
     WHERE delete_flag = 'N'
       AND max_output_tokens IS NOT NULL
       AND COALESCE(max_tokens, -1) <> max_output_tokens
       AND COALESCE(model_type, '') NOT IN ('embedding', 'multi_embedding');

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RAISE NOTICE 'max_tokens alias reconcile: % row(s) updated', v_updated;
END $$;
