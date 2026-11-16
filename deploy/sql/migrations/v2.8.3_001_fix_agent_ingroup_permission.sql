-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- Normalize legacy agent in-group permission values left by the pre-redesign
-- deployment form. The classic form saved "EDITABLE" for the "editable" option,
-- while backend draft-edit authorization (require_agent_draft_edit) only
-- accepts the exact value "EDIT". Agents saved through the legacy form stayed
-- read-only for non-creator, non-admin users even though the UI showed them
-- as editable, and removing/configuring tools on such agents failed with
-- agent_read_only. Align the stored value with the canonical enum so existing
-- agents match what the UI intended.
--
-- Scope notes:
--   - Case variants (e.g. "editable") are covered via UPPER().
--   - NULL is intentionally untouched: it means "not configured" and resolves
--     to READ_ONLY by design.
--   - "INHERIT" is intentionally untouched: its inheritance semantics for
--     draft-edit are a separate product decision.
--   - Idempotent: re-running matches no rows. Safe under the migration
--     runner's reapply-on-checksum-change behavior.

UPDATE nexent.ag_tenant_agent_t
SET ingroup_permission = 'EDIT'
WHERE UPPER(ingroup_permission) = 'EDITABLE';
