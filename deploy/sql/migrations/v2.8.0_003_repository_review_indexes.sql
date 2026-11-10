-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Index the installation source relationship; reviews use the independent review table.
CREATE INDEX IF NOT EXISTS ix_ag_skill_info_repository_source
    ON nexent.ag_skill_info_t (tenant_id, source_repository_id)
    WHERE delete_flag <> 'Y';
