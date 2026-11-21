-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
-- Read the durable marker written by the one-shot Workbench consolidation.
SELECT to_regclass('nexent.schema_migrations') IS NOT NULL AS has_migration_table \gset
\if :has_migration_table
SELECT CASE WHEN EXISTS (
    SELECT 1 FROM nexent.schema_migrations
    WHERE migration_id = '__once_shared_system_agents_v1'
) THEN 'complete' ELSE 'pending' END;
\else
SELECT 'pending';
\endif
