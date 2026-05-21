-- Add concurrency_limit column to model_record_t table
ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS concurrency_limit INTEGER DEFAULT NULL;

-- Add comment to the column
COMMENT ON COLUMN nexent.model_record_t.concurrency_limit IS 'Maximum concurrent requests for this model. Default is NULL (unlimited).';

-- Add timeout_seconds column to model_record_t table
ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS timeout_seconds INTEGER DEFAULT 120;

-- Add comment to the column
COMMENT ON COLUMN nexent.model_record_t.timeout_seconds IS 'Request timeout in seconds for this model. Default is 120 seconds.';
