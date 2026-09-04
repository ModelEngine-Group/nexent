-- v2.5.4 Tag value usage-count covering index (redesign-unified-tag-management task 12.4)
--
-- Benchmark at the documented capacity limits (100 definitions / 1,000 values each /
-- 100 assignments per resource) showed that TagManagementDB._value_usage_count performs
-- a sequential scan of the tenant's assignments because no index starts with
-- (tenant_id, value_id). The definition-keyed path is already covered by
-- idx_resource_tag_assignment_definition; this partial index covers the value-keyed
-- path used when deleting / disabling a tag value and when reporting usage counts.
--
-- Partial (delete_flag = 'N') keeps the index small and matches the active-row filter
-- every caller applies. Idempotent via IF NOT EXISTS.

CREATE INDEX IF NOT EXISTS idx_resource_tag_assignment_value
    ON nexent.resource_tag_assignment (tenant_id, value_id, delete_flag)
    WHERE delete_flag = 'N';
