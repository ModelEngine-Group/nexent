-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

ALTER TABLE nexent.tenant_group_info_t
    ADD COLUMN IF NOT EXISTS parent_group_id INTEGER,
    ADD COLUMN IF NOT EXISTS casdoor_scope VARCHAR(64),
    ADD COLUMN IF NOT EXISTS casdoor_group_key VARCHAR(200);

COMMENT ON COLUMN nexent.tenant_group_info_t.parent_group_id IS 'Parent group identifier in the same tenant, null for a root group';
COMMENT ON COLUMN nexent.tenant_group_info_t.casdoor_scope IS 'Hash of the Casdoor endpoint and organization for a mirrored group';
COMMENT ON COLUMN nexent.tenant_group_info_t.casdoor_group_key IS 'Casdoor internal group name and creation time for a mirrored group';
