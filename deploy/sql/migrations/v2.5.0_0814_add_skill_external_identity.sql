-- Add source-specific identity for skills installed from external markets.

SET search_path TO nexent;

ALTER TABLE IF EXISTS nexent.ag_skill_info_t
    ADD COLUMN IF NOT EXISTS unique_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS version_update_time TIMESTAMPTZ;

COMMENT ON COLUMN nexent.ag_skill_info_t.unique_id IS
    'Stable skill identifier from an external source, for example a ModelScope repo ID';

COMMENT ON COLUMN nexent.ag_skill_info_t.version_update_time IS
    'External source update time captured when the skill was installed';
