-- Migration script: Migrate vlm model type to image_understanding
-- This script updates historical data where users had configured VLM models
-- The model type should be changed from 'vlm' to 'image_understanding'
-- Date: 2026-05-10

-- Step 1: Preview affected records (optional - can be removed in production)
-- SELECT model_id, model_name, model_type, display_name, tenant_id
-- FROM nexent.model_record_t
-- WHERE model_type = 'vlm' AND delete_flag = 'N';

-- Step 2: Update model_type from 'vlm' to 'image_understanding'
UPDATE nexent.model_record_t
SET model_type = 'image_understanding',
    update_time = CURRENT_TIMESTAMP
WHERE model_type = 'vlm'
  AND delete_flag = 'N';

-- Step 3: Verify the update
-- SELECT model_type, COUNT(*) as count
-- FROM nexent.model_record_t
-- WHERE delete_flag = 'N'
-- GROUP BY model_type;
