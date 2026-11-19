-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- v2.8.5_002_dreaming_user_config.sql copies the parameters before this cleanup.
ALTER TABLE nexent.memory_dreaming_schedule_t
    DROP CONSTRAINT IF EXISTS ck_memory_dreaming_length_tolerance,
    DROP COLUMN IF EXISTS min_score,
    DROP COLUMN IF EXISTS min_recall_count,
    DROP COLUMN IF EXISTS min_unique_queries,
    DROP COLUMN IF EXISTS source_limit,
    DROP COLUMN IF EXISTS long_term_max_chars,
    DROP COLUMN IF EXISTS long_term_length_tolerance_percent,
    DROP COLUMN IF EXISTS summarization_max_attempts;
