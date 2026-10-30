-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Preserve the existing hard output cap; store the LLM request default once.
ALTER TABLE nexent.model_record_t
    ADD COLUMN IF NOT EXISTS default_max_output_tokens INTEGER;
COMMENT ON COLUMN nexent.model_record_t.default_max_output_tokens IS
    'Saved LLM request output default; separate from the hard output cap. NULL omitted unless explicitly marked null.';
