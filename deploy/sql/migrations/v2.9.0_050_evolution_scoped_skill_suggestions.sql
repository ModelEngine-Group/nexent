-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
ALTER TABLE nexent.evolution_suggestion_t
    ADD COLUMN IF NOT EXISTS released_guide_candidate_id bigint
    CHECK (released_guide_candidate_id IS NULL OR (released_guide_candidate_id > 0 AND skill_id IS NULL));

COMMENT ON COLUMN nexent.evolution_suggestion_t.released_guide_candidate_id IS
    'New Skill proposal mounted on this tenant, Agent, and published version when the suggestion was submitted.';
