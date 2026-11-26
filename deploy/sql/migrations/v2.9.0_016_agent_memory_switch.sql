-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.ag_tenant_agent_t
    ADD COLUMN IF NOT EXISTS enable_memory BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.enable_memory IS
    'Whether this Agent version permits automatic memory operations';
