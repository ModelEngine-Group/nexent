-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.knowledge_legacy_file_identity_t
    ADD COLUMN IF NOT EXISTS activated_at TIMESTAMPTZ;

COMMENT ON COLUMN nexent.knowledge_legacy_file_identity_t.activated_at IS
    'Set in the same transaction that moves the lifecycle row to the standard ID.';
