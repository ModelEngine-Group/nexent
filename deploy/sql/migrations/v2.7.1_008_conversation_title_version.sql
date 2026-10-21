-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.conversation_record_t
    ADD COLUMN IF NOT EXISTS title_version INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN nexent.conversation_record_t.title_version IS
    'Monotonic title revision; every stored rename advances it independently of activity';
