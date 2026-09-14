-- Citation support for conversation source search records:
-- 1. Preserve exact lexical retrieval terms so source-card highlighting survives
--    conversation history reloads without changing the search index or query count.
-- 2. Elasticsearch accurate-search scores are raw relevance scores and may exceed
--    9.999999, so widen score_overall before saving conversation source records.

SET search_path TO nexent;

ALTER TABLE nexent.conversation_source_search_t
    ADD COLUMN IF NOT EXISTS retrieval_highlight_terms JSONB;

COMMENT ON COLUMN nexent.conversation_source_search_t.retrieval_highlight_terms IS
    'Exact lexical terms returned by retrieval for source highlighting.';

ALTER TABLE nexent.conversation_source_search_t
    ALTER COLUMN score_overall TYPE numeric(14, 6);
