ALTER TABLE nexent.model_record_t
ADD COLUMN expected_chunk_size INT4,
ADD COLUMN maximum_chunk_size INT4;

COMMENT ON COLUMN nexent.model_record_t.expected_chunk_size IS 'Expected chunk size for embedding models, used during document chunking';
COMMENT ON COLUMN nexent.model_record_t.maximum_chunk_size IS 'Maximum chunk size for embedding models, used during document chunking';

