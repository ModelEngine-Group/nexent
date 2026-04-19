-- Add is_multimodal column to knowledge_record_t table
ALTER TABLE nexent.knowledge_record_t
ADD COLUMN IF NOT EXISTS is_multimodal varchar(1) DEFAULT 'N';

COMMENT ON COLUMN nexent.knowledge_record_t.is_multimodal IS 'whether it is multimodal';
