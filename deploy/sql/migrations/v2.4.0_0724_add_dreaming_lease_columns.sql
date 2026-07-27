-- Add worker lease columns to the Dreaming audit table so the executor can
-- claim, renew, and release row-level leases with FOR UPDATE SKIP LOCKED.
SET search_path TO nexent;
BEGIN;

ALTER TABLE nexent.memory_dreaming_audit_t
    ADD COLUMN IF NOT EXISTS lock_owner VARCHAR(100);

ALTER TABLE nexent.memory_dreaming_audit_t
    ADD COLUMN IF NOT EXISTS lock_until TIMESTAMP;

COMMIT;
