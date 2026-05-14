-- Migration: Add timeout_seconds column to model_record_t table
-- Date: 2026-05-07
-- Description: Add timeout_seconds field to control request timeout per model

-- Add timeout_seconds column to model_record_t table
ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS timeout_seconds INTEGER DEFAULT 120;

-- Add comment to the column
COMMENT ON COLUMN nexent.model_record_t.timeout_seconds IS 'Request timeout in seconds for this model. Default is 120 seconds.';
