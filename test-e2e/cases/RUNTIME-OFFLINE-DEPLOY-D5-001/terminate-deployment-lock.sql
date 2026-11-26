-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

WITH lock_key AS (
    SELECT hashtextextended('nexent:runtime:deployment', 0) AS value
), holder AS (
    SELECT min(held.pid) AS pid
    FROM pg_locks AS held
    JOIN pg_stat_activity AS connection USING (pid)
    CROSS JOIN lock_key
    WHERE held.locktype = 'advisory' AND held.granted AND held.mode = 'ExclusiveLock'
      AND held.classid = ((lock_key.value >> 32) & 4294967295)::oid
      AND held.objid = (lock_key.value & 4294967295)::oid AND held.objsubid = 1
      AND connection.datname = current_database() AND connection.usename = current_user
      AND connection.application_name = :'lock_name' AND connection.pid <> pg_backend_pid()
    HAVING count(*) = 1
)
SELECT pid, pg_terminate_backend(pid) FROM holder;
