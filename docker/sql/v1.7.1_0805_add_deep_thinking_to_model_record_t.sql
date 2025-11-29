ALTER TABLE nexent.model_record_t
ADD COLUMN is_deep_thinking BOOLEAN DEFAULT FALSE;
COMMENT ON COLUMN nexent.model_record_t.is_deep_thinking IS 'deep thinking switch, true=open, false=close';