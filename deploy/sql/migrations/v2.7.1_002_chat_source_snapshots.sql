-- Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

-- Preserve AIDP retrieval attributes while using explicit AIDP-specific column names.
ALTER TABLE nexent.conversation_source_search_t
    ADD COLUMN IF NOT EXISTS aidp_metadata JSONB,
    ADD COLUMN IF NOT EXISTS aidp_source_reference JSONB;

DO $$
DECLARE
    legacy_column TEXT;
BEGIN
    FOREACH legacy_column IN ARRAY ARRAY['retrieval_metadata', 'source_metadata'] LOOP
        IF EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'nexent'
              AND table_name = 'conversation_source_search_t'
              AND column_name = legacy_column
        ) THEN
            EXECUTE format(
                'UPDATE nexent.conversation_source_search_t '
                'SET aidp_metadata = COALESCE(aidp_metadata, %I)',
                legacy_column
            );
            EXECUTE format(
                'ALTER TABLE nexent.conversation_source_search_t DROP COLUMN %I',
                legacy_column
            );
        END IF;
    END LOOP;

    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'nexent'
          AND table_name = 'conversation_source_search_t'
          AND column_name = 'source_reference'
    ) THEN
        UPDATE nexent.conversation_source_search_t
        SET aidp_source_reference = COALESCE(aidp_source_reference, source_reference);
        ALTER TABLE nexent.conversation_source_search_t
            DROP COLUMN source_reference;
    END IF;
END
$$;

COMMENT ON COLUMN nexent.conversation_source_search_t.aidp_metadata
    IS 'Opaque AIDP metadata snapshot returned for this retrieval hit';
COMMENT ON COLUMN nexent.conversation_source_search_t.aidp_source_reference
    IS 'AIDP source reference attributes for this retrieval hit, excluding metadata';
