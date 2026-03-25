ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS model_appid VARCHAR(100) DEFAULT '';


ALTER TABLE nexent.model_record_t
ADD COLUMN IF NOT EXISTS access_token VARCHAR(100) DEFAULT '';

COMMENT ON COLUMN nexent.model_record_t.model_appid IS 'Application ID for model authentication.';
COMMENT ON COLUMN nexent.model_record_t.access_token IS 'Access token for model authentication.';
