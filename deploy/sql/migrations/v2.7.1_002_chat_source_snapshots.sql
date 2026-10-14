-- Preserve the original per-hit attributes without changing existing source identities.
ALTER TABLE nexent.conversation_source_search_t
    ADD COLUMN IF NOT EXISTS source_metadata JSONB,
    ADD COLUMN IF NOT EXISTS source_reference JSONB;

COMMENT ON COLUMN nexent.conversation_source_search_t.source_metadata
    IS 'Opaque business metadata snapshot returned for this retrieval hit';
COMMENT ON COLUMN nexent.conversation_source_search_t.source_reference
    IS 'Technical retrieval attributes for this hit, excluding business metadata';
