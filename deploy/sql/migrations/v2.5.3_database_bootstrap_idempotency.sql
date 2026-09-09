BEGIN;

-- Explicit seeded IDs do not advance SERIAL sequences. Re-synchronize the
-- sequence after every currently shipped migration and keep re-runs safe.
SELECT setval(
    pg_get_serial_sequence('nexent.role_permission_t', 'role_permission_id'),
    COALESCE(MAX(role_permission_id), 1),
    MAX(role_permission_id) IS NOT NULL
)
FROM nexent.role_permission_t;

-- The platform super-admin mapping intentionally uses an empty tenant ID. It
-- is not a tenant to provision, so ignore only that reserved mapping while
-- retaining normal provisioning for active tenant rows.
CREATE OR REPLACE FUNCTION nexent.provision_unified_tag_management_after_user_tenant_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(NEW.delete_flag, 'N') <> 'Y'
       AND NULLIF(btrim(NEW.tenant_id), '') IS NOT NULL THEN
        PERFORM nexent.provision_unified_tag_management(
            NEW.tenant_id,
            COALESCE(NEW.created_by, 'system')
        );
    END IF;
    RETURN NEW;
END;
$$;

COMMIT;
