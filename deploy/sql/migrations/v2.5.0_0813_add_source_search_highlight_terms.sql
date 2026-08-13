-- Preserve exact lexical retrieval terms so source-card highlighting survives
-- conversation history reloads without changing the search index or query count.

SET search_path TO nexent;

ALTER TABLE nexent.conversation_source_search_t
    ADD COLUMN IF NOT EXISTS retrieval_highlight_terms JSONB;

COMMENT ON COLUMN nexent.conversation_source_search_t.retrieval_highlight_terms IS
    'Exact lexical terms returned by retrieval for source highlighting.';
