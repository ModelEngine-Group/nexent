-- Migration: Add preserve_source_file to knowledge_record_t table
-- Date: 2026-06-01
-- Description: Whether to preserve uploaded source documents after vectorization (default: true)

ALTER TABLE nexent.knowledge_record_t
ADD COLUMN IF NOT EXISTS preserve_source_file BOOLEAN NOT NULL DEFAULT true;

COMMENT ON COLUMN nexent.knowledge_record_t.preserve_source_file IS 'Whether to preserve uploaded source documents after vectorization';
