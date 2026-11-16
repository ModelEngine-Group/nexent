-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.ag_tenant_agent_t
    ADD COLUMN IF NOT EXISTS enable_memory BOOLEAN NOT NULL DEFAULT TRUE;
