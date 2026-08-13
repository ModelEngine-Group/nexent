-- Elasticsearch accurate-search scores are raw relevance scores and may exceed
-- 9.999999.  Preserve them when saving conversation source records.
ALTER TABLE nexent.conversation_source_search_t
    ALTER COLUMN score_overall TYPE numeric(14, 6);
