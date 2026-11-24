-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
ALTER TABLE nexent.evolution_skill_candidate_t
    ALTER COLUMN skill_id DROP NOT NULL,
    ADD COLUMN IF NOT EXISTS source_agent_id integer,
    ADD COLUMN IF NOT EXISTS source_version_no integer,
    ADD COLUMN IF NOT EXISTS released_guide_candidate_id bigint;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
        WHERE conrelid = 'nexent.evolution_skill_candidate_t'::regclass AND conname = 'ck_evolution_skill_candidate_target') THEN
        ALTER TABLE nexent.evolution_skill_candidate_t
            ADD CONSTRAINT ck_evolution_skill_candidate_target CHECK (
                (skill_id IS NOT NULL AND source_agent_id IS NULL AND source_version_no IS NULL AND released_guide_candidate_id IS NULL)
                OR (skill_id IS NULL AND source_agent_id IS NOT NULL AND source_agent_id > 0
                    AND source_version_no IS NOT NULL AND source_version_no > 0
                    AND released_guide_candidate_id IS NOT NULL AND released_guide_candidate_id > 0));
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_evolution_scoped_skill_candidate ON nexent.evolution_skill_candidate_t
    (tenant_id, source_agent_id, source_version_no, released_guide_candidate_id, base_digest,
     result_digest, created_by, feedback_digest) WHERE released_guide_candidate_id IS NOT NULL;

COMMENT ON COLUMN nexent.evolution_skill_candidate_t.source_agent_id IS 'Business Agent that owns the scoped Skill guide.';
COMMENT ON COLUMN nexent.evolution_skill_candidate_t.source_version_no IS 'Published Agent version supplying the guide package being edited.';
COMMENT ON COLUMN nexent.evolution_skill_candidate_t.released_guide_candidate_id IS 'New Skill proposal whose guide is revised by this candidate.';
