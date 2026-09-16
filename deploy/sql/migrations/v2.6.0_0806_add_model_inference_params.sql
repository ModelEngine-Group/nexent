-- Migration kind: REQUIRED_SCHEMA
-- Required for: model inference params (temperature/top_p) defaults on model_record_t
--                + extra_params JSONB for fixed inference params without dedicated columns
--                and per-agent model param overrides on ag_tenant_agent_t.
-- Reason: new code reads/writes these inference parameter columns and per-agent overrides.

SET search_path TO nexent;

-- ============================================================
-- model_record_t: 推理参数默认值（常用，独立列便于校验/查询）
-- ============================================================

ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS temperature FLOAT DEFAULT NULL;

ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS top_p FLOAT DEFAULT NULL;

COMMENT ON COLUMN nexent.model_record_t.temperature IS
  'Default sampling temperature for LLM/VLM models. NULL means provider default. Nullable.';
COMMENT ON COLUMN nexent.model_record_t.top_p IS
  'Default nucleus sampling probability for LLM/VLM models. NULL means provider default. Nullable.';

-- ============================================================
-- model_record_t: 其他固定推理参数（frequency_penalty/presence_penalty/stop/seed/voice/speed 等）
-- 无独立列的固定字段统一收纳到此 JSONB 列，键集合由后端 FIXED_INFERENCE_FIELDS_BY_TYPE 约束
-- ============================================================

ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS extra_params JSONB DEFAULT NULL;

COMMENT ON COLUMN nexent.model_record_t.extra_params IS
  'Fixed inference params without dedicated columns (key-value pairs constrained by '
  'FIXED_INFERENCE_FIELDS_BY_TYPE). NULL means no extra params.';

-- ============================================================
-- ag_tenant_agent_t: per-agent 模型参数覆盖（含预定义字段与 extra_params）
-- Shape: {"<model_id>": {"temperature": 0.5, "top_p": null, "extra_params": {...}}}
-- ============================================================

ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS model_params_override JSONB DEFAULT NULL;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.model_params_override IS
  'Per-agent overrides for model inference params. Shape: '
  '{"<model_id>": {"temperature": 0.5, "top_p": null, "extra_params": {...}}}. '
  'NULL means inherit model defaults.';
