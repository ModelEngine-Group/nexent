ALTER TABLE nexent.model_record_t
ADD COLUMN ssl_verify BOOLEAN DEFAULT TRUE;

COMMENT ON COLUMN nexent.model_record_t.ssl_verify IS 'Whether to verify SSL certificates when connecting to this model API. Default is true. Set to false for local services without SSL support.';

