-- Migration kind: RECOMMENDED_DATA_FIX
-- Required for: upgraded deployments with existing model_record_t rows
--   whose (model_factory, model_name) now match expanded catalog entries.
-- Safe to skip when: fresh deployment, or no matching rows exist.
-- Reason: the v2.2.0_0617 catalog backfill only covered 10 model entries.
--   This migration extends coverage to 54 additional SiliconFlow-hosted models.
--
-- Idempotent: only writes when context_window_tokens IS NULL.
-- Catalog source of truth: backend/consts/capability_profiles.py
--   CATALOG_REVISION 2026-06-27.1

-- Pre-run self-check:
--
--   SELECT model_id, model_name, model_factory,
--          context_window_tokens, max_output_tokens
--     FROM nexent.model_record_t
--    WHERE delete_flag = 'N'
--      AND context_window_tokens IS NULL
--      AND (
--        (LOWER(model_factory) = 'deepseek')
--        OR (LOWER(model_factory) = 'silicon')
--      );
--
-- If the result is empty, this migration is a no-op and safe to skip.

DO $$
DECLARE
    v_updated INTEGER := 0;
    v_total   INTEGER := 0;
BEGIN
    -- deepseek models on SiliconFlow (11 entries)
    UPDATE nexent.model_record_t
       SET context_window_tokens = 1048576,
           max_output_tokens = 384000,
           default_output_reserve_tokens = 8192
     WHERE LOWER(model_factory) = 'deepseek'
       AND model_name = 'deepseek-ai/DeepSeek-V4-Pro'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 1048576,
           max_output_tokens = 384000,
           default_output_reserve_tokens = 8192
     WHERE LOWER(model_factory) = 'deepseek'
       AND model_name = 'deepseek-ai/DeepSeek-V4-Flash'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 164000,
           max_output_tokens = 8192,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'deepseek'
       AND model_name = 'deepseek-ai/DeepSeek-V3.2'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 164000,
           max_output_tokens = 8192,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'deepseek'
       AND model_name = 'deepseek-ai/DeepSeek-V3.1-Terminus'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 163840,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 8192
     WHERE LOWER(model_factory) = 'deepseek'
       AND model_name = 'deepseek-ai/DeepSeek-R1'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 164000,
           max_output_tokens = 8192,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'deepseek'
       AND model_name = 'deepseek-ai/DeepSeek-V3'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 131072,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'deepseek'
       AND model_name = 'deepseek-ai/DeepSeek-R1-0528-Qwen3-8B'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 164000,
           max_output_tokens = 8192,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'deepseek'
       AND model_name = 'Pro/deepseek-ai/DeepSeek-V3.2'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 164000,
           max_output_tokens = 8192,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'deepseek'
       AND model_name = 'Pro/deepseek-ai/DeepSeek-V3.1-Terminus'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 163840,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 8192
     WHERE LOWER(model_factory) = 'deepseek'
       AND model_name = 'Pro/deepseek-ai/DeepSeek-R1'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 164000,
           max_output_tokens = 8192,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'deepseek'
       AND model_name = 'Pro/deepseek-ai/DeepSeek-V3'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    -- silicon models on SiliconFlow (43 entries)
    UPDATE nexent.model_record_t
       SET context_window_tokens = 262144,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen3.6-35B-A3B'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 262144,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen3.5-397B-A17B'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 262144,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen3.5-122B-A10B'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 262144,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen3.5-35B-A3B'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 262144,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen3.5-27B'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 262144,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen3.5-9B'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 262144,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen3.5-4B'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 262144,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen3-VL-32B-Instruct'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 262144,
           max_output_tokens = 32768,
           default_output_reserve_tokens = 8192
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen3-VL-32B-Thinking'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 262144,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen3-VL-8B-Instruct'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 262144,
           max_output_tokens = 32768,
           default_output_reserve_tokens = 8192
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen3-VL-8B-Thinking'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 262144,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen3-VL-30B-A3B-Instruct'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 262144,
           max_output_tokens = 32768,
           default_output_reserve_tokens = 8192
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen3-VL-30B-A3B-Thinking'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 32768,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen3-Omni-30B-A3B-Instruct'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 32768,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen3-Omni-30B-A3B-Thinking'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 32768,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen3-Omni-30B-A3B-Captioner'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 262144,
           max_output_tokens = 65536,
           default_output_reserve_tokens = 8192
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen3-Coder-30B-A3B-Instruct'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 262144,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen3-30B-A3B-Instruct-2507'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 131072,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen3-32B'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 131072,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen3-14B'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 131072,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen3-8B'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 131072,
           max_output_tokens = 8192,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen2.5-72B-Instruct-128K'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 32768,
           max_output_tokens = 8192,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen2.5-72B-Instruct'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 32768,
           max_output_tokens = 8192,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen2.5-32B-Instruct'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 32768,
           max_output_tokens = 8192,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen2.5-14B-Instruct'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 32768,
           max_output_tokens = 8192,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Qwen/Qwen2.5-7B-Instruct'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 32768,
           max_output_tokens = 8192,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'THUDM/GLM-4-32B-0414'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 32768,
           max_output_tokens = 8192,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'THUDM/GLM-Z1-9B-0414'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 32768,
           max_output_tokens = 8192,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'THUDM/GLM-4-9B-0414'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 1048576,
           max_output_tokens = 131072,
           default_output_reserve_tokens = 8192
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'zai-org/GLM-5.2'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 131072,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'zai-org/GLM-4.5V'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 131072,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'zai-org/GLM-4.5-Air'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 202752,
           max_output_tokens = 131072,
           default_output_reserve_tokens = 8192
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Pro/zai-org/GLM-5.1'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 524288,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'ByteDance-Seed/Seed-OSS-36B-Instruct'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 131072,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'inclusionAI/Ling-flash-2.0'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 131072,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'inclusionAI/Ling-mini-2.0'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 204800,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'MiniMaxAI/MiniMax-M2.5'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 204800,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'Pro/MiniMaxAI/MiniMax-M2.5'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 262144,
           max_output_tokens = 32768,
           default_output_reserve_tokens = 8192
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'moonshotai/Kimi-K2.7-Code'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 262144,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'nex-agi/Nex-N2-Pro'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 262144,
           max_output_tokens = 16384,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'stepfun-ai/Step-3.5-Flash'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 32768,
           max_output_tokens = 2048,
           default_output_reserve_tokens = 1024
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'tencent/Hunyuan-MT-7B'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    UPDATE nexent.model_record_t
       SET context_window_tokens = 131072,
           max_output_tokens = 8192,
           default_output_reserve_tokens = 4096
     WHERE LOWER(model_factory) = 'silicon'
       AND model_name = 'tencent/Hunyuan-A13B-Instruct'
       AND delete_flag = 'N'
       AND context_window_tokens IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    v_total := v_total + v_updated;

    RAISE NOTICE 'W11 expanded catalog backfill: % row(s) updated', v_total;
END $$;

-- Reconcile the legacy max_tokens column with max_output_tokens
-- for rows touched by this migration.

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
