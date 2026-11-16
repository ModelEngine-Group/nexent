-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
-- Keep content identity independent of the lifecycle optimistic-lock version.
BEGIN;
ALTER TABLE nexent.knowledge_file_lifecycle_t
    ADD COLUMN IF NOT EXISTS source_generation INT4 NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS source_space VARCHAR(64),
    ADD COLUMN IF NOT EXISTS source_key VARCHAR(1024),
    ADD COLUMN IF NOT EXISTS source_revision VARCHAR(128),
    ADD COLUMN IF NOT EXISTS source_sha256 VARCHAR(64);
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
        WHERE conrelid='nexent.knowledge_file_lifecycle_t'::regclass
          AND conname='ck_knowledge_file_cleanse_source') THEN
        ALTER TABLE nexent.knowledge_file_lifecycle_t ADD CONSTRAINT ck_knowledge_file_cleanse_source CHECK (
            source_generation >= 0 AND (
                (source_space IS NULL AND source_key IS NULL AND source_revision IS NULL AND source_sha256 IS NULL)
                OR (source_space IS NOT NULL AND source_key IS NOT NULL AND source_revision IS NOT NULL AND source_sha256 IS NOT NULL
                    AND source_space ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'
                    AND length(source_key) > 0 AND length(source_revision) > 0
                    AND source_sha256 ~ '^[0-9a-f]{64}$')
            )
        );
    END IF;
END $$;
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.source_generation IS 'Content generation independent of lifecycle CAS version; changes only with source replacement.';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.source_space IS 'Authorized logical source space; null until source is pinned.';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.source_key IS 'Authorized logical source key; null until source is pinned.';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.source_revision IS 'Immutable source object revision; not a content checksum.';
COMMENT ON COLUMN nexent.knowledge_file_lifecycle_t.source_sha256 IS 'Independent SHA256 of source bytes; null until source is pinned.';
COMMIT;
