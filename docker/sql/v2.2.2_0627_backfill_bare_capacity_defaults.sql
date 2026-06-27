-- Migration kind: RECOMMENDED_DATA_FIX
-- Required for: upgraded deployments where LLM/VLM rows still have NULL
--   capacity columns after the catalog backfill (v2.2.0_0617).
-- Safe to skip when: fresh deployment, or all LLM/VLM rows already have
--   context_window_tokens and max_output_tokens populated.
-- Reason: the catalog backfill only covers exact (model_factory, model_name)
--   matches. Rows added via the manual-add path (model_factory =
--   'OpenAI-API-Compatible' per CM-031) or any model not in the approved
--   catalog remain bare. This migration applies safe defaults so W2
--   output-token enforcement and W1 dispatch consistency checks activate.
--
-- Defaults match the save-time defaults in buildCapacityPayload:
--   context_window_tokens  = 32768
--   max_output_tokens      = 4096
--   default_output_reserve = 4096
--
-- Pre-run self-check:
--
--   SELECT model_id, model_name, model_factory, model_type,
--          context_window_tokens, max_output_tokens
--     FROM nexent.model_record_t
--    WHERE delete_flag = 'N'
--      AND COALESCE(model_type, 'llm') IN ('llm', 'vlm')
--      AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);
--
-- If the result is empty, this migration is a no-op and safe to skip.

-- ============================================================
-- Backfill bare LLM/VLM rows with safe capacity defaults
-- ============================================================
-- Idempotent: only writes when the target column IS NULL.
-- Scoped to LLM/VLM rows (embedding/rerank/stt/tts excluded).
-- capacity_source = 'operator' because these are operator-level defaults,
-- not catalog profile matches.

DO $$
DECLARE
    v_updated INTEGER := 0;
BEGIN
    UPDATE nexent.model_record_t
       SET context_window_tokens = CASE
               WHEN context_window_tokens IS NULL
               THEN GREATEST(32768, COALESCE(max_output_tokens, 0) + 1)
               ELSE context_window_tokens
           END,
           max_output_tokens = CASE
               WHEN max_output_tokens IS NULL
               THEN LEAST(4096, COALESCE(context_window_tokens, 32768) - 1)
               ELSE max_output_tokens
           END,
           default_output_reserve_tokens = COALESCE(default_output_reserve_tokens, 4096),
           capacity_source = COALESCE(capacity_source, 'operator')
     WHERE delete_flag = 'N'
       AND COALESCE(model_type, 'llm') IN ('llm', 'vlm')
       AND (context_window_tokens IS NULL OR max_output_tokens IS NULL);

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RAISE NOTICE 'Bare capacity defaults: % LLM/VLM row(s) backfilled', v_updated;
END $$;

-- ============================================================
-- Reconcile the legacy max_tokens column with max_output_tokens
-- ============================================================
-- Same reconcile as v2.2.0_0617 but scoped to the rows this migration
-- just touched, plus any rows that gained max_output_tokens since the
-- last reconcile run.

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
