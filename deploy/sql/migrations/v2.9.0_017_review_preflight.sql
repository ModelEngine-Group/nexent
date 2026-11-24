-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

-- The deployment preflight runs this block read-only. The import repeats it
-- under the repository locks and writes the exact records it validated.
DO $review_upgrade$
DECLARE
    importing boolean := coalesce(current_setting('nexent.import_legacy_reviews', true), '') = 'on';
    imported boolean := false;
    candidate record;
    submitter text;
    archive_size integer;
    problems integer := 0;
BEGIN
    IF to_regclass('nexent.schema_migrations') IS NOT NULL THEN
        SELECT EXISTS (
            SELECT 1 FROM nexent.schema_migrations WHERE status IN ('applied','baselined')
            AND migration_id IN ('v2.8.0_004_resource_review_submissions.sql',
                                 'v2.9.0_018_resource_review_submissions.sql')
        ) INTO imported;
    END IF;
    IF imported THEN
        -- Only the old branch migration needs correction. Preserve settled decisions.
        IF EXISTS (SELECT 1 FROM nexent.schema_migrations
                   WHERE migration_id='v2.9.0_018_resource_review_submissions.sql'
                     AND status IN ('applied','baselined')) THEN RETURN; END IF;
        FOR candidate IN
            SELECT r.*,r.resource_snapshot->'payload' AS payload
            FROM nexent.ag_resource_review_t r WHERE r.created_by='review_migration'
              AND r.review_status='pending_review' AND r.delete_flag='N'
        LOOP
            SELECT nullif(btrim(n.created_by),'') INTO submitter FROM nexent.notification_t n
            WHERE n.event_type='repository_review_pending' AND n.tenant_id=candidate.tenant_id
              AND ((n.resource_type=candidate.resource_type || '_repository' AND n.unique_id=candidate.repository_id)
                OR (n.resource_type='resource_review' AND n.unique_id=candidate.review_id))
              AND n.is_active AND n.delete_flag='N' ORDER BY n.notification_id DESC LIMIT 1;
            IF submitter IS NULL AND candidate.resource_type <> 'mcp' THEN
                submitter := nullif(btrim(candidate.payload->>'publisher_user_id'),'');
            ELSIF submitter IS NULL AND candidate.payload->>'updated_by'=candidate.payload->>'user_id' THEN
                submitter := nullif(btrim(candidate.payload->>'user_id'),'');
            END IF;
            IF submitter IS NULL THEN
                problems := problems + 1;
                RAISE WARNING 'Review upgrade: tenant=%, kind=%, listing=%: unresolved submitter',
                    candidate.tenant_id,candidate.resource_type,candidate.repository_id;
                CONTINUE;
            END IF;
            IF importing AND submitter <> candidate.submitted_user_id THEN
                UPDATE nexent.ag_resource_review_t SET submitted_user_id=submitter WHERE review_id=candidate.review_id;
            END IF;
        END LOOP;
        IF problems > 0 THEN RAISE EXCEPTION '% unresolved review submissions', problems; END IF;
        RETURN;
    END IF;
    IF NOT importing AND (to_regclass('nexent.ag_agent_repository_t') IS NULL
       OR to_regclass('nexent.ag_skill_repository_t') IS NULL
       OR to_regclass('nexent.mcp_market_record_t') IS NULL
       OR to_regclass('nexent.notification_t') IS NULL) THEN
        RAISE NOTICE 'Review preflight deferred until prerequisite schema migrations complete';
        RETURN;
    END IF;

    FOR candidate IN
        WITH pending AS (
            SELECT 'agent' AS kind, r.publisher_tenant_id AS tenant, r.agent_repository_id AS listing,
                   r.agent_id AS source, r.version_no AS version, r.publisher_user_id AS publisher,
                   s.agent_id IS NOT NULL AS source_exists, to_jsonb(r) AS payload, r.update_time AS submitted
            FROM nexent.ag_agent_repository_t r LEFT JOIN nexent.ag_tenant_agent_t s
              ON (s.tenant_id,s.agent_id,s.version_no) = (r.publisher_tenant_id,r.agent_id,r.version_no)
             AND s.delete_flag <> 'Y'
            WHERE r.status='pending_review' AND r.delete_flag <> 'Y'
            UNION ALL
            SELECT 'skill',r.publisher_tenant_id,r.skill_repository_id,r.skill_id,NULL,r.publisher_user_id,
                   s.skill_id IS NOT NULL,to_jsonb(r),r.update_time
            FROM nexent.ag_skill_repository_t r LEFT JOIN nexent.ag_skill_info_t s
              ON (s.tenant_id,s.skill_id) = (r.publisher_tenant_id,r.skill_id) AND s.delete_flag <> 'Y'
            WHERE r.status='pending_review' AND r.delete_flag <> 'Y'
            UNION ALL
            SELECT 'mcp',r.tenant_id,r.market_id,r.source_mcp_id,NULL,r.user_id,
                   s.mcp_id IS NOT NULL,to_jsonb(r),r.update_time
            FROM nexent.mcp_market_record_t r LEFT JOIN nexent.mcp_record_t s
              ON (s.tenant_id,s.mcp_id) = (r.tenant_id,r.source_mcp_id) AND s.delete_flag <> 'Y'
            WHERE r.review_status='pending_review' AND r.delete_flag <> 'Y'
        )
        SELECT p.*, count(*) OVER (PARTITION BY tenant,kind,source) AS pending_count
        FROM pending p
    LOOP
        BEGIN
            IF NOT candidate.source_exists THEN RAISE EXCEPTION 'missing source'; END IF;
            IF candidate.submitted IS NULL THEN RAISE EXCEPTION 'missing submission time'; END IF;
            IF candidate.pending_count > 1 THEN RAISE EXCEPTION 'duplicate pending submissions'; END IF;
            IF candidate.kind='agent' AND NOT coalesce((candidate.payload->'agent_info_json')
                ?& ARRAY['agent_id','agent_info','mcp_info'], false) THEN
                RAISE EXCEPTION 'invalid agent snapshot';
            ELSIF candidate.kind='skill' THEN
                archive_size := length(decode(candidate.payload->>'skill_zip_base64','base64'));
                IF candidate.payload->>'skill_info_json' IS NULL OR coalesce(archive_size,0)<22 THEN
                    RAISE EXCEPTION 'invalid skill snapshot';
                END IF;
            ELSIF candidate.kind='mcp' AND candidate.payload->>'mcp_name' IS NULL THEN
                RAISE EXCEPTION 'missing MCP name';
            END IF;

            SELECT nullif(btrim(n.created_by),'') INTO submitter FROM nexent.notification_t n
            WHERE n.event_type='repository_review_pending' AND n.resource_type=candidate.kind || '_repository'
              AND n.tenant_id=candidate.tenant AND n.unique_id=candidate.listing
              AND n.is_active AND n.delete_flag='N'
            ORDER BY n.notification_id DESC LIMIT 1;
            -- A delegated MCP resubmission retains the original owner. Without
            -- the event, only use that owner if the listing audit agrees.
            IF submitter IS NULL AND (candidate.kind <> 'mcp' OR
                candidate.payload->>'updated_by' IS NOT DISTINCT FROM candidate.publisher) THEN
                submitter := nullif(btrim(candidate.publisher),'');
            END IF;
            IF submitter IS NULL THEN RAISE EXCEPTION 'unresolved submitter'; END IF;

            IF importing THEN
                IF EXISTS (SELECT 1 FROM nexent.ag_resource_review_t WHERE tenant_id=candidate.tenant
                           AND resource_type=candidate.kind AND repository_id=candidate.listing
                           AND created_by='review_migration') THEN CONTINUE; END IF;
                INSERT INTO nexent.ag_resource_review_t
                    (tenant_id,resource_type,source_resource_id,version_no,repository_id,submitted_user_id,
                     submitted_at,submit_description,resource_snapshot,created_by,updated_by)
                VALUES (candidate.tenant,candidate.kind,candidate.source,candidate.version,candidate.listing,
                        submitter,candidate.submitted AT TIME ZONE 'UTC',candidate.payload->>'content',
                        jsonb_build_object('schema_version',1,'payload',candidate.payload),
                        'review_migration','review_migration');
            END IF;
        EXCEPTION WHEN OTHERS THEN
            problems := problems + 1;
            RAISE WARNING 'Review upgrade: tenant=%, kind=%, listing=%: %',
                candidate.tenant,candidate.kind,candidate.listing,SQLERRM;
        END;
    END LOOP;
    IF problems > 0 THEN RAISE EXCEPTION '% invalid review submissions', problems; END IF;
END
$review_upgrade$;
