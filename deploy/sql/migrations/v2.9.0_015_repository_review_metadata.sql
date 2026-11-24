-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Preserve the installation source link independently of resource review storage.

ALTER TABLE nexent.ag_skill_info_t
    ADD COLUMN IF NOT EXISTS source_repository_id BIGINT NULL;
COMMENT ON COLUMN nexent.ag_skill_info_t.source_repository_id IS
    'Source Skill repository listing ID for an installed copy; NULL when not associated';

-- Historical identities, business timestamps and installation sources are not inferred.
-- Query indexes will be added with the actual query implementation and plan evidence.
