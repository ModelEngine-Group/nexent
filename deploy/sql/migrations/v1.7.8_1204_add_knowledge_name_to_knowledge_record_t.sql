-- Add knowledge_name column if it does not exist
ALTER TABLE nexent.knowledge_record_t
ADD COLUMN IF NOT EXISTS knowledge_name varchar(100) COLLATE "pg_catalog"."default";

COMMENT ON COLUMN nexent.knowledge_record_t.knowledge_name IS 'User-facing knowledge base name (display name), mapped to internal index_name';
COMMENT ON COLUMN nexent.knowledge_record_t.index_name IS 'Internal Elasticsearch index name';

-- Backfill existing records: for legacy data, use index_name as knowledge_name
UPDATE nexent.knowledge_record_t
SET knowledge_name = index_name
WHERE knowledge_name IS NULL;


-- Add chunk_batch column in model_record_t table
ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS chunk_batch INT4;

COMMENT ON COLUMN nexent.model_record_t.chunk_batch IS 'Batch size for concurrent embedding requests during document chunking';