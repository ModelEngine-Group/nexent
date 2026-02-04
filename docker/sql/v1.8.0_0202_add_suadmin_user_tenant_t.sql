INSERT INTO nexent.user_tenant_t (user_id, tenant_id, user_role, user_email, created_by, updated_by)
VALUES ('suadmin', '', 'SU', NULL, 'system', 'system')
ON CONFLICT (user_id, tenant_id) DO NOTHING;
