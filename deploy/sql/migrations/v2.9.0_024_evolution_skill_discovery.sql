-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
ALTER TABLE nexent.evolution_skill_candidate_t DROP CONSTRAINT IF EXISTS evolution_skill_candidate_t_check;
ALTER TABLE nexent.evolution_skill_candidate_t DROP CONSTRAINT IF EXISTS evolution_skill_candidate_change;
ALTER TABLE nexent.evolution_skill_candidate_t ADD CONSTRAINT evolution_skill_candidate_change CHECK (
    CASE WHEN feedback->>'method' = 'S1' THEN COALESCE(
        base_digest = result_digest AND jsonb_typeof(feedback->'edit'->'old') = 'string'
        AND jsonb_typeof(feedback->'edit'->'new') = 'string'
        AND length(trim(feedback->'edit'->>'new')) BETWEEN 1 AND 1000
        AND feedback->'edit'->>'old' <> feedback->'edit'->>'new', false)
    ELSE base_digest <> result_digest END
);
