-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Nexent merged SQL migrations: v2.10.0
-- Previous release tag: v2.9.0
-- Source bodies are embedded in deployment order, byte-for-byte except for
-- each source file's leading copyright line, which appears once above.
-- Do not reorder or rewrite sections without equivalence validation.

-- Source migration: v2.10.0_001_purge_ghost_tenant_name_rows.sql
-- One-time cleanup for the deleted-tenant read-backfill defect: soft-delete
-- active TENANT_NAME rows whose tenant has no live TENANT_ID identity row.
-- Such name-only rows made deleted tenants reappear in listings and let other
-- consumers keep counting them. NOT EXISTS (instead of NOT IN) keeps NULL
-- tenant_ids from vacating the predicate. Idempotent: re-running affects 0 rows.
UPDATE nexent.tenant_config_t AS t
    SET delete_flag = 'Y',
        updated_by = 'system',
        update_time = NOW()
    WHERE t.config_key = 'TENANT_NAME'
      AND t.delete_flag = 'N'
      AND NOT EXISTS (
          SELECT 1
            FROM nexent.tenant_config_t AS c
           WHERE c.tenant_id = t.tenant_id
             AND c.config_key = 'TENANT_ID'
             AND c.delete_flag = 'N'
      );
