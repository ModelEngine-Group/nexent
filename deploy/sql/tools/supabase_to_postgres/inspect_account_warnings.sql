-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
-- Add contact details only when an existing account table has coverage gaps.
CREATE OR REPLACE FUNCTION pg_temp.inspect_accounts_with_warnings() RETURNS json LANGUAGE plpgsql AS $$
DECLARE
    state json := pg_temp.inspect_local_accounts();
    warnings json;
BEGIN
    IF (state->>'account_table')::boolean AND NOT (state->>'complete')::boolean THEN
        SELECT coalesce(json_agg(w ORDER BY w.user_id,w.user_email),'[]'::json) INTO warnings
        FROM (
            SELECT DISTINCT unresolved.user_id,
                coalesce(to_jsonb(a)->>'user_email',to_jsonb(a)->>'email',to_jsonb(u)->>'user_email') AS user_email
            FROM json_array_elements_text(state->'unresolved_ids') AS unresolved(user_id)
            LEFT JOIN nexent.user_account_t a ON a.user_id=unresolved.user_id
            LEFT JOIN nexent.user_tenant_t u ON u.user_id=unresolved.user_id AND u.delete_flag='N'
        ) w;
        RETURN state::jsonb || jsonb_build_object('account_warnings',warnings);
    END IF;
    RETURN state;
END
$$;
SELECT pg_temp.inspect_accounts_with_warnings();
