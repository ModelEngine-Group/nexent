-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
ALTER TABLE nexent.ag_a2a_external_agent_t
    ADD COLUMN IF NOT EXISTS ssl_verify BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN nexent.ag_a2a_external_agent_t.ssl_verify IS
    'Verify peer TLS certificates for Agent Card retrieval and A2A invocation';
