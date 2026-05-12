-- Add embedding_model_id column to knowledge_record_t table
-- This field stores the ID of the embedding model used by the knowledge base

-- Add embedding_model_id column
ALTER TABLE "knowledge_record_t"
ADD COLUMN IF NOT EXISTS "embedding_model_id" INTEGER;

-- Add column comment
COMMENT ON COLUMN "knowledge_record_t"."embedding_model_id" IS 'Embedding model ID, foreign key reference to model_record_t.model_id';
