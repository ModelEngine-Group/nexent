-- ============================================================
-- Strip legacy AIDP credentials from tool instance params.
-- Migration Date: 2026-07-23
-- Description:
--   Earlier versions of the aidp_search tool accepted ``server_url`` and
--   ``api_key`` via the per-instance params (sometimes stored in plain
--   text in browser localStorage). The v7.1 permission redesign makes
--   Nexent the sole owner of those credentials, sourced from the
--   AIDP_SERVER_URL / AIDP_API_KEY environment variables.
--
--   This migration removes any persisted ``server_url`` / ``api_key``
--   entries from ``ag_tool_instance_t.params`` for ``aidp_search`` tool
--   instances so historical rows do not leak the old value.
--
-- Idempotent: rewrites params only when at least one of the keys is
-- present; safe to re-run.
-- ============================================================

BEGIN;

UPDATE nexent.ag_tool_instance_t instance
SET params = (
    REPLACE(
        REPLACE(instance.params::text, '"server_url"', '"_removed_server_url"'),
        '"api_key"', '"_removed_api_key"'
    )::jsonb - '_removed_server_url' - '_removed_api_key'
)::text::json
FROM nexent.ag_tool_info_t tool
WHERE instance.tool_id = tool.tool_id
  AND tool.name = 'aidp_search'
  AND instance.delete_flag = 'N'
  AND instance.params IS NOT NULL
  AND (
      instance.params::text LIKE '%server_url%'
      OR instance.params::text LIKE '%api_key%'
  );

-- Validation query (manual):
--   SELECT COUNT(*) FROM nexent.ag_tool_instance_t instance
--   JOIN nexent.ag_tool_info_t tool ON instance.tool_id = tool.tool_id
--   WHERE tool.name = 'aidp_search'
--     AND instance.delete_flag = 'N'
--     AND instance.params::text LIKE '%server_url%';

COMMIT;
