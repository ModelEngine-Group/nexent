-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
ALTER TABLE nexent.ag_skill_instance_t ADD COLUMN IF NOT EXISTS released_catalog_entry json;
COMMENT ON COLUMN nexent.ag_skill_instance_t.released_catalog_entry IS
    'Version-specific Skill discovery description from independent evaluation. SQL NULL inherits the shared catalog.';
