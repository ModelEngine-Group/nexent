-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.knowledge_record_t ADD COLUMN IF NOT EXISTS group_permissions JSONB;
ALTER TABLE nexent.ag_tenant_agent_t ADD COLUMN IF NOT EXISTS group_permissions JSONB;

COMMENT ON COLUMN nexent.knowledge_record_t.group_permissions IS 'Explicit tenant group read or edit grants, null for legacy sharing';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.group_permissions IS 'Explicit tenant group read or edit grants, null for legacy sharing';
