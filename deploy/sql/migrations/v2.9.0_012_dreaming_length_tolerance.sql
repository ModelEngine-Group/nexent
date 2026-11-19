-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.memory_dreaming_schedule_t
    ADD COLUMN IF NOT EXISTS long_term_length_tolerance_percent INTEGER
        CONSTRAINT ck_memory_dreaming_length_tolerance
        CHECK (long_term_length_tolerance_percent BETWEEN 0 AND 100);
